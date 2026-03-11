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
from src.sync_filter import filter_rules_for_target, has_sync_tags
from src.symlink_cleaner import SymlinkCleaner
from src.utils.hashing import hash_file_sha256
from src.utils.logger import Logger


class SyncOrchestrator:
    """Coordinates sync operations across all adapters.

    Note: sync_all() does NOT acquire locks or check debounce.
    Callers (commands, hooks) handle concurrency control.
    """

    def __init__(self, project_dir: Path, scope: str = "all", dry_run: bool = False,
                 allow_secrets: bool = False, account: str = None, cc_home: Path = None,
                 only_sections: set = None, skip_sections: set = None,
                 incremental: bool = False,
                 cli_only_targets: set = None, cli_skip_targets: set = None):
        """Initialize orchestrator.

        Args:
            project_dir: Project root directory
            scope: "user" | "project" | "all"
            dry_run: If True, preview changes without writing
            allow_secrets: If True, allow sync even when secrets detected in env vars
            account: Account name for per-account sync (None = v1 behavior)
            cc_home: Custom Claude Code config directory (derived from account if provided)
            only_sections: If set, only sync these sections (rules/skills/agents/commands/mcp/settings)
            skip_sections: If set, skip these sections
            incremental: If True, skip targets where no source files changed since last sync
        """
        self.project_dir = project_dir
        self.scope = scope
        self.dry_run = dry_run
        self.allow_secrets = allow_secrets
        self.account = account
        self.cc_home = cc_home
        self.only_sections = only_sections or set()
        self.skip_sections = skip_sections or set()
        self.incremental = incremental
        # CLI-level target filters (applied before per-project .harnesssync overrides)
        self.cli_only_targets: set[str] = cli_only_targets or set()
        self.cli_skip_targets: set[str] = cli_skip_targets or set()
        self.logger = Logger()
        self.state_manager = StateManager()
        self.account_config = None
        # Per-project config target overrides (populated by _apply_project_config)
        self._project_skip_targets: set[str] = set()
        self._project_only_targets: set[str] = set()
        self._profile_targets: list[str] | None = None

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
            "skip_sections": ["mcp"],     // sections to skip
            "only_sections": ["rules"],   // only these sections
            "skip_targets": ["aider"],    // harness targets to exclude
            "only_targets": ["codex"]     // only these harness targets
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
        adapter_data['mcp'] = adapter_data.pop('mcp_servers', {})
        # Pass scoped MCP data for v2.0 scope-aware adapters
        adapter_data['mcp_scoped'] = source_data.get('mcp_servers_scoped', {})

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

        # --- PRE-SYNC: SECRET DETECTION ---
        # Run secret detection on MCP env vars (before any writes)
        try:
            secret_detector = SecretDetector()
            detections = secret_detector.scan_mcp_env(source_data.get('mcp_servers', {}))

            if secret_detector.should_block(detections, self.allow_secrets):
                # Block sync - return early with warning
                formatted_warnings = secret_detector.format_warnings(detections)
                self.logger.warn("Sync blocked: secrets detected in environment variables")
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

                # Build target-specific data (applying sync tag filtering)
                target_data = dict(adapter_data)
                if _rules_have_tags:
                    target_data['rules'] = [
                        {**r, 'content': filter_rules_for_target(r.get('content', ''), target)}
                        for r in adapter_data.get('rules', [])
                        if isinstance(r, dict)
                    ]

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

                # Apply --only / --skip section filtering
                target_data = self._apply_section_filter(target_data)

                # Sync with backup/rollback protection
                try:
                    target_results = adapter.sync_all(target_data)
                    results[target] = target_results
                except Exception as e:
                    self.logger.error(f"{target}: sync failed: {e}")
                    results[target] = {
                        'error': SyncResult(failed=1, failed_files=[str(e)])
                    }

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

        # --- POST-SYNC: COMPATIBILITY REPORT + COVERAGE SCORE ---
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
        except ImportError as e:
            self.logger.warn(f"CompatibilityReporter unavailable: {e}")

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

        # --- POST-SYNC: WEBHOOK NOTIFICATION ---
        if not self.dry_run:
            try:
                self._send_webhook(results)
            except Exception as e:
                self.logger.warn(f"Webhook notification failed: {e}")

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
                for target, target_results in results.items():
                    if target.startswith("_") or not isinstance(target_results, dict):
                        continue
                    # Collect written output files for each adapter
                    for adapter in [a for a in targets if a == target]:
                        pass  # adapters variable holds adapter objects, not names
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

        return results

    def _apply_section_filter(self, data: dict) -> dict:
        """Apply --only and --skip section filters to adapter data.

        Sections: rules, skills, agents, commands, mcp, settings.
        If only_sections is set, zero out all sections not in it.
        Then zero out any sections in skip_sections.

        Args:
            data: Source data dict for a target adapter

        Returns:
            Filtered data dict (sections cleared to empty, not removed)
        """
        if not self.only_sections and not self.skip_sections:
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
        }

        filtered = dict(data)

        for section, default in section_defaults.items():
            # Normalize: mcp_scoped tracks with mcp
            section_key = "mcp" if section == "mcp_scoped" else section

            # If only_sections specified and this section is not in it → zero out
            if self.only_sections and section_key not in self.only_sections:
                filtered[section] = default
            # If skip_sections specified and this section is in it → zero out
            elif section_key in self.skip_sections:
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
