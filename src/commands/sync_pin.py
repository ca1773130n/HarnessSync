from __future__ import annotations

"""
/sync-pin slash command — named config version pinning (item 13).

Pin a snapshot of synced configs so you can safely experiment with new rules
knowing you can rollback to a named checkpoint at any time.

    /sync-pin create v1.2          Create a named pin (checkpoint)
    /sync-pin list                 List all pins
    /sync-pin show v1.2            Show details of a pin
    /sync-pin restore v1.2         Restore CLAUDE.md from a pin
    /sync-pin delete v1.2          Delete a named pin

Pins are stored as JSON files at ~/.harnesssync/pins/<name>.json using the
same schema as ConfigSnapshot so they are human-readable and portable.
Restoring a pin writes the pinned rules content back to CLAUDE.md (and
optionally triggers a re-sync).
"""

import os
import sys
import json
import shlex
import argparse
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.utils.logger import Logger


_PINS_DIR = Path.home() / ".harnesssync" / "pins"
_PIN_VERSION = "1"


# ---------------------------------------------------------------------------
# Pin storage helpers
# ---------------------------------------------------------------------------

def _pin_path(name: str) -> Path:
    return _PINS_DIR / f"{name}.json"


def _save_pin(name: str, data: dict) -> Path:
    _PINS_DIR.mkdir(parents=True, exist_ok=True)
    path = _pin_path(name)
    import tempfile
    tmp = None
    try:
        fd = tempfile.NamedTemporaryFile(
            mode="w", dir=_PINS_DIR, suffix=".tmp", delete=False, encoding="utf-8"
        )
        tmp = fd.name
        json.dump(data, fd, indent=2, ensure_ascii=False)
        fd.write("\n")
        fd.flush()
        os.fsync(fd.fileno())
        fd.close()
        os.replace(tmp, str(path))
    except Exception:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise
    return path


