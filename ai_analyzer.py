"""
ai_analyzer.py — Rule-based legal document risk analyzer.

STRICT RULES (enforced by design):
1. Only reference clauses that EXPLICITLY exist in the document.
2. Every risk point includes a direct quote extracted from the document.
3. No clause is invented, assumed, or paraphrased beyond document content.
4. Unfilled blank fields are detected and reported separately.

OUTPUT per point:
    {
        "number":      int,
        "risk_level":  "HIGH" | "MEDIUM" | "LOW",
        "section":     str,               # e.g. "Section 5" or detected label
        "quote":       str,               # verbatim excerpt from document
        "plain_english": str,             # 1-2 sentence plain-language explanation
        "page_numbers": [int, ...],
    }
"""

import re
from pdf_processor import build_chunks


# ─────────────────────────────────────────────────────────────────────────────
# Keyword lists
# ─────────────────────────────────────────────────────────────────────────────

HIGH_RISK_KEYWORDS = [
    "terminate", "termination", "terminates", "terminating",
    "liable", "liability", "liabilities",
    "indemnify", "indemnification", "indemnifies", "hold harmless",
    "forfeit", "forfeiture", "penalty", "penalties",
    "irrevocable", "non-refundable", "waive", "waiver",
    "reprocurement", "breach", "default",
    "ownership", "title to all", "work product", "all rights",
    "perpetual", "royalty-free", "unconditional right",
    "suspend payment", "withhold payment", "delay payment",
    "collateral", "lien", "seizure", "liquidated damages",
]

MEDIUM_RISK_KEYWORDS = [
    "prior written approval", "prior written consent", "written authorization",
    "reserves the right", "at its discretion", "sole discretion",
    "subject to approval", "without prior", "written consent",
    "insurance", "certificate of insurance", "coverage",
    "audit", "inspection", "retain", "records",
    "milestone", "not to exceed", "overhead rate",
    "prevailing wage", "subcontract", "subconsultant",
    "assignment", "nonassignment", "governing law",
    "jurisdiction", "binding", "amendment", "modify",
]

LOW_RISK_EXCLUSIONS = [
    "equal employment", "nondiscrimination", "non-discrimination",
    "harassment", "sexual harassment", "disability",
    "veteran status", "marital status", "sexual orientation",
    "race", "color", "religion", "national origin",
    "independent consultant status", "independent contractor",
    "acknowledgment", "notification address", "complete agreement",
    "signatures", "in witness whereof", "distribution",
]

# NOTE: SECTION_MAP is intentionally removed.
# Section labels are now extracted from the actual document text — see
# extract_section_from_text() below. Invented friendly names are never used.

# ─────────────────────────────────────────────────────────────────────────────
# Blank-field detection patterns
# ─────────────────────────────────────────────────────────────────────────────

# Matches common unfilled contract blanks
BLANK_FIELD_PATTERNS = [
    r'\b(_{2,})\b',                        # Underscores: ___
    r'\[\s*INSERT[^\]]*\]',               # [INSERT NAME]
    r'\[\s*TO BE[^\]]*\]',                # [TO BE COMPLETED]
    r'\[\s*DATE[^\]]*\]',                 # [DATE]
    r'\[\s*NAME[^\]]*\]',                 # [NAME]
    r'\[\s*ADDRESS[^\]]*\]',             # [ADDRESS]
    r'\[\s*STATE[^\]]*\]',               # [STATE]
    r'\[\s*AMOUNT[^\]]*\]',              # [AMOUNT]
    r'\[\s*NUMBER[^\]]*\]',              # [NUMBER]
    r'\[\s*TBD[^\]]*\]',                 # [TBD]
    r'\[\s*N/A[^\]]*\]',                 # [N/A]
    r'\bN\.?A\.?\b',                      # N.A. / N/A as standalone
    r'☐',                                 # Unchecked checkbox
    r'□',                                 # Unchecked checkbox (unicode box)
    r'\(\s*\)',                            # Empty parentheses ()
    r'<<[^>]+>>',                         # <<FIELD>>
]

BLANK_FIELD_LABELS = {
    r'\b(_{2,})\b':              "Blank line (unfilled field)",
    r'\[\s*INSERT[^\]]*\]':      "INSERT placeholder not filled",
    r'\[\s*TO BE[^\]]*\]':       "TO BE COMPLETED placeholder",
    r'\[\s*DATE[^\]]*\]':        "Date field not filled",
    r'\[\s*NAME[^\]]*\]':        "Name field not filled",
    r'\[\s*ADDRESS[^\]]*\]':     "Address field not filled",
    r'\[\s*STATE[^\]]*\]':       "State/jurisdiction not filled",
    r'\[\s*AMOUNT[^\]]*\]':      "Amount not filled",
    r'\[\s*NUMBER[^\]]*\]':      "Number field not filled",
    r'\[\s*TBD[^\]]*\]':         "TBD — field pending completion",
    r'\[\s*N/A[^\]]*\]':         "N/A field — confirm applicability",
    r'\bN\.?A\.?\b':             "N/A value — confirm applicability",
    r'☐':                        "Unchecked checkbox — action required",
    r'□':                        "Unchecked checkbox (□) — action required",
    r'\(\s*\)':                  "Empty parentheses — field not filled",
    r'<<[^>]+>>':                "Template placeholder not replaced",
}


# ─────────────────────────────────────────────────────────────────────────────
# Utility functions
# ─────────────────────────────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    """Normalize whitespace and strip non-ASCII control characters."""
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[^\x20-\x7E\u2610\u2611\u2612\u2713\u2714\u2717\u2718☐☑]', '', text)
    return text.strip()


def detect_risk(text: str) -> str:
    """Return HIGH / MEDIUM / LOW based on keyword scan."""
    lower = text.lower()
    for excl in LOW_RISK_EXCLUSIONS:
        if excl in lower:
            return "LOW"
    for kw in HIGH_RISK_KEYWORDS:
        if kw in lower:
            return "HIGH"
    for kw in MEDIUM_RISK_KEYWORDS:
        if kw in lower:
            return "MEDIUM"
    return "LOW"


def extract_section_from_text(raw_text: str, page_numbers: list) -> str:
    """
    Extract the real section heading from the chunk's raw text.

    Strategy (tried in order):
    1. Numbered section heading at the start of a line:
       e.g. "Section 12.", "12.", "12.1", "ARTICLE IV", "SECTION 5 —"
    2. ALL-CAPS heading line (≤ 6 words) that precedes the clause text.
    3. Fall back to "Page [N]" using the first page number in the chunk.

    The function NEVER invents or translates a heading — it only returns
    text that is literally present in the document.
    """
    # ── Pattern 1: numeric / named section headers ──────────────────────────
    # Matches: "Section 5", "5.", "5.1", "5.1.2", "Article III", "SECTION 5 —"
    header_patterns = [
        # "Section 12" / "Section 12." / "Section 12 —"
        r'^\s*(?:Section|SECTION|Sec\.)\s+(\d+(?:\.\d+)*)(?:[\s.\-—:]+([A-Z][^\n]{0,60}))?',
        # "Article IV" / "ARTICLE 3"
        r'^\s*(?:Article|ARTICLE)\s+([IVXLCDM]+|\d+)(?:[\s.\-—:]+([A-Z][^\n]{0,60}))?',
        # Bare number: "12." / "12.1" / "12.1.2" at line start
        r'^\s*(\d+(?:\.\d+)+)(?:[.\-—:\s]+([A-Z][^\n]{0,60}))?',
        # Bare single digit followed by dot: "5. Termination"
        r'^\s*(\d+)\.\s+([A-Z][^\n]{3,60})',
        # "PARAGRAPH 5" / "CLAUSE 3"
        r'^\s*(?:Paragraph|PARAGRAPH|Clause|CLAUSE)\s+(\d+(?:\.\d+)*)(?:[\s.\-—:]+([A-Z][^\n]{0,60}))?',
    ]

    for pattern in header_patterns:
        m = re.search(pattern, raw_text, re.MULTILINE)
        if m:
            # Build label from matched groups, stripping trailing punctuation
            parts = [g.strip().rstrip('.—:-') for g in m.groups() if g and g.strip()]
            label = ' '.join(parts)
            if label and len(label) <= 80:
                return label

    # ── Pattern 2: ALL-CAPS short heading line ───────────────────────────────
    # e.g. "TERMINATION\n..." or "INDEMNIFICATION\n..."
    caps_m = re.search(
        r'^\s*([A-Z][A-Z0-9 &/\-]{2,50})\s*$',
        raw_text, re.MULTILINE,
    )
    if caps_m:
        heading = caps_m.group(1).strip()
        # Only accept if it looks like a heading (not a full sentence)
        if 2 <= len(heading.split()) <= 6:
            return heading

    # ── Fallback: page reference ─────────────────────────────────────────────
    if page_numbers:
        if len(page_numbers) == 1:
            return f"Page {page_numbers[0]}"
        return f"Pages {page_numbers[0]}–{page_numbers[-1]}"
    return "Unspecified Section"


