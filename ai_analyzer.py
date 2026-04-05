"""
ai_analyzer.py — AI-powered legal document analysis using google/flan-t5-base
"""

import streamlit as st
import os
os.environ["USE_TF"] = "0"
os.environ["USE_TORCH"] = "1"
from pdf_processor import build_chunks

# ─────────────────────────────────────────────────────────────────────────────
# Risk keyword lists
# ─────────────────────────────────────────────────────────────────────────────

HIGH_RISK_KEYWORDS = [
    "terminate", "termination", "penalty", "penalties", "forfeit",
    "liable", "liability", "indemnify", "indemnification", "waive",
    "irrevocable", "non-refundable", "unlimited liability",
    "exclusive jurisdiction", "arbitration only", "no refund",
    "auto-renew", "personal guarantee", "collateral", "lien"
]

MEDIUM_RISK_KEYWORDS = [
    "reserves the right", "at its discretion", "subject to change",
    "without notice", "binding", "may terminate", "may modify",
    "late fee", "interest on overdue", "governing law", "jurisdiction"
]


# ─────────────────────────────────────────────────────────────────────────────
# Model loader — cached so the model is only downloaded / loaded once
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_resource(show_spinner=False)
def load_model():
    """
    Loads the google/flan-t5-base text2text-generation pipeline.
    Decorated with @st.cache_resource so it is initialised only once
    per Streamlit server process.

    Returns:
        A HuggingFace transformers pipeline object.
    """
    from transformers import pipeline
    pipe = pipeline(
        "text2text-generation",
        model="google/flan-t5-base",
        max_new_tokens=200
    )
    return pipe


# ─────────────────────────────────────────────────────────────────────────────
# Risk detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_risk_by_keywords(text: str) -> str:
    """
    Scans the chunk text for risk keywords.

    Returns:
        "HIGH"   if any HIGH_RISK_KEYWORDS found.
        "MEDIUM" if any MEDIUM_RISK_KEYWORDS found (and no high-risk ones).
        "LOW"    otherwise.
    """
    lower_text = text.lower()

    for kw in HIGH_RISK_KEYWORDS:
        if kw in lower_text:
            return "HIGH"

    for kw in MEDIUM_RISK_KEYWORDS:
        if kw in lower_text:
            return "MEDIUM"

    return "LOW"


# ─────────────────────────────────────────────────────────────────────────────
# Chunk analysis
# ─────────────────────────────────────────────────────────────────────────────

def analyze_chunk(pipe, chunk_text: str) -> str:
    """
    Sends the chunk to the flan-t5 model with a plain-English summarisation
    prompt and returns the generated summary string.

    Falls back to a safe error message if generation fails.
    """
    prompt = (
        "Summarize the following legal clause in one clear, plain English sentence "
        "that a non-lawyer can understand. Focus on what it means for the reader. "
        f"Legal text: {chunk_text}"
    )
    try:
        result = pipe(prompt)
        generated = result[0]["generated_text"].strip()
        if not generated:
            return "Could not analyze this section."
        return generated
    except Exception as e:
        print(f"[ai_analyzer] analyze_chunk error: {e}")
        return "Could not analyze this section."


# ─────────────────────────────────────────────────────────────────────────────
# Full document analysis
# ─────────────────────────────────────────────────────────────────────────────

def analyze_document(pages: list) -> dict:
    """
    Full pipeline: chunk → summarise → risk-tag → deduplicate → prioritise.

    Args:
        pages: Output of pdf_processor.extract_pages()

    Returns:
        {
            "bullet_points": [
                {
                    "point":        "Plain English text …",
                    "page_numbers": [2, 3],
                    "risk_level":   "HIGH" | "MEDIUM" | "LOW"
                },
                …
            ],
            "overall_risk":  "HIGH" | "MEDIUM" | "LOW",
            "total_pages":   <int>,
            "total_points":  <int>
        }
    """
    pipe = load_model()
    chunks = build_chunks(pages, max_words=350)

    # Cap at 25 chunks to avoid long runtimes
    chunks = chunks[:25]

    raw_results = []
    seen_points = set()

    import re

    for chunk in chunks:
        summary = analyze_chunk(pipe, chunk["chunk_text"])
        risk = detect_risk_by_keywords(chunk["chunk_text"])

        if "Could not analyze this section" in summary:
            continue

        # Normalize to ignore minor punctuation/casing differences in deduplication
        norm_summary = re.sub(r'[^a-z0-9]', '', summary.lower())
        
        if not norm_summary or norm_summary in seen_points:
            continue
            
        seen_points.add(norm_summary)

        raw_results.append({
            "point":        summary,
            "page_numbers": chunk["page_numbers"],
            "risk_level":   risk
        })

    # ── Prioritise: HIGH first, then MEDIUM, then LOW ────────────────────────
    high   = [r for r in raw_results if r["risk_level"] == "HIGH"]
    medium = [r for r in raw_results if r["risk_level"] == "MEDIUM"]
    low    = [r for r in raw_results if r["risk_level"] == "LOW"]

    prioritised = high + medium + low

    # Keep less than 15 points (max 14)
    if len(prioritised) > 14:
        # Always include at least all HIGH items, then fill to 14
        selected = high[:14]
        remaining_slots = 14 - len(selected)
        if remaining_slots > 0:
            selected += (medium + low)[:remaining_slots]
    else:
        selected = prioritised

    # ── Overall risk ─────────────────────────────────────────────────────────
    risk_levels = [r["risk_level"] for r in selected]
    if "HIGH" in risk_levels:
        overall_risk = "HIGH"
    elif "MEDIUM" in risk_levels:
        overall_risk = "MEDIUM"
    else:
        overall_risk = "LOW"

    return {
        "bullet_points": selected,
        "overall_risk":  overall_risk,
        "total_pages":   len(pages),
        "total_points":  len(selected)
    }