def _load_pin(name: str) -> dict | None:
    path = _pin_path(name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _list_pins() -> list[str]:
    if not _PINS_DIR.exists():
        return []
    return sorted(p.stem for p in _PINS_DIR.glob("*.json"))


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_create(name: str, project_dir: Path, message: str = "") -> int:
    """Create a named pin from the current CLAUDE.md state."""
    logger = Logger()

    # Read current CLAUDE.md content
    claude_md = project_dir / "CLAUDE.md"
    if not claude_md.exists():
        print(f"Error: CLAUDE.md not found at {claude_md}", file=sys.stderr)
        return 1

    content = claude_md.read_text(encoding="utf-8")

    # Build pin data
    pin: dict = {
        "version": _PIN_VERSION,
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "message": message,
        "project": str(project_dir),
        "rules": content,
        "source_file": str(claude_md),
    }

    # Check for overwrite
    if _pin_path(name).exists():
        existing = _load_pin(name)
        if existing:
            ts = existing.get("created_at", "unknown")
            print(f"Warning: Pin '{name}' already exists (created {ts}).")
            if sys.stdin.isatty():
                answer = input("Overwrite? [y/N]: ").strip().lower()
                if answer != "y":
                    print("Cancelled.")
                    return 0
            else:
                print("Non-interactive mode — overwriting existing pin.")

    path = _save_pin(name, pin)
    line_count = len(content.splitlines())
    print(f"Pin '{name}' created ({line_count} lines of CLAUDE.md).")
    print(f"Saved to: {path}")
    if message:
        print(f"Message: {message}")
    return 0


def cmd_list() -> int:
    """List all pins with creation timestamps and messages."""
    pins = _list_pins()
    if not pins:
        print("No pins found. Create one with /sync-pin create <name>.")
        return 0

    print(f"{'Name':<20}  {'Created':<22}  Message")
    print("-" * 70)
    for name in pins:
        data = _load_pin(name)
        if not data:
            print(f"  {name:<18}  <unreadable>")
            continue
        ts = data.get("created_at", "")[:19].replace("T", " ")
        msg = data.get("message", "")
        if len(msg) > 40:
            msg = msg[:37] + "..."
        print(f"  {name:<18}  {ts:<22}  {msg}")
    return 0


def cmd_show(name: str) -> int:
    """Show details of a named pin."""
    data = _load_pin(name)
    if not data:
        print(f"Error: Pin '{name}' not found. Use /sync-pin list to see available pins.",
              file=sys.stderr)
        return 1

    print(f"Pin: {name}")
    print(f"  Created:  {data.get('created_at', 'unknown')}")
    print(f"  Project:  {data.get('project', 'unknown')}")
    if data.get("message"):
        print(f"  Message:  {data['message']}")
    rules = data.get("rules", "")
    print(f"  Content:  {len(rules.splitlines())} lines of CLAUDE.md")
    print(f"  Stored:   {_pin_path(name)}")
    return 0


def cmd_restore(name: str, project_dir: Path, dry_run: bool = False) -> int:
    """Restore CLAUDE.md content from a named pin."""
    data = _load_pin(name)
    if not data:
        print(f"Error: Pin '{name}' not found.", file=sys.stderr)
        return 1

    rules = data.get("rules", "")
    if not rules:
        print(f"Error: Pin '{name}' contains no rule content.", file=sys.stderr)
        return 1

    claude_md = project_dir / "CLAUDE.md"
    ts = data.get("created_at", "unknown")

    if dry_run:
        print(f"[dry-run] Would restore CLAUDE.md from pin '{name}' (created {ts}).")
        print(f"  {len(rules.splitlines())} lines would be written to {claude_md}")
        return 0

    # Back up current CLAUDE.md before overwriting
    if claude_md.exists():
        backup = claude_md.with_suffix(".md.pre-pin-restore")
        backup.write_text(claude_md.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Backed up current CLAUDE.md to {backup.name}")

    claude_md.write_text(rules, encoding="utf-8")
    print(f"Restored CLAUDE.md from pin '{name}' (created {ts}).")
    print(f"Written {len(rules.splitlines())} lines to {claude_md}")
    print("Run /sync to propagate the restored config to all target harnesses.")
    return 0


def cmd_delete(name: str) -> int:
    """Delete a named pin."""
    path = _pin_path(name)
    if not path.exists():
        print(f"Error: Pin '{name}' not found.", file=sys.stderr)
        return 1

    if sys.stdin.isatty():
        answer = input(f"Delete pin '{name}'? This cannot be undone. [y/N]: ").strip().lower()
        if answer != "y":
            print("Cancelled.")
            return 0

    path.unlink()
    print(f"Pin '{name}' deleted.")
    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sync-pin",
        description="Manage named config version pins (named checkpoints for CLAUDE.md).",
    )
    sub = parser.add_subparsers(dest="subcommand")

    # create
    c = sub.add_parser("create", help="Pin current CLAUDE.md state")
    c.add_argument("name", help="Pin name (e.g. v1.2, before-refactor)")
    c.add_argument("-m", "--message", default="", help="Optional description")
    c.add_argument("--project-dir", type=Path, default=None,
                   help="Project directory (default: cwd)")

    # list
    sub.add_parser("list", help="List all pins")

    # show
    s = sub.add_parser("show", help="Show pin details")
    s.add_argument("name", help="Pin name")

    # restore
    r = sub.add_parser("restore", help="Restore CLAUDE.md from a pin")
    r.add_argument("name", help="Pin name")
    r.add_argument("--dry-run", action="store_true", help="Preview without writing")
    r.add_argument("--project-dir", type=Path, default=None,
                   help="Project directory (default: cwd)")

    # delete
    d = sub.add_parser("delete", help="Delete a named pin")
    d.add_argument("name", help="Pin name")

    return parser


def main(argv: list[str] | None = None) -> int:
    raw = os.environ.get("CLAUDE_ARGS", "")
    if raw and argv is None:
        argv = shlex.split(raw)

    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.subcommand:
        parser.print_help()
        return 0

    project_dir = getattr(args, "project_dir", None) or Path.cwd()

    if args.subcommand == "create":
        return cmd_create(args.name, project_dir, message=args.message)
    elif args.subcommand == "list":
        return cmd_list()
    elif args.subcommand == "show":
        return cmd_show(args.name)
    elif args.subcommand == "restore":
        return cmd_restore(args.name, project_dir, dry_run=args.dry_run)
    elif args.subcommand == "delete":
        return cmd_delete(args.name)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
