from __future__ import annotations

"""HarnessSync exception hierarchy.

Provides a structured exception hierarchy so that callers can catch
specific failure modes instead of bare ``Exception``.  All custom
exceptions inherit from ``HarnessSyncError`` which itself inherits
from ``Exception``, so existing ``except Exception`` handlers continue
to work as before.

Hierarchy
---------
HarnessSyncError
    ConfigError          -- config file parsing / loading failures
    AdapterError         -- adapter sync failures (write, translate, etc.)
    SyncError            -- orchestrator-level sync pipeline failures
    SecretDetectedError  -- secret detection blocked the sync
    ConflictError        -- target file conflict with manual edits
    StateError           -- state persistence / drift detection failures
    CompatibilityError   -- harness version / feature compatibility issues
"""


class HarnessSyncError(Exception):
    """Base exception for all HarnessSync errors.

    Catch this to handle any HarnessSync-specific error without catching
    unrelated standard library exceptions.
    """


class ConfigError(HarnessSyncError):
    """Raised when a configuration file cannot be read, parsed, or validated.

    Examples: malformed JSON/TOML, missing required fields, invalid paths.
    """


class AdapterError(HarnessSyncError):
    """Raised when an adapter fails to sync configuration to a target.

    Examples: write failures, unsupported field translation, missing
    target directories.
    """


class SyncError(HarnessSyncError):
    """Raised when the sync orchestrator encounters a pipeline-level failure.

    Examples: pre-sync check failures, post-sync verification errors,
    webhook dispatch failures.
    """


class SecretDetectedError(HarnessSyncError):
    """Raised when secret detection blocks a sync operation.

    The sync is aborted because API keys, tokens, or other sensitive
    values were found in environment variables or config content.
    """


class ConflictError(HarnessSyncError):
    """Raised when target files have been manually edited since the last sync.

    This is a warning-level condition: the sync can proceed but the user
    should be informed that their manual changes may be overwritten.
    """


class StateError(HarnessSyncError):
    """Raised when state persistence or drift detection fails.

    Examples: corrupted state JSON, atomic write failure, backup of
    corrupted state file failure.
    """


class CompatibilityError(HarnessSyncError):
    """Raised when a harness version or feature is incompatible.

    Examples: deprecated config fields, unsupported transport types,
    missing feature flags.
    """
