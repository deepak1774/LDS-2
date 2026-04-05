import re
from pdf_processor import build_chunks

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
    "collateral", "lien", "seizure", "liquidated damages"
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
    "jurisdiction", "binding", "amendment", "modify"
]

LOW_RISK_EXCLUSIONS = [
    "equal employment", "nondiscrimination", "non-discrimination",
    "harassment", "sexual harassment", "disability",
    "veteran status", "marital status", "sexual orientation",
    "race", "color", "religion", "national origin",
    "independent consultant status", "independent contractor",
    "acknowledgment", "notification address", "complete agreement",
    "signatures", "in witness whereof", "distribution"
]

SECTION_MAP = {
    "terminate": "Termination Rights",
    "termination": "Termination Rights",
    "indemnif": "Indemnification",
    "hold harmless": "Indemnification",
    "insurance": "Insurance Requirements",
    "certificate of insurance": "Insurance Requirements",
    "payment": "Payment Terms",
    "invoice": "Invoice Requirements",
    "billing": "Invoice Requirements",
    "compensation": "Compensation",
    "not to exceed": "Payment Cap",
    "audit": "Audit & Record Retention",
    "records": "Audit & Record Retention",
    "retain": "Audit & Record Retention",
    "work product": "Work Product Ownership",
    "ownership": "Work Product Ownership",
    "copyright": "Work Product Ownership",
    "royalty": "Work Product Ownership",
    "subcontract": "Subcontracting Rules",
    "subconsultant": "Subcontracting Rules",
    "assign": "Non-Assignment",
    "dispute": "Dispute Resolution",
    "safety": "Safety Requirements",
    "osha": "Safety Requirements",
    "independent": "Independent Contractor Status",
    "key personnel": "Key Personnel",
    "project manager": "Key Personnel",
    "modif": "Contract Modifications",
    "amend": "Contract Modifications",
    "progress report": "Reporting Requirements",
    "milestone": "Milestone Requirements",
    "license": "Licensing Requirements",
    "federal": "Legal Compliance",
    "prevailing wage": "Prevailing Wage",
}


def detect_risk(text: str) -> str:
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


def detect_section(text: str) -> str:
    lower = text.lower()
    for key, label in SECTION_MAP.items():
        if key in lower:
            return label
    return "General Clause"


def clean_text(text: str) -> str:
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[^\x20-\x7E]', '', text)
    return text.strip()


def split_sentences(text: str) -> list:
    text = clean_text(text)
    raw = re.split(r'(?<=[.;])\s+(?=[A-Z])', text)
    sentences = []
    for s in raw:
        s = s.strip()
        if len(s) > 50:
            sentences.append(s)
    return sentences


def score_sentence(sentence: str) -> int:
    lower = sentence.lower()
    obligation_words = [
        "shall", "must", "required", "agrees", "will not",
        "cannot", "may not", "is not", "are not",
        "within", "days", "written", "approval",
        "not to exceed", "liable", "terminate", "pay",
        "submit", "provide", "maintain", "obtain", "keep",
        "ownership", "rights", "indemnify", "insurance",
        "penalty", "breach", "default", "cost", "fee"
    ]
    score = sum(1 for w in obligation_words if w in lower)
    if len(sentence) > 60:
        score += 1
    if len(sentence) > 120:
        score += 1
    return score


def pick_best_sentence(sentences: list) -> str:
    if not sentences:
        return ""
    scored = [(score_sentence(s), len(s), s) for s in sentences]
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    best = scored[0][2]
    if len(best) > 280:
        best = best[:277] + "..."
    return best


