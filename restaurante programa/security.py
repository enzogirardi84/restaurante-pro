"""Utilidades de seguridad sin dependencias de Streamlit."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from pathlib import Path


HASH_PREFIX = "pbkdf2_sha256"
HASH_ITERATIONS = 260_000


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
    return ""
