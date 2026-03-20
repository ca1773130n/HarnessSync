from __future__ import annotations

"""Version pinning, format matrix change detection, update feed, and update detection.

Manages config version pins (snapshots of source config at a point in time),
detects when the HarnessSync feature matrix itself changes, tracks harness
version updates over time, and provides an update feed for sync improvements.
"""

import hashlib as _hashlib
import json
import json as _json_fmt
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from src.version_detection import (
    _detect_installed_version,
    _version_gte,
    _version_lt,
)
from src.compat_rules import VERSIONED_FEATURES


# ──────────────────────────────────────────────────────────────────────────────
# Format Change Notifier
# ──────────────────────────────────────────────────────────────────────────────

_FORMAT_MATRIX_CACHE_FILE = Path.home() / ".harnesssync" / "format-matrix.json"


def _compute_matrix_hash(matrix: dict[str, dict[str, tuple[str, str]]]) -> str:
    """Compute a stable SHA256 hash of the feature matrix.

    Args:
        matrix: VERSIONED_FEATURES dict (or equivalent).

    Returns:
        Hex digest string.
    """
    # Serialise with sorted keys so the hash is stable across Python sessions
    payload = _json_fmt.dumps(
        {
            target: {
                feat: list(data)
                for feat, data in sorted(features.items())
            }
            for target, features in sorted(matrix.items())
        },
        sort_keys=True,
        ensure_ascii=True,
    )
    return _hashlib.sha256(payload.encode()).hexdigest()


def _load_format_matrix_cache() -> dict:
    """Load the cached format matrix record from disk.

    Returns:
        Dict with keys ``hash`` (str) and ``features`` (dict snapshot),
        or empty dict if no cache exists.
    """
    if not _FORMAT_MATRIX_CACHE_FILE.exists():
        return {}
    try:
        data = _json_fmt.loads(_FORMAT_MATRIX_CACHE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, _json_fmt.JSONDecodeError):
        return {}