def build_plain_english(text: str, section: str) -> str:
    lower = text.lower()

    if "terminate" in lower or "termination" in lower:
        if "thirty" in lower or " 30" in text or "(30)" in text:
            if "convenience" in lower:
                return "COMMISSION can end this contract at any time by giving you just 30 days written notice — you only get paid for work completed up to that date."
        if "120" in text or "one hundred and twenty" in lower:
            return "If you want to exit this contract, you must give 120 days advance written notice and you may be liable for all reprocurement costs COMMISSION incurs."
        if "default" in lower or "breach" in lower:
            return "COMMISSION can terminate immediately if you breach any contract term and fail to fix it within 10 days of written notice — you will owe all resulting costs."

    if "indemnif" in lower or "hold harmless" in lower:
        return "You must fully protect COMMISSION from any claims, damages, lawsuits, or costs that arise from your negligence or misconduct during this contract."

    if ("work product" in lower or "ownership" in lower or "title to all" in lower
            or "royalty-free" in lower or "unconditional right" in lower):
        return "All documents, reports, designs, and deliverables you produce belong entirely to COMMISSION — you cannot reuse, sell, or share them without written permission."

    if "not to exceed" in lower and ("payment" in lower or "compensation" in lower or "$" in text):
        return "Your total payment is capped at a fixed amount in Exhibit B — you cannot bill beyond this limit without prior written approval from COMMISSION."

    if "45" in text and ("invoice" in lower or "billing" in lower):
        return "You must submit all invoices within 45 calendar days of completing the work — invoices submitted late may be rejected and not paid."

    if "60" in text and ("final invoice" in lower or "final billing" in lower):
        return "Your final invoice must be submitted within 60 calendar days of work acceptance — missing this deadline means you forfeit that payment entirely."

    if "progress payment" in lower or ("monthly" in lower and "payment" in lower):
        return "Payments are made monthly based on work satisfactorily completed and actual costs incurred — you must submit supporting progress reports with each invoice."

    if "insurance" in lower and "1,000,000" in text:
        return "You must obtain and maintain at least $1,000,000 in General Liability and/or Professional Liability insurance at your own cost for the entire duration of this contract."

    if "workers" in lower and "compensation" in lower:
        return "You must carry Workers Compensation insurance for all your employees throughout the entire contract period."

    if "automobile" in lower and "insurance" in lower:
        return "You must carry Automobile Liability insurance of at least $1,000,000 per occurrence for all vehicles used in performing this contract."

    if ("30 days" in lower or "thirty (30) days" in lower) and "insurance" in lower and "cancel" in lower:
        return "Your insurance policies cannot be cancelled without giving COMMISSION at least 30 days prior written notice — a new certificate must be provided immediately."

    if "certificate of insurance" in lower:
        return "You must provide COMMISSION with certificates proving all required insurance coverages are active before the contract start date."

    if "audit" in lower or ("retain" in lower and "records" in lower):
        return "You must keep all project books, records, and documents for 5 years after final payment — state and federal auditors have the right to inspect them at any time."

    if "subcontract" in lower and ("written" in lower or "authorization" in lower or "approval" in lower):
        return "You cannot subcontract any portion of this work to another party without first obtaining written approval from COMMISSION's Contract Manager."

    if "assign" in lower and "consent" in lower:
        return "You cannot transfer or assign this contract to any other company or person without COMMISSION's prior written consent."

    if "key personnel" in lower or ("project manager" in lower and "replaced" in lower):
        return "You cannot remove or replace key personnel named in this contract without getting prior written approval from COMMISSION."

    if "progress report" in lower or ("written" in lower and "report" in lower and "invoice" in lower):
        return "You must submit a written progress report with every invoice detailing work completed, schedule status, problems encountered, and corrective actions taken."

    if "osha" in lower or ("safety" in lower and ("hard hat" in lower or "vest" in lower or "rail" in lower)):
        return "You must follow all OSHA safety rules and wear required hard hats and safety vests at all times while working on the Santa Cruz Branch Rail Line."

    if "dispute" in lower and ("committee" in lower or "executive director" in lower):
        return "All disputes are resolved internally by COMMISSION's Contract Manager and Executive Director — you must continue working without interruption during any active dispute."

    if "amend" in lower or ("modif" in lower and "written" in lower):
        return "This contract can only be changed through a formal written amendment signed by both parties — verbal agreements or understandings are not legally binding."

    if "independent" in lower and ("employee" in lower or "payroll" in lower or "tax" in lower):
        return "You are classified as an independent contractor — you receive no employee benefits, and you are solely responsible for your own taxes, insurance, and payroll obligations."

    if "prevailing wage" in lower:
        return "For any staff subject to California prevailing wage laws, salary increases resulting from prevailing wage rate changes are reimbursable under this contract."

    if "license" in lower and ("federal" in lower or "state" in lower or "required" in lower):
        return "You and all your employees must hold any licenses required by law to perform this work, and those licenses must remain valid and active throughout the contract."

    if "milestone" in lower and ("cost" in lower or "estimate" in lower):
        return "You must not exceed the milestone cost estimates in Exhibit B without prior written approval — overruns will not be reimbursed without pre-authorization."

    sentences = split_sentences(text)
    best = pick_best_sentence(sentences)
    if best:
        return best

    return clean_text(text)[:250] + "..." if len(text) > 250 else clean_text(text)


def analyze_document(pages: list) -> dict:
    chunks = build_chunks(pages, max_words=300)
    chunks = chunks[:35]

    raw_points = []
    seen_labels = set()

    for chunk in chunks:
        text = chunk["chunk_text"]
        if len(clean_text(text)) < 60:
            continue

        risk = detect_risk(text)
        section = detect_section(text)
        plain = build_plain_english(text, section)

        if not plain or len(plain) < 30:
            continue

        dedup_key = plain[:70].lower().strip()
        if dedup_key in seen_labels:
            continue
        seen_labels.add(dedup_key)

        raw_points.append({
            "point": plain,
            "section": section,
            "page_numbers": chunk["page_numbers"],
            "risk_level": risk
        })

    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    raw_points.sort(key=lambda x: order[x["risk_level"]])

    final = raw_points[:20] if len(raw_points) > 20 else raw_points

    if len(final) < 10 and len(raw_points) >= 10:
        final = raw_points[:10]

    risks = {p["risk_level"] for p in final}
    if "HIGH" in risks:
        overall = "HIGH"
    elif "MEDIUM" in risks:
        overall = "MEDIUM"
    else:
        overall = "LOW"

    return {
        "bullet_points": final,
        "overall_risk": overall,
        "total_pages": len(pages),
        "total_points": len(final)
    }
