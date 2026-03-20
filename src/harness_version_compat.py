from __future__ import annotations

"""Harness version compatibility pinning — re-export shim.

This module was split into focused sub-modules for maintainability:
  - src/version_detection.py  — version parsing, detection, pinned version loading
  - src/compat_rules.py       — feature matrices, deprecated fields, compat checks
  - src/compat_transforms.py  — migration rules/functions, migration guides, update alerts
  - src/version_pinning.py    — config version pins, format matrix changes, update feed

All public names are re-exported here for backward compatibility.
Any ``from src.harness_version_compat import X`` continues to work.
"""

# -- version_detection exports --
from src.version_detection import (  # noqa: F401
    _DEFAULT_VERSIONS,
    _GLOBAL_VERSIONS_FILE,
    _detect_installed_version,
    _parse_version,
    _update_pinned_version,
    _version_gte,
    _version_lt,
    detect_all_installed_versions,
    detect_installed_version,
    load_pinned_versions,
)

# -- compat_rules exports --
from src.compat_rules import (  # noqa: F401
    DEPRECATED_FIELDS,
    VERSIONED_FEATURES,
    UpgradeRequirement,
    VersionCompatResult,
    check_deprecated_fields_in_output,
    check_version_compat,
    format_compat_warnings,
    format_installed_version_warnings,
    format_upgrade_requirements,
    format_upgrade_suggestions,
    get_compat_flags,
    get_installed_vs_required_table,
    get_upgrade_requirements,
    suggest_capability_upgrades,
    warn_deprecated_fields,
)

# -- compat_transforms exports --
from src.compat_transforms import (  # noqa: F401
    ConfigUpdateAlert,
    MigrationResult,
    detect_and_migrate,
    format_update_alerts,
    format_upgrade_migration_guide,
    generate_upgrade_migration_guide,
    migrate_config,
    validate_configs_after_update,
)

# -- version_pinning exports --
from src.version_pinning import (  # noqa: F401
    HarnessUpdateFeed,
    VersionPin,
    check_format_matrix_changes,
    check_pin_drift,
    detect_harness_updates,
    format_matrix_change_report,
    format_update_report,
    list_pins,
    pin_config_version,
    remove_pin,
)
