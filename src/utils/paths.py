"""
OS-aware symlink creation with fallback chain.

Provides symlink creation that works across Windows/macOS/Linux with automatic
fallback to junction points (Windows dirs) or file copies (last resort).
"""

import json
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path


def ensure_dir(path: Path) -> None:
    """
    Create directory with all parent directories.
    Simple wrapper for mkdir with parents=True, exist_ok=True.
    """
    path.mkdir(parents=True, exist_ok=True)


def create_symlink_with_fallback(src: Path, dst: Path) -> tuple[bool, str]:
    """
    Create symlink with OS-aware fallback chain.

    Returns: (success: bool, method: str)
    Methods: 'symlink', 'junction', 'copy', 'skipped', or 'failed: {reason}'

    Fallback chain:
    1. Native symlink (macOS/Linux, Windows with admin/dev mode)
    2. Junction point (Windows directories only, no admin required)
    3. Copy with marker file (last resort)
    """
    # Ensure parent directory exists
    ensure_dir(dst.parent)

    # Handle existing destination
    if dst.exists() or dst.is_symlink():
        # If dst is symlink pointing to same resolved target, skip
        if dst.is_symlink():
            try:
                if dst.resolve() == src.resolve():
                    return (True, 'skipped')
            except (OSError, RuntimeError):
                pass  # Broken symlink or resolution error

        # Remove existing destination
        if dst.is_symlink():
            dst.unlink()
        elif dst.is_dir():
            shutil.rmtree(dst)
        else:
            dst.unlink()

    # Try 1: Native symlink (works on macOS/Linux, Windows with admin/dev mode)
    try:
        target_is_dir = src.is_dir()
        dst.symlink_to(src, target_is_directory=target_is_dir)
        return (True, 'symlink')
    except (OSError, NotImplementedError):
        pass  # Fall through to junction or copy

    # Try 2: Junction point (Windows directories only, no admin required)
    if platform.system() == 'Windows' and src.is_dir():
        try:
            # Use mklink /J for junction points
            subprocess.run(
                ['mklink', '/J', str(dst), str(src)],
                check=True,
                capture_output=True,
                shell=True
            )
            return (True, 'junction')
        except subprocess.CalledProcessError:
            pass  # Fall through to copy

    # Try 3: Copy with marker file (last resort)
    try:
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)

        # Create marker file to indicate this is a managed copy
        marker = dst.parent / f".harnesssync-source-{dst.name}.txt"
        marker.write_text(str(src.resolve()), encoding='utf-8')

        return (True, 'copy')
    except (OSError, shutil.Error) as e:
        return (False, f'failed: {e}')


def cleanup_stale_symlinks(directory: Path) -> int:
    """
    Remove broken symlinks in directory.
    Also cleans up orphaned .harnesssync-source-*.txt marker files.
    Returns count of cleaned items.
    """
    if not directory.exists() or not directory.is_dir():
        return 0

    cleaned = 0

    # Use list() to avoid "directory changed during iteration" errors
    for item in list(directory.iterdir()):
        # Check if symlink points to non-existent target
        if item.is_symlink():
            try:
                # Check if target exists
                if not item.resolve().exists():
                    item.unlink()
                    cleaned += 1
            except (OSError, RuntimeError):
                # Resolution error (broken symlink) - remove it
                try:
                    item.unlink()
                    cleaned += 1
                except OSError:
                    pass

        # Clean up orphaned marker files
        if item.name.startswith('.harnesssync-source-') and item.name.endswith('.txt'):
            # Extract the target name from marker filename
            target_name = item.name[len('.harnesssync-source-'):-len('.txt')]
            target_path = directory / target_name
            if not target_path.exists():
                try:
                    item.unlink()
                    cleaned += 1
                except OSError:
                    pass

    return cleaned


def read_json_safe(file_path: Path, default=None) -> dict:
    """
    Read JSON file with comprehensive error handling.
    Returns default value (or {}) if file missing or corrupted.
    """
    if default is None:
        default = {}

    if not file_path.exists():
        return default

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        # Log corruption details (no logger dependency here)
        print(f"Warning: JSON corrupted at line {e.lineno}, col {e.colno}: {e.msg}")
        return default
    except (OSError, UnicodeDecodeError) as e:
        # File read failed
        print(f"Warning: Failed to read {file_path}: {e}")
        return default


def write_json_safe(file_path: Path, data: dict) -> None:
    """
    Write JSON file with basic safety.
    Note: Atomic writes are in state_manager.py (Plan 02).
    This is for general JSON writes.
    """
    ensure_dir(file_path.parent)

    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write('\n')  # Trailing newline
    except (OSError, TypeError) as e:
        print(f"Warning: Failed to write {file_path}: {e}")


def write_json_atomic(path: Path, data: dict) -> None:
    """Write JSON content atomically using tempfile + os.replace.

    Uses the atomic write pattern to prevent corrupted JSON files on
    interrupted writes. Follows the same pattern as write_toml_atomic.

    Args:
        path: Target file path
        data: Dict to write as JSON

    Raises:
        OSError: If write or rename fails
        TypeError: If data is not JSON serializable
    """
    # Ensure parent directory exists
    ensure_dir(path.parent)

    # Create temp file in same directory for atomic rename
    temp_fd = tempfile.NamedTemporaryFile(
        mode='w',
        dir=path.parent,
        suffix='.tmp',
        delete=False,
        encoding='utf-8'
    )
    temp_path = Path(temp_fd.name)

    try:
        # Write content
        json.dump(data, temp_fd, indent=2, ensure_ascii=False)
        temp_fd.write('\n')  # Trailing newline
        temp_fd.flush()
        os.fsync(temp_fd.fileno())
        temp_fd.close()

        # Atomic rename
        os.replace(str(temp_path), str(path))

    except Exception:
        # Cleanup on failure
        if not temp_fd.closed:
            temp_fd.close()
        if temp_path.exists():
            temp_path.unlink()
        raise
