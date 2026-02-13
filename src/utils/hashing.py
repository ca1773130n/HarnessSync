"""
Version-aware SHA256 file hashing.

Uses hashlib.file_digest on Python 3.11+ for optimized hashing,
falls back to manual chunked reading on Python 3.10.
"""

import hashlib
import sys
from pathlib import Path


def hash_file_sha256(file_path: Path) -> str:
    """
    Compute SHA256 hash of file, truncated to 16 chars for readability.
    Uses optimized file_digest on Python 3.11+, chunked reading on 3.10.

    If file_path is a symlink, resolves it first before hashing to avoid
    hashing symlink metadata (which changes unpredictably).

    Returns empty string if file doesn't exist.
    """
    if not file_path.exists():
        return ""

    # Resolve symlinks to hash the target file content
    if file_path.is_symlink():
        file_path = file_path.resolve()

    # Python 3.11+: Use optimized file_digest (releases GIL, may use fd directly)
    if sys.version_info >= (3, 11):
        try:
            with open(file_path, 'rb') as f:
                digest = hashlib.file_digest(f, 'sha256')
                return digest.hexdigest()[:16]
        except Exception:
            pass  # Fall through to manual method

    # Python 3.10 or fallback: Manual chunked reading
    h = hashlib.sha256()
    try:
        with open(file_path, 'rb') as f:
            # Read in 8KB chunks (releases GIL for chunks >2047 bytes)
            while chunk := f.read(8192):
                h.update(chunk)
        return h.hexdigest()[:16]
    except Exception:
        return ""  # File read failed


def hash_content(content: str) -> str:
    """
    Hash a string directly (useful for generated content like AGENTS.md).
    Encode to UTF-8 bytes, SHA256 hash, truncate to 16 chars.
    """
    h = hashlib.sha256()
    h.update(content.encode('utf-8'))
    return h.hexdigest()[:16]