def verify_quote_in_source(quote: str, raw_chunk_text: str) -> bool:
    """
    Self-check gate: verify the quote is a real substring of the source.

    Comparison is done on normalised whitespace so that minor PDF
    extraction artefacts (extra spaces, soft hyphens) don't cause false
    negatives. A quote that ends with '...' is matched as a prefix.

    Returns True only if the quote (or its prefix) is found in the source.
    NEVER modifies or invents text — returns False rather than guessing.
    """
    def _normalize(s: str) -> str:
        # Collapse all whitespace, strip soft-hyphens and zero-width chars
        s = re.sub(r'[\xad\u200b\u200c\u200d\ufeff]', '', s)
        return re.sub(r'\s+', ' ', s).strip().lower()

    norm_source = _normalize(raw_chunk_text)

    # Handle truncated quotes ending in '...'
    check_quote = quote.rstrip('.')
    if quote.endswith('...'):
        check_quote = quote[:-3].rstrip()

    norm_quote = _normalize(check_quote)

    if not norm_quote or len(norm_quote) < 20:
        return False

    return norm_quote in norm_source


# Keep detect_risk using the module-level keyword lists (unchanged)
# detect_risk is defined above and remains unchanged.


def split_sentences(text: str) -> list:
    """Split cleaned text into meaningful sentences (≥ 50 chars)."""
    text = clean_text(text)
    raw = re.split(r'(?<=[.;])\s+(?=[A-Z])', text)
    return [s.strip() for s in raw if len(s.strip()) >= 50]


def score_sentence(sentence: str) -> int:
    """Score a sentence for legal obligation relevance."""
    lower = sentence.lower()
    obligation_words = [
        "shall", "must", "required", "agrees", "will not",
        "cannot", "may not", "is not", "are not",
        "within", "days", "written", "approval",
        "not to exceed", "liable", "terminate", "pay",
        "submit", "provide", "maintain", "obtain", "keep",
        "ownership", "rights", "indemnify", "insurance",
        "penalty", "breach", "default", "cost", "fee",
    ]
    score = sum(1 for w in obligation_words if w in lower)
    if len(sentence) > 60:
        score += 1
    if len(sentence) > 120:
        score += 1
    return score


def extract_best_quote(text: str, max_len: int = 9999) -> str:
    """
    Extract a COMPLETE, meaningful sentence.
    """
    sentences = split_sentences(text)
    if not sentences:
        return ""

    scored = sorted(
        [(score_sentence(s), len(s), s) for s in sentences],
        key=lambda x: (x[0], x[1]),
        reverse=True,
    )
    best = scored[0][2].strip()
    
    # STRICT RULE: Quote must be a complete sentence, no truncation guessing.
    if not re.search(r'[.;:!?]\s*$', best) or best.endswith("..."):
        return ""
        
    return best

# ─────────────────────────────────────────────────────────────────────────────
# Plain-English generator — derived STRICTLY from the extracted quote
# ─────────────────────────────────────────────────────────────────────────────

def get_party_actor(ql: str) -> str:
    if re.search(r'\b(both|each|mutual|the parties)\b', ql):
        return "both"
    elif re.search(r'\b(client|owner|commission|agency|employer|licensor|company|target|other party)\b', ql) and not re.search(r'\b(contractor|consultant|employee|vendor|you|subcontractor)\b', ql):
        return "them"
    return "you"

def get_base_prefix(party: str, polarity: str) -> str:
    if party == "both":
        if polarity == "prohibition": return "Both parties are prohibited from "
        if polarity == "permission" or polarity == "exclusion": return "Both parties are entitled to "
        return "Both parties must "
    elif party == "them":
        if polarity == "prohibition": return "The other party is prohibited from "
        if polarity == "permission" or polarity == "exclusion": return "The other party is entitled to "
        return "The other party must "
    else: # you
        if polarity == "prohibition": return "You are prohibited from "
        if polarity == "permission" or polarity == "exclusion": return "You are entitled to "
        return "You are required to "

def build_plain_english(quote: str) -> str:
    q = clean_text(quote)
    ql = q.lower()
    
    timeframe = _extract_timeframe(q)
    dollar = _extract_dollar(q)
    
    polarity = _detect_polarity(ql)
    party_actor = get_party_actor(ql)
    
    prefix = get_base_prefix(party_actor, polarity)
    
    # ── Termination
    if re.search(r'\bterminat', ql):
        cond = f" with {timeframe} notice" if timeframe else " under the conditions described"
        if polarity == "prohibition":
            return prefix + f"refrain from terminating the contract unilaterally — specific restrictions apply."
        return prefix + f"follow the specific termination process{cond} if choosing to exit the contract."

    # ── Indemnification
    if re.search(r'\bindemnif|\bhold\s+harmless\b', ql):
        return prefix + "cover out-of-pocket costs and legal damages if a lawsuit arises from these actions."

    # ── IP / Ownership
    if re.search(r'\bwork\s+product\b|\bintellectual\s+property\b|\bcopyright\b', ql) or \
       (re.search(r'\bownership\b|\btitle\b', ql) and re.search(r'\ball\b|\bvests\b', ql)):
        return prefix + "surrender ownership of the creative work or intellectual property produced under this contract."

    # ── Payment Cap
    if re.search(r'\bnot\s+to\s+exceed\b', ql):
        cap = dollar if dollar else "the stated budget limit"
        return prefix + f"ensure billings do not exceed {cap} without prior written approval."

    # ── Insurance
    if re.search(r'\binsurance\b|\bcoverage\b|\bpolicy\b', ql):
        return prefix + "keep the specified insurance policies active for the full duration of the contract."

    # ── Subcontracting
    if re.search(r'\bsubcontract\b', ql):
        if polarity == "prohibition":
            return prefix + "delegate or hand off this work to another company without explicit permission."
        return prefix + "follow the specific restrictions outlined before subcontracting any work."

    # ── Assignment
    if re.search(r'\bassign\b|\bassignment\b', ql):
        if polarity == "prohibition":
             return prefix + "transfer this contract to another entity without consent."
        return prefix + "get approval before transferring or assigning this contract to anyone else."

    # ── Dispute Resolution
    if re.search(r'\bdispute\b|\barbitrat\b', ql):
        return prefix + "resolve disagreements through the specific formal process outlined here."

    # ── Liquidated Damages
    if re.search(r'\bliquidated\s+damages\b', ql):
        return prefix + f"pay a fixed financial penalty{(' of ' + dollar) if dollar else ''} automatically if a specific breach occurs."

    # ── Fees/Payment
    if re.search(r'\bfee[s]?\b|\bpayment\b|\bpay\b', ql) and re.search(r'\bshall\b|\bmust\b', ql):
        return prefix + f"make the payment{(' of ' + dollar) if dollar else ''}{(' within ' + timeframe) if timeframe else ''} as stated."

    # ── Confidentiality
    if re.search(r'\bconfidential\b|\bnon.disclos\b|\bproprietary\b', ql):
        if polarity == "exclusion":
             return prefix + "freely use or discuss the information described here because it is NOT protected."
        elif polarity == "permission":
             return prefix + "access this confidential information but ONLY for the purposes of this contract."
        else:
             return prefix + "keep the other party's information strictly secret and not share it without permission."

    # ── Limitation of Liability
    if re.search(r'\bin\s+no\s+event\b|\blimit(?:ation)?\s+of\s+liability\b', ql):
        return "Both parties are prohibited from recovering damages beyond the restricted cap stated in this clause."

    # ── Force Majeure
    if re.search(r'\bforce\s+majeure\b|\bact\s+of\s+god\b', ql):
        return "Both parties are entitled to be excused from performance if a truly unforeseeable natural disaster occurs."

    # ── Non-Compete
    if re.search(r'\bnon.compet\b|\bcompeting\s+business\b', ql):
        return prefix + f"avoid starting or joining a competing business{(' for ' + timeframe) if timeframe else ''}."

    # ── Non-Solicitation
    if re.search(r'\bnon.solicit\b|\bsolicit\b', ql):
        return prefix + f"avoid poaching or hiring the other party's staff or clients{(' for ' + timeframe) if timeframe else ''}."

    # ── Warranties
    if re.search(r'\brepresents?\b|\bwarrant\b', ql):
        return prefix + "take legal responsibility for the absolute truth of these formal promises."

    # ── Written Notice
    if re.search(r'\bwritten\s+notice\b|\bnotice\s+(?:shall|must)\b', ql):
        return prefix + f"send formal written notice{(' at least ' + timeframe) if timeframe else ''} before taking action."

    # ── Amendments
    if re.search(r'\bamend\b|\bmodif\b', ql) and re.search(r'\bwritten\b', ql):
        return "Both parties must sign a formal written document to make any legally binding changes to this contract."

    # ── Independent Contractor
    if re.search(r'\bindependent\s+contractor\b|\bconsultant\b', ql):
        return prefix + "act as a self-employed business and pay your own taxes and benefits."

    # ── Licensing
    if re.search(r'\blicense\b|\bpermit\b', ql):
        return prefix + "hold and maintain all necessary legal permits and licences for this work."
        
    # ── Specific Prohibition Fallback
    prohib_match = re.search(r'\b(shall\s+not|may\s+not|will\s+not|cannot|prohibited\s+from)\s+(.{10,80}?)(?:[.;]|$)', ql)
    if prohib_match:
        action = prohib_match.group(2).strip()
        pfx = "You are prohibited from "
        if party_actor == "them": pfx = "The other party is prohibited from "
        elif party_actor == "both": pfx = "Both parties are prohibited from "
        return pfx + f"{action}."

    # ── Specific Obligation Fallback
    oblig_match = re.search(r'\b(shall|must|required\s+to|agrees\s+to)\s+(.{10,80}?)(?:[.;]|$)', ql)
    if oblig_match:
        action = oblig_match.group(2).strip()
        pfx = "You are required to "
        if party_actor == "them": pfx = "The other party must "
        elif party_actor == "both": pfx = "Both parties must "
        return pfx + f"{action}."
        
    return ""

