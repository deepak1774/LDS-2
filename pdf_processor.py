"""
pdf_processor.py — PDF text extraction and chunking for Legal Document Simplifier
"""

import fitz  # PyMuPDF


def extract_pages(pdf_bytes: bytes) -> list:
    """
    Opens a PDF from raw bytes and extracts the text of each page.

    Args:
        pdf_bytes: Raw bytes of the PDF file.

    Returns:
        A list of dicts: [{"page_number": 1, "text": "..."}, ...]
        Pages with no extractable text are skipped.
    """
    pages = []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for page_index in range(len(doc)):
            page = doc[page_index]
            text = page.get_text("text")
            if text and text.strip():
                pages.append({
                    "page_number": page_index + 1,
                    "text": text.strip()
                })
        doc.close()
    except Exception as e:
        # Return empty list on unrecoverable errors; caller handles this
        print(f"[pdf_processor] Error extracting pages: {e}")
        return []
    return pages


def build_chunks(pages: list, max_words: int = 350) -> list:
    """
    Splits page texts into chunks of at most max_words words.

    Each chunk carries the page number(s) it came from so the UI
    can display "Page X" or "Pages X, Y" next to each bullet point.

    Args:
        pages:     Output of extract_pages().
        max_words: Maximum number of words per chunk.

    Returns:
        A list of dicts: [{"chunk_text": "...", "page_numbers": [3]}, ...]
    """
    chunks = []

    for page in pages:
        page_num = page["page_number"]
        words = page["text"].split()

        if not words:
            continue

        # Split this page's words into sub-chunks of max_words each
        for start in range(0, len(words), max_words):
            chunk_words = words[start: start + max_words]
            chunk_text = " ".join(chunk_words)
            if chunk_text.strip():
                chunks.append({
                    "chunk_text": chunk_text,
                    "page_numbers": [page_num]
                })

    return chunks
