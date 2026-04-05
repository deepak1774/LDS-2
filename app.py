"""
app.py — Main Streamlit application for Legal Document Simplifier
"""

import streamlit as st
import json
import datetime

from database import (
    init_db,
    save_document,
    get_user_documents,
    get_document_by_id,
    update_document_name,
    delete_document,
)
from auth import login_user
from pdf_processor import extract_pages
from ai_analyzer import analyze_document

# ─────────────────────────────────────────────────────────────────────────────
# Page configuration — MUST be the very first Streamlit call
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Legal Document Simplifier",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Global CSS — black & blue theme
# ─────────────────────────────────────────────────────────────────────────────

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    /* ── Base ── */
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    .stApp {
        background-color: #0d0d0d;
        color: #e0e8ff;
    }

    /* ── Sidebar ── */
    [data-testid="stSidebar"] {
        background-color: #111111 !important;
    }
    [data-testid="stSidebar"] * {
        color: #ccddff !important;
    }

    /* ── Inputs ── */
    .stTextInput > div > div > input,
    .stTextArea > div > div > textarea {
        background-color: #1a1a1a !important;
        border: 1px solid #1e50d0 !important;
        color: #ffffff !important;
        border-radius: 6px !important;
    }

    /* ── Buttons ── */
    .stButton > button {
        background-color: #1a55e3 !important;
        color: #ffffff !important;
        border: none !important;
        border-radius: 6px !important;
        font-weight: 600 !important;
        padding: 10px 24px !important;
        transition: background-color 0.2s ease !important;
    }
    .stButton > button:hover {
        background-color: #1440b5 !important;
        border: none !important;
    }

    /* ── Tabs ── */
    .stTabs [data-baseweb="tab"] {
        color: #8899bb !important;
        font-weight: 500;
    }
    .stTabs [aria-selected="true"] {
        color: #4d7fff !important;
        border-bottom: 2px solid #4d7fff !important;
    }

    /* ── Expanders ── */
    .streamlit-expanderHeader {
        background-color: #151515 !important;
        border: 1px solid #1e3a7a !important;
        color: #ccddff !important;
    }
    .streamlit-expanderContent {
        background-color: #151515 !important;
        border: 1px solid #1e3a7a !important;
    }

    /* ── Alert overrides ── */
    div[data-testid="stAlert"] {
        border-radius: 6px !important;
    }
    /* success */
    .stSuccess {
        background-color: #0a2040 !important;
        color: #4d9fff !important;
        border: 1px solid #1a4a80 !important;
    }
    /* error */
    .stError {
        background-color: #1a0808 !important;
        color: #ff4444 !important;
        border: 1px solid #550000 !important;
    }
    /* warning */
    .stWarning {
        background-color: #1a1200 !important;
        color: #ffcc00 !important;
        border: 1px solid #554400 !important;
    }

    /* ── Metric cards ── */
    [data-testid="stMetric"] {
        background-color: #121826 !important;
        border: 1px solid #1e3a7a !important;
        border-radius: 8px !important;
        padding: 16px !important;
        margin: 6px 0 !important;
    }
    [data-testid="stMetricLabel"] {
        color: #8899bb !important;
    }
    [data-testid="stMetricValue"] {
        color: #e0e8ff !important;
    }

    /* ── Custom bullet classes ── */
    .bullet-high {
        border-left: 4px solid #ff3333;
        background: #1a0505;
        padding: 12px;
        border-radius: 0 8px 8px 0;
        margin: 8px 0;
    }
    .bullet-medium {
        border-left: 4px solid #ffaa00;
        background: #1a1000;
        padding: 12px;
        border-radius: 0 8px 8px 0;
        margin: 8px 0;
    }
    .bullet-low {
        border-left: 4px solid #1a6bff;
        background: #050d1a;
        padding: 12px;
        border-radius: 0 8px 8px 0;
        margin: 8px 0;
    }

    /* ── Metric card class ── */
    .metric-card {
        background: #121826;
        border: 1px solid #1e3a7a;
        border-radius: 8px;
        padding: 16px;
        margin: 6px 0;
    }

    /* ── Scrollbar ── */
    ::-webkit-scrollbar {
        width: 8px;
        height: 8px;
    }
    ::-webkit-scrollbar-track {
        background: #111111;
    }
    ::-webkit-scrollbar-thumb {
        background: #1e3a7a;
        border-radius: 4px;
    }
    ::-webkit-scrollbar-thumb:hover {
        background: #1a55e3;
    }

    /* ── File uploader ── */
    [data-testid="stFileUploader"] {
        background-color: #1a1a1a !important;
        border: 1px dashed #1e50d0 !important;
        border-radius: 8px !important;
    }

    /* ── General text colour ── */
    p, li, span, label {
        color: #e0e8ff;
    }
    h1, h2, h3, h4 {
        color: #e0e8ff;
    }

    /* ── Divider ── */
    hr {
        border-color: #1e3a7a !important;
    }

    /* ── Selectbox / dropdown ── */
    .stSelectbox > div > div {
        background-color: #1a1a1a !important;
        border: 1px solid #1e50d0 !important;
        color: #ffffff !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# Initialise database and session state
# ─────────────────────────────────────────────────────────────────────────────

init_db()

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user" not in st.session_state:
    st.session_state.user = None
if "current_analysis" not in st.session_state:
    st.session_state.current_analysis = None
if "current_pdf_name" not in st.session_state:
    st.session_state.current_pdf_name = None
if "editing_doc_id" not in st.session_state:
    st.session_state.editing_doc_id = None
if "viewing_doc_id" not in st.session_state:
    st.session_state.viewing_doc_id = None
if "confirm_delete_id" not in st.session_state:
    st.session_state.confirm_delete_id = None


# ─────────────────────────────────────────────────────────────────────────────
# Helper utilities
# ─────────────────────────────────────────────────────────────────────────────

def _format_date(date_str: str) -> str:
    """Convert a SQLite datetime string to 'DD Mon YYYY' format."""
    try:
        dt = datetime.datetime.strptime(date_str[:19], "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%d %b %Y")
    except Exception:
        return date_str or ""


def _risk_banner_html(overall_risk: str) -> str:
    """Return the HTML for the overall risk banner."""
    if overall_risk == "HIGH":
        bg     = "#1a0000"
        border = "#ff3333"
        text   = "🔴 OVERALL RISK: HIGH"
        color  = "#ff6666"
    elif overall_risk == "MEDIUM":
        bg     = "#1a1000"
        border = "#ffaa00"
        text   = "🟡 OVERALL RISK: MEDIUM"
        color  = "#ffcc44"
    else:
        bg     = "#050d1a"
        border = "#1a6bff"
        text   = "🔵 OVERALL RISK: LOW"
        color  = "#6699ff"

    return (
        f'<div style="background:{bg};border:2px solid {border};border-radius:8px;'
        f'padding:16px;text-align:center;margin:12px 0;">'
        f'<span style="color:{color};font-size:20px;font-weight:700;">{text}</span>'
        f'</div>'
    )


def _risk_badge_html(risk_level: str) -> str:
    """Return the inline HTML badge for HIGH / MEDIUM / LOW."""
    styles = {
        "HIGH":   ("background:#550000;color:#ff6666", "🔴 HIGH RISK"),
        "MEDIUM": ("background:#443300;color:#ffcc44", "🟡 MEDIUM RISK"),
        "LOW":    ("background:#051030;color:#6699ff", "🔵 LOW RISK"),
    }
    style, label = styles.get(risk_level, styles["LOW"])
    return (
        f'<span style="{style};padding:2px 8px;border-radius:4px;font-size:12px;'
        f'font-weight:600;">{label}</span>'
    )


def _page_badge_html(page_numbers: list) -> str:
    """Return the inline HTML badge for page number(s)."""
    if len(page_numbers) == 1:
        label = f"📄 Page {page_numbers[0]}"
    else:
        pages_str = ", ".join(str(p) for p in page_numbers)
        label = f"📄 Pages {pages_str}"
    return (
        f'<span style="background:#0a1a30;color:#88aadd;padding:2px 8px;'
        f'border-radius:4px;font-size:12px;">{label}</span>'
    )


def _render_analysis_results(result: dict, show_save: bool = False, user_id: int = None, pdf_name: str = None):
    """
    Renders the full analysis result (risk banner + stats + bullets).
    If show_save is True, also renders the save section.
    """
    # -- Overall risk banner --------------------------------------------------
    st.markdown(_risk_banner_html(result["overall_risk"]), unsafe_allow_html=True)

    # -- Stats row ------------------------------------------------------------
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Pages Scanned", result["total_pages"])
    with col2:
        st.metric("Key Points Found", result["total_points"])
    with col3:
        st.metric("Overall Risk Level", result["overall_risk"])

    # -- Bullet points --------------------------------------------------------
    st.markdown("### 📋 Simplified Analysis — Key Points")

    bullet_points = result.get("bullet_points", [])
    if not bullet_points:
        st.info("No key points could be extracted from this document.")
    else:
        for idx, item in enumerate(bullet_points, start=1):
            risk      = item.get("risk_level", "LOW")
            page_nums = item.get("page_numbers", [])
            point     = item.get("point", "")

            css_class   = {"HIGH": "bullet-high", "MEDIUM": "bullet-medium"}.get(risk, "bullet-low")
            risk_badge  = _risk_badge_html(risk)
            page_badge  = _page_badge_html(page_nums) if page_nums else ""

            html = (
                f'<div class="{css_class}">'
                f'<div style="margin-bottom:6px;">'
                f'<span style="color:#8899bb;font-size:13px;margin-right:8px;">#{idx}</span>'
                f'{risk_badge}&nbsp;&nbsp;{page_badge}'
                f'</div>'
                f'<div style="color:#e0e8ff;line-height:1.6;margin-top:6px;">{point}</div>'
                f'</div>'
            )
            st.markdown(html, unsafe_allow_html=True)

    # -- Save section ---------------------------------------------------------
    if show_save and user_id is not None:
        st.divider()
        st.markdown("### 💾 Save This Analysis")

        default_name = (pdf_name or "document").rsplit(".", 1)[0]
        doc_name_input = st.text_input(
            "Document name:",
            value=default_name,
            key="save_name_input"
        )

        if st.button("💾 Save Analysis", key="btn_save_analysis"):
            save_document(
                user_id=user_id,
                doc_name=doc_name_input,
                original_filename=pdf_name or "",
                analysis_json=json.dumps(result)
            )
            st.success(f"✅ Saved as '{doc_name_input}' successfully!")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE A — LOGIN
# ─────────────────────────────────────────────────────────────────────────────

def render_login_page():
    _, center, _ = st.columns([1, 2, 1])

    with center:
        st.markdown(
            """
            <div style="text-align:center;padding:40px 0 20px 0;">
                <div style="font-size:48px;">⚖️</div>
                <h1 style="color:#4d7fff;margin:12px 0 4px 0;font-size:32px;">
                    Legal Document Simplifier
                </h1>
                <p style="color:#8899bb;font-size:16px;margin:0;">
                    AI-Powered Legal Analysis
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            '<hr style="border-color:#1e3a7a;margin:16px 0;">',
            unsafe_allow_html=True,
        )

        username = st.text_input(
            "Username",
            placeholder="Enter your username",
            key="login_username"
        )
        password = st.text_input(
            "Password",
            type="password",
            placeholder="Enter your password",
            key="login_password"
        )

        if st.button("Login", key="btn_login", use_container_width=True):
            if not username.strip():
                st.error("Please enter your username.")
            elif not password:
                st.error("Please enter your password.")
            else:
                user = login_user(username, password)
                if user is not None:
                    st.session_state.logged_in = True
                    st.session_state.user = user
                    st.rerun()
                else:
                    st.error("Invalid username or password. Please try again.")

        st.markdown(
            '<p style="text-align:center;color:#556688;font-size:13px;margin-top:16px;">'
            "Default: admin / admin123 &nbsp;•&nbsp; user1 / user123 &nbsp;•&nbsp; user2 / user456"
            "</p>",
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# PAGE B — MAIN APP
# ─────────────────────────────────────────────────────────────────────────────

def render_sidebar():
    """Renders the sidebar with saved documents and logout."""
    with st.sidebar:
        st.markdown(
            '<h2 style="color:#4d7fff;">⚖️ Legal Doc Simplifier</h2>',
            unsafe_allow_html=True,
        )
        username = st.session_state.user.get("username", "User")
        st.markdown(
            f'<p style="color:#aabbdd;font-size:15px;">👤 {username}</p>',
            unsafe_allow_html=True,
        )
        st.divider()

        st.markdown(
            '<p style="color:#4d7fff;font-weight:600;font-size:14px;">📂 My Saved Documents</p>',
            unsafe_allow_html=True,
        )

        docs = get_user_documents(st.session_state.user["id"])

        if not docs:
            st.markdown(
                '<p style="color:#556688;font-size:13px;">No saved documents yet.</p>',
                unsafe_allow_html=True,
            )
        else:
            for doc in docs:
                name = doc["doc_name"]
                display_name = name[:30] + "…" if len(name) > 30 else name
                date_str     = _format_date(doc.get("created_at", ""))

                st.markdown(
                    f"""
                    <div style="background:#161b2a;border:1px solid #1e3a7a;border-radius:6px;
                                padding:8px 10px;margin-bottom:6px;">
                        <div style="color:#c8d8ff;font-weight:500;font-size:14px;">{display_name}</div>
                        <div style="color:#556688;font-size:12px;">{date_str}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                if st.button("📂 View", key=f"sidebar_view_{doc['id']}"):
                    try:
                        analysis = json.loads(doc["analysis_json"])
                        st.session_state.current_analysis = analysis
                        st.session_state.current_pdf_name = doc.get("original_filename", doc["doc_name"])
                        st.session_state.viewing_doc_id   = doc["id"]
                    except Exception:
                        st.error("Could not load this document's analysis.")
                    st.rerun()

        st.divider()

        if st.button("🚪 Logout", key="btn_logout", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()


def render_tab1():
    """Tab 1 — Analyze New Document."""
    st.markdown(
        '<h2 style="color:#4d7fff;">Upload a Legal Document for AI Analysis</h2>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p style="color:#8899bb;">Supports PDF files &nbsp;•&nbsp; Results in 10–20 plain English '
        'bullet points with page numbers and risk flags</p>',
        unsafe_allow_html=True,
    )

    uploaded_file = st.file_uploader(
        "Choose a PDF file",
        type=["pdf"],
        key="pdf_uploader"
    )

    if uploaded_file is not None:
        file_size_kb = round(uploaded_file.size / 1024, 1)
        st.markdown(
            f"""
            <div style="background:#121826;border:1px solid #1e3a7a;border-radius:6px;
                        padding:10px 14px;margin:8px 0;display:inline-block;">
                <span style="color:#88aadd;">📄 {uploaded_file.name}</span>
                &nbsp;&nbsp;
                <span style="color:#556688;font-size:13px;">{file_size_kb} KB</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if st.button("🔍 Analyze Document", key="btn_analyze", type="primary"):
            with st.spinner(
                "Analyzing your legal document with AI… "
                "This may take 1–2 minutes on first run while the model loads."
            ):
                pdf_bytes = uploaded_file.read()
                pages = extract_pages(pdf_bytes)

                if not pages:
                    st.error(
                        "Could not extract text from PDF. "
                        "Ensure the PDF is not scanned or image-only."
                    )
                    st.stop()

                result = analyze_document(pages)
                st.session_state.current_analysis  = result
                st.session_state.current_pdf_name  = uploaded_file.name
                st.session_state.viewing_doc_id    = None
            st.rerun()

    # ── Show results if analysis is stored ───────────────────────────────────
    if st.session_state.current_analysis is not None:
        st.divider()
        _render_analysis_results(
            result        = st.session_state.current_analysis,
            show_save     = True,
            user_id       = st.session_state.user["id"],
            pdf_name      = st.session_state.current_pdf_name,
        )


def render_tab2():
    """Tab 2 — Saved Documents."""
    st.markdown(
        '<h2 style="color:#4d7fff;">Your Saved Legal Documents</h2>',
        unsafe_allow_html=True,
    )

    docs = get_user_documents(st.session_state.user["id"])

    if not docs:
        st.info("No saved documents yet. Go to 'Analyze New Document' to get started.")
        return

    for doc in docs:
        doc_id   = doc["id"]
        doc_name = doc["doc_name"]
        date_str = _format_date(doc.get("created_at", ""))

        # ── Card header ──────────────────────────────────────────────────────
        with st.container():
            st.markdown(
                f"""
                <div style="background:#121826;border:1px solid #1e3a7a;border-radius:8px;
                            padding:14px 16px;margin-bottom:4px;">
                    <span style="color:#c8d8ff;font-weight:600;font-size:16px;">{doc_name}</span>
                    <br>
                    <span style="color:#556688;font-size:13px;">Saved on {date_str}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

            col_view, col_rename, col_delete, col_spacer = st.columns([1, 1, 1, 3])

            with col_view:
                if st.button("📂 View", key=f"view_{doc_id}"):
                    # Toggle: clicking again on the same doc hides it
                    if st.session_state.viewing_doc_id == doc_id:
                        st.session_state.viewing_doc_id = None
                    else:
                        st.session_state.viewing_doc_id  = doc_id
                        st.session_state.editing_doc_id  = None
                        st.session_state.confirm_delete_id = None
                    st.rerun()

            with col_rename:
                if st.button("✏️ Rename", key=f"rename_{doc_id}"):
                    if st.session_state.editing_doc_id == doc_id:
                        st.session_state.editing_doc_id = None
                    else:
                        st.session_state.editing_doc_id    = doc_id
                        st.session_state.viewing_doc_id    = None
                        st.session_state.confirm_delete_id = None
                    st.rerun()

            with col_delete:
                if st.button("🗑️ Delete", key=f"delete_{doc_id}"):
                    if st.session_state.confirm_delete_id == doc_id:
                        st.session_state.confirm_delete_id = None
                    else:
                        st.session_state.confirm_delete_id = doc_id
                        st.session_state.editing_doc_id    = None
                        st.session_state.viewing_doc_id    = None
                    st.rerun()

            # ── Inline rename form ────────────────────────────────────────────
            if st.session_state.editing_doc_id == doc_id:
                st.markdown('<div style="margin-top:8px;"></div>', unsafe_allow_html=True)
                new_name = st.text_input(
                    "New document name:",
                    value=doc_name,
                    key=f"rename_input_{doc_id}"
                )
                if st.button("💾 Save Name", key=f"save_name_{doc_id}"):
                    if new_name.strip():
                        update_document_name(doc_id, new_name.strip())
                        st.session_state.editing_doc_id = None
                        st.success(f"Renamed to '{new_name.strip()}'")
                        st.rerun()
                    else:
                        st.error("Name cannot be empty.")

            # ── Inline delete confirmation ────────────────────────────────────
            if st.session_state.confirm_delete_id == doc_id:
                st.markdown(
                    '<p style="color:#ff6666;margin-top:8px;">⚠️ Are you sure? This cannot be undone.</p>',
                    unsafe_allow_html=True,
                )
                col_yes, col_no, _ = st.columns([1, 1, 4])
                with col_yes:
                    if st.button("✅ Yes, Delete", key=f"confirm_del_{doc_id}"):
                        delete_document(doc_id)
                        st.session_state.confirm_delete_id = None
                        st.rerun()
                with col_no:
                    if st.button("❌ Cancel", key=f"cancel_del_{doc_id}"):
                        st.session_state.confirm_delete_id = None
                        st.rerun()

            # ── Inline analysis view ──────────────────────────────────────────
            if st.session_state.viewing_doc_id == doc_id:
                st.markdown(
                    '<hr style="border-color:#1e3a7a;margin:12px 0;">',
                    unsafe_allow_html=True,
                )
                try:
                    analysis = json.loads(doc["analysis_json"])
                    _render_analysis_results(analysis, show_save=False)
                except Exception:
                    st.error("Could not load analysis data for this document.")

        st.divider()


def render_main_app():
    """Renders the main application with sidebar and tabbed content."""
    render_sidebar()

    tab1, tab2 = st.tabs(["📄 Analyze New Document", "📚 Saved Documents"])

    with tab1:
        render_tab1()

    with tab2:
        render_tab2()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if st.session_state.logged_in:
    render_main_app()
else:
    render_login_page()