# ─────────────────────────────────────────────────────────────────────────────
# Blank-field detection patterns
# ─────────────────────────────────────────────────────────────────────────────

# Matches common unfilled contract blanks
BLANK_FIELD_PATTERNS = [
    r'\b(_{2,})\b',                        # Underscores: ___
    r'\[\s*INSERT[^\]]*\]',               # [INSERT NAME]
    r'\[\s*TO BE[^\]]*\]',                # [TO BE COMPLETED]
    r'\[\s*DATE[^\]]*\]',                 # [DATE]
    r'\[\s*NAME[^\]]*\]',                 # [NAME]
    r'\[\s*ADDRESS[^\]]*\]',             # [ADDRESS]
    r'\[\s*STATE[^\]]*\]',               # [STATE]
    r'\[\s*AMOUNT[^\]]*\]',              # [AMOUNT]
    r'\[\s*NUMBER[^\]]*\]',              # [NUMBER]
    r'\[\s*TBD[^\]]*\]',                 # [TBD]
    r'\[\s*N/A[^\]]*\]',                 # [N/A]
    r'\bN\.?A\.?\b',                      # N.A. / N/A as standalone
    r'☐',                                 # Unchecked checkbox
    r'□',                                 # Unchecked checkbox (unicode box)
    r'\(\s*\)',                            # Empty parentheses ()
    r'<<[^>]+>>',                         # <<FIELD>>
]

BLANK_FIELD_LABELS = {
    r'\b(_{2,})\b':              "Blank line (unfilled field)",
    r'\[\s*INSERT[^\]]*\]':      "INSERT placeholder not filled",
    r'\[\s*TO BE[^\]]*\]':       "TO BE COMPLETED placeholder",
    r'\[\s*DATE[^\]]*\]':        "Date field not filled",
    r'\[\s*NAME[^\]]*\]':        "Name field not filled",
    r'\[\s*ADDRESS[^\]]*\]':     "Address field not filled",
    r'\[\s*STATE[^\]]*\]':       "State/jurisdiction not filled",
    r'\[\s*AMOUNT[^\]]*\]':      "Amount not filled",
    r'\[\s*NUMBER[^\]]*\]':      "Number field not filled",
    r'\[\s*TBD[^\]]*\]':         "TBD — field pending completion",
    r'\[\s*N/A[^\]]*\]':         "N/A field — confirm applicability",
    r'\bN\.?A\.?\b':             "N/A value — confirm applicability",
    r'☐':                        "Unchecked checkbox — action required",
    r'□':                        "Unchecked checkbox (□) — action required",
    r'\(\s*\)':                  "Empty parentheses — field not filled",
    r'<<[^>]+>>':                "Template placeholder not replaced",
}


# ─────────────────────────────────────────────────────────────────────────────
# Utility functions
# ─────────────────────────────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    """Normalize whitespace and strip non-ASCII control characters."""
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[^\x20-\x7E\u2610\u2611\u2612\u2713\u2714\u2717\u2718☐☑]', '', text)
    return text.strip()


def detect_risk(text: str) -> str:
    """Return HIGH / MEDIUM / LOW based on keyword scan."""
    lower = text.lower()
    for excl in LOW_RISK_EXCLUSIONS:
        if excl in lower:
            return "LOW"
    for kw in HIGH_RISK_KEYWORDS:
        if kw in lower:
            return "HIGH"
    for kw in MEDIUM_RISK_KEYWORDS:
        if kw in lower:
            return "MEDIUM"
    return "LOW"


def extract_section_from_text(raw_text: str, page_numbers: list) -> str:
    """
    Extract the real section heading from the chunk's raw text.

    Strategy (tried in order):
    1. Numbered section heading at the start of a line:
       e.g. "Section 12.", "12.", "12.1", "ARTICLE IV", "SECTION 5 —"
    2. ALL-CAPS heading line (≤ 6 words) that precedes the clause text.
    3. Fall back to "Page [N]" using the first page number in the chunk.

    The function NEVER invents or translates a heading — it only returns
    text that is literally present in the document.
    """
    # ── Pattern 1: numeric / named section headers ──────────────────────────
    # Matches: "Section 5", "5.", "5.1", "5.1.2", "Article III", "SECTION 5 —"
    header_patterns = [
        # "Section 12" / "Section 12." / "Section 12 —"
        r'^\s*(?:Section|SECTION|Sec\.)\s+(\d+(?:\.\d+)*)(?:[\s.\-—:]+([A-Z][^\n]{0,60}))?',
        # "Article IV" / "ARTICLE 3"
        r'^\s*(?:Article|ARTICLE)\s+([IVXLCDM]+|\d+)(?:[\s.\-—:]+([A-Z][^\n]{0,60}))?',
        # Bare number: "12." / "12.1" / "12.1.2" at line start
        r'^\s*(\d+(?:\.\d+)+)(?:[.\-—:\s]+([A-Z][^\n]{0,60}))?',
        # Bare single digit followed by dot: "5. Termination"
        r'^\s*(\d+)\.\s+([A-Z][^\n]{3,60})',
        # "PARAGRAPH 5" / "CLAUSE 3"
        r'^\s*(?:Paragraph|PARAGRAPH|Clause|CLAUSE)\s+(\d+(?:\.\d+)*)(?:[\s.\-—:]+([A-Z][^\n]{0,60}))?',
    ]

    for pattern in header_patterns:
        m = re.search(pattern, raw_text, re.MULTILINE)
        if m:
            # Build label from matched groups, stripping trailing punctuation
            parts = [g.strip().rstrip('.—:-') for g in m.groups() if g and g.strip()]
            label = ' '.join(parts)
            if label and len(label) <= 80:
                return label

    # ── Pattern 2: ALL-CAPS short heading line ───────────────────────────────
    # e.g. "TERMINATION\n..." or "INDEMNIFICATION\n..."
    caps_m = re.search(
        r'^\s*([A-Z][A-Z0-9 &/\-]{2,50})\s*$',
        raw_text, re.MULTILINE,
    )
    if caps_m:
        heading = caps_m.group(1).strip()
        # Only accept if it looks like a heading (not a full sentence)
        if 2 <= len(heading.split()) <= 6:
            return heading

    # ── Fallback: page reference ─────────────────────────────────────────────
    if page_numbers:
        if len(page_numbers) == 1:
            return f"Page {page_numbers[0]}"
        return f"Pages {page_numbers[0]}–{page_numbers[-1]}"
    return "Unspecified Section"


