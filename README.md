# Legal Document Simplifier

An AI-powered web application that converts complex legal documents into plain English, highlights risky clauses, and tracks per-user document history.

---

## Setup

1. **Install Python 3.10+**

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the app**
   ```bash
   streamlit run app.py
   ```

4. Open your browser at **http://localhost:8501**

---

## Default Login Credentials

| Username | Password  |
|----------|-----------|
| admin    | admin123  |
| user1    | user123   |
| user2    | user456   |

---

## First Run Note

On first run the app will download the AI model **google/flan-t5-base** (~250 MB) from HuggingFace.
This happens **only once** — subsequent runs use the locally cached model.

---

## Tech Stack

| Layer            | Technology                             |
|------------------|----------------------------------------|
| UI Framework     | Streamlit                              |
| AI Model         | google/flan-t5-base (HuggingFace)      |
| PDF Extraction   | PyMuPDF (fitz)                         |
| Database         | SQLite (Python built-in)               |
| Password Security| bcrypt                                 |

---

## Features

- **Login system** — per-user document history stored in SQLite
- **PDF upload** — full-text extraction with per-page tracking
- **AI analysis** — 10–20 plain-English bullet points per document
- **Risk detection** — HIGH / MEDIUM / LOW flags per bullet point
- **Page references** — every bullet point shows its source page(s)
- **Save analyses** — store, rename, and delete past results
- **Dark UI** — premium black & blue Streamlit theme
- **No paid APIs** — 100% free and open-source stack

---

## Project Structure

```
LDS-2/
├── app.py              # Main Streamlit application
├── ai_analyzer.py      # Flan-T5 model + risk detection
├── pdf_processor.py    # PyMuPDF text extraction & chunking
├── auth.py             # bcrypt login helpers
├── database.py         # SQLite CRUD layer
├── requirements.txt    # Pinned dependencies
├── legal_app.db        # SQLite database (auto-created on first run)
└── README.md
```

---

## Usage

1. Log in with any of the default credentials.
2. Go to the **"📄 Analyze New Document"** tab.
3. Upload a PDF legal document.
4. Click **"🔍 Analyze Document"** — the AI will return 10–20 simplified bullet points with risk flags and page numbers.
5. Optionally **save** the analysis with a custom name.
6. View, rename, or delete past analyses in the **"📚 Saved Documents"** tab or the sidebar.
