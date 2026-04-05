"""
auth.py — Authentication helpers for Legal Document Simplifier
"""

import bcrypt
from database import get_user_by_username


def hash_password(plain_password: str) -> str:
    """
    Hashes a plain-text password with bcrypt and returns the hash
    as a UTF-8 decoded string suitable for storing in the database.
    """
    hashed_bytes = bcrypt.hashpw(
        plain_password.encode("utf-8"),
        bcrypt.gensalt()
    )
    return hashed_bytes.decode("utf-8")


def verify_password(plain_password: str, hashed: str) -> bool:
    """
    Checks whether plain_password matches the stored bcrypt hash.
    Returns True if they match, False otherwise.
    """
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed.encode("utf-8")
        )
    except Exception:
        return False


def login_user(username: str, password: str):
    """
    Attempts to authenticate the user.

    Returns:
        dict — the user row {id, username, password_hash, created_at}
                if credentials are valid.
        None  — if username does not exist or password is wrong.
    """
    user = get_user_by_username(username.strip())
    if user is None:
        return None
    if verify_password(password, user["password_hash"]):
        return user
    return None
