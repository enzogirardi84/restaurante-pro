"""Utilidades de seguridad sin dependencias de Streamlit."""
from __future__ import annotations

import hashlib
import hmac
import mimetypes
import secrets
from pathlib import Path


HASH_PREFIX = "pbkdf2_sha256"
HASH_ITERATIONS = 260_000
LOGIN_LOGO_PATH = Path(__file__).parent / "assets" / "logo-el-patron.jpeg"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        HASH_ITERATIONS,
    ).hex()
    return f"{HASH_PREFIX}${HASH_ITERATIONS}${salt}${digest}"


def is_password_hash(value: str) -> bool:
    return str(value or "").startswith(f"{HASH_PREFIX}$")


def verify_password(password: str, stored: str) -> bool:
    stored = str(stored or "")
    if not is_password_hash(stored):
        return hmac.compare_digest(password, stored)
    try:
        prefix, iterations, salt, digest = stored.split("$", 3)
        if prefix != HASH_PREFIX:
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iterations),
        ).hex()
        return hmac.compare_digest(candidate, digest)
    except (ValueError, TypeError):
        return False


def login_logo_tag() -> str:
    import base64

    path = login_logo_path()
    if not path.exists():
        return ""
    b64 = base64.b64encode(path.read_bytes()).decode()
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f'<img src="data:{mime};base64,{b64}" alt="Logo El Patron" class="login-logo-img">'


def login_logo_path() -> Path:
    return LOGIN_LOGO_PATH
