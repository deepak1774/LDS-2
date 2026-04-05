"""
database.py — SQLite database layer for Legal Document Simplifier
"""

import sqlite3
import bcrypt
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "legal_app.db")


def _get_connection():
    """Return a new SQLite connection with row_factory set to dict-like."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _row_to_dict(row):
    """Convert a sqlite3.Row to a plain Python dict."""
    if row is None:
        return None
    return dict(row)


def _rows_to_dicts(rows):
    """Convert a list of sqlite3.Row objects to a list of plain dicts."""
    return [dict(r) for r in rows]


def init_db():
    """
    Creates the users and documents tables if they don't exist.
    Inserts 3 default users if the users table is empty.
    Safe to call on every app run (idempotent).
    """
    conn = _get_connection()
    cursor = conn.cursor()

    # --- Create users table ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            created_at    TEXT    DEFAULT (datetime('now'))
        )
    """)

    # --- Create documents table ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id           INTEGER NOT NULL REFERENCES users(id),
            doc_name          TEXT    NOT NULL,
            original_filename TEXT,
            analysis_json     TEXT    NOT NULL,
            created_at        TEXT    DEFAULT (datetime('now')),
            updated_at        TEXT    DEFAULT (datetime('now'))
        )
    """)

    # --- Seed default users if table is empty ---
    cursor.execute("SELECT COUNT(*) as cnt FROM users")
    row = cursor.fetchone()
    if row["cnt"] == 0:
        defaults = [
            ("admin", "admin123"),
            ("user1", "user123"),
            ("user2", "user456"),
        ]
        for username, plain_pw in defaults:
            pw_hash = bcrypt.hashpw(
                plain_pw.encode("utf-8"), bcrypt.gensalt()
            ).decode("utf-8")
            cursor.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, pw_hash),
            )

    conn.commit()
    conn.close()


def get_user_by_username(username: str):
    """
    Returns the user row as a dict {id, username, password_hash, created_at},
    or None if not found.
    """
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username, password_hash, created_at FROM users WHERE username = ?",
        (username,),
    )
    row = cursor.fetchone()
    conn.close()
    return _row_to_dict(row)


def create_user(username: str, password_hash: str) -> bool:
    """
    Inserts a new user row.  Returns True on success, False on duplicate username.
    """
    conn = _get_connection()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, password_hash),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def save_document(
    user_id: int, doc_name: str, original_filename: str, analysis_json: str
) -> int:
    """
    Inserts a new document row and returns the new document id.
    """
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO documents (user_id, doc_name, original_filename, analysis_json)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, doc_name, original_filename, analysis_json),
    )
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return new_id


def get_user_documents(user_id: int) -> list:
    """
    Returns all documents for the given user, ordered newest first.
    Each item is a dict: {id, doc_name, original_filename, analysis_json, created_at, updated_at}
    """
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, doc_name, original_filename, analysis_json, created_at, updated_at
        FROM documents
        WHERE user_id = ?
        ORDER BY created_at DESC
        """,
        (user_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def get_document_by_id(doc_id: int):
    """
    Returns a single document row as a dict, or None if not found.
    """
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, user_id, doc_name, original_filename, analysis_json, created_at, updated_at
        FROM documents
        WHERE id = ?
        """,
        (doc_id,),
    )
    row = cursor.fetchone()
    conn.close()
    return _row_to_dict(row)


def update_document_name(doc_id: int, new_name: str) -> bool:
    """
    Updates the doc_name and updated_at for the given document id.
    Returns True on success.
    """
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE documents
        SET doc_name = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (new_name, doc_id),
    )
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def delete_document(doc_id: int) -> bool:
    """
    Deletes the document row with the given id.
    Returns True on success.
    """
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0
