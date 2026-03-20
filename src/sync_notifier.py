from __future__ import annotations

"""Webhook and notification dispatch for sync operations.

Handles webhook delivery (both WebhookNotifier-based and legacy env var),
desktop notifications, and ambient terminal summary. Extracted from
SyncOrchestrator.
"""

import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

from src.adapters.result import SyncResult
from src.utils.logger import Logger


def send_webhook(
    results: dict,
    project_dir: Path | None,
    dry_run: bool,
    scope: str,
    account: str | None,
    logger: Logger,
) -> None:
    """Dispatch configured webhooks and scripts via WebhookNotifier.

    Delegates to ``WebhookNotifier`` (which reads ~/.harnesssync/webhooks.json)
    for full webhook/script support. Also honours the legacy env-var
    ``HARNESSSYNC_WEBHOOK_URL`` for backward compatibility.

    Network/script errors are logged but never block the sync.

    Args:
        results: Sync results dict from sync_all()
        project_dir: Project root directory
        dry_run: If True, preview mode (WebhookNotifier may skip sending)
        scope: Sync scope ("user" | "project" | "all")
        account: Account name (None = v1 behavior)
        logger: Logger instance
    """
    # Full webhook notifier (reads webhooks.json config)
    try:
        from src.webhook_notifier import WebhookNotifier
        notifier = WebhookNotifier(logger=logger)
        notifier.notify(results, project_dir=project_dir, dry_run=dry_run)
    except Exception as exc:
        logger.warn(f"WebhookNotifier failed: {exc}")

    # Legacy single-URL support via environment variable
    webhook_url = os.environ.get("HARNESSSYNC_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return

    summary: dict[str, dict] = {}
    for target, target_results in results.items():
        if target.startswith("_") or not isinstance(target_results, dict):
            continue
        synced = skipped = failed = 0
        for config_type, r in target_results.items():
            if isinstance(r, SyncResult):
                synced += r.synced
                skipped += r.skipped
                failed += r.failed
        summary[target] = {"synced": synced, "skipped": skipped, "failed": failed}

    payload = {
        "event": "sync_complete",
        "account": account,
        "scope": scope,
        "timestamp": datetime.now().isoformat(),
        "targets": summary,
    }
    body = json.dumps(payload).encode("utf-8")

    try:
        req = urllib.request.Request(
            webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception as exc:
        logger.warn(f"Legacy webhook POST failed: {exc}")


def send_desktop_notification(results: dict) -> None:
    """Send desktop notification with sync summary.

    Best-effort, never blocks sync.

    Args:
        results: Sync results dict from sync_all()
    """
    try:
        from src.desktop_notifier import notify_from_results
        notify_from_results(results)
    except Exception:
        pass  # Desktop notifications are best-effort, never block


def send_ambient_summary(results: dict) -> None:
    """Write a one-line summary + terminal bell to /dev/tty.

    So hook-triggered background syncs are always visible to the user
    without checking logs.

    Best-effort, never blocks sync.

    Args:
        results: Sync results dict from sync_all()
    """
    try:
        synced_count = sum(
            1 for t in results
            if not t.startswith("_") and isinstance(results.get(t), dict)
        )
        conflict_count = len(results.get("_conflicts") or {})
        failed_count = sum(
            getattr(r, "failed", 0)
            for t in results
            if not t.startswith("_") and isinstance(results.get(t), dict)
            for r in results[t].values()
            if hasattr(r, "failed")
        )
        parts = [f"Synced {synced_count} target(s)"]
        if conflict_count:
            parts.append(f"{conflict_count} conflict(s) skipped")
        if failed_count:
            parts.append(f"{failed_count} item(s) failed")
        summary_line = "HarnessSync: " + ". ".join(parts) + "."
        try:
            with open("/dev/tty", "w") as tty:
                tty.write(f"\x07{summary_line}\n")
                tty.flush()
        except OSError:
            if hasattr(sys.stderr, "isatty") and sys.stderr.isatty():
                try:
                    sys.stderr.write(f"\x07{summary_line}\n")
                    sys.stderr.flush()
                except OSError:
                    pass
    except Exception:
        pass  # Ambient notification is best-effort, never block sync
