"""File-based locking and time-based debouncing for sync operations.

sync_lock: Non-blocking exclusive file lock using fcntl.flock (Unix)
            with graceful Windows fallback (skip locking with warning).
should_debounce: Check if last sync was < N seconds ago to prevent
                 rapid successive syncs.
"""

import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

LOCK_FILE_DEFAULT = Path.home() / ".harnesssync" / "sync.lock"
DEBOUNCE_SECONDS = 3.0


@contextmanager
def sync_lock(lock_path: Path = None):
    """Acquire exclusive non-blocking file lock.

    Args:
        lock_path: Path to lock file (default: ~/.harnesssync/sync.lock)

    Yields:
        File descriptor on Unix, None on Windows

    Raises:
        BlockingIOError: If lock cannot be acquired (another sync in progress)
    """
    if lock_path is None:
        lock_path = LOCK_FILE_DEFAULT

    if sys.platform == "win32":
        import warnings
        warnings.warn(
            "File locking not available on Windows - "
            "concurrent syncs may conflict"
        )
        yield None
        return

    import fcntl

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise

    try:
        yield fd
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def should_debounce(state_manager, debounce_seconds: float = DEBOUNCE_SECONDS) -> bool:
    """Check if sync should be skipped due to debounce.

    Args:
        state_manager: StateManager instance with last_sync property
        debounce_seconds: Minimum seconds between syncs (default: 3.0)

    Returns:
        True if last sync was < debounce_seconds ago (skip this sync)
    """
    last_sync = state_manager.last_sync
    if not last_sync:
        return False

    try:
        last_sync_time = datetime.fromisoformat(last_sync).timestamp()
    except (ValueError, TypeError):
        return False

    elapsed = time.time() - last_sync_time
    return elapsed < debounce_seconds
