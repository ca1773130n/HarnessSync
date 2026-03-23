from __future__ import annotations

"""Rule provenance annotation for synced target files.

Wraps HarnessSync-injected content blocks with comment markers so users
can distinguish native edits from synced content, and so conflict detection
can be precise about which lines were written by HarnessSync.

Marker format (Markdown / plain text):
    <!-- [harness-sync:start source=CLAUDE.md line=1-42] -->
    ... synced content ...
    <!-- [harness-sync:end] -->

The mapping from target path -> source attribution is persisted to
.harness-sync/rule-attribution.json for auditing and incremental re-sync.
"""

import json
import re
from pathlib import Path


_START_RE = re.compile(
    r"<!--\s*\[harness-sync:start(?:\s+source=([^\s\]]+))?(?:\s+line=([^\s\]]+))?\]\s*-->",
    re.IGNORECASE,
)
_END_RE = re.compile(r"<!--\s*\[harness-sync:end\]\s*-->", re.IGNORECASE)

_ATTRIBUTION_PATH = ".harness-sync/rule-attribution.json"


def annotate(
    content: str,
    source_path: str = "CLAUDE.md",
    line_range: str | None = None,
) -> str:
    """Wrap content with harness-sync provenance markers.

    Args:
        content: The text block to annotate.
        source_path: Relative path to the source file (e.g. 'CLAUDE.md').
        line_range: Optional line range string like '1-42' or '10'.

    Returns:
        The annotated content string.
    """
    attrs = f"source={source_path}"
    if line_range:
        attrs += f" line={line_range}"
    start_marker = f"<!-- [harness-sync:start {attrs}] -->"
    end_marker = "<!-- [harness-sync:end] -->"
    return f"{start_marker}\n{content}\n{end_marker}"


def strip_annotations(content: str) -> str:
    """Remove harness-sync annotation markers from content.

    Keeps the content between markers; removes only the marker lines.
    This is used before re-syncing to avoid double-wrapping.
    """
    lines = content.splitlines(keepends=True)
    result: list[str] = []
    for line in lines:
        if _START_RE.match(line.strip()):
            continue
        if _END_RE.match(line.strip()):
            continue
        result.append(line)
    return "".join(result)


def extract_annotated_blocks(content: str) -> list[dict]:
    """Extract all annotated blocks and their attribution metadata.

    Returns:
        List of dicts with keys: 'source', 'line_range', 'content'.
    """
    blocks: list[dict] = []
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        m = _START_RE.match(lines[i].strip())
        if m:
            source = m.group(1) or "unknown"
            line_range = m.group(2)
            block_lines: list[str] = []
            i += 1
            while i < len(lines) and not _END_RE.match(lines[i].strip()):
                block_lines.append(lines[i])
                i += 1
            blocks.append({
                "source": source,
                "line_range": line_range,
                "content": "\n".join(block_lines),
            })
        i += 1
    return blocks


class RuleAttributionStore:
    """Persist rule→source mapping in .harness-sync/rule-attribution.json."""

    def __init__(self, project_dir: Path):
        self._path = project_dir / _ATTRIBUTION_PATH

    def _load(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def record(self, target_path: str, source_path: str, line_range: str | None = None) -> None:
        """Record that target_path content came from source_path."""
        data = self._load()
        data[target_path] = {
            "source": source_path,
            "line_range": line_range,
        }
        self._save(data)

    def get_source(self, target_path: str) -> dict | None:
        """Return attribution for target_path, or None if unknown."""
        return self._load().get(target_path)

    def all_attributions(self) -> dict:
        """Return the full attribution map."""
        return self._load()
