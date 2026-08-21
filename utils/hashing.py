import hashlib


def calculate_file_hash(file_bytes: bytes) -> str:
    """Return a SHA-256 digest for the exact uploaded file bytes."""
    return hashlib.sha256(file_bytes).hexdigest()
