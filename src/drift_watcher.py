from __future__ import annotations

"""Real-time drift alert watcher (item 3).

Runs a background thread that polls target harness config files for changes
not originating from HarnessSync and surfaces notifications with a /sync-restore
prompt. Solves silent config divergence that only surfaces as confusing behavior
differences between harnesses.

This module is a thin re-export facade. All implementation has been split into:
- src.drift_detector  — core detection logic, DriftWatcher class, drift_summary()
- src.drift_notifier  — notification delivery (OS, Slack, Discord, webhooks)
- src.drift_semantic  — semantic intent-level drift analysis
- src.drift_enforcement — ZeroDriftGuarantee, SourceChangeWatcher, guided merge
"""

# --- Core detection (drift_detector) ---
from src.drift_detector import (  # noqa: F401
    DEFAULT_POLL_INTERVAL,
    DriftAlert,
    DriftRootCause,
    DriftWatcher,
    analyze_drift_root_cause,
    drift_summary,
)

# --- Notification delivery (drift_notifier) ---
from src.drift_notifier import (  # noqa: F401
    format_status_line,
    make_notifying_alert_callback,
    send_discord_notification,
    send_generic_webhook_notification,
    send_os_notification,
    send_slack_notification,
)

# --- Semantic drift analysis (drift_semantic) ---
from src.drift_semantic import (  # noqa: F401
    SemanticDriftAlert,
    analyze_semantic_drift,
    semantic_drift_summary,
)

# --- Enforcement and merge (drift_enforcement) ---
from src.drift_enforcement import (  # noqa: F401
    GuidedMergeResult,
    MergeChoice,
    SourceChangeWatcher,
    ZeroDriftGuarantee,
    guided_merge_prompt,
)

__all__ = [
    # drift_detector
    "DEFAULT_POLL_INTERVAL",
    "DriftAlert",
    "DriftRootCause",
    "DriftWatcher",
    "analyze_drift_root_cause",
    "drift_summary",
    # drift_notifier
    "format_status_line",
    "make_notifying_alert_callback",
    "send_discord_notification",
    "send_generic_webhook_notification",
    "send_os_notification",
    "send_slack_notification",
    # drift_semantic
    "SemanticDriftAlert",
    "analyze_semantic_drift",
    "semantic_drift_summary",
    # drift_enforcement
    "GuidedMergeResult",
    "MergeChoice",
    "SourceChangeWatcher",
    "ZeroDriftGuarantee",
    "guided_merge_prompt",
]
