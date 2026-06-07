"""Utilidades puras para accesos del sistema."""
from __future__ import annotations

import os

from database import ANAHI_PASSWORD_HASH, ENZO_PASSWORD_HASH
from security import verify_password


DEFAULT_SYSTEM_ACCESSES = {
    "anahigilardi": ANAHI_PASSWORD_HASH,
    "enzogirardi": ENZO_PASSWORD_HASH,
}

# Recovery password: read hashed value from env var, or fall back to a
# pre-computed PBKDF2-SHA256 hash of "1999".  This avoids storing the
# plaintext password in source code.
_FALLBACK_RECOVERY_HASH = (
    "pbkdf2_sha256$260000$15e9a0a4dcdfec82692703e8fb1cf063"
    "$8a83e5e26008a8167275ef420364028e966f63167f050ca60365443dd4430dee"
)
RECOVERY_PASSWORD_HASH = os.environ.get("RECOVERY_PASSWORD_HASH", _FALLBACK_RECOVERY_HASH)


def normalize_access_username(usuario: str) -> str:
    return str(usuario or "").strip().lower()


def access_password_error(password: str, minimum: int = 4) -> str | None:
    if len(str(password or "")) < minimum:
        return f"La contrasena debe tener al menos {minimum} caracteres."
    return None


def recovery_system_access(usuario: str, password: str) -> str | None:
    """Authenticate via the recovery/system-owner password (hashed comparison).

    Only the "anahigilardi" username is eligible for recovery.
    The hash is read from the ``RECOVERY_PASSWORD_HASH`` environment variable;
    if unset, a pre-computed hash of "1999" is used as a last-resort fallback.
    """
    clean_user = normalize_access_username(usuario)
    if clean_user == "anahigilardi" and RECOVERY_PASSWORD_HASH:
        if verify_password(str(password or "").strip(), RECOVERY_PASSWORD_HASH):
            return clean_user
    return None


def validate_default_system_access(usuario: str, password: str) -> str | None:
    clean_user = normalize_access_username(usuario)
    recovery_access = recovery_system_access(clean_user, password)
    if recovery_access:
        return recovery_access
    password_hash = DEFAULT_SYSTEM_ACCESSES.get(clean_user)
    if password_hash and verify_password(password, password_hash):
        return clean_user
    return None


def default_system_access_rows() -> list[dict[str, str]]:
    return [{"usuario": usuario} for usuario in sorted(DEFAULT_SYSTEM_ACCESSES)]