def verify_quote_in_source(quote: str, raw_chunk_text: str) -> bool:
    """
    Self-check gate: verify the quote is a real substring of the source.

    Comparison is done on normalised whitespace so that minor PDF
    extraction artefacts (extra spaces, soft hyphens) don't cause false
    negatives. A quote that ends with '...' is matched as a prefix.

    Returns True only if the quote (or its prefix) is found in the source.
    NEVER modifies or invents text — returns False rather than guessing.
    """
    def _normalize(s: str) -> str:
        # Collapse all whitespace, strip soft-hyphens and zero-width chars
        s = re.sub(r'[\xad\u200b\u200c\u200d\ufeff]', '', s)
        return re.sub(r'\s+', ' ', s).strip().lower()

    norm_source = _normalize(raw_chunk_text)

    # Handle truncated quotes ending in '...'
    check_quote = quote.rstrip('.')
    if quote.endswith('...'):
        check_quote = quote[:-3].rstrip()

    norm_quote = _normalize(check_quote)

    if not norm_quote or len(norm_quote) < 20:
        return False

    return norm_quote in norm_source


# Keep detect_risk using the module-level keyword lists (unchanged)
# detect_risk is defined above and remains unchanged.


def split_sentences(text: str) -> list:
    """Split cleaned text into meaningful sentences (≥ 50 chars)."""
    text = clean_text(text)
    raw = re.split(r'(?<=[.;])\s+(?=[A-Z])', text)
    return [s.strip() for s in raw if len(s.strip()) >= 50]


def score_sentence(sentence: str) -> int:
    """Score a sentence for legal obligation relevance."""
    lower = sentence.lower()
    obligation_words = [
        "shall", "must", "required", "agrees", "will not",
        "cannot", "may not", "is not", "are not",
        "within", "days", "written", "approval",
        "not to exceed", "liable", "terminate", "pay",
        "submit", "provide", "maintain", "obtain", "keep",
        "ownership", "rights", "indemnify", "insurance",
        "penalty", "breach", "default", "cost", "fee",
    ]
    score = sum(1 for w in obligation_words if w in lower)
    if len(sentence) > 60:
        score += 1
    if len(sentence) > 120:
        score += 1
    return score


def extract_best_quote(text: str, max_len: int = 9999) -> str:
    """
    Extract a COMPLETE, meaningful sentence.
    """
    sentences = split_sentences(text)
    if not sentences:
        return ""

    scored = sorted(
        [(score_sentence(s), len(s), s) for s in sentences],
        key=lambda x: (x[0], x[1]),
        reverse=True,
    )
    best = scored[0][2].strip()
    
    # STRICT RULE: Quote must be a complete sentence, no truncation guessing.
    if not re.search(r'[.;:!?]\s*$', best) or best.endswith("..."):
        return ""
        
    return best

# ─────────────────────────────────────────────────────────────────────────────
# Plain-English generator — derived STRICTLY from the extracted quote
# ─────────────────────────────────────────────────────────────────────────────

# Parties to recognise in document text and replace with a readable label
_PARTY_PATTERNS = [
    (r'\bthe\s+contractor\b',         'the contractor'),
    (r'\bthe\s+consultant\b',         'the consultant'),
    (r'\bthe\s+vendor\b',             'the vendor'),
    (r'\bthe\s+supplier\b',           'the supplier'),
    (r'\bthe\s+client\b',             'the client'),
    (r'\bthe\s+owner\b',              'the owner'),
    (r'\bthe\s+commission\b',         'the Commission'),
    (r'\bthe\s+agency\b',             'the Agency'),
    (r'\bthe\s+company\b',            'the Company'),
    (r'\bthe\s+employer\b',           'the Employer'),
    (r'\bthe\s+licen[sc]ee\b',        'the Licensee'),
    (r'\bthe\s+licen[sc]or\b',        'the Licensor'),
    (r'\bthe\s+parties\b',            'both parties'),
    (r'\bthe\s+party\b',              'a party'),
    (r'\b(?:he|she|they|it)\s+shall\b', 'the responsible party shall'),
]


def _extract_parties(ql: str) -> tuple[str, str]:
    """
    Return (subject, object) party labels found in the quote.
    Falls back to generic 'you' / 'the other party' if none found.
    """
    subject = "You"
    obj     = "the other party"

    # Detect subject (who has the obligation)
    if re.search(r'\bconsultant\b', ql):         subject = "The consultant"
    elif re.search(r'\bcontractor\b', ql):       subject = "The contractor"
    elif re.search(r'\bvendor\b', ql):           subject = "The vendor"
    elif re.search(r'\bsupplier\b', ql):         subject = "The supplier"
    elif re.search(r'\blicensee\b', ql):         subject = "The licensee"
    elif re.search(r'\bemployee\b', ql):         subject = "The employee"
    elif re.search(r'\bsubcontractor\b', ql):    subject = "The subcontractor"

    # Detect object (who benefits / holds the right)
    if re.search(r'\bcommission\b', ql):         obj = "the Commission"
    elif re.search(r'\bclient\b', ql):           obj = "the Client"
    elif re.search(r'\bowner\b', ql):            obj = "the Owner"
    elif re.search(r'\bagency\b', ql):           obj = "the Agency"
    elif re.search(r'\bemployer\b', ql):         obj = "the Employer"
    elif re.search(r'\blicensor\b', ql):         obj = "the Licensor"

    return subject, obj


def _extract_timeframe(q: str) -> str | None:
    """Return the first explicit time period found in the quote, or None."""
    m = re.search(
        r'(\d+)\s*(?:calendar\s+)?(?:business\s+)?(days?|months?|years?|weeks?|hours?)',
        q, re.IGNORECASE,
    )
    return m.group(0).strip() if m else None


def _extract_dollar(q: str) -> str | None:
    """Return the first dollar amount found in the quote, or None."""
    m = re.search(r'\$\s?[\d,]+(?:\.\d+)?(?:\s*(?:million|thousand|M|K))?', q, re.IGNORECASE)
    return m.group(0).strip() if m else None


def _obligation_verb(ql: str) -> str:
    """Detect the primary obligation type from the quote."""
    if re.search(r'\bshall\s+not\b|\bmay\s+not\b|\bwill\s+not\b|\bcannot\b|\bshall\s+be\s+prohibited\b', ql):
        return "is prohibited from"
    if re.search(r'\bshall\b|\bmust\b|\bis\s+required\s+to\b|\bare\s+required\s+to\b|\bagrees\s+to\b', ql):
        return "must"
    if re.search(r'\breserves\s+the\s+right\b|\bmay\b', ql):
        return "has the right to"
    if re.search(r'\bhas\s+the\s+right\b|\bshall\s+have\s+the\s+right\b', ql):
        return "has the right to"
    return "must"


def _detect_polarity(ql: str) -> str:
    """
    Determine the quote's INTENT before writing any plain-English text.

    STEP 1 of the self-check: read the quote.
    STEP 2: is this giving a right or taking one away?
    STEP 3: who benefits?

    Returns one of:
        "exclusion"  — clause says something is NOT protected / NOT included
        "definition" — clause defines a term
        "prohibition"— clause forbids an action
        "permission" — clause explicitly allows an action
        "obligation" — clause requires an action
        "unknown"    — cannot determine
    """
    # ── Exclusion / carve-out (check FIRST — these often contain prohibition
    #    words like "not" which would otherwise fire the prohibition branch)
    if re.search(
        r'\bdoes\s+not\s+include\b|\bshall\s+not\s+include\b'
        r'|\bnot\s+deemed\b|\bnot\s+considered\b|\bnot\s+constitute\b'
        r'|\bexclud(?:es?|ing)\b|\bexcept(?:ing)?\b|\bcarve.out\b'
        r'|\bdoes\s+not\s+apply\b|\bshall\s+not\s+apply\b'
        r'|\bis\s+not\s+(?:subject|bound|applicable)\b'
        r'|\bwithout\s+limitation\b|\bnotwithstanding\b',
        ql,
    ):
        return "exclusion"

    # ── Definition
    if re.search(
        r'\bmeans\b|\brefers?\s+to\b|\bis\s+defined\s+as\b'
        r'|\bshall\s+mean\b|\bhereinafter\b|\bthe\s+term\b',
        ql,
    ):
        return "definition"

    # ── Prohibition
    if re.search(
        r'\bshall\s+not\b|\bmay\s+not\b|\bwill\s+not\b'
        r'|\bcannot\b|\bprohibit\b|\bforbid\b|\bis\s+not\s+permitted\b'
        r'|\bmust\s+not\b|\bno\s+(?:party|person|entity)\b',
        ql,
    ):
        return "prohibition"

    # ── Permission / right
    if re.search(
        r'\bmay\s+(?!not\b)|\bhas\s+the\s+right\b|\bshall\s+have\s+the\s+right\b'
        r'|\bis\s+permitted\b|\bis\s+authorized\b|\bis\s+entitled\b'
        r'|\breserves\s+the\s+right\b|\bat\s+its\s+(?:sole\s+)?discretion\b',
        ql,
    ):
        return "permission"

    # ── Obligation
    if re.search(
        r'\bshall\b|\bmust\b|\bwill\b|\bis\s+required\b'
        r'|\bagrees?\s+to\b|\bundertakes?\s+to\b',
        ql,
    ):
        return "obligation"

    return "unknown"