def _save_format_matrix_cache(matrix: dict[str, dict[str, tuple[str, str]]]) -> None:
    """Persist current feature matrix hash and snapshot to disk.

    Args:
        matrix: Current VERSIONED_FEATURES dict.
    """
    _FORMAT_MATRIX_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "hash": _compute_matrix_hash(matrix),
        "features": {
            target: {feat: list(data) for feat, data in features.items()}
            for target, features in matrix.items()
        },
    }
    try:
        _FORMAT_MATRIX_CACHE_FILE.write_text(
            _json_fmt.dumps(record, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
    except OSError:
        pass


def check_format_matrix_changes(
    matrix: dict[str, dict[str, tuple[str, str]]] | None = None,
    acknowledge: bool = False,
) -> list[str]:
    """Check if the HarnessSync feature matrix has changed since last run.

    Compares the current VERSIONED_FEATURES matrix against a cached snapshot.
    Returns a list of human-readable change notices so callers can surface them
    to the user (e.g. during /sync or /sync-health).

    Args:
        matrix: Feature matrix to check. Defaults to VERSIONED_FEATURES.
        acknowledge: If True, update the cache after computing the diff
                     (marks the user as having seen the changes).

    Returns:
        List of change notice strings. Empty list means no changes detected.
    """
    if matrix is None:
        matrix = VERSIONED_FEATURES

    current_hash = _compute_matrix_hash(matrix)
    cache = _load_format_matrix_cache()

    if not cache:
        # First run — establish baseline silently
        _save_format_matrix_cache(matrix)
        return []

    if cache.get("hash") == current_hash:
        return []  # No changes

    # Matrix changed — compute diff
    notices: list[str] = []
    prev_features: dict = cache.get("features", {})

    for target, features in sorted(matrix.items()):
        prev = prev_features.get(target, {})

        added = {f: v for f, v in features.items() if f not in prev}
        removed = {f: v for f, v in prev.items() if f not in features}
        changed = {
            f: (prev[f], v)
            for f, v in features.items()
            if f in prev and list(v) != list(prev[f])
        }

        if added or removed or changed:
            notices.append(f"HarnessSync compat matrix updated for {target.upper()}:")
            for feat, (min_ver, desc) in added.items():
                notices.append(f"  + Added:   {feat} (requires {target} v{min_ver}+) — {desc}")
            for feat, data in removed.items():
                prev_ver = data[0] if isinstance(data, (list, tuple)) else "?"
                notices.append(f"  - Removed: {feat} (was v{prev_ver}+)")
            for feat, (old_data, new_data) in changed.items():
                old_ver = old_data[0] if isinstance(old_data, (list, tuple)) else "?"
                new_ver = new_data[0] if isinstance(new_data, (list, tuple)) else "?"
                if old_ver != new_ver:
                    notices.append(
                        f"  ~ Changed: {feat} min version {old_ver} → {new_ver}"
                    )

    if acknowledge:
        _save_format_matrix_cache(matrix)

    return notices


def format_matrix_change_report(notices: list[str]) -> str:
    """Format format-matrix change notices as a user-facing message.

    Args:
        notices: Output of check_format_matrix_changes().

    Returns:
        Formatted string, or empty string if no notices.
    """
    if not notices:
        return ""
    header = [
        "⚠  HarnessSync compatibility matrix has changed.",
        "   Run /sync to apply the updated config schema.",
        "",
    ]
    return "\n".join(header + notices)


# ──────────────────────────────────────────────────────────────────────────────
# Harness Version Update Detector
# ──────────────────────────────────────────────────────────────────────────────

_DETECTED_VERSIONS_FILE = Path.home() / ".harnesssync" / "detected-versions.json"


def _load_detected_versions() -> dict[str, str]:
    """Load previously recorded harness versions from disk."""
    if not _DETECTED_VERSIONS_FILE.exists():
        return {}
    try:
        data = json.loads(_DETECTED_VERSIONS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_detected_versions(versions: dict[str, str]) -> None:
    """Persist detected harness versions to disk (atomic write)."""
    _DETECTED_VERSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        dir=_DETECTED_VERSIONS_FILE.parent,
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    )
    try:
        json.dump(versions, tmp, indent=2, ensure_ascii=False)
        tmp.write("\n")
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, str(_DETECTED_VERSIONS_FILE))
    except Exception:
        tmp.close()
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


def detect_harness_updates(
    current_versions: dict[str, str | None],
    acknowledge: bool = True,
) -> list[dict]:
    """Detect harnesses that have been updated since the last check.

    Compares ``current_versions`` (harness → detected version) against the
    previously stored versions. Returns one entry per harness that has changed.

    Args:
        current_versions: Dict mapping harness name → currently detected version
                          (None if not installed or version unknown).
        acknowledge: If True, update the stored versions to the current values
                     so repeated calls don't keep reporting the same updates.

    Returns:
        List of dicts, each with keys:
            - ``harness``: str
            - ``old_version``: str | None  (None if first detection)
            - ``new_version``: str | None
            - ``kind``: "new" | "updated" | "removed"
    """
    stored = _load_detected_versions()
    updates: list[dict] = []

    all_harnesses = set(stored.keys()) | {k for k, v in current_versions.items() if v}

    for harness in sorted(all_harnesses):
        old_ver = stored.get(harness)
        new_ver = current_versions.get(harness)

        if old_ver is None and new_ver:
            # Newly detected harness
            updates.append({
                "harness": harness,
                "old_version": None,
                "new_version": new_ver,
                "kind": "new",
            })
        elif old_ver and not new_ver:
            # Harness was removed / uninstalled
            updates.append({
                "harness": harness,
                "old_version": old_ver,
                "new_version": None,
                "kind": "removed",
            })
        elif old_ver and new_ver and old_ver != new_ver:
            # Version changed
            updates.append({
                "harness": harness,
                "old_version": old_ver,
                "new_version": new_ver,
                "kind": "updated",
            })

    if acknowledge and updates:
        # Write the new detected versions, removing entries for removed harnesses
        new_stored = dict(stored)
        for entry in updates:
            harness = entry["harness"]
            if entry["kind"] == "removed":
                new_stored.pop(harness, None)
            else:
                new_stored[harness] = entry["new_version"]
        _save_detected_versions(new_stored)
    elif acknowledge and not stored:
        # First run — just record current versions
        initial = {h: v for h, v in current_versions.items() if v}
        if initial:
            _save_detected_versions(initial)

    return updates


def format_update_report(updates: list[dict]) -> str:
    """Format harness update notices as a user-facing message.

    Args:
        updates: Output of detect_harness_updates().

    Returns:
        Human-readable string, or empty string if no updates.
    """
    if not updates:
        return ""

    lines = ["Harness version changes detected:", ""]
    for entry in updates:
        harness = entry["harness"]
        kind = entry["kind"]
        old_ver = entry["old_version"] or "?"
        new_ver = entry["new_version"] or "?"
        if kind == "new":
            lines.append(f"  + {harness}: newly detected (v{new_ver})")
        elif kind == "removed":
            lines.append(f"  - {harness}: no longer detected (was v{old_ver})")
        else:
            lines.append(f"  ↑ {harness}: v{old_ver} → v{new_ver}")

    lines.append("")
    lines.append("Run /sync-status to check for config schema changes.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Harness Update Feed — What's New
# ---------------------------------------------------------------------------

# Known harness version improvements that unlock better sync fidelity.
# Format: {harness: [(version, feature_name, sync_improvement_note)]}
_VERSION_IMPROVEMENTS: dict[str, list[tuple[str, str, str]]] = {
    "cursor": [
        ("0.40", "mdc_alwaysApply", "alwaysApply support in .mdc rules — rules now activate globally without manual trigger"),
        ("0.42", "mdc_glob_scoping", "glob-based scoping in rules — use globs to target rules to specific file patterns"),
        ("0.43", "mcp_json", "native .cursor/mcp.json — MCP servers now sync directly without manual setup"),
    ],
    "gemini": [
        ("1.5", "tools_exclude", "tools.exclude permission field — tool restrictions now sync cleanly"),
        ("2.0", "tools_allowed", "tools.allowed allowlist — precise tool allowlists now supported"),
        ("2.0", "mcp_servers", "native MCP server support — all configured MCP servers sync to Gemini"),
    ],
    "codex": [
        ("1.0", "mcp_servers", "MCP server config in config.toml — MCP servers now sync to Codex"),
        ("1.1", "sandbox_mode", "sandbox_mode field — execution safety settings sync correctly"),
        ("1.2", "approval_policy", "approval_policy — permission modes now translate faithfully to Codex"),
    ],
    "windsurf": [
        ("1.0", "mcp_config_json", ".codeium/windsurf/mcp_config.json — MCP servers sync to Windsurf"),
        ("1.2", "memory_files", ".windsurf/memories/ — persistent memory files sync as skills"),
    ],
    "aider": [
        ("0.50", "read_files_list", "read_files list in .aider.conf.yml — context files sync cleanly"),
    ],
}


class HarnessUpdateFeed:
    """Monitor harness versions and surface sync-relevant improvements.

    When a harness update unlocks better sync fidelity (e.g. Gemini CLI
    1.5 now supports native MCP), this feed notifies users so they know
    upgrading is worthwhile.
    """

    def get_available_improvements(
        self,
        harness: str,
        current_version: str | None,
    ) -> list[dict]:
        """Return improvements available if the user upgrades from current_version.

        Args:
            harness: Canonical harness name.
            current_version: Current installed version string (e.g. "1.4.2").
                             None if version is unknown.

        Returns:
            List of improvement dicts, each with keys:
                - version: str — the harness version that introduced this
                - feature: str — internal feature name
                - note: str — human-readable improvement description
                - unlocks_sync: bool — always True (all listed improvements affect sync)
        """
        improvements = _VERSION_IMPROVEMENTS.get(harness, [])
        if not improvements:
            return []

        if current_version is None:
            # Unknown version — return all improvements as potential gains
            return [
                {"version": v, "feature": f, "note": n, "unlocks_sync": True}
                for v, f, n in improvements
            ]

        result = []
        for min_ver, feature, note in improvements:
            if _version_lt(current_version, min_ver):
                result.append({
                    "version": min_ver,
                    "feature": feature,
                    "note": note,
                    "unlocks_sync": True,
                })
        return result

    def get_all_improvements(
        self,
        installed: dict[str, str | None],
    ) -> dict[str, list[dict]]:
        """Check all installed harnesses for available sync improvements.

        Args:
            installed: Dict mapping harness name -> current version (or None).

        Returns:
            Dict mapping harness name -> list of improvement dicts.
            Only includes harnesses that have pending improvements.
        """
        result: dict[str, list[dict]] = {}
        for harness, version in installed.items():
            improvements = self.get_available_improvements(harness, version)
            if improvements:
                result[harness] = improvements
        return result

    def format_feed(self, improvements: dict[str, list[dict]]) -> str:
        """Format the update feed as a human-readable report.

        Args:
            improvements: Output of get_all_improvements().

        Returns:
            Formatted string, or message indicating everything is up to date.
        """
        if not improvements:
            return "All installed harnesses support current sync capabilities. No upgrades needed."

        lines = ["Harness Update Feed — Sync Improvements Available", "=" * 55, ""]
        for harness in sorted(improvements):
                items = improvements[harness]
                lines.append(f"  {harness}  ({len(items)} improvement(s)):")
                for item in sorted(items, key=lambda x: x["version"]):
                    lines.append(f"    ↑ v{item['version']}: {item['note']}")
                lines.append("")

        lines.append("Upgrade these harnesses to unlock better HarnessSync fidelity.")
        lines.append("After upgrading, run /sync to apply improved config translation.")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Config Version Pinning
# ---------------------------------------------------------------------------

_PIN_STORE_PATH = Path.home() / ".harnesssync" / "version_pins.json"


@dataclass
class VersionPin:
    """A snapshot of the HarnessSync source config pinned at a specific point.

    Pinning records the source-side config hash at a moment in time.  When
    the source drifts from the pin, a notification is emitted so that teams
    running stable AI-assisted workflows can decide consciously when to
    accept config changes.

    Attributes:
        harness: Target harness the pin applies to (or "all").
        pinned_hash: SHA-256 hash of the source config at pin time.
        pinned_at: ISO 8601 timestamp when the pin was created.
        label: Optional human-readable label (e.g. "v1.2-stable").
        notify_on_drift: Whether to notify when source drifts from this pin.
    """
    harness: str
    pinned_hash: str
    pinned_at: str
    label: str = ""
    notify_on_drift: bool = True


def _load_pins() -> dict[str, VersionPin]:
    """Load pins from the persistent pin store."""
    if not _PIN_STORE_PATH.exists():
        return {}
    try:
        data = json.loads(_PIN_STORE_PATH.read_text(encoding="utf-8"))
        return {
            k: VersionPin(
                harness=k,
                pinned_hash=v.get("pinned_hash", ""),
                pinned_at=v.get("pinned_at", ""),
                label=v.get("label", ""),
                notify_on_drift=v.get("notify_on_drift", True),
            )
            for k, v in data.items()
        }
    except Exception:
        return {}


def _save_pins(pins: dict[str, VersionPin]) -> None:
    """Persist pins to the pin store."""
    _PIN_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        k: {
            "pinned_hash": p.pinned_hash,
            "pinned_at": p.pinned_at,
            "label": p.label,
            "notify_on_drift": p.notify_on_drift,
        }
        for k, p in pins.items()
    }
    _PIN_STORE_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def pin_config_version(
    harness: str,
    source_hash: str,
    label: str = "",
    notify_on_drift: bool = True,
) -> VersionPin:
    """Pin the current source config hash for a harness.

    Records the current hash so future syncs can detect when the source
    has changed relative to the pin.

    Args:
        harness: Harness name to pin, or "all" to pin all harnesses.
        source_hash: SHA-256 hash of the source config at pin time.
        label: Optional descriptive label (e.g. "v1.2-stable").
        notify_on_drift: Emit a notification when source drifts from pin.

    Returns:
        The created VersionPin.
    """
    from datetime import datetime, timezone
    pins = _load_pins()
    pin = VersionPin(
        harness=harness,
        pinned_hash=source_hash,
        pinned_at=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        label=label,
        notify_on_drift=notify_on_drift,
    )
    pins[harness] = pin
    _save_pins(pins)
    return pin


def check_pin_drift(
    harness: str,
    current_source_hash: str,
) -> dict:
    """Check whether the current source config has drifted from its pin.

    Args:
        harness: Harness name to check.
        current_source_hash: SHA-256 hash of the current source config.

    Returns:
        Dict with keys:
          ``pinned``: bool — True if a pin exists for this harness.
          ``drifted``: bool — True if the current hash differs from the pin.
          ``pin``: The VersionPin (or None if not pinned).
          ``message``: Human-readable status message.
    """
    pins = _load_pins()
    pin = pins.get(harness) or pins.get("all")
    if pin is None:
        return {"pinned": False, "drifted": False, "pin": None, "message": f"No pin set for '{harness}'."}

    drifted = pin.pinned_hash != current_source_hash
    label_str = f" ({pin.label})" if pin.label else ""
    if drifted:
        msg = (
            f"Config has drifted from pin set on {pin.pinned_at}{label_str}. "
            f"Review changes before syncing to '{harness}'."
        )
    else:
        msg = f"Config matches pin set on {pin.pinned_at}{label_str} — no drift detected."

    return {"pinned": True, "drifted": drifted, "pin": pin, "message": msg}


def list_pins() -> str:
    """Return a formatted list of all active version pins.

    Returns:
        Human-readable table of pins.
    """
    pins = _load_pins()
    if not pins:
        return "No version pins configured. Use /sync-pin to create one."

    lines = [
        "Active Version Pins",
        "=" * 50,
        f"{'Harness':<16} {'Pinned At':<26} {'Label':<20} Drift-Notify",
        "-" * 80,
    ]
    for harness, pin in sorted(pins.items()):
        notify_str = "yes" if pin.notify_on_drift else "no"
        lines.append(
            f"{harness:<16} {pin.pinned_at:<26} {pin.label[:20]:<20} {notify_str}"
        )
    return "\n".join(lines)


def remove_pin(harness: str) -> bool:
    """Remove the version pin for a harness.

    Args:
        harness: Harness name to unpin.

    Returns:
        True if a pin was removed, False if no pin existed.
    """
    pins = _load_pins()
    if harness not in pins:
        return False
    del pins[harness]
    _save_pins(pins)
    return True
