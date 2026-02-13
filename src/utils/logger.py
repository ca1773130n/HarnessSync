"""Colored logger with summary statistics."""

import os
import sys
from datetime import datetime


class Logger:
    """
    Colored logger with summary statistics.

    Features:
    - ANSI color codes for terminal output (detects Windows CMD vs Terminal)
    - Counters for synced, skipped, error, cleaned operations
    - Audit trail recording all messages with timestamps
    - Reset capability for watch mode reuse
    """

    COLORS = {
        'reset': '\033[0m',
        'bold': '\033[1m',
        'dim': '\033[2m',
        'red': '\033[31m',
        'green': '\033[32m',
        'yellow': '\033[33m',
        'blue': '\033[34m',
        'cyan': '\033[36m',
    }

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self._counts = {'synced': 0, 'skipped': 0, 'error': 0, 'cleaned': 0}
        self.audit_trail = []

        # Disable colors on Windows CMD (not Windows Terminal) or when not a TTY
        # Windows Terminal supports ANSI, CMD does not
        self.use_colors = sys.stdout.isatty() and not (
            sys.platform == 'win32' and 'WT_SESSION' not in os.environ
        )

    def _c(self, color: str, text: str) -> str:
        """Colorize text with ANSI codes if colors are enabled."""
        if not self.use_colors:
            return text
        return f"{self.COLORS.get(color, '')}{text}{self.COLORS['reset']}"

    def _record(self, level: str, msg: str):
        """Record message to audit trail."""
        self.audit_trail.append({
            'level': level,
            'msg': msg,
            'timestamp': datetime.now().isoformat()
        })

    def info(self, msg: str):
        """Green checkmark for success."""
        print(f"  {self._c('green', '✓')} {msg}")
        self._record('info', msg)

    def error(self, msg: str):
        """Red X for errors."""
        print(f"  {self._c('red', '✗')} {msg}")
        self._counts['error'] += 1
        self._record('error', msg)

    def warn(self, msg: str):
        """Yellow warning triangle."""
        print(f"  {self._c('yellow', '⚠')} {msg}")
        self._record('warn', msg)

    def skip(self, msg: str):
        """Dimmed dot for skipped items (only in verbose mode)."""
        if self.verbose:
            print(f"  {self._c('dim', '·')} {msg}")
        self._counts['skipped'] += 1
        self._record('skip', msg)

    def debug(self, msg: str):
        """Debug output (only in verbose mode)."""
        if self.verbose:
            print(f"  {self._c('dim', f'  {msg}')}")

    def header(self, msg: str):
        """Bold blue section header."""
        print(f"\n{self._c('bold', self._c('blue', f'[{msg}]'))}")

    def synced(self):
        """Increment synced count."""
        self._counts['synced'] += 1

    def cleaned(self):
        """Increment cleaned count."""
        self._counts['cleaned'] += 1

    def summary(self) -> str:
        """Generate summary string with colored counts."""
        c = self._counts
        parts = []
        if c['synced']:
            parts.append(self._c('green', f"{c['synced']} synced"))
        if c['skipped']:
            parts.append(self._c('dim', f"{c['skipped']} skipped"))
        if c['cleaned']:
            parts.append(self._c('yellow', f"{c['cleaned']} cleaned"))
        if c['error']:
            parts.append(self._c('red', f"{c['error']} errors"))

        return ', '.join(parts) if parts else 'nothing to do'

    def get_audit_trail(self) -> list[dict]:
        """Return the audit trail of all logged messages."""
        return self.audit_trail

    def reset(self):
        """Clear counts and audit trail (for watch mode reuse)."""
        self._counts = {'synced': 0, 'skipped': 0, 'error': 0, 'cleaned': 0}
        self.audit_trail = []