def build_plain_english(quote: str) -> str:
    """
    Return a 1-2 sentence plain-English explanation derived ONLY from the quote.

    SELF-CHECK (enforced in code):
      STEP 1: Read the quote.
      STEP 2: Detect polarity — is this granting a right or taking one away?
      STEP 3: Who benefits — the user or the other party?
      STEP 4: Write what the user CAN or CANNOT do in real life because of this.

    FORBIDDEN outputs:
      "review with a legal professional"
      "read carefully before signing"
      "this clause creates an obligation"
      Copying the quote verbatim as the plain English.
    """
    q        = clean_text(quote)
    ql       = q.lower()
    subject, obj = _extract_parties(ql)
    timeframe    = _extract_timeframe(q)
    dollar       = _extract_dollar(q)
    verb         = _obligation_verb(ql)

    # ── STEP 2: Determine the clause's intent BEFORE writing anything ─────────
    polarity = _detect_polarity(ql)

    # ── Termination ───────────────────────────────────────────────────────────
    if re.search(r'\bterminat', ql):
        if re.search(r'\bcommission\b|\bclient\b|\bowner\b|\bagency\b', ql):
            actor = obj.replace("the ", "The ").strip()
        else:
            actor = subject
        if polarity == "permission" or polarity == "unknown":
            if timeframe:
                notice = f"by giving {timeframe} written notice"
            elif re.search(r'\bimmediately\b|\bwithout\s+notice\b', ql):
                notice = "immediately and without notice"
            else:
                notice = "by following the process described"
            consequence = ""
            if re.search(r'\breprocurement\b', ql):
                consequence = " You may be liable for all reprocurement costs the other party incurs."
            elif re.search(r'\bwork\s+(?:completed|performed|done)\b|\bdate\s+of\s+termination\b', ql):
                consequence = " You will only be paid for work actually completed before the termination date."
            elif re.search(r'\bliable\b|\bliability\b|\bcost\b|\bdamage\b', ql):
                consequence = " You may owe costs or damages as a result."
            return f"{actor} can end this contract {notice}.{consequence}"
        elif polarity == "prohibition":
            return f"{actor} cannot terminate the contract under the conditions described — specific restrictions apply."
        elif polarity == "obligation":
            if timeframe:
                return f"If you want to exit the contract, you must give {timeframe} advance written notice — failing to do so may make you liable for costs."
            return f"{subject} must follow the termination process described — unilateral exit without notice may create liability."

    # ── Indemnification / Hold Harmless ───────────────────────────────────────
    if re.search(r'\bindemnif|\bhold\s+harmless\b', ql):
        scope = []
        if re.search(r'\bclaim', ql):   scope.append("claims")
        if re.search(r'\bdamage', ql):  scope.append("damages")
        if re.search(r'\bloss\b', ql):  scope.append("losses")
        if re.search(r'\bcost\b', ql):  scope.append("costs")
        if re.search(r'\bsuit\b|\blawsuit\b|\baction\b', ql): scope.append("lawsuits")
        scope_str = ", ".join(scope) if scope else "any resulting liability"
        trigger = ""
        if re.search(r'\bnegligen', ql):       trigger = " caused by your negligence"
        elif re.search(r'\bmisconduct\b', ql): trigger = " caused by your misconduct"
        elif re.search(r'\bbreach\b', ql):     trigger = " caused by a breach of this contract"
        elif re.search(r'\bact\b|\bomission\b', ql): trigger = " caused by your acts or omissions"
        return (
            f"If {obj} suffers {scope_str}{trigger}, you must cover those costs out of your own pocket. "
            f"You cannot argue that the other party should absorb those losses."
        )

    # ── Intellectual Property / Work Product Ownership ────────────────────────
    if re.search(r'\bwork\s+product\b|\bintellectual\s+property\b|\bip\b|\bcopyright\b', ql) or \
       (re.search(r'\bownership\b|\btitle\b', ql) and re.search(r'\ball\b|\bvests\b|\bassigns\b', ql)):
        if polarity == "permission":
            return f"You are granted rights to use the intellectual property described — but only for the purposes stated in this contract."
        extra = ""
        if re.search(r'\broyalty.free\b', ql): extra = " on a royalty-free basis"
        elif re.search(r'\birrevocable\b', ql): extra = " and this transfer cannot be undone"
        elif re.search(r'\bperpetual\b', ql):   extra = " permanently"
        no_reuse = " You cannot reuse, sell, or share them without written permission." \
            if re.search(r'\bwithout\s+(?:written\s+)?(?:consent|permission|approval)\b', ql) else ""
        return f"Everything you create under this contract belongs to {obj}{extra}.{no_reuse}"

    # ── Payment Cap / Not To Exceed ───────────────────────────────────────────
    if re.search(r'\bnot\s+to\s+exceed\b', ql):
        cap = dollar if dollar else "the fixed amount stated"
        approval = " To bill beyond this, you need prior written approval." \
            if re.search(r'\bprior\s+written\b|\bwritten\s+approval\b|\bwritten\s+authorization\b', ql) else ""
        return f"The total amount you can be paid under this contract is capped at {cap}.{approval}"

    # ── Invoice / Billing Deadlines ───────────────────────────────────────────
    if re.search(r'\binvoice\b|\bbilling\b|\bbill\b', ql):
        if timeframe:
            kind = "final invoice" if re.search(r'\bfinal\b', ql) else "invoices"
            deadline_msg = f"All {kind} must be submitted within {timeframe}."
        else:
            deadline_msg = "Invoices must be submitted within the timeframe stated."
        forfeiture = " Submit late and the invoice may be rejected — you could lose that payment entirely." \
            if re.search(r'\bforfe\b|\bnot\s+be\s+paid\b|\brejected\b|\bwaived\b', ql) else ""
        return deadline_msg + forfeiture

    # ── Insurance ─────────────────────────────────────────────────────────────
    if re.search(r'\binsurance\b|\bcoverage\b|\bpolicy\b|\bpolicies\b', ql):
        ins_types = []
        if re.search(r'\bgeneral\s+liability\b', ql):      ins_types.append("General Liability")
        if re.search(r'\bprofessional\s+liability\b|\berrors\s+and\s+omissions\b|\be&o\b', ql):
            ins_types.append("Professional Liability")
        if re.search(r'\bworkers[\s\-]*compensation\b', ql, re.IGNORECASE): ins_types.append("Workers' Compensation")
        if re.search(r'\bautomobile\b|\bvehicle\b', ql):   ins_types.append("Automobile Liability")
        if re.search(r'\bcommercial\b', ql):               ins_types.append("Commercial insurance")
        ins_label = " and ".join(ins_types) if ins_types else "the required insurance"
        amt = f" of at least {dollar}" if dollar else ""
        base = f"You must keep {ins_label}{amt} active for the full duration of this contract."
        cancel = ""
        if re.search(r'\bcancell?\b|\bcancellation\b', ql) and timeframe:
            cancel = f" The policy cannot be cancelled without {timeframe} prior written notice to the other party."
        elif re.search(r'\bcertificate\b', ql):
            cancel = f" You must give {obj} a certificate proving this coverage before the contract starts."
        return base + cancel

    # ── Audit / Record Retention ──────────────────────────────────────────────
    if re.search(r'\baudit\b|\brecords?\b|\bbooks\b|\bretain\b|\bpreserve\b', ql):
        period = f" for {timeframe}" if timeframe else ""
        government = " Government or state auditors have the right to inspect those records at any time." \
            if re.search(r'\bstate\b|\bfederal\b|\bgovernment\b|\bpublic\b', ql) else ""
        return f"You must keep all project records and documents{period} after the contract ends.{government}"

    # ── Subcontracting ────────────────────────────────────────────────────────
    if re.search(r'\bsubcontract\b|\bsubconsultant\b|\bsubcontractor\b', ql):
        if polarity == "prohibition" or (re.search(r'\bwithout\b', ql) and re.search(r'\bwritten\b|\bapproval\b|\bconsent\b', ql)):
            return f"You cannot hand this work off to another company or individual without getting written approval first — doing so without permission is a breach."
        return "Any subcontracting arrangement is subject to the restrictions and approval process described in this clause."

    # ── Assignment ────────────────────────────────────────────────────────────
    if re.search(r'\bassign\b|\bassignment\b', ql):
        if polarity == "prohibition" or (re.search(r'\bwithout\b', ql) and re.search(r'\bconsent\b|\bapproval\b|\bpermission\b', ql)):
            return "You cannot transfer this contract to another person or company — doing so without written consent is a breach, and the transfer would be void."
        elif polarity == "permission":
            return "This clause allows assignment of the contract — but check whether conditions or limitations apply."
        return "Assignment of this contract is governed by the conditions in this clause — do not transfer without checking the restrictions first."

    # ── Key Personnel ─────────────────────────────────────────────────────────
    if re.search(r'\bkey\s+personnel\b|\bproject\s+manager\b|\bnamed\s+staff\b', ql):
        if re.search(r'\breplace\b|\bremove\b|\bsubstitut\b', ql):
            cond = " without prior written approval" if re.search(r'\bwritten\s+approval\b|\bwritten\s+consent\b|\bprior\s+approval\b', ql) else ""
            return f"You cannot swap out or remove named key staff{cond} — doing so is a breach and could trigger a formal dispute."
        return "Any change to the key people named in this contract is subject to the other party's approval."

    # ── Dispute Resolution ────────────────────────────────────────────────────
    if re.search(r'\bdispute\b|\bclaim\b', ql) and re.search(r'\bresolv\b|\bnegotiat\b|\barbitrat\b|\bescalat\b', ql):
        mechanism = ""
        if re.search(r'\barbitrat\b', ql):  mechanism = " through binding arbitration (not a court)"
        elif re.search(r'\bcommittee\b|\bdirector\b|\bmanager\b', ql): mechanism = " through the internal authority named"
        cont = " You must keep working throughout — you cannot stop performance just because a dispute has started." \
            if re.search(r'\bcontinue\b|\bperform\b|\bwork\b', ql) else ""
        return f"Disagreements are resolved{mechanism} under the process described here.{cont}"

    # ── Governing Law / Jurisdiction ──────────────────────────────────────────
    if re.search(r'\bgoverning\s+law\b|\bjurisdiction\b|\bgovern[s]?\s+by\b|\bvenue\b', ql):
        location = ""
        loc_m = re.search(r'(?:state|courts?)\s+of\s+([A-Za-z ]+?)(?:[.,;]|$)', q, re.IGNORECASE)
        if loc_m: location = f" of {loc_m.group(1).strip()}"
        return (
            f"If there is ever a legal dispute about this contract, it will be handled in the courts{location}. "
            f"If that jurisdiction is far from you, you may have to travel there to defend yourself."
        )

    # ── Liquidated Damages ────────────────────────────────────────────────────
    if re.search(r'\bliquidated\s+damages\b', ql):
        amt = f" of {dollar}" if dollar else ""
        per_m = re.search(r'per\s+(day|week|month|occurrence)', ql, re.IGNORECASE)
        per = f" per {per_m.group(1)}" if per_m else ""
        return (
            f"If you breach the condition described, you automatically owe a fixed sum{amt}{per}. "
            f"This applies regardless of whether the other party actually suffered that much loss."
        )

    # ── Waiver ────────────────────────────────────────────────────────────────
    if re.search(r'\bwaiver\b|\bwaive\b', ql):
        if polarity == "exclusion":
            return "This clause prevents either side from claiming that a past failure to enforce the contract means they gave up their rights — they can still enforce it in future."
        return "The fact that someone did not enforce a rule once does not mean they have permanently given up that right — they can still hold you to it next time."

    # ── Non-Refundable / Forfeiture ───────────────────────────────────────────
    if re.search(r'\bnon.refundable\b|\bforfe\b', ql):
        amt = f" of {dollar}" if dollar else ""
        return f"The payment{amt} described in this clause will NOT be returned to you under any circumstances — once paid, it is gone."

    # ── Sole / Unilateral Discretion ──────────────────────────────────────────
    if re.search(r'\bsole\s+discretion\b|\bat\s+its\s+discretion\b|\bunilateral\b', ql):
        act_m = re.search(r'discretion\s+(?:to|in)\s+([^.,;]{5,40})', ql, re.IGNORECASE)
        action = f" to {act_m.group(1).strip()}" if act_m else ""
        who = obj.replace("the ", "The ") if obj != "the other party" else "The other party"
        return (
            f"{who} has the sole right{action} with no obligation to explain or justify their decision to you. "
            f"You have no mechanism to challenge or override this."
        )

    # ── Amendments / Modifications ────────────────────────────────────────────
    if re.search(r'\bamend\b|\bmodif\b', ql) and re.search(r'\bwritten\b|\bsigned\b', ql):
        return "This contract can only be changed through a formal written document signed by both sides — a verbal agreement or email agreement is not enough and is not binding."

    # ── Independent Contractor ────────────────────────────────────────────────
    if re.search(r'\bindependent\s+contractor\b|\bindependent\s+consultant\b', ql):
        ic_items = []
        if re.search(r'\btax\b', ql):      ic_items.append("taxes")
        if re.search(r'\binsurance\b', ql): ic_items.append("insurance")
        if re.search(r'\bbenefit\b', ql):  ic_items.append("employee benefits")
        ic_str = (", ".join(ic_items) + " ") if ic_items else ""
        return (
            f"You are treated as a self-employed person under this contract — "
            f"{ic_str}are entirely your own responsibility and {obj} will not contribute to them."
        )

    # ── Prevailing Wage ───────────────────────────────────────────────────────
    if re.search(r'\bprevailing\s+wage\b', ql):
        return "Legal minimum wage rates set by the government apply to workers covered by this clause — check the rates and confirm which of your workers are affected."

    # ── Licensing ─────────────────────────────────────────────────────────────
    if re.search(r'\blicense\b|\blicensed\b|\bpermit\b|\bcertif\b', ql) and \
       re.search(r'\bshall\b|\bmust\b|\brequired\b', ql):
        return "You and your team must hold valid licences and permits for this type of work throughout the contract — if any expire, you are immediately in breach."

    # ── Milestone / Cost Estimate ─────────────────────────────────────────────
    if re.search(r'\bmilestone\b', ql) and re.search(r'\bcost\b|\bexceed\b|\bestimate\b', ql):
        cap = dollar if dollar else "the amount per milestone stated"
        return f"You cannot spend more than {cap} on any milestone without written pre-approval — overruns beyond this limit will not be reimbursed."

    # ── Safety / OSHA ─────────────────────────────────────────────────────────
    if re.search(r'\bosha\b|\bsafety\b', ql) and re.search(r'\bshall\b|\bmust\b|\brequired\b|\bcomply\b', ql):
        reqs = []
        if re.search(r'\bhard\s+hat\b', ql):    reqs.append("hard hats")
        if re.search(r'\bsafety\s+vest\b', ql): reqs.append("safety vests")
        if re.search(r'\bgoggle\b|\beye\s+protection\b', ql): reqs.append("eye protection")
        req_str = (" — including always wearing " + ", ".join(reqs)) if reqs else ""
        return f"All safety rules must be followed at all times on site{req_str}. Ignoring safety requirements is a breach and could get work stopped."

    # ── Confidentiality / NDA — polarity-driven ───────────────────────────────
    if re.search(r'\bconfidential\b|\bnon.disclos\b|\bproprietary\b|\btrade\s+secret\b|\bsecret\b', ql):

        # STEP 2 applied: read polarity before generating text
        if polarity == "exclusion":
            # Clause defines what is NOT confidential — user is FREE to use/share it
            carve_parts = []
            if re.search(r'\bpublic\s+domain\b|\bpublicly\s+(?:known|available)\b|\bgeneral\s+knowledge\b', ql):
                carve_parts.append("already publicly known or in the public domain")
            if re.search(r'\bindependently\b|\bprior\s+to\b|\balready\s+(?:knew|known|had)\b', ql):
                carve_parts.append("information you already had before signing this agreement")
            if re.search(r'\bthird\s+party\b|\bindependently\s+developed\b', ql):
                carve_parts.append("information you independently developed or received from a third party")
            exceptions = " and ".join(carve_parts) if carve_parts else "certain types of information"
            return (
                f"This clause defines what does NOT count as confidential. "
                f"Specifically, {exceptions} is NOT protected — you are free to discuss or use it without restriction."
            )

        elif polarity == "permission":
            purpose = ""
            if re.search(r'\bperform\b|\bpurpose\b|\bscope\b|\bwork\b', ql):
                purpose = " — but only for the purposes of performing this contract"
            return f"You are permitted to access and use the confidential information described{purpose}. Do not use it for any other purpose."

        elif polarity == "definition":
            # Clause defines what confidential means
            return (
                "This clause defines exactly what counts as 'confidential information' under this agreement. "
                "Any information matching this definition cannot be shared or used outside this contract."
            )

        else:
            # Prohibition or obligation — you CANNOT share it
            conf_actions = []
            if re.search(r'\bdisclose\b|\bdisclosure\b|\bshare\b|\breveal\b', ql): conf_actions.append("share or disclose")
            if re.search(r'\bcopy\b|\breproduce\b', ql): conf_actions.append("copy")
            if re.search(r'\buse\b|\butiliz\b', ql): conf_actions.append("use for your own benefit")
            if re.search(r'\bpublish\b|\bdistribut\b', ql): conf_actions.append("publish or distribute")
            action_str = " or ".join(conf_actions) if conf_actions else "disclose, share, or use"
            consent_note = " — you need their written permission first" \
                if re.search(r'\bwritten\s+(?:consent|permission|approval)\b', ql) else ""
            return (
                f"You cannot {action_str} the other party's confidential information{consent_note}. "
                f"Doing so could expose you to legal action and financial damages."
            )

    # ── Limitation of Liability ───────────────────────────────────────────────
    if re.search(r'\bin\s+no\s+event\b|\blimit(?:ation)?\s+of\s+liability\b|\bliability\s+(?:cap|limit)\b', ql):
        ll_cap = dollar if dollar else "the amount stated"
        excluded = []
        if re.search(r'\bindirect\b', ql):     excluded.append("indirect")
        if re.search(r'\bincidental\b', ql):   excluded.append("incidental")
        if re.search(r'\bconsequential\b', ql): excluded.append("consequential")
        if re.search(r'\bspecial\b', ql):      excluded.append("special")
        if re.search(r'\bpunitive\b', ql):     excluded.append("punitive")
        excl_str = (", ".join(excluded) + " damages") if excluded else "certain categories of losses"
        return (
            f"The maximum either side can claim under this contract is capped at {ll_cap}. "
            f"Even if you suffer larger losses, you cannot recover {excl_str} beyond this cap."
        )

    # ── Force Majeure ─────────────────────────────────────────────────────────
    if re.search(r'\bforce\s+majeure\b|\bact\s+of\s+god\b|\bbeyond\s+(?:its|their|the)?\s*control\b', ql):
        return (
            "If something completely outside your control — like a natural disaster, war, or government ban — "
            "stops you from performing, you cannot be penalised for that specific failure. "
            "But normal business problems like budget issues or supplier delays do not qualify."
        )

    # ── Non-Compete ───────────────────────────────────────────────────────────
    if re.search(r'\bnon.compet\b|\bcompeting\s+business\b', ql):
        nc_period = f" for {timeframe}" if timeframe else ""
        return (
            f"You cannot start, join, or work with a business that competes with {obj}{nc_period}. "
            f"This applies even if you leave voluntarily — breaking it could result in a court order or financial damages."
        )

    # ── Non-Solicitation ──────────────────────────────────────────────────────
    if re.search(r'\bnon.solicit\b|\bsolicit(?:ing)?\s+(?:employees?|clients?|customers?)\b', ql):
        ns_targets = "employees or clients"
        if re.search(r'\bemployee\b|\bstaff\b', ql) and not re.search(r'\bclient\b|\bcustomer\b', ql):
            ns_targets = "employees or staff"
        elif re.search(r'\bclient\b|\bcustomer\b', ql) and not re.search(r'\bemployee\b|\bstaff\b', ql):
            ns_targets = "clients or customers"
        ns_period = f" for {timeframe}" if timeframe else ""
        return (
            f"You cannot approach or hire {obj}'s {ns_targets}{ns_period}. "
            f"This restriction continues after this contract ends, not just while it's active."
        )

    # ── Representations & Warranties ──────────────────────────────────────────
    if re.search(r'\brepresents?\b|\bwarrant(?:ies|y|s)?\b', ql) and \
       re.search(r'\bshall\b|\bmust\b|\bagrees?\b|\bhereby\b', ql):
        if polarity == "exclusion":
            return "Certain warranties are explicitly excluded — you should not assume any implied guarantees apply beyond what is written."
        consequence = ""
        if re.search(r'\bterminat\b', ql):
            consequence = " If you make a false statement here, the other party can terminate this contract immediately."
        elif re.search(r'\bliable\b|\bindemnif\b', ql):
            consequence = " If a statement proves incorrect, you could be personally liable for the resulting losses."
        return (
            f"By signing, {subject.lower()} is making legally binding promises about the specific facts in this clause — "
            f"not just general assurances.{consequence}"
        )

    # ── Written Notice ────────────────────────────────────────────────────────
    if re.search(r'\bwritten\s+notice\b|\bnotice\s+(?:shall|must|will)\b|\bgive\s+notice\b', ql):
        delivery = ""
        if re.search(r'\bemail\b|\belectronic\s+mail\b', ql):            delivery = " by email"
        elif re.search(r'\bcertified\s+mail\b|\bregistered\s+mail\b', ql): delivery = " by certified mail"
        elif re.search(r'\bhand\s+deliver\b|\bin\s+person\b', ql):        delivery = " in person"
        advance = f"at least {timeframe} before" if timeframe else "before"
        return (
            f"You must send a formal written notice{delivery} {advance} taking the action described. "
            f"A verbal message or casual email does not meet this requirement and will not protect you legally."
        )

    # ── Fees / Payment Obligations ────────────────────────────────────────────
    if re.search(r'\bfee[s]?\b|\bpayment\b|\bpay\b|\bcompensation\b', ql) and \
       re.search(r'\bshall\b|\bmust\b|\bwill\b|\brequired\b', ql):
        amt  = f" of {dollar}" if dollar else ""
        when = f" within {timeframe}" if timeframe else ""
        return (
            f"A payment{amt} must be made{when} — if this is late or not paid, "
            f"the other party may charge penalties, suspend services, or pursue a claim against you."
        )

    # ─────────────────────────────────────────────────────────────────────────
    # FALLBACK TIERS — polarity-aware, concrete, no forbidden phrases
    # ─────────────────────────────────────────────────────────────────────────

    # Tier 1: Prohibition — extract what is forbidden and state it plainly
    prohib_match = re.search(
        r'\b(shall\s+not|may\s+not|will\s+not|cannot|is\s+prohibited\s+from)\s+(.{8,120}?)(?:[.;]|$)',
        ql, re.IGNORECASE,
    )
    if prohib_match:
        action = prohib_match.group(2).strip().rstrip('.,;')
        return (
            f"You are not allowed to {action}. "
            f"Doing this means you have broken the contract and the other party can take action against you."
        )

    # Tier 2: Obligation — extract what must be done and the consequence
    oblig_match = re.search(
        r'\b(shall|must|is\s+required\s+to|agrees\s+to|will)\s+(.{8,120}?)(?:[.;]|$)',
        ql, re.IGNORECASE,
    )
    if oblig_match:
        action = oblig_match.group(2).strip().rstrip('.,;')
        when = f" within {timeframe}" if timeframe else ""
        return (
            f"You must {action}{when}. "
            f"Failing to do this puts you in breach of contract."
        )

    # Tier 3: Exclusion — something is explicitly NOT restricted or NOT included
    if polarity == "exclusion":
        if re.search(r'\bconfidential\b|\bdisclos\b|\bprotect\b|\bproprietary\b', ql):
            return "This clause carves out exceptions — the information described is NOT protected and you are free to use or share it without restriction."
        if re.search(r'\bliab\b|\bresponsib\b', ql):
            return "This clause removes a potential liability — the situation described does NOT create financial responsibility for the named party."
        return "This clause establishes an exception or carve-out — the thing described is explicitly excluded from the main obligation."

    # Tier 4: Permission — something is explicitly allowed
    if polarity == "permission":
        act_m = re.search(r'\bmay\s+(.{5,80}?)(?:[.;]|$)', ql, re.IGNORECASE)
        if act_m:
            perm_action = act_m.group(1).strip().rstrip('.,;')
            return f"You are explicitly allowed to {perm_action} — this is a right granted to you by this clause."
        return f"This clause grants a specific right or permission to {subject.lower()} — understand exactly what you are permitted to do."

    # Tier 5: Topic-based impact (when no obligation verb was found)
    IMPACTS = [
        (r'\bconfidential\b|\bproprietary\b',
         "This clause protects sensitive information — you cannot use or share it outside the scope of this contract without facing legal consequences."),
        (r'\bpayment\b|\bfee\b',
         f"A payment{(' of ' + dollar) if dollar else ''}{(' within ' + timeframe) if timeframe else ''} is required — missing it could trigger penalties or suspension."),
        (r'\bterminate\b|\btermination\b',
         "One or both parties can end this contract under the circumstances described — know the notice period and what money remains owed."),
        (r'\bindemnif\b|\bhold\s+harmless\b',
         f"You are financially responsible for covering {obj}'s losses that arise from your actions."),
        (r'\bliability\b|\bliable\b',
         f"This clause determines who pays when things go wrong{(' — up to ' + dollar) if dollar else ''} — check whether the financial risk falls on you."),
        (r'\binsurance\b|\bcoverage\b',
         "You must keep insurance active — letting it lapse is a breach of contract, even if no claim has arisen."),
        (r'\bexclusiv\b',
         "This clause creates an exclusive arrangement — you or the other party is legally locked in and cannot work with competitors in this area."),
        (r'\bgovern\b|\bjurisdiction\b|\bvenue\b',
         "Any legal dispute must go through the courts named here — this could be far from you and expensive."),
        (r'\bintellectual\b|\bcopyright\b|\btrademark\b',
         "Who owns ideas or creative work produced under this contract is set here — understand what you keep and what you give away."),
        (r'\bpenalt\b|\bfine\b',
         f"A financial penalty{(' of ' + dollar) if dollar else ''} applies if the conditions described are breached."),
        (r'\bexpir\b|\brenew\b|\bterm\b',
         "This clause controls the contract's duration — check whether it auto-renews and what you must do to exit cleanly."),
        (r'\bapproval\b|\bconsent\b',
         "You need the other party's explicit sign-off before taking this action — assuming permission without asking is not safe."),
        (r'\bright\b|\brights\b',
         "This clause grants or removes a specific right — determine whether you are gaining or losing something important."),
    ]
    for pattern, message in IMPACTS:
        if re.search(pattern, ql):
            return message

    # Tier 6: Extract concrete numbers and describe their real-world impact
    if timeframe and dollar:
        return f"This clause sets both a {timeframe} deadline and a {dollar} financial obligation — missing either could put you in breach."
    if timeframe:
        return f"A strict {timeframe} deadline applies under this clause — missing it could have financial or legal consequences."
    if dollar:
        return f"A financial amount of {dollar} is involved in this clause — understand exactly when and whether this money is owed by you or to you."

    # If we cannot write a clear, specific, accurate plain English explanation, drop it.
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Blank-field detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_unfilled_fields(pages: list) -> list:
    """
    Scan every page for patterns that indicate unfilled blank fields.
    Returns a deduplicated list of human-readable descriptions.
    """
    found = []
    seen = set()

    full_text = " ".join(p.get("text", "") for p in pages)
    cleaned = clean_text(full_text)

    for pattern, label in BLANK_FIELD_LABELS.items():
        matches = re.findall(pattern, cleaned, flags=re.IGNORECASE)
        if matches and label not in seen:
            # For underscore patterns, only flag if the blank is clearly a field
            if pattern == r'\b(_{2,})\b':
                # Require at least 4 underscores to avoid false positives
                if any(len(m) >= 4 for m in matches):
                    seen.add(label)
                    found.append(label)
            else:
                seen.add(label)
                found.append(label)

    return found


