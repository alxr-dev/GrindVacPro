"""GrindVacPro — Cryptographic helpers for content deduplication."""

from hashlib import sha256


def sha256_hex(text: str) -> str:
    """Return the SHA-256 hex digest of *text* (UTF-8 encoded)."""
    return sha256(text.encode("utf-8")).hexdigest()
