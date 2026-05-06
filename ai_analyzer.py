"""
ai_analyzer.py — Groq-powered legal document risk analyzer.

Uses the Groq API (llama-3.1-8b-instant) — completely free, no credit card,
14,400 requests/day free tier. Sign up at https://console.groq.com

analyze_document(pages) is the ONLY public function called by app.py.
Return structure is identical to the original — app.py needs zero changes.

app.py reads these keys from each bullet_point dict:
    number, risk_level, section, quote, plain_english, page_numbers

app.py reads these top-level keys from the result dict:
    document_type, bullet_points, overall_risk,
    total_pages, total_points, unfilled_fields
"""

import os
import json
import re
import time

from dotenv import load_dotenv
from groq import Groq
from pdf_processor import build_chunks

# ─────────────────────────────────────────────────────────────────────────────
# Setup — runs once at import time
# ─────────────────────────────────────────────────────────────────────────────

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
if not GROQ_API_KEY:
    raise ValueError(
        "\n[ai_analyzer] GROQ_API_KEY not found in .env file!\n"
        "  1. Sign up FREE at: https://console.groq.com\n"
        "  2. Go to API Keys → Create API Key\n"
        "  3. Add to your .env file:\n"
        "     GROQ_API_KEY=your_key_here\n"
        "  4. Restart the app.\n"
    )

client = Groq(api_key=GROQ_API_KEY)

# ─────────────────────────────────────────────────────────────────────────────
# Helper: clean LLM response before JSON parsing
# ─────────────────────────────────────────────────────────────────────────────