# ─────────────────────────────────────────────────────────────────────────────
# Main analysis entry point
# ─────────────────────────────────────────────────────────────────────────────


def detect_document_type(pages: list) -> str:
    """
    Scan the first page(s) to determine the likely document type.
    """
    if not pages:
        return "Unknown Document"
    
    first_page = pages[0].get("text", "").upper()
    
    if re.search(r'\bNON-?DISCLOSURE\b|\bNDA\b|\bCONFIDENTIALITY AGREEMENT\b', first_page):
        return "Non-Disclosure Agreement"
    if re.search(r'\bLEASE\b|\bTENANT\b|\bLANDLORD\b', first_page):
        return "Lease Agreement"
    if re.search(r'\bEMPLOYMENT\b|\bOFFER OF EMPLOYMENT\b|\bEMPLOYEE AGREEMENT\b', first_page):
        return "Employment Contract"
    if re.search(r'\bMEDICAL\b|\bCONSENT\b|\bHIPAA\b|\bPATIENT\b', first_page):
        return "Medical Consent Form"
    if re.search(r'\bLOAN\b|\bPROMISSORY NOTE\b|\bLENDER\b|\bBORROWER\b', first_page):
        return "Loan Agreement"
    if re.search(r'\bTERMS OF SERVICE\b|\bTOS\b|\bTERMS AND CONDITIONS\b', first_page):
        return "Terms of Service"
    if re.search(r'\bINDEPENDENT CONTRACTOR\b|\bCONSULTING AGREEMENT\b', first_page):
        return "Consulting/Contractor Agreement"
        
    return "Legal Document (General)"

