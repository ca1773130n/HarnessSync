from __future__ import annotations

"""Sync orchestrator coordinating SourceReader -> AdapterRegistry -> StateManager.

SyncOrchestrator is the central coordination layer invoked by both
/sync command and PostToolUse hook. It reads source config, syncs to
all registered adapters, and updates state. Supports scope filtering,
dry-run preview mode, and per-account sync operations.
"""

from datetime import datetime
from pathlib import Path

from src.adapters import AdapterRegistry
from src.adapters.result import SyncResult
from src.backup_manager import BackupManager
from src.changelog_manager import ChangelogManager
from src.compatibility_reporter import CompatibilityReporter
from src.config_linter import ConfigLinter
from src.conflict_detector import ConflictDetector
from src.diff_formatter import DiffFormatter
from src.secret_detector import SecretDetector
from src.source_reader import SourceReader
from src.state_manager import StateManager
from src.sync_filter import filter_rules_for_target, filter_rules_for_env, has_sync_tags
from src.symlink_cleaner import SymlinkCleaner
from src.utils.hashing import hash_file_sha256
from src.utils.logger import Logger


class SyncOrchestrator:
    """Coordinates sync operations across all adapters.

    Note: sync_all() does NOT acquire locks or check debounce.
    Callers (commands, hooks) handle concurrency control.
    """

    def __init__(self, project_dir: Path, scope: str = "all", dry_run: bool = False,
                 allow_secrets: bool = False, scrub_secrets: bool = False,
                 account: str = None, cc_home: Path = None,
                 only_sections: set = None, skip_sections: set = None,
                 incremental: bool = False,
                 cli_only_targets: set = None, cli_skip_targets: set = None,
                 harness_env: str = None,
                 cli_per_target_only: dict = None,
                 minimal: bool = False):
        """Initialize orchestrator.

        Args:
            project_dir: Project root directory
            scope: "user" | "project" | "all"
            dry_run: If True, preview changes without writing
            allow_secrets: If True, allow sync even when secrets detected in env vars
            scrub_secrets: If True, replace detected secret values with ${VAR_NAME}
                           placeholders before syncing instead of blocking.
            account: Account name for per-account sync (None = v1 behavior)
            cc_home: Custom Claude Code config directory (derived from account if provided)
            only_sections: If set, only sync these sections (rules/skills/agents/commands/mcp/settings)
            skip_sections: If set, skip these sections
            incremental: If True, skip targets where no source files changed since last sync
            harness_env: Environment name for env-tagged section filtering (e.g. 'production', 'dev').
                         Falls back to HARNESS_ENV environment variable if not provided.
            cli_per_target_only: Per-target section overrides from --only-for CLI flag.
                                 Maps target_name -> set of section names to sync for that target only.
                                 E.g. {"gemini": {"skills", "rules"}, "codex": {"rules", "mcp"}}
            minimal: If True, activate Minimal Footprint Mode — sync only the highest-value
                     subset to each target (rules + essential MCP servers only). Skills, agents,
                     commands, and non-essential MCP servers are skipped. This is equivalent to
                     setting only_sections={"rules", "mcp"} with essential-only MCP filtering.
        """
        self.project_dir = project_dir
        self.scope = scope
        self.dry_run = dry_run
        self.minimal = minimal
        # Minimal Footprint Mode: restrict to rules + essential MCP only.
        # Applied before CLI flags so explicit --only overrides it.
        if minimal and not only_sections:
            only_sections = {"rules", "mcp"}
        self.allow_secrets = allow_secrets
        self.scrub_secrets = scrub_secrets
        self.account = account
        self.cc_home = cc_home
        self.only_sections = only_sections or set()
        self.skip_sections = skip_sections or set()
        self.incremental = incremental
        # CLI-level target filters (applied before per-project .harnesssync overrides)
        self.cli_only_targets: set[str] = cli_only_targets or set()
        self.cli_skip_targets: set[str] = cli_skip_targets or set()
        # CLI-level per-target section overrides (from --only-for TARGET:sections)
        self._cli_per_target_only: dict[str, set[str]] = cli_per_target_only or {}
        # Environment-aware sync: resolve from arg, then HARNESS_ENV env var
        import os as _os
        self.harness_env: str | None = harness_env or _os.environ.get("HARNESS_ENV") or None
        self.logger = Logger()
        self.state_manager = StateManager()
        # Apply persistent global dry-run mode if not already enabled by caller
        if not dry_run and self.state_manager.get_global_dry_run():
            self.dry_run = True
            self.logger.info("Global dry-run mode is active (set via /sync --enable-global-dry-run)")
        self.account_config = None
        # Per-project config target overrides (populated by _apply_project_config)
        self._project_skip_targets: set[str] = set()
        self._project_only_targets: set[str] = set()
        self._profile_targets: list[str] | None = None
        self._per_target_skip: dict[str, set] = {}
        self._per_target_only: dict[str, set] = {}

        # Resolve account config if account specified
        if account and not cc_home:
            try:
                from src.account_manager import AccountManager
                am = AccountManager()
                acc = am.get_account(account)
                if acc:
                    self.cc_home = Path(acc["source"]["path"])
                    self.account_config = acc
                else:
                    self.logger.warn(f"Account '{account}' not found, using defaults")
            except Exception as e:
                self.logger.warn(f"Could not load account '{account}': {e}")

    def _load_project_config(self) -> dict:
        """Load per-project .harnesssync config file overrides.

        The file at <project_dir>/.harnesssync (JSON) can override global
        sync options for this specific project:

        {
            "profile": "minimal",         // activate a named profile
            "skip_sections": ["mcp"],     // sections to skip (all targets)
            "only_sections": ["rules"],   // only these sections (all targets)
            "skip_targets": ["aider"],    // harness targets to exclude
            "only_targets": ["codex"],    // only these harness targets
            "targets": {                  // per-target section overrides (item 3)
                "cursor": {"skip_sections": ["skills"]},
                "aider":  {"only_sections": ["rules"]}
            }
        }

        Returns:
            Dict with project-level overrides (empty if file not found/invalid)
        """
        if not self.project_dir:
            return {}
        config_path = self.project_dir / ".harnesssync"
        if not config_path.exists():
            return {}
        try:
            import json
            data = json.loads(config_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _apply_project_config(self, project_cfg: dict) -> None:
        """Merge project-level .harnesssync overrides into orchestrator settings.

        Args:
            project_cfg: Dict from _load_project_config()
        """
        if not project_cfg:
            return

        # Apply named profile if specified
        profile_name = project_cfg.get("profile")
        if profile_name:
            try:
                from src.profile_manager import ProfileManager
                pm = ProfileManager()
                base = {
                    "scope": self.scope,
                    "only_sections": self.only_sections,
                    "skip_sections": self.skip_sections,
                }
                merged = pm.apply_to_kwargs(profile_name, base)
                self.scope = merged.get("scope", self.scope)
                self.only_sections = merged.get("only_sections", self.only_sections)
                self.skip_sections = merged.get("skip_sections", self.skip_sections)
                self._profile_targets = merged.get("profile_targets")
            except (KeyError, Exception):
                pass  # Profile not found or error — proceed without it

        # Section overrides (additive — project config extends CLI flags)
        cfg_skip = set(project_cfg.get("skip_sections", []))
        if cfg_skip:
            self.skip_sections = self.skip_sections | cfg_skip

        cfg_only = set(project_cfg.get("only_sections", []))
        if cfg_only:
            # Intersect: only sync sections that both caller AND project want
            if self.only_sections:
                self.only_sections = self.only_sections & cfg_only
            else:
                self.only_sections = cfg_only

        # Target overrides stored for use in sync_all
        self._project_skip_targets = set(project_cfg.get("skip_targets", []))
        self._project_only_targets = set(project_cfg.get("only_targets", []))

        # Per-target section overrides (item 3 — Per-Feature Sync Toggles).
        # Stored as: {target_name: {"skip": set(...), "only": set(...)}}
        # Config format in .harnesssync:
        #   "targets": {
        #     "cursor": {"skip_sections": ["skills"]},
        #     "aider":  {"only_sections": ["rules"]}
        #   }
        self._per_target_skip: dict[str, set] = {}
        self._per_target_only: dict[str, set] = {}
        for tgt, tgt_cfg in project_cfg.get("targets", {}).items():
            tgt = tgt.lower()
            tgt_skip = set(tgt_cfg.get("skip_sections", []))
            tgt_only = set(tgt_cfg.get("only_sections", []))
            if tgt_skip:
                self._per_target_skip[tgt] = tgt_skip
            if tgt_only:
                self._per_target_only[tgt] = tgt_only

        # --- CONDITIONAL SYNC RULES ENGINE (Item 12) ---
        # Evaluate ``sync_conditions`` entries in .harnesssync and apply their
        # actions when their predicates are satisfied at runtime.
        #
        # Supported predicate keys:
        #   "file_exists": "<relative-path>"        — true when file present
        #   "file_missing": "<relative-path>"       — true when file absent
        #   "file_size_gt": {"<path>": <bytes>}     — true when file exceeds size
        #   "env_set": "<VAR_NAME>"                 — true when env var is non-empty
        #
        # Supported action keys:
        #   "then_skip_targets": [...]              — add targets to skip list
        #   "then_only_targets": [...]              — restrict to these targets only
        #   "then_skip_sections": [...]             — add sections to skip
        #   "then_only_sections": [...]             — restrict to these sections
        #
        # Example .harnesssync:
        #   {
        #     "sync_conditions": [
        #       {"if_file_exists": ".cursorrules",    "then_skip_targets": ["cursor"]},
        #       {"if_file_size_gt": {"GEMINI.md": 51200}, "then_skip_targets": ["gemini"]},
        #       {"if_env_set": "CI", "then_skip_sections": ["commands"]}
        #     ]
        #   }
        try:
            _conditions = project_cfg.get("sync_conditions", [])
            if _conditions and self.project_dir:
                import os as _os
                for _cond in _conditions:
                    if not isinstance(_cond, dict):
                        continue

                    # --- Evaluate predicate ---
                    _satisfied = False

                    if "if_file_exists" in _cond:
                        _fp = self.project_dir / _cond["if_file_exists"]
                        _satisfied = _fp.exists()
                    elif "if_file_missing" in _cond:
                        _fp = self.project_dir / _cond["if_file_missing"]
                        _satisfied = not _fp.exists()
                    elif "if_file_size_gt" in _cond:
                        _size_map = _cond["if_file_size_gt"]
                        if isinstance(_size_map, dict):
                            for _rel, _thresh in _size_map.items():
                                _fp = self.project_dir / _rel
                                if _fp.exists():
                                    try:
                                        if _fp.stat().st_size > int(_thresh):
                                            _satisfied = True
                                            break
                                    except OSError:
                                        pass
                    elif "if_env_set" in _cond:
                        _env_name = _cond["if_env_set"]
                        _satisfied = bool(_os.environ.get(str(_env_name), "").strip())

                    if not _satisfied:
                        continue

                    # --- Apply actions ---
                    _skip_tgts = _cond.get("then_skip_targets", [])
                    if _skip_tgts:
                        self._project_skip_targets = self._project_skip_targets | set(_skip_tgts)

                    _only_tgts = _cond.get("then_only_targets", [])
                    if _only_tgts:
                        existing = self._project_only_targets
                        if existing:
                            self._project_only_targets = existing & set(_only_tgts)
                        else:
                            self._project_only_targets = set(_only_tgts)

                    _skip_secs = _cond.get("then_skip_sections", [])
                    if _skip_secs:
                        self.skip_sections = self.skip_sections | set(_skip_secs)

                    _only_secs = _cond.get("then_only_sections", [])
                    if _only_secs:
                        if self.only_sections:
                            self.only_sections = self.only_sections & set(_only_secs)
                        else:
                            self.only_sections = set(_only_secs)

                    self.logger.info(
                        f"Conditional sync rule applied: {_cond}"
                    )
        except Exception as _cond_err:
            self.logger.warn(f"Conditional sync rules evaluation failed: {_cond_err}")

        # Apply git branch-aware profile overrides (most specific branch match wins)
        try:
            from src.branch_aware_sync import resolve_branch_profile, apply_branch_profile, describe_active_profile
            branch_profile = resolve_branch_profile(self.project_dir, project_cfg)
            if branch_profile and not branch_profile.is_empty:
                import subprocess as _sp
                branch_name = ""
                try:
                    r = _sp.run(
                        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                        capture_output=True, text=True,
                        cwd=str(self.project_dir), timeout=3,
                    )
                    branch_name = r.stdout.strip() if r.returncode == 0 else ""
                except Exception:
                    pass
                (
                    self.skip_sections,
                    self.only_sections,
                    self._project_skip_targets,
                    self._project_only_targets,
                    self.scope,
                ) = apply_branch_profile(
                    branch_profile,
                    self.skip_sections,
                    self.only_sections,
                    self._project_skip_targets,
                    self._project_only_targets,
                    self.scope,
                )
                if branch_name:
                    self.logger.info(describe_active_profile(branch_profile, branch_name))
        except Exception as _e:
            self.logger.warn(f"Branch profile resolution failed: {_e}")

    def sync_all(self) -> dict:
        """Sync all configuration to all registered adapters.

        Implements full safety pipeline:
        1. Load per-project .harnesssync config overrides
        2. Secret detection (blocks if secrets found, unless allow_secrets=True)
        3. Conflict detection (warns but does not block)
        4. Backup (pre-sync, with automatic rollback on failure)
        5. Sync adapters
        6. Symlink cleanup (post-sync)
        7. Compatibility report (post-sync)
        8. Backup retention cleanup

        Returns:
            Dict mapping target_name -> {config_type: SyncResult} or preview dict
            Special keys: '_blocked', '_reason', '_warnings', '_conflicts', '_compatibility_report'
        """
        # --- PRE-SYNC: LOAD PER-PROJECT CONFIG OVERRIDES ---
        project_cfg = self._load_project_config()
        if project_cfg:
            self._apply_project_config(project_cfg)

        # Create SourceReader with account-specific cc_home if provided
        reader = SourceReader(scope=self.scope, project_dir=self.project_dir,
                              cc_home=self.cc_home)
        source_data = reader.discover_all()

        # --- PRE-SYNC: SKILL DEPENDENCY CHECK (item 28) ---
        # Build a dependency graph from skills and warn about circular deps or
        # references to skills that don't exist — before they cause silent sync failures.
        try:
            from src.skill_dependency_graph import SkillDependencyGraph
            _skill_graph = SkillDependencyGraph.from_source_data(source_data)
            _cycles = _skill_graph.find_cycles()
            for _cycle in _cycles:
                _arrow = " \u2192 "
                self.logger.warn(
                    f"Skill dependency cycle detected: {_arrow.join(_cycle)} "
                    "— this may cause unexpected behavior when skills are synced"
                )
            # Warn about edges referencing skills that don't exist in the skills dir
            _known_skills = set(_skill_graph._nodes.keys())
            _missing_warned: set[str] = set()
            for _edge in _skill_graph._edges:
                if (
                    _edge.target not in _known_skills
                    and _edge.kind in ("explicit", "slash")
                    and _edge.target not in _missing_warned
                ):
                    _missing_warned.add(_edge.target)
                    self.logger.warn(
                        f"Skill '{_edge.source}' references '/{_edge.target}' which is "
                        "not in your skills directory — dependency will be absent on sync targets"
                    )
        except Exception:
            pass  # Dependency check is informational, never blocks sync

        # --- PRE-SYNC: CONFIG VARIABLE SUBSTITUTION (${VAR} placeholders) ---
        # Substitute ${PROJECT_NAME}, ${GIT_USER}, ${REPO_URL}, etc. in rules content.
        # Custom variables can be declared in .harnesssync under "vars".
        try:
            from src.source_reader import substitute_config_vars
            rules_raw = source_data.get('rules', '')
            if isinstance(rules_raw, str) and '${' in rules_raw:
                substituted, replaced_vars = substitute_config_vars(
                    rules_raw, project_dir=self.project_dir
                )
                source_data['rules'] = substituted
                if replaced_vars:
                    self.logger.info(
                        f"Config vars substituted: {', '.join(f'${{{v}}}' for v in sorted(set(replaced_vars)))}"
                    )
        except Exception:
            pass  # Variable substitution is best-effort, never blocks sync

        # Convert rules string to list[dict] format expected by adapters
        rules_str = source_data.get('rules', '')
        if isinstance(rules_str, str) and rules_str:
            source_data['rules'] = [{'path': 'CLAUDE.md', 'content': rules_str}]
        elif isinstance(rules_str, str):
            source_data['rules'] = []

        # Merge rules from .claude/rules/ directories into the rules list
        rules_files = source_data.get('rules_files', [])
        for rf in rules_files:
            source_data['rules'].append({
                'path': str(rf['path']),
                'content': rf['content'],
                'scope_patterns': rf.get('scope_patterns', []),
                'scope': rf.get('scope', 'project'),
            })

        # --- PRE-SYNC: RULE SOURCE ATTRIBUTION RECORDING ---
        # Record provenance for each source rule file so users can trace synced
        # rules back to their origin (file, line number, section heading).
        if not self.dry_run and self.project_dir:
            try:
                from src.rule_source_attribution import RuleAttributor
                _attributor = RuleAttributor(project_dir=self.project_dir)
                for _rf in source_data.get('rules', []):
                    if isinstance(_rf, dict):
                        _rule_path = _rf.get('path')
                        if _rule_path:
                            _full_path = self.project_dir / _rule_path
                            if _full_path.is_file():
                                _attributor.record_from_file(_full_path)
                if _attributor.rule_count > 0:
                    _attributor.save_index()
            except Exception:
                pass  # Attribution recording is best-effort, never blocks sync

        # --- PRE-SYNC: PROJECT-TYPE ADAPTIVE SYNC ---
        # Auto-detect project type and apply relevant config filtering defaults.
        # Only applied when user hasn't manually set only_sections/skip_sections.
        if not self.only_sections and not self.skip_sections:
            try:
                from src.project_detector import ProjectTypeDetector
                detector = ProjectTypeDetector(self.project_dir)
                profile = detector.detect()
                if profile and profile.suggested_skip_sections:
                    self.skip_sections = set(profile.suggested_skip_sections)
                    self.logger.info(
                        f"Project type '{profile.project_type}' detected — "
                        f"auto-skipping sections: {', '.join(sorted(self.skip_sections))}"
                    )
            except Exception:
                pass  # Adaptive sync is best-effort, never blocks

        # Translate key: SourceReader uses 'mcp_servers', adapters expect 'mcp'
        adapter_data = dict(source_data)
        raw_mcp = adapter_data.pop('mcp_servers', {}) or {}

        # Minimal Footprint Mode: strip non-essential MCP servers so each target
        # only receives the servers marked "essential": true in .mcp.json.
        # An MCP server without an "essential" key is treated as non-essential.
        if self.minimal and isinstance(raw_mcp, dict):
            essential_mcp = {
                name: cfg for name, cfg in raw_mcp.items()
                if isinstance(cfg, dict) and cfg.get("essential", False)
            }
            if not essential_mcp:
                # No servers explicitly marked essential — keep all (better than empty)
                essential_mcp = raw_mcp
                self.logger.info(
                    "Minimal mode: no MCP servers marked 'essential' — syncing all MCP servers. "
                    "Add '\"essential\": true' to a server in .mcp.json to limit footprint."
                )
            else:
                skipped_count = len(raw_mcp) - len(essential_mcp)
                self.logger.info(
                    f"Minimal mode: syncing {len(essential_mcp)} essential MCP server(s), "
                    f"skipping {skipped_count} non-essential."
                )
            raw_mcp = essential_mcp

        adapter_data['mcp'] = raw_mcp
        # Pass scoped MCP data for v2.0 scope-aware adapters
        adapter_data['mcp_scoped'] = source_data.get('mcp_servers_scoped', {})

        # --- MODEL ROUTING HINTS: parse Claude Code settings for model preferences ---
        _model_routing_hints = None
        _model_routing_summary: list[str] = []  # Per-target model sync annotations
        try:
            from src.model_routing import ModelRoutingAdapter, extract_routing_hints_from_settings_file
            _mr_adapter = ModelRoutingAdapter()
            _settings_raw = source_data.get('settings', {})
            if isinstance(_settings_raw, dict) and _settings_raw:
                _model_routing_hints = _mr_adapter.read_from_settings(_settings_raw)
            elif self.cc_home:
                _settings_path = (self.cc_home or Path.home() / ".claude") / "settings.json"
                if _settings_path.exists():
                    _model_routing_hints = extract_routing_hints_from_settings_file(_settings_path)
        except Exception:
            pass  # Model routing extraction is best-effort

        # --- PRE-SYNC: SYNC IMPACT PREDICTION ---
        # Predict behavioral impact of pending changes (informational, never blocks)
        if self.dry_run:
            try:
                from src.sync_impact_predictor import SyncImpactPredictor
                from src.state_manager import StateManager as _SM
                _prev_source: dict = {}
                try:
                    # Attempt to reconstruct previous source from state snapshot
                    _sm_prev = _SM()
                    _prev_snap = _sm_prev.get_all_status().get("last_source_snapshot", {})
                    if isinstance(_prev_snap, dict):
                        _prev_source = _prev_snap
                except Exception:
                    pass
                predictor = SyncImpactPredictor(self.project_dir)
                impact_report = predictor.predict(source_data, _prev_source)
                if not impact_report.is_empty:
                    self.logger.info(impact_report.format())
            except Exception:
                pass  # Impact prediction is informational, never blocks

        # --- PRE-SYNC: MCP REACHABILITY CHECK ---
        # Warn (but do not block) if any MCP servers are unreachable
        try:
            from src.mcp_reachability import McpReachabilityChecker
            checker = McpReachabilityChecker()
            mcp_servers_for_check = source_data.get('mcp_servers', {})
            if mcp_servers_for_check:
                reach_results = checker.check_all(mcp_servers_for_check)
                for warning in checker.get_warnings(reach_results):
                    self.logger.warn(f"Pre-sync: {warning}")
        except Exception as e:
            self.logger.warn(f"MCP reachability check failed: {e}")

        # --- PRE-SYNC: CAPABILITY GAP WARNINGS (Item 1) ---
        # Surface which rules/skills/MCP servers will be silently dropped or
        # approximated in each target harness before sync begins.
        try:
            from src.capability_advisor import CapabilityAdvisor
            _cap_advisor = CapabilityAdvisor()
            _cap_report = _cap_advisor.analyze_source_data(source_data)
            if _cap_report and not _cap_report.is_empty:
                for _cap_warning in _cap_report.warnings:
                    self.logger.warn(
                        f"Capability gap [{_cap_warning.harness}]: {_cap_warning.message}"
                    )
        except Exception:
            pass  # Capability gap warnings are informational, never block sync

        # --- PRE-SYNC: SECRET DETECTION ---
        # Scan MCP env vars AND CLAUDE.md/rules files before any writes.
        # Item 4: catches API keys pasted into markdown rules, not just MCP env.
        try:
            secret_detector = SecretDetector()

            # Scan MCP server environment variables
            detections = secret_detector.scan_mcp_env(source_data.get('mcp_servers', {}))

            # Also scan CLAUDE.md and related config files for inline secrets
            if self.project_dir:
                file_detections = secret_detector.scan_config_files(self.project_dir)
                detections = detections + file_detections

            if detections:
                if self.scrub_secrets:
                    # Scrub mode: replace secret values with ${VAR_NAME} placeholders
                    # instead of blocking. Sync proceeds with sanitised MCP config.
                    scrubbed_mcp, scrubbed_names = secret_detector.scrub_mcp_env(
                        source_data.get('mcp_servers', {})
                    )
                    if scrubbed_names:
                        source_data['mcp_servers'] = scrubbed_mcp
                        adapter_data['mcp'] = scrubbed_mcp
                        scrub_report = secret_detector.format_scrub_report(scrubbed_names)
                        self.logger.warn(scrub_report)

                    # Also scrub inline secrets from rules content
                    rules = source_data.get('rules', [])
                    if rules:
                        scrubbed_rules, rule_descs = secret_detector.scrub_rules_content(rules)
                        if rule_descs:
                            source_data['rules'] = scrubbed_rules
                            adapter_data['rules'] = scrubbed_rules
                            self.logger.warn(
                                f"Scrubbed {len(rule_descs)} inline secret(s) from rules: "
                                + ", ".join(rule_descs[:5])
                                + ("..." if len(rule_descs) > 5 else "")
                            )
                elif secret_detector.should_block(detections, self.allow_secrets):
                    # Block sync - return early with warning
                    formatted_warnings = secret_detector.format_warnings(detections)
                    self.logger.warn("Sync blocked: secrets detected in config files or environment variables")
                    # Record to audit log so /sync-status can show what was blocked and why
                    try:
                        from src.audit_log import AuditLog
                        _audit = AuditLog(project_dir=self.project_dir)
                        from src.adapters import AdapterRegistry
                        _protected = AdapterRegistry.list_targets()
                        _audit.record_secret_block(
                            detections=detections,
                            protected_targets=_protected,
                        )
                    except Exception:
                        pass  # Audit logging is best-effort
                    return {
                        '_blocked': True,
                        '_reason': 'secrets_detected',
                        '_warnings': formatted_warnings
                    }
        except ImportError as e:
            self.logger.warn(f"SecretDetector unavailable: {e}")

        # --- PRE-SYNC: CONFIG LINTING ---
        try:
            linter = ConfigLinter()
            lint_errors = linter.lint(source_data, self.project_dir, self.cc_home)
            if lint_errors:
                self.logger.warn("Config linter found issues:")
                for err in lint_errors:
                    self.logger.warn(f"  {err}")
        except Exception as e:
            self.logger.warn(f"Config linter failed: {e}")

        # --- PRE-SYNC: HARNESS VERSION COMPATIBILITY CHECK ---
        try:
            from src.harness_version_compat import format_compat_warnings
            compat_warnings = format_compat_warnings(project_dir=self.project_dir)
            for w in compat_warnings:
                self.logger.warn(f"Version compat: {w}")
        except Exception:
            pass  # Version compat check is informational, never blocks

        # --- PRE-SYNC: PERMISSION ESCALATION GUARD ---
        # Detect when sync would grant targets MORE permissions than the source.
        try:
            from src.permission_escalation_guard import check_escalation
            _source_settings = source_data.get('settings', {}) or {}
            if _source_settings:
                _esc_report = check_escalation(_source_settings)
                if _esc_report.has_blocks:
                    self.logger.warn("Permission escalation guard: BLOCK-level escalations detected:")
                    for _esc_w in _esc_report.warnings:
                        if _esc_w.severity == "block":
                            self.logger.warn(f"  {_esc_w.format()}")
                    self.logger.warn(
                        "Tip: Use /sync-override to set per-harness restrictions, "
                        "or /sync-permissions to review the full report."
                    )
                elif _esc_report.has_escalations:
                    self.logger.warn("Permission escalation guard: potential permission gaps:")
                    for _esc_w in _esc_report.warnings:
                        self.logger.warn(f"  {_esc_w.format()}")
        except Exception:
            pass  # Escalation guard is best-effort, never blocks sync

        # --- PRE-SYNC: POLICY ENFORCEMENT (item 25) ---
        # Check org/team policy before any writes; block if must_not_sync violated.
        try:
            from src.sync_policy import PolicyEnforcer
            _policy = PolicyEnforcer(project_dir=self.project_dir)
            if _policy.has_policy:
                _pre_policy_targets = AdapterRegistry.list_targets()
                _policy_result = _policy.check_all(source_data, targets=_pre_policy_targets)
                if _policy_result.any_blocked:
                    self.logger.warn("Sync blocked by policy:")
                    for _pr in _policy_result.reports:
                        if _pr.blocked:
                            for _pv in _pr.violations:
                                if _pv.severity == "error":
                                    self.logger.warn(f"  [{_pv.target}] {_pv.section}: {_pv.message}")
                    return {
                        '_blocked': True,
                        '_reason': 'policy_violation',
                        '_warnings': _policy_result.format(),
                    }
                for _pr in _policy_result.reports:
                    for _w in _pr.warnings:
                        self.logger.warn(f"Policy [{_pr.target}]: {_w}")
        except Exception:
            pass  # Policy check is best-effort, never crashes sync

        # --- PRE-SYNC: CONFLICT DETECTION ---
        # Run conflict detection (non-blocking, informational)
        conflicts = {}
        try:
            conflict_detector = ConflictDetector(self.state_manager)
            conflicts = conflict_detector.check_all()

            # Log conflicts but do not block
            if any(conflicts.values()):
                formatted_conflicts = conflict_detector.format_warnings(conflicts)
                self.logger.warn(formatted_conflicts)
        except ImportError as e:
            self.logger.warn(f"ConflictDetector unavailable: {e}")

        targets = AdapterRegistry.list_targets()

        # Apply per-project and per-profile target filters
        if self._project_only_targets:
            targets = [t for t in targets if t in self._project_only_targets]
        if self._project_skip_targets:
            targets = [t for t in targets if t not in self._project_skip_targets]
        if self._profile_targets:
            targets = [t for t in targets if t in self._profile_targets]

        # Apply CLI-level --only-targets / --skip-targets (highest priority)
        if self.cli_only_targets:
            targets = [t for t in targets if t in self.cli_only_targets]
        if self.cli_skip_targets:
            targets = [t for t in targets if t not in self.cli_skip_targets]

        results = {}

        # --- PRE-SYNC: BACKUP (skip in dry-run) ---
        backup_manager = None
        if not self.dry_run:
            try:
                backup_manager = BackupManager()
            except ImportError as e:
                self.logger.warn(f"BackupManager unavailable: {e}")

        # --- PRE-SYNC: AUTO-SNAPSHOT (Config Snapshot Versioning, item 28) ---
        # Take a named snapshot before every real sync so users can restore
        # to any past state, not just the most recent backup.
        if not self.dry_run:
            try:
                from src.config_time_machine import ConfigTimeMachine
                _ctm = ConfigTimeMachine(self.project_dir)
                _snap_name = f"pre-sync-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
                _ctm.take_snapshot(name=_snap_name, cc_home=self.cc_home)
                self.logger.debug(f"Auto-snapshot saved: {_snap_name}")
            except Exception:
                pass  # Auto-snapshot is best-effort, never blocks sync

        # --- PRE-SYNC: CAPTURE USER ANNOTATIONS (skip in dry-run) ---
        _captured_annotations: dict = {}
        if not self.dry_run:
            try:
                from src.annotation_preserver import AnnotationPreserver
                _ann_preserver = AnnotationPreserver(self.project_dir)
                _captured_annotations = _ann_preserver.capture_all(targets)
            except Exception:
                pass  # Annotation preservation is best-effort

        # Detect if any rules have sync tags (used for per-target filtering)
        _rules_have_tags = any(
            has_sync_tags(r.get('content', '')) for r in adapter_data.get('rules', [])
            if isinstance(r, dict)
        )

        # Detect if any rules have inline harness annotations (<!-- cursor-only -->, <!-- skip:aider -->)
        _rules_have_annotations = False
        try:
            from src.annotation_filter import AnnotationFilter as _AnnFilter
            _rules_have_annotations = any(
                _AnnFilter.has_annotations(r.get('content', ''))
                for r in adapter_data.get('rules', [])
                if isinstance(r, dict)
            )
            if _rules_have_annotations:
                self.logger.info(
                    f"Inline harness annotations detected — will filter per target"
                )
        except Exception:
            pass  # Annotation filter is best-effort

        # --- USER-DEFINED TRANSFORM RULES: load once per sync run ---
        _transform_engine = None
        try:
            from src.transform_engine import TransformEngine
            _transform_engine = TransformEngine.load(self.project_dir)
            if _transform_engine.has_rules():
                self.logger.info(f"Transform engine: {len(_transform_engine.rules)} rule(s) loaded")
        except Exception:
            pass  # Transform rules are best-effort

        # --- INCREMENTAL: PRE-COMPUTE CURRENT FILE HASHES (for delta check) ---
        _current_hashes: dict[str, str] = {}
        if self.incremental:
            _source_paths = reader.get_source_paths()
            for _paths in _source_paths.values():
                for _p in _paths:
                    if _p.is_file():
                        _h = hash_file_sha256(_p)
                        if _h:
                            _current_hashes[str(_p)] = _h

        # --- SYNC: EXECUTE ADAPTERS (wrapped in BackupContext if available) ---
        for target in targets:
            adapter = AdapterRegistry.get_adapter(target, self.project_dir)
            _tmp_dir = None  # Temp dir for agent translation hints; cleaned up in finally

            # --- INCREMENTAL: skip target if no source files changed ---
            if self.incremental and _current_hashes:
                drifted = self.state_manager.detect_drift(target, _current_hashes,
                                                           account=self.account)
                if not drifted:
                    self.logger.info(f"{target}: no changes since last sync, skipping (incremental)")
                    results[target] = {'_skipped_incremental': SyncResult(skipped=1)}
                    continue

            if self.dry_run:
                results[target] = self._preview_sync(adapter, adapter_data)
            else:
                # --- OFFLINE QUEUE: check target availability before syncing ---
                try:
                    from src.offline_queue import OfflineQueue, is_target_available
                    if not is_target_available(target, self.project_dir):
                        self.logger.warn(
                            f"{target}: config directory unavailable — queuing for later replay"
                        )
                        oq = OfflineQueue()
                        oq.enqueue(
                            target=target,
                            source_snapshot=adapter_data,
                            reason="target config directory unavailable",
                            project_dir=str(self.project_dir),
                        )
                        results[target] = {
                            '_queued': SyncResult(skipped=1, skipped_files=[
                                f"{target}: queued (offline)"
                            ])
                        }
                        continue
                except ImportError:
                    pass  # offline_queue not available — proceed normally

                # Build target-specific data (applying env + sync tag filtering)
                target_data = dict(adapter_data)
                # Step 1: filter env-tagged sections (e.g. @env:production blocks)
                if self.harness_env:
                    target_data['rules'] = [
                        {**r, 'content': filter_rules_for_env(r.get('content', ''), self.harness_env)}
                        for r in adapter_data.get('rules', [])
                        if isinstance(r, dict)
                    ]
                # Step 2: filter per-target sync tags (e.g. <!-- sync:codex-only -->)
                if _rules_have_tags:
                    _rules_source = target_data.get('rules', adapter_data.get('rules', []))
                    target_data['rules'] = [
                        {**r, 'content': filter_rules_for_target(r.get('content', ''), target)}
                        for r in _rules_source
                        if isinstance(r, dict)
                    ]
                # Step 2b: filter inline harness annotations (<!-- cursor-only -->, <!-- skip:aider -->)
                if _rules_have_annotations:
                    try:
                        _ann_rules = target_data.get('rules', adapter_data.get('rules', []))
                        _ann_filtered = _AnnFilter.filter_rules_for_target(_ann_rules, target)
                        if isinstance(_ann_filtered, list):
                            target_data['rules'] = _ann_filtered
                    except Exception:
                        pass  # Annotation filter is best-effort

                # Step 3: apply user-defined transform rules
                if _transform_engine and _transform_engine.has_rules():
                    target_data['rules'] = _transform_engine.apply_to_rules(
                        target_data.get('rules', adapter_data.get('rules', [])), target
                    )
                # Step 4: apply rule category tag filtering (Item 12)
                # Filters tagged sections (<!-- #security --> etc.) per harness policy.
                try:
                    from src.rule_tagger import RuleTagger
                    _rule_tagger = RuleTagger(project_dir=self.project_dir)
                    if _rule_tagger.is_configured:
                        target_data['rules'] = _rule_tagger.filter_rules_list(
                            target_data.get('rules', adapter_data.get('rules', [])), target
                        )
                except Exception:
                    pass  # Tag filtering is best-effort, never blocks sync

                # --- PER-HARNESS OVERRIDE FILES: append CLAUDE.<target>.md content ---
                _override_content = reader.get_harness_override(target)
                if _override_content:
                    target_data['rules'] = list(target_data.get('rules', []))
                    target_data['rules'].append({
                        'path': f'CLAUDE.{target}.md',
                        'content': _override_content,
                        'scope': 'project',
                        'scope_patterns': [],
                    })

                # --- INLINE HARNESS BLOCKS: inject <!-- harness:X --> blocks ---
                try:
                    _inline_block = reader.get_inline_harness_block(target)
                    if _inline_block:
                        target_data['rules'] = list(target_data.get('rules', []))
                        target_data['rules'].append({
                            'path': f'CLAUDE.md#harness:{target}',
                            'content': _inline_block,
                            'scope': 'project',
                            'scope_patterns': [],
                        })
                except Exception:
                    pass  # Inline block extraction is best-effort

                # --- MCP ALIASING: apply per-target server name aliases ---
                try:
                    from src.mcp_aliasing import load_aliases, apply_aliases
                    _mcp_aliases = load_aliases(project_dir=self.project_dir)
                    if _mcp_aliases and target_data.get('mcp'):
                        target_data['mcp'] = apply_aliases(
                            target_data['mcp'], target, _mcp_aliases
                        )
                except Exception:
                    pass  # Aliasing is best-effort

                # --- MCP ROUTING: filter servers to only those routed to this target (Item 22) ---
                try:
                    from src.mcp_routing import McpRouter
                    _mcp_router = McpRouter(project_dir=self.project_dir)
                    if _mcp_router.is_configured and isinstance(target_data.get('mcp'), dict):
                        _dropped = _mcp_router.dropped_servers(target_data['mcp'], target)
                        target_data['mcp'] = _mcp_router.filter_for_target(
                            target_data['mcp'], target
                        )
                        for _dropped_srv in _dropped:
                            self.logger.warn(
                                f"MCP routing: '{_dropped_srv}' not synced to {target} "
                                f"(per .harnesssync/mcp_routing.json)"
                            )
                except Exception:
                    pass  # MCP routing is best-effort, never blocks sync

                # --- MCP DEPENDENCY ORDERING: reorder servers for safe startup ---
                try:
                    from src.mcp_dependency_resolver import MCPDependencyResolver
                    _mcp_data = target_data.get('mcp')
                    if isinstance(_mcp_data, dict) and len(_mcp_data) > 1:
                        _dep_resolver = MCPDependencyResolver()
                        _ordered_mcp = _dep_resolver.apply_ordering_to_dict(_mcp_data)
                        target_data['mcp'] = _ordered_mcp
                        _cycle_warnings = _dep_resolver.check_cycles(_mcp_data)
                        for _cw in _cycle_warnings:
                            self.logger.warn(
                                f"{target}: MCP dependency cycle detected for '{_cw}' "
                                "— startup order may be incorrect"
                            )
                except Exception:
                    pass  # Dependency ordering is best-effort

                # --- MODEL ROUTING: merge translated model preferences into settings ---
                try:
                    if _model_routing_hints and not _model_routing_hints.is_empty:
                        from src.model_routing import ModelRoutingAdapter as _MRA
                        _translated = _MRA().translate_for_target(_model_routing_hints, target)
                        if _translated and _translated.default_model:
                            _settings = target_data.get('settings')
                            if isinstance(_settings, dict):
                                # Only inject if no model already configured
                                if 'model' not in _settings:
                                    _settings['model'] = _translated.default_model
                                    # Track for post-sync summary (item 27)
                                    _model_routing_summary.append(
                                        f"  {target}: model → {_translated.default_model}"
                                    )
                except Exception:
                    pass  # Model routing merge is best-effort

                # Step 4: filter skills per YAML frontmatter sync: tag
                try:
                    from src.skill_sync_tags import filter_skills_for_target as _fst
                    _skills_raw = target_data.get('skills')
                    if isinstance(_skills_raw, dict) and _skills_raw:
                        target_data['skills'] = _fst(_skills_raw, target)
                except Exception:
                    pass  # Skill tag filtering is best-effort, never blocks

                # Step 5: inject skill/agent translation hints (item 9)
                # Prepend inline comments to agent files explaining what Claude Code
                # features are not available in the target harness, so users know
                # what to expect when a skill behaves differently.
                try:
                    from src.skill_translator import inject_agent_translation_hints
                    import tempfile as _tempfile
                    _agents_raw = target_data.get('agents')
                    if isinstance(_agents_raw, dict) and _agents_raw:
                        _annotated_agents: dict = {}
                        _tmp_dir = Path(_tempfile.mkdtemp(prefix="harnesssync_hints_"))
                        for _aname, _apath in _agents_raw.items():
                            try:
                                _apath_obj = Path(_apath)
                                if not _apath_obj.exists():
                                    _annotated_agents[_aname] = _apath
                                    continue
                                _orig_content = _apath_obj.read_text(encoding="utf-8")
                                _hinted_content = inject_agent_translation_hints(
                                    _orig_content, _aname, target
                                )
                                if _hinted_content != _orig_content:
                                    _tmp_path = _tmp_dir / f"{_aname}.md"
                                    _tmp_path.write_text(_hinted_content, encoding="utf-8")
                                    _annotated_agents[_aname] = _tmp_path
                                else:
                                    _annotated_agents[_aname] = _apath
                            except Exception:
                                _annotated_agents[_aname] = _apath
                        target_data['agents'] = _annotated_agents
                except Exception:
                    pass  # Translation hints are best-effort, never blocks

                # Apply --only / --skip section filtering (global + per-target)
                target_data = self._apply_section_filter(target_data, target=target)

                # Sync with backup/rollback protection
                try:
                    target_results = adapter.sync_all(target_data)
                    results[target] = target_results
                except Exception as e:
                    self.logger.error(f"{target}: sync failed: {e}")
                    results[target] = {
                        'error': SyncResult(failed=1, failed_files=[str(e)])
                    }
                finally:
                    # Clean up temp directory from agent translation hints
                    if _tmp_dir and _tmp_dir.exists():
                        import shutil as _shutil
                        try:
                            _shutil.rmtree(_tmp_dir)
                        except OSError:
                            pass

        # --- POST-SYNC: RESTORE USER ANNOTATIONS (skip in dry-run) ---
        if not self.dry_run and _captured_annotations:
            try:
                from src.annotation_preserver import AnnotationPreserver
                _ann_preserver = AnnotationPreserver(self.project_dir)
                restored = _ann_preserver.restore_all(_captured_annotations)
                if restored:
                    total_restored = sum(restored.values())
                    self.logger.info(
                        f"Preserved user annotations in {total_restored} file(s)"
                    )
            except Exception:
                pass  # Best-effort

        # --- POST-SYNC: SYMLINK CLEANUP (skip in dry-run) ---
        if not self.dry_run:
            try:
                symlink_cleaner = SymlinkCleaner(self.project_dir)
                cleanup_results = symlink_cleaner.cleanup_all()

                # Log removed symlinks count
                total_removed = sum(len(removed) for removed in cleanup_results.values())
                if total_removed > 0:
                    self.logger.info(f"Cleaned up {total_removed} broken symlink(s)")
            except ImportError as e:
                self.logger.warn(f"SymlinkCleaner unavailable: {e}")

        # --- POST-SYNC: COMPATIBILITY REPORT + COVERAGE SCORE + FIDELITY ---
        try:
            compatibility_reporter = CompatibilityReporter()
            report = compatibility_reporter.generate(results)

            if compatibility_reporter.has_issues(report):
                results['_compatibility_report'] = compatibility_reporter.format_report(report)

            # Coverage score: what % of source capabilities made it to each target
            coverage = compatibility_reporter.calculate_coverage_score(results, source_data)
            if coverage:
                results['_coverage_scores'] = coverage
                coverage_str = compatibility_reporter.format_coverage_scores(coverage)
                if coverage_str.strip():
                    self.logger.info(coverage_str)

            # Fidelity scores: translation quality per target (0-100)
            fidelity = compatibility_reporter.calculate_fidelity_score(results)
            if fidelity:
                results['_fidelity_scores'] = fidelity
                fidelity_str = compatibility_reporter.format_fidelity_scores(fidelity)
                if fidelity_str.strip():
                    results['_fidelity_report'] = fidelity_str
        except ImportError as e:
            self.logger.warn(f"CompatibilityReporter unavailable: {e}")

        # --- POST-SYNC: MODEL ROUTING SUMMARY (item 27) ---
        # Surface which model preferences were synced to which targets.
        if _model_routing_summary:
            results['_model_routing_summary'] = (
                "Model Preference Sync:\n" + "\n".join(_model_routing_summary)
            )

        # --- POST-SYNC: STATE UPDATE ---
        if not self.dry_run:
            self._update_state(results, reader, source_data)

        # --- POST-SYNC: CHANGELOG ---
        if not self.dry_run:
            try:
                changelog = ChangelogManager(self.project_dir)
                changelog.record(results, scope=self.scope, account=self.account)
            except Exception as e:
                self.logger.warn(f"Changelog update failed: {e}")

        # --- POST-SYNC: TAMPER-EVIDENT AUDIT LOG (item 28) ---
        if not self.dry_run:
            try:
                from src.audit_log import AuditLog
                _audit = AuditLog(project_dir=self.project_dir)
                _synced_targets = [
                    t for t in results
                    if not t.startswith("_") and isinstance(results[t], dict)
                ]
                _files_changed: list[str] = []
                for _t in _synced_targets:
                    _t_results = results[_t]
                    for _section_result in _t_results.values():
                        if hasattr(_section_result, "files_written"):
                            _files_changed.extend(
                                str(p) for p in (_section_result.files_written or [])
                            )
                _source_hash = ""
                if self.project_dir:
                    _claude_md = self.project_dir / "CLAUDE.md"
                    if _claude_md.is_file():
                        try:
                            _source_hash = hash_file_sha256(_claude_md)
                        except Exception:
                            pass
                _audit.record(
                    event="sync",
                    targets=_synced_targets,
                    files_changed=_files_changed,
                    source_hash=_source_hash,
                    scope=self.scope or "all",
                )
            except Exception as _ae:
                self.logger.warn(f"Audit log update failed: {_ae}")

        # --- POST-SYNC: WEBHOOK NOTIFICATION ---
        if not self.dry_run:
            try:
                self._send_webhook(results)
            except Exception as e:
                self.logger.warn(f"Webhook notification failed: {e}")

        # --- POST-SYNC: DESKTOP NOTIFICATION ---
        if not self.dry_run:
            try:
                from src.desktop_notifier import notify_from_results
                notify_from_results(results)
            except Exception:
                pass  # Desktop notifications are best-effort, never block

        # --- POST-SYNC: BACKUP RETENTION CLEANUP (skip in dry-run) ---
        if not self.dry_run and backup_manager:
            try:
                for target in targets:
                    backup_manager.cleanup_old_backups(target, keep_count=10)
            except Exception as e:
                self.logger.warn(f"Backup cleanup failed: {e}")

        # --- POST-SYNC: INTEGRITY SIGNING (skip in dry-run) ---
        if not self.dry_run:
            try:
                from src.sync_integrity import SyncIntegrityStore
                from src.adapters.base import BaseAdapter
                integrity_store = SyncIntegrityStore(project_dir=self.project_dir)
                files_to_sign: list[Path] = []
                # Sign well-known output files for each registered target
                for t_name in list(results.keys()):
                    if t_name.startswith("_"):
                        continue
                    from src.dead_config_detector import _TARGET_OUTPUT_FILES
                    for rel in _TARGET_OUTPUT_FILES.get(t_name, []):
                        candidate = self.project_dir / rel
                        if candidate.is_file():
                            files_to_sign.append(candidate)
                signed_count = integrity_store.sign_target_files(files_to_sign)
                if signed_count:
                    self.logger.info(f"Integrity: signed {signed_count} synced file(s)")
            except Exception as _ie:
                self.logger.warn(f"Integrity signing failed: {_ie}")

        # --- POST-SYNC: CONFIG VERIFICATION (item 28) ---
        if not self.dry_run:
            try:
                from src.post_sync_verifier import PostSyncVerifier
                verifier = PostSyncVerifier(project_dir=self.project_dir)
                verify_result = verifier.verify_all_targets(results)
                if verify_result.issues:
                    results["_post_sync_verify"] = {
                        "ok": verify_result.ok,
                        "error_count": verify_result.error_count,
                        "warning_count": verify_result.warning_count,
                        "issues": [
                            {"target": i.target, "file": i.file_path,
                             "severity": i.severity, "message": i.message}
                            for i in verify_result.issues
                        ],
                    }
                    if verify_result.error_count:
                        self.logger.warn(
                            f"Post-sync verification: {verify_result.error_count} error(s) "
                            f"in written config files. Run /sync again or check output files."
                        )
                    for issue in verify_result.issues:
                        self.logger.warn(
                            f"  [{issue.severity.upper()}] {issue.target}: "
                            f"{issue.file_path} — {issue.message}"
                        )
            except Exception as _ve:
                self.logger.warn(f"Post-sync verification failed: {_ve}")

        # Add conflicts to results if any were found
        if any(conflicts.values()):
            results['_conflicts'] = conflicts

        # --- POST-SYNC: HARNESS UPGRADE ADVISOR (item 20) ---
        # Detect when installed harness versions have changed and surface
        # new capabilities that could improve sync quality.
        if not self.dry_run:
            try:
                from src.harness_version_compat import detect_harness_updates, format_update_report
                updates = detect_harness_updates(acknowledge=True)
                if updates:
                    report = format_update_report(updates)
                    if report:
                        results['_upgrade_notices'] = report
            except Exception:
                pass  # Upgrade advisor is informational, never blocks

        # --- POST-SYNC: CAPABILITY GAP REPORT ---
        # Show which skills/capabilities are missing in synced targets.
        if not self.dry_run:
            try:
                from src.skill_gap_analyzer import post_sync_capability_report
                synced_targets = [
                    t for t in results
                    if not t.startswith('_')
                    and isinstance(results[t], dict)
                    and 'error' not in results[t]
                    and '_skipped_incremental' not in results[t]
                    and '_queued' not in results[t]
                ]
                if synced_targets:
                    cap_report = post_sync_capability_report(
                        synced_targets, project_dir=self.project_dir
                    )
                    if cap_report:
                        results['_capability_report'] = cap_report
                        self.logger.info(cap_report)
            except Exception:
                pass  # Capability report is informational, never blocks

        # --- POST-SYNC: SYNC HEALTH SCORE (item 7) ---
        # Compute per-harness 0-100 health score after sync and persist trend data.
        if not self.dry_run:
            try:
                from src.config_health import SyncHealthTracker
                _tracker = SyncHealthTracker(cc_home=self.cc_home)
                _health_scores: dict[str, dict] = {}
                _synced_targets_health = [
                    t for t in results
                    if not t.startswith("_")
                    and isinstance(results[t], dict)
                    and "error" not in results[t]
                ]
                for _ht in _synced_targets_health:
                    try:
                        _ht_results = results[_ht]
                        # Estimate fidelity from coverage/fidelity scores if available
                        _cov = (results.get("_coverage_scores") or {}).get(_ht, 1.0)
                        _fid = (results.get("_fidelity_scores") or {}).get(_ht, 1.0)
                        if isinstance(_cov, (int, float)):
                            _cov = min(1.0, max(0.0, _cov / 100.0 if _cov > 1 else _cov))
                        else:
                            _cov = 1.0
                        if isinstance(_fid, (int, float)):
                            _fid = min(1.0, max(0.0, _fid / 100.0 if _fid > 1 else _fid))
                        else:
                            _fid = 1.0
                        # Skills coverage: fraction of skills synced (not skipped)
                        _skills_synced = sum(
                            r.synced for r in _ht_results.values()
                            if hasattr(r, "synced") and getattr(r, "__class__", None)
                            and r.__class__.__name__ == "SyncResult"
                        )
                        _hs_score = _tracker.compute_score(
                            target=_ht,
                            rule_fidelity=_fid,
                            skills_coverage=_cov,
                        )
                        _health_scores[_ht] = {
                            "score": _hs_score.score,
                            "label": _hs_score.label,
                            "trend": _hs_score.trend,
                        }
                    except Exception:
                        pass  # Per-target scoring is best-effort
                if _health_scores:
                    results["_health_scores"] = _health_scores
            except Exception:
                pass  # Health tracking is informational, never blocks

        # --- POST-SYNC: AMBIENT SUMMARY NOTIFICATION (item 30) ---
        # Write a one-line summary + terminal bell to /dev/tty so hook-triggered
        # background syncs are always visible to the user without checking logs.
        if not self.dry_run:
            try:
                _synced_count = sum(
                    1 for _t in results
                    if not _t.startswith("_") and isinstance(results.get(_t), dict)
                )
                _conflict_count = len(results.get("_conflicts") or {})
                _failed_count = sum(
                    getattr(_r, "failed", 0)
                    for _t in results
                    if not _t.startswith("_") and isinstance(results.get(_t), dict)
                    for _r in results[_t].values()
                    if hasattr(_r, "failed")
                )
                _parts = [f"Synced {_synced_count} target(s)"]
                if _conflict_count:
                    _parts.append(f"{_conflict_count} conflict(s) skipped")
                if _failed_count:
                    _parts.append(f"{_failed_count} item(s) failed")
                _summary_line = "HarnessSync: " + ". ".join(_parts) + "."
                import sys as _sys_ambient
                try:
                    with open("/dev/tty", "w") as _tty:
                        _tty.write(f"\x07{_summary_line}\n")
                        _tty.flush()
                except OSError:
                    if hasattr(_sys_ambient.stderr, "isatty") and _sys_ambient.stderr.isatty():
                        try:
                            _sys_ambient.stderr.write(f"\x07{_summary_line}\n")
                            _sys_ambient.stderr.flush()
                        except OSError:
                            pass
            except Exception:
                pass  # Ambient notification is best-effort, never block sync

        return results

    def _apply_section_filter(self, data: dict, target: str = "") -> dict:
        """Apply --only and --skip section filters to adapter data.

        Sections: rules, skills, agents, commands, mcp, settings.
        If only_sections is set, zero out all sections not in it.
        Then zero out any sections in skip_sections.

        Per-target overrides (item 3 — Per-Feature Sync Toggles) are applied on top:
          - ``.harnesssync`` → ``targets.cursor.skip_sections`` adds to global skip for cursor
          - ``.harnesssync`` → ``targets.aider.only_sections`` restricts to those sections for aider

        Args:
            data:   Source data dict for a target adapter.
            target: Harness target name (used to look up per-target overrides).

        Returns:
            Filtered data dict (sections cleared to empty, not removed)
        """
        # Merge global + per-target overrides
        effective_skip = set(self.skip_sections)
        effective_only = set(self.only_sections)

        if target:
            tgt_lower = target.lower()
            if tgt_lower in self._per_target_skip:
                effective_skip = effective_skip | self._per_target_skip[tgt_lower]
            if tgt_lower in self._per_target_only:
                tgt_only = self._per_target_only[tgt_lower]
                # Intersect with global only_sections if both are set
                effective_only = (effective_only & tgt_only) if effective_only else tgt_only
            # Apply CLI --only-for overrides (merged on top of project config overrides)
            if tgt_lower in self._cli_per_target_only:
                cli_tgt_only = self._cli_per_target_only[tgt_lower]
                effective_only = (effective_only & cli_tgt_only) if effective_only else cli_tgt_only

        if not effective_only and not effective_skip:
            return data

        # Mapping from section name to default empty value
        section_defaults: dict[str, object] = {
            "rules": [],
            "skills": {},
            "agents": {},
            "commands": {},
            "mcp": {},
            "mcp_scoped": {},
            "settings": {},
            "hooks": {},
        }

        filtered = dict(data)

        for section, default in section_defaults.items():
            # Normalize: mcp_scoped tracks with mcp
            section_key = "mcp" if section == "mcp_scoped" else section

            # If only_sections specified and this section is not in it → zero out
            if effective_only and section_key not in effective_only:
                filtered[section] = default
            # If skip_sections specified and this section is in it → zero out
            elif section_key in effective_skip:
                filtered[section] = default

        return filtered

    def _send_webhook(self, results: dict) -> None:
        """Dispatch configured webhooks and scripts via WebhookNotifier.

        Delegates to ``WebhookNotifier`` (which reads ~/.harnesssync/webhooks.json)
        for full webhook/script support. Also honours the legacy env-var
        ``HARNESSSYNC_WEBHOOK_URL`` for backward compatibility.

        Network/script errors are logged but never block the sync.

        Args:
            results: Sync results dict from sync_all()
        """
        import os

        # Full webhook notifier (reads webhooks.json config)
        try:
            from src.webhook_notifier import WebhookNotifier
            notifier = WebhookNotifier(logger=self.logger)
            notifier.notify(results, project_dir=self.project_dir, dry_run=self.dry_run)
        except Exception as exc:
            self.logger.warn(f"WebhookNotifier failed: {exc}")

        # Legacy single-URL support via environment variable
        import json
        import urllib.request

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
            "account": self.account,
            "scope": self.scope,
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
            self.logger.warn(f"Legacy webhook POST failed: {exc}")

    def sync_all_accounts(self) -> dict:
        """Sync all configured accounts sequentially.

        If no accounts configured, falls back to sync_all() (v1 behavior).

        Returns:
            Dict mapping account_name -> results dict,
            or direct results dict if no accounts configured
        """
        try:
            from src.account_manager import AccountManager
            am = AccountManager()

            if not am.has_accounts():
                # No accounts configured — v1 behavior
                return self.sync_all()

            all_results = {}
            for account_name in am.list_accounts():
                acc = am.get_account(account_name)
                if not acc:
                    continue

                cc_home = Path(acc["source"]["path"])
                orch = SyncOrchestrator(
                    project_dir=self.project_dir,
                    scope=self.scope,
                    dry_run=self.dry_run,
                    allow_secrets=self.allow_secrets,
                    scrub_secrets=self.scrub_secrets,
                    account=account_name,
                    cc_home=cc_home
                )
                all_results[account_name] = orch.sync_all()

            return all_results

        except Exception as e:
            self.logger.warn(f"Multi-account sync failed, falling back to v1: {e}")
            return self.sync_all()

    def _preview_sync(self, adapter, source_data: dict) -> dict:
        """Generate diff preview without writing files.

        Reads current target files from disk to produce real unified diffs,
        showing exactly what will change. Falls back to showing new content
        if the target file doesn't exist yet.

        Args:
            adapter: Target adapter instance
            source_data: Source configuration data

        Returns:
            Dict with 'preview' key containing formatted diff output
        """
        df = DiffFormatter()
        target = adapter.target_name

        # --- Rules diff: read existing rules file ---
        rules = source_data.get('rules', '')
        if rules:
            new_rules_str = (
                "\n\n".join(r.get('content', '') for r in rules if isinstance(r, dict))
                if isinstance(rules, list)
                else str(rules)
            )
            # Determine current rules file path per target
            rules_file = self._get_target_rules_path(adapter)
            df.add_file_diff(f"{target}/rules", rules_file, new_rules_str)

        # --- Skills diff: compare current vs new skill names ---
        skills = source_data.get('skills', {})
        if skills:
            current_skills = self._get_current_skills(adapter)
            df.add_structural_diff(
                f"{target}/skills",
                current_skills,
                {name: str(path) for name, path in skills.items()}
            )

        # --- Agents diff ---
        agents = source_data.get('agents', {})
        if agents:
            current_agents = self._get_current_agents(adapter)
            df.add_structural_diff(
                f"{target}/agents",
                current_agents,
                {name: str(path) for name, path in agents.items()}
            )

        # --- Commands diff ---
        commands = source_data.get('commands', {})
        if commands:
            current_commands = self._get_current_commands(adapter)
            df.add_structural_diff(
                f"{target}/commands",
                current_commands,
                {name: str(path) for name, path in commands.items()}
            )

        # --- MCP diff: compare current vs new MCP server keys ---
        mcp = source_data.get('mcp', {})
        if mcp:
            current_mcp = self._get_current_mcp(adapter)
            df.add_structural_diff(f"{target}/mcp", current_mcp, mcp)

        # --- Settings diff: read current settings JSON ---
        settings = source_data.get('settings', {})
        if settings:
            current_settings = self._get_current_settings(adapter)
            df.add_structural_diff(f"{target}/settings", current_settings, settings)

        return {"preview": df.format_output(), "is_preview": True}

    def _get_target_rules_path(self, adapter) -> Path | None:
        """Return the path of the rules file for a given adapter, or None."""
        # Each adapter exposes a known path attribute
        for attr in ("agents_md_path", "gemini_md_path", "rules_path"):
            p = getattr(adapter, attr, None)
            if p is not None:
                return p
        # Fallback: guess from target_name
        target = adapter.target_name
        rules_filenames = {
            "codex": "AGENTS.md",
            "gemini": "GEMINI.md",
            "opencode": "OPENCODE.md",
            "cursor": ".cursor/rules/harnesssync.mdc",
            "aider": "CONVENTIONS.md",
            "windsurf": ".windsurfrules",
            "cline": ".clinerules",
            "continue": ".continue/rules/harnesssync.md",
            "zed": ".zed/system-prompt.md",
            "neovim": ".avante/system-prompt.md",
        }
        fname = rules_filenames.get(target)
        if fname:
            return self.project_dir / fname
        return None

    def _get_current_skills(self, adapter) -> dict:
        """Read current skill names from adapter's skill output directory."""
        skills_dir = getattr(adapter, 'skills_dir', None)
        if skills_dir is None:
            # Guess common locations
            for candidate in (".agents/skills", ".gemini/skills", ".opencode/skills"):
                p = self.project_dir / candidate
                if p.is_dir():
                    skills_dir = p
                    break
        if not skills_dir or not Path(skills_dir).is_dir():
            return {}
        return {d.name: str(d) for d in Path(skills_dir).iterdir() if d.is_dir()}

    def _get_current_agents(self, adapter) -> dict:
        """Read current agent names from adapter's agents output directory."""
        for candidate in (".gemini/agents", ".opencode/agents"):
            p = self.project_dir / candidate
            if p.is_dir():
                return {f.stem: str(f) for f in p.iterdir()
                        if f.is_file() and f.suffix == ".md"}
        return {}

    def _get_current_commands(self, adapter) -> dict:
        """Read current command names from adapter's commands output directory."""
        for candidate in (".gemini/commands", ".opencode/commands"):
            p = self.project_dir / candidate
            if p.is_dir():
                return {f.stem: str(f) for f in p.iterdir()
                        if f.is_file() and f.suffix in (".md", ".toml")}
        return {}

    def _get_current_mcp(self, adapter) -> dict:
        """Read current MCP config from adapter's output location."""
        import json as _json
        # Common MCP output locations
        for candidate in (
            ".gemini/settings.json",
            ".codex/config.toml",
            ".opencode/settings.json",
        ):
            p = self.project_dir / candidate
            if p.exists() and p.suffix == ".json":
                try:
                    data = _json.loads(p.read_text(encoding="utf-8"))
                    return data.get("mcpServers", {})
                except (OSError, _json.JSONDecodeError):
                    pass
        return {}

    def _get_current_settings(self, adapter) -> dict:
        """Read current settings from adapter's settings output."""
        import json as _json
        for candidate in (
            ".gemini/settings.json",
            ".opencode/settings.json",
        ):
            p = self.project_dir / candidate
            if p.exists():
                try:
                    data = _json.loads(p.read_text(encoding="utf-8"))
                    return {k: v for k, v in data.items() if k != "mcpServers"}
                except (OSError, _json.JSONDecodeError):
                    pass
        return {}

    def _extract_plugin_metadata(self, mcp_scoped: dict) -> dict:
        """Extract plugin metadata from mcp_scoped data.

        Args:
            mcp_scoped: MCP servers with scope metadata (from SourceReader.discover_all())

        Returns:
            Dict mapping plugin_name -> {version, mcp_count, mcp_servers, last_sync}
        """
        plugins = {}

        for server_name, server_data in mcp_scoped.items():
            metadata = server_data.get('metadata', {})

            # Filter to plugin-sourced MCPs only
            if metadata.get('source') != 'plugin':
                continue

            plugin_name = metadata.get('plugin_name', 'unknown')
            plugin_version = metadata.get('plugin_version', 'unknown')

            # Group by plugin_name
            if plugin_name not in plugins:
                plugins[plugin_name] = {
                    'version': plugin_version,
                    'mcp_count': 0,
                    'mcp_servers': [],
                    'last_sync': datetime.now().isoformat()
                }

            # Increment MCP count and add server name
            plugins[plugin_name]['mcp_count'] += 1
            plugins[plugin_name]['mcp_servers'].append(server_name)

        return plugins

    def _update_state(self, results: dict, reader: SourceReader, source_data: dict = None) -> None:
        """Update state manager with sync results and plugin metadata.

        Args:
            results: Per-target sync results
            reader: SourceReader used for this sync (for source paths)
            source_data: Source configuration data (optional, avoids re-calling discover_all)
        """
        source_paths = reader.get_source_paths()

        # Hash all source files
        file_hashes = {}
        for config_type, paths in source_paths.items():
            for p in paths:
                if p.is_file():
                    h = hash_file_sha256(p)
                    if h:
                        file_hashes[str(p)] = h

        for target, target_results in results.items():
            # Skip special keys
            if target.startswith('_'):
                continue

            # Aggregate counts across config types
            synced = 0
            skipped = 0
            failed = 0
            sync_methods = {}

            if isinstance(target_results, dict):
                for config_type, result in target_results.items():
                    if isinstance(result, SyncResult):
                        synced += result.synced
                        skipped += result.skipped
                        failed += result.failed

            self.state_manager.record_sync(
                target=target,
                scope=self.scope,
                file_hashes=file_hashes,
                sync_methods=sync_methods,
                synced=synced,
                skipped=skipped,
                failed=failed,
                account=self.account
            )

        # --- PLUGIN METADATA PERSISTENCE ---
        # Extract and record plugin metadata after successful target syncs
        if source_data is None:
            source_data = reader.discover_all()

        mcp_scoped = source_data.get('mcp_servers_scoped', {})
        plugins_metadata = self._extract_plugin_metadata(mcp_scoped)

        if plugins_metadata:
            self.state_manager.record_plugin_sync(plugins_metadata, account=self.account)

    def get_status(self) -> dict:
        """Get sync status with drift detection.

        Returns:
            State dict with added drift info per target
        """
        state = self.state_manager.get_all_status()

        # Add drift detection for each target
        reader = SourceReader(scope=self.scope, project_dir=self.project_dir,
                              cc_home=self.cc_home)
        source_paths = reader.get_source_paths()

        current_hashes = {}
        for config_type, paths in source_paths.items():
            for p in paths:
                if p.is_file():
                    h = hash_file_sha256(p)
                    if h:
                        current_hashes[str(p)] = h

        targets = state.get("targets", {})
        for target in targets:
            drifted = self.state_manager.detect_drift(target, current_hashes,
                                                       account=self.account)
            targets[target]["drift"] = drifted

        return state

    def canary_sync(
        self,
        canary_target: str,
        remaining_targets: list[str] | None = None,
        confirm_fn=None,
    ) -> dict[str, dict]:
        """Incremental sync rollout: sync one canary target first, then the rest.

        Syncs ``canary_target`` first as a trial. If ``confirm_fn`` approves
        (or is None), proceeds to sync remaining targets. Prevents a bad config
        from hitting all harnesses simultaneously for risky changes.

        Args:
            canary_target: The first target to sync as the canary.
            remaining_targets: Targets to sync after canary succeeds. If None,
                               syncs all registered targets except the canary.
            confirm_fn: Optional callable(canary_result) -> bool. If it returns
                        False, the rollout is aborted after the canary. If None,
                        always proceeds (use for CI/automation).

        Returns:
            Dict mapping target_name -> {
                "success": bool,
                "phase": "canary" | "rollout" | "skipped",
                "error": str | None,
            }
        """
        results: dict[str, dict] = {}

        # --- Phase 1: Canary sync ---
        self.logger.info(f"[canary] Syncing canary target: {canary_target}")
        canary_orchestrator = SyncOrchestrator(
            project_dir=self.project_dir,
            scope=self.scope,
            dry_run=self.dry_run,
            cc_home=self.cc_home,
            only_sections=self.only_sections,
            skip_sections=self.skip_sections,
            cli_only_targets={canary_target},
            harness_env=self.harness_env,
        )

        canary_sync_results = canary_orchestrator.sync_all()
        canary_result = (canary_sync_results or {}).get(canary_target)
        canary_ok = getattr(canary_result, "success", canary_result is not None)

        results[canary_target] = {
            "success": canary_ok,
            "phase": "canary",
            "error": getattr(canary_result, "error", None) if not canary_ok else None,
        }

        # --- Check canary success ---
        if not canary_ok:
            self.logger.warn(f"[canary] Canary sync to '{canary_target}' failed — aborting rollout.")
            # Mark remaining as skipped
            if remaining_targets:
                for t in remaining_targets:
                    results[t] = {"success": False, "phase": "skipped", "error": "canary failed"}
            return results

        # --- Confirm before rollout ---
        if confirm_fn is not None:
            proceed = confirm_fn(results[canary_target])
            if not proceed:
                self.logger.info("[canary] Rollout aborted by confirm_fn.")
                if remaining_targets:
                    for t in remaining_targets:
                        results[t] = {"success": False, "phase": "skipped", "error": "aborted by user"}
                return results

        # --- Phase 2: Rollout to remaining targets ---
        if remaining_targets is None:
            # Discover all registered targets and exclude the canary
            try:
                from src.adapters import AdapterRegistry
                reg = AdapterRegistry(project_dir=self.project_dir)
                all_targets = list(reg.list_targets())
                remaining_targets = [t for t in all_targets if t != canary_target]
            except Exception:
                remaining_targets = []

        if not remaining_targets:
            return results

        self.logger.info(f"[canary] Rolling out to {len(remaining_targets)} remaining target(s).")
        rollout_orchestrator = SyncOrchestrator(
            project_dir=self.project_dir,
            scope=self.scope,
            dry_run=self.dry_run,
            cc_home=self.cc_home,
            only_sections=self.only_sections,
            skip_sections=self.skip_sections,
            cli_only_targets=set(remaining_targets),
            harness_env=self.harness_env,
        )

        rollout_results = rollout_orchestrator.sync_all()
        for target, result in (rollout_results or {}).items():
            ok = getattr(result, "success", result is not None)
            results[target] = {
                "success": ok,
                "phase": "rollout",
                "error": getattr(result, "error", None) if not ok else None,
            }

        return results