def clean_json_response(raw_text: str) -> str:
    """
    Strip any markdown fences and extract only the {...} JSON block.
    """
    text = raw_text.strip()

    # Remove ```json ... ``` or ``` ... ``` fences
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*```$', '', text)
    text = text.strip()

    # Keep only from first { to last }
    start = text.find('{')
    end   = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    return text


# ─────────────────────────────────────────────────────────────────────────────
# Groq API call — one chunk at a time
# ─────────────────────────────────────────────────────────────────────────────

def analyze_chunk(chunk_text: str) -> dict | None:
    """
    Send a single text chunk to Groq (llama-3.1-8b-instant) and parse the response.

    Returns a dict with keys: title, explanation, risk_level, reason, is_important
    Returns None on any failure so the caller can skip this chunk gracefully.
    """
    user_message = f"""Analyze this legal contract text and return ONLY this JSON structure:

{{
  "title": "clause name like Termination Rights or Payment Terms",
  "explanation": "explain in 2 plain English sentences what this means for the person signing, what they must do or give up",
  "risk_level": "HIGH or MEDIUM or LOW",
  "reason": "one sentence why this risk level",
  "is_important": true or false
}}

Risk levels:
HIGH = termination, liability, indemnification, penalty, IP ownership, work product ownership, irrevocable rights, payment withholding, forfeit, breach, default, liquidated damages, lien
MEDIUM = approval requirements, audit rights, insurance, subcontracting, assignment, jurisdiction, milestone caps, amendments
LOW = definitions, signatures, boilerplate, acknowledgments, equal opportunity, notification addresses

is_important = true if clause affects money, rights, or obligations
is_important = false if it is standard boilerplate

Legal text:
{chunk_text}

Return ONLY the JSON object. Nothing else."""

    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a legal document risk analyst. Your job is to analyze "
                        "legal contract clauses and return structured JSON. You must return "
                        "ONLY valid JSON with no extra text, no markdown formatting, no "
                        "explanation. Always return exactly the JSON structure requested."
                    ),
                },
                {
                    "role": "user",
                    "content": user_message,
                },
            ],
            temperature=0.1,
            max_tokens=400,
        )

        raw     = response.choices[0].message.content
        cleaned = clean_json_response(raw)
        parsed  = json.loads(cleaned)

        # Validate all required keys exist
        required = {"title", "explanation", "risk_level", "reason", "is_important"}
        if not required.issubset(parsed.keys()):
            print(f"[ai_analyzer] Missing keys in response: {required - parsed.keys()}")
            return None

        return parsed

    except json.JSONDecodeError as e:
        print(f"[ai_analyzer] JSON parse error: {e}")
        return None
    except Exception as e:
        print(f"[ai_analyzer] Groq API error: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Blank-field detection (regex only — no AI needed)
# ─────────────────────────────────────────────────────────────────────────────

_BLANK_FIELD_LABELS = {
    r'\b(_{4,})\b':              "Blank line (unfilled field)",
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
    r'☐':                        "Unchecked checkbox — action required",
    r'□':                        "Unchecked checkbox — action required",
    r'<<[^>]+>>':                "Template placeholder not replaced",
}


def _detect_unfilled_fields(pages: list) -> list:
    """Scan all pages for common unfilled-blank patterns."""
    full_text = " ".join(p.get("text", "") for p in pages)
    full_text = re.sub(r'\s+', ' ', full_text)

    found = []
    seen  = set()
    for pattern, label in _BLANK_FIELD_LABELS.items():
        if re.search(pattern, full_text, flags=re.IGNORECASE) and label not in seen:
            seen.add(label)
            found.append(label)
    return found


# ─────────────────────────────────────────────────────────────────────────────
# Document type detector (regex only)
# ─────────────────────────────────────────────────────────────────────────────

def _detect_document_type(pages: list) -> str:
    if not pages:
        return "Unknown Document"
    first = pages[0].get("text", "").upper()

    checks = [
        (r'\bNON-?DISCLOSURE\b|\bNDA\b|\bCONFIDENTIALITY AGREEMENT\b', "Non-Disclosure Agreement"),
        (r'\bLEASE\b|\bTENANT\b|\bLANDLORD\b',                         "Lease Agreement"),
        (r'\bEMPLOYMENT\b|\bOFFER OF EMPLOYMENT\b|\bEMPLOYEE AGREEMENT\b', "Employment Contract"),
        (r'\bMEDICAL\b|\bHIPAA\b|\bPATIENT\b',                          "Medical Consent Form"),
        (r'\bLOAN\b|\bPROMISSORY NOTE\b|\bBORROWER\b',                  "Loan Agreement"),
        (r'\bTERMS OF SERVICE\b|\bTERMS AND CONDITIONS\b',               "Terms of Service"),
        (r'\bINDEPENDENT CONTRACTOR\b|\bCONSULTING AGREEMENT\b',        "Consulting/Contractor Agreement"),
        (r'\bPURCHASE AGREEMENT\b|\bSALE AGREEMENT\b|\bBUYER\b',         "Purchase Agreement"),
        (r'\bPARTNERSHIP AGREEMENT\b',                                   "Partnership Agreement"),
        (r'\bSERVICE AGREEMENT\b|\bSOW\b|\bSTATEMENT OF WORK\b',        "Service Agreement"),
    ]
    for pattern, label in checks:
        if re.search(pattern, first):
            return label
    return "Legal Document (General)"


# ─────────────────────────────────────────────────────────────────────────────
# Main public entry point — called directly by app.py
# ─────────────────────────────────────────────────────────────────────────────

def analyze_document(pages: list) -> dict:
    """
    Analyze a list of page dicts from pdf_processor.extract_pages() and
    return a structured risk report.

    Input:
        pages: [{"page_number": int, "text": str}, ...]

    Output (identical structure — app.py needs zero changes):
        {
            "document_type":   str,
            "bullet_points":   list[dict],
            "overall_risk":    "HIGH" | "MEDIUM" | "LOW",
            "total_pages":     int,
            "total_points":    int,
            "unfilled_fields": list[str],
        }

    Each bullet_point dict (exact keys that app.py reads):
        {
            "number":        int,
            "risk_level":    "HIGH" | "MEDIUM" | "LOW",
            "section":       str,   <- Groq's "title"
            "quote":         str,   <- Groq's "reason"
            "plain_english": str,   <- Groq's "explanation"
            "page_numbers":  list[int],
        }
    """
    # ── Build chunks ──────────────────────────────────────────────────────────
    chunks = build_chunks(pages, max_words=150)
    chunks = chunks[:50]

    results          = []
    seen_explanations = set()

    # ── Process each chunk ────────────────────────────────────────────────────
    for chunk in chunks:
        text         = chunk.get("chunk_text", "").strip()
        page_numbers = chunk.get("page_numbers", [])

        # Skip tiny chunks
        if len(text) < 50:
            continue

        # ── Call Groq ─────────────────────────────────────────────────────────
        result = analyze_chunk(text)

        if result is None:
            time.sleep(0.3)
            continue

        # ── Normalise risk_level ──────────────────────────────────────────────
        risk_level = str(result.get("risk_level", "LOW")).upper().strip()
        if risk_level not in ("HIGH", "MEDIUM", "LOW"):
            risk_level = "LOW"



        # ── Deduplication: first 30 chars of explanation ──────────────────────
        explanation = str(result.get("explanation", "")).strip()
        dedup_key   = explanation[:30].lower().strip()
        if dedup_key in seen_explanations or not dedup_key:
            time.sleep(0.3)
            continue
        seen_explanations.add(dedup_key)

        # ── Build bullet point using keys app.py expects ──────────────────────
        results.append({
            "risk_level":    risk_level,
            "section":       str(result.get("title", "Legal Clause")).strip(),
            "quote":         str(result.get("reason", "")).strip(),
            "plain_english": explanation,
            "page_numbers":  page_numbers,
        })

        time.sleep(0.3)   # stay within free-tier rate limits

    # ── Sort: HIGH → MEDIUM → LOW ─────────────────────────────────────────────
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    results.sort(key=lambda x: order.get(x["risk_level"], 2))

    # ── Cap at 20 ─────────────────────────────────────────────────────────────
    final = results[:20]

    # ── Fallback: nothing was extracted ──────────────────────────────────────
    if not final:
        return {
            "document_type": _detect_document_type(pages),
            "bullet_points": [
                {
                    "number":        1,
                    "risk_level":    "LOW",
                    "section":       "Analysis Failed",
                    "quote":         "API error or no important clauses found.",
                    "plain_english": (
                        "Could not analyze this document. "
                        "Check that GROQ_API_KEY is set correctly in your .env file."
                    ),
                    "page_numbers":  [],
                }
            ],
            "overall_risk":    "LOW",
            "total_pages":     len(pages),
            "total_points":    1,
            "unfilled_fields": _detect_unfilled_fields(pages),
        }

    # ── Number sequentially ───────────────────────────────────────────────────
    for idx, pt in enumerate(final, start=1):
        pt["number"] = idx

    # ── Overall risk ──────────────────────────────────────────────────────────
    risk_levels = [b["risk_level"] for b in final]
    if "HIGH" in risk_levels:
        overall = "HIGH"
    elif "MEDIUM" in risk_levels:
        overall = "MEDIUM"
    else:
        overall = "LOW"

    return {
        "document_type":   _detect_document_type(pages),
        "bullet_points":   final,
        "overall_risk":    overall,
        "total_pages":     len(pages),
        "total_points":    len(final),
        "unfilled_fields": _detect_unfilled_fields(pages),
    }