def analyze_document(pages: list) -> dict:
    """
    Analyze a list of extracted page dicts and return a structured risk report.

    Each bullet point in the output has:
        number, risk_level, section, quote, plain_english, page_numbers

    The output also includes:
        unfilled_fields: list[str]  — blank fields detected in the document
        overall_risk:    str        — aggregate HIGH / MEDIUM / LOW
        total_pages:     int
        total_points:    int
    """
    chunks = build_chunks(pages, max_words=300)
    # No arbitrary cap — process every chunk so no section is silently skipped.

    # Build a normalised full-document corpus for quote verification
    raw_points = []
    seen_quotes = set()   # dedup by quote prefix

    for chunk in chunks:
        raw_text = chunk["chunk_text"]          # original — used for verification
        cleaned  = clean_text(raw_text)          # normalised — used for analysis

        if len(cleaned) < 60:
            continue

        # ── RULE 3: extract a direct quote first ──────────────────────────
        quote = extract_best_quote(cleaned, max_len=300)
        if not quote or len(quote) < 30:
            continue  # cannot produce a quote → skip

        # ── SELF-CHECK: verify quote is literally in the source chunk ─────
        # (Rule: "Is my quote actually in the document?")          
        if not verify_quote_in_source(quote, raw_text):
            continue  # quote not verifiable → delete this point

        # ── Dedup by quote prefix ─────────────────────────────────────────
        dedup_key = quote[:80].lower().strip()
        if dedup_key in seen_quotes:
            continue
        seen_quotes.add(dedup_key)

        # ── RULE 5: section name from the actual document text ────────────
        page_nums = chunk["page_numbers"]
        section   = extract_section_from_text(raw_text, page_nums)

        # ── Risk detection and plain-English from the quote only ──────────
        risk  = detect_risk(cleaned)
        plain = build_plain_english(quote)  # RULE 4: quote-grounded only

        if not plain or len(plain) < 20:
            continue

        raw_points.append({
            "risk_level":    risk,
            "section":       section,
            "quote":         quote,
            "plain_english": plain,
            "page_numbers":  page_nums,
        })

    # ── Sort: HIGH → MEDIUM → LOW ─────────────────────────────────────────
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    raw_points.sort(key=lambda x: order[x["risk_level"]])

    # ── Output cap: show up to 15 findings, prioritised HIGH → MEDIUM → LOW ──
    # No minimum floor — output only what was actually found in the document.
    final = raw_points[:15]

    # ── Number points sequentially ─────────────────────────────────────────
    for idx, pt in enumerate(final, start=1):
        pt["number"] = idx

    # ── Overall risk ──────────────────────────────────────────────────────
    risks = {p["risk_level"] for p in final}
    if "HIGH" in risks:
        overall = "HIGH"
    elif "MEDIUM" in risks:
        overall = "MEDIUM"
    else:
        overall = "LOW"

    # ── Detect unfilled fields ────────────────────────────────────────────
    unfilled = detect_unfilled_fields(pages)

    return {
        "document_type":   detect_document_type(pages),
        "bullet_points":   final,
        "overall_risk":    overall,
        "total_pages":     len(pages),
        "total_points":    len(final),
        "unfilled_fields": unfilled,
    }
