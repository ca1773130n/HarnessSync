from __future__ import annotations

"""Sync orchestrator coordinating SourceReader -> AdapterRegistry -> StateManager.

SyncOrchestrator is the central coordination layer invoked by both
/sync command and PostToolUse hook. It reads source config, syncs to
all registered adapters, and updates state. Supports scope filtering,
dry-run preview mode, and per-account sync operations.

Implementation is split across several sub-modules:
- src.sync_config_loader  -- project config loading and merging
- src.sync_pipeline       -- pre-sync and post-sync pipeline steps
- src.sync_preview        -- dry-run diff preview generation
- src.sync_state_updater  -- state persistence after sync
- src.sync_notifier       -- webhook/notification dispatch
"""

from pathlib import Path

from src.adapters import AdapterRegistry
from src.adapters.result import SyncResult
from src.backup_manager import BackupManager
from src.exceptions import AdapterError, ConfigError, SyncError
from src.source_reader import SourceReader
from src.state_manager import StateManager
from src.sync_filter import filter_rules_for_target, filter_rules_for_env, has_sync_tags
from src.utils.hashing import hash_file_sha256
from src.utils.logger import Logger

# Sub-module imports for delegation
from src.sync_config_loader import load_project_config, ProjectConfigApplier
from src.sync_pipeline import PreSyncPipeline, PostSyncPipeline
from src.sync_preview import SyncPreviewGenerator
from src.sync_state_updater import update_state, extract_plugin_metadata
from src.sync_notifier import send_webhook, send_desktop_notification, send_ambient_summary
from src.sync_target_builder import build_target_data


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
            minimal: If True, activate Minimal Footprint Mode -- sync only the highest-value
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
            except ImportError as e:
                self.logger.warn(f"Account manager unavailable: {e}")
            except (ConfigError, OSError, KeyError) as e:
                self.logger.warn(f"Could not load account '{account}': {e}")
            except Exception as e:
                self.logger.warn(f"Unexpected error loading account '{account}': {e}")

    # --- Backward-compatible delegate methods ---
    # These exist so that any code referencing the old private methods
    # (e.g. in tests) still works. New code should use the sub-modules directly.

    def _load_project_config(self) -> dict:
        """Load per-project .harnesssync config file overrides."""
        return load_project_config(self.project_dir)

    def _apply_project_config(self, project_cfg: dict) -> None:
        """Merge project-level .harnesssync overrides into orchestrator settings."""
        applier = ProjectConfigApplier(
            project_dir=self.project_dir,
            scope=self.scope,
            only_sections=self.only_sections,
            skip_sections=self.skip_sections,
            logger=self.logger,
        )
        applier.apply(project_cfg)
        # Read back mutated state
        self.scope = applier.scope
        self.only_sections = applier.only_sections
        self.skip_sections = applier.skip_sections
        self._project_skip_targets = applier.project_skip_targets
        self._project_only_targets = applier.project_only_targets
        self._profile_targets = applier.profile_targets
        self._per_target_skip = applier.per_target_skip
        self._per_target_only = applier.per_target_only

    def _preview_sync(self, adapter, source_data: dict) -> dict:
        """Generate diff preview without writing files."""
        generator = SyncPreviewGenerator(self.project_dir)
        return generator.preview_sync(adapter, source_data)

    def _get_target_rules_path(self, adapter):
        """Return the path of the rules file for a given adapter, or None."""
        generator = SyncPreviewGenerator(self.project_dir)
        return generator.get_target_rules_path(adapter)

    def _get_current_skills(self, adapter) -> dict:
        """Read current skill names from adapter's skill output directory."""
        generator = SyncPreviewGenerator(self.project_dir)
        return generator.get_current_skills(adapter)

    def _get_current_agents(self, adapter) -> dict:
        """Read current agent names from adapter's agents output directory."""
        generator = SyncPreviewGenerator(self.project_dir)
        return generator.get_current_agents(adapter)

    def _get_current_commands(self, adapter) -> dict:
        """Read current command names from adapter's commands output directory."""
        generator = SyncPreviewGenerator(self.project_dir)
        return generator.get_current_commands(adapter)

    def _get_current_mcp(self, adapter) -> dict:
        """Read current MCP config from adapter's output location."""
        generator = SyncPreviewGenerator(self.project_dir)
        return generator.get_current_mcp(adapter)

    def _get_current_settings(self, adapter) -> dict:
        """Read current settings from adapter's settings output."""
        generator = SyncPreviewGenerator(self.project_dir)
        return generator.get_current_settings(adapter)

    def _extract_plugin_metadata(self, mcp_scoped: dict) -> dict:
        """Extract plugin metadata from mcp_scoped data."""
        return extract_plugin_metadata(mcp_scoped)

    def _update_state(self, results: dict, reader: SourceReader, source_data: dict = None) -> None:
        """Update state manager with sync results and plugin metadata."""
        update_state(
            results=results,
            reader=reader,
            state_manager=self.state_manager,
            scope=self.scope,
            account=self.account,
            source_data=source_data,
        )

    def _send_webhook(self, results: dict) -> None:
        """Dispatch configured webhooks and scripts."""
        send_webhook(
            results=results,
            project_dir=self.project_dir,
            dry_run=self.dry_run,
            scope=self.scope,
            account=self.account,
            logger=self.logger,
        )

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

        # Create pre-sync pipeline
        pre = PreSyncPipeline(
            project_dir=self.project_dir,
            cc_home=self.cc_home,
            scope=self.scope,
            dry_run=self.dry_run,
            allow_secrets=self.allow_secrets,
            scrub_secrets=self.scrub_secrets,
            minimal=self.minimal,
            logger=self.logger,
        )

        # --- PRE-SYNC CHECKS (informational) ---
        pre.check_skill_dependencies(source_data)
        pre.substitute_config_vars(source_data)
        pre.normalize_rules(source_data)
        pre.record_rule_attribution(source_data)

        # Project-type adaptive sync (may update skip_sections)
        self.skip_sections = pre.apply_project_type_detection(
            self.only_sections, self.skip_sections
        )

        # Prepare adapter data (rename keys, apply minimal MCP filtering)
        adapter_data = pre.prepare_adapter_data(source_data)

        # Model routing hints
        _model_routing_hints = pre.extract_model_routing_hints(source_data)
        _model_routing_summary: list[str] = []

        # Impact prediction (dry-run only)
        pre.predict_sync_impact(source_data)

        # MCP reachability
        pre.check_mcp_reachability(source_data)

        # Capability gap warnings
        pre.check_capability_gaps(source_data)

        # --- PRE-SYNC: SECRET DETECTION ---
        block_result = pre.detect_secrets(source_data, adapter_data)
        if block_result:
            return block_result

        # --- PRE-SYNC: CONFIG LINTING ---
        pre.lint_config(source_data)

        # --- PRE-SYNC: VERSION COMPAT ---
        pre.check_harness_version_compat()

        # --- PRE-SYNC: PERMISSION ESCALATION GUARD ---
        pre.check_permission_escalation(source_data)

        # --- PRE-SYNC: POLICY ENFORCEMENT ---
        policy_block = pre.check_policy(source_data)
        if policy_block:
            return policy_block

        # --- PRE-SYNC: CONFLICT DETECTION ---
        conflicts = pre.detect_conflicts(self.state_manager)

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

        # --- PRE-SYNC: AUTO-SNAPSHOT ---
        pre.take_auto_snapshot()

        # --- PRE-SYNC: CAPTURE USER ANNOTATIONS ---
        _captured_annotations = pre.capture_annotations(targets)

        # Detect if any rules have sync tags (used for per-target filtering)
        _rules_have_tags = any(
            has_sync_tags(r.get('content', '')) for r in adapter_data.get('rules', [])
            if isinstance(r, dict)
        )

        # Detect if any rules have inline harness annotations
        _rules_have_annotations = False
        _AnnFilter = None
        try:
            from src.annotation_filter import AnnotationFilter as _AnnFilterCls
            _AnnFilter = _AnnFilterCls
            _rules_have_annotations = any(
                _AnnFilter.has_annotations(r.get('content', ''))
                for r in adapter_data.get('rules', [])
                if isinstance(r, dict)
            )
            if _rules_have_annotations:
                self.logger.info(
                    f"Inline harness annotations detected -- will filter per target"
                )
        except ImportError:
            pass  # Annotation filter module not available
        except Exception as e:
            self.logger.warn(f"Annotation filter check failed: {e}")

        # --- USER-DEFINED TRANSFORM RULES: load once per sync run ---
        _transform_engine = None
        try:
            from src.transform_engine import TransformEngine
            _transform_engine = TransformEngine.load(self.project_dir)
            if _transform_engine and _transform_engine.has_rules():
                self.logger.info(f"Transform engine: {len(_transform_engine.rules)} rule(s) loaded")
        except ImportError:
            pass  # Transform engine module not available
        except Exception as e:
            self.logger.warn(f"Transform engine load failed: {e}")

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

        # --- SYNC: EXECUTE ADAPTERS ---
        for target in targets:
            adapter = AdapterRegistry.get_adapter(target, self.project_dir)
            _tmp_dir = None

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
                # --- OFFLINE QUEUE ---
                try:
                    from src.offline_queue import OfflineQueue, is_target_available
                    if not is_target_available(target, self.project_dir):
                        self.logger.warn(
                            f"{target}: config directory unavailable -- queuing for later replay"
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
                    pass  # offline_queue not available

                # Build target-specific data (applying env + sync tag filtering)
                target_data = build_target_data(
                    adapter_data=adapter_data,
                    target=target,
                    reader=reader,
                    project_dir=self.project_dir,
                    harness_env=self.harness_env,
                    rules_have_tags=_rules_have_tags,
                    rules_have_annotations=_rules_have_annotations,
                    ann_filter_cls=_AnnFilter,
                    transform_engine=_transform_engine,
                    model_routing_hints=_model_routing_hints,
                    model_routing_summary=_model_routing_summary,
                    logger=self.logger,
                )

                # Apply --only / --skip section filtering (global + per-target)
                target_data = self._apply_section_filter(target_data, target=target)

                # Apply per-harness overrides from .harness-sync/overrides/
                try:
                    from src.override_manager import OverrideManager
                    _om = OverrideManager(self.project_dir)
                    if _om.has_overrides(target):
                        if "rules" in target_data and isinstance(target_data.get("rules"), str):
                            target_data = dict(target_data)
                            target_data["rules"] = _om.merge_overrides(
                                target, target_data["rules"], "md"
                            )
                        if "mcp" in target_data and isinstance(target_data.get("mcp"), dict):
                            target_data = dict(target_data)
                            target_data["mcp"] = _om.merge_overrides(
                                target, target_data["mcp"], "json"
                            )
                except Exception:
                    pass  # overrides are best-effort; never block core sync

                # Sync with backup/rollback protection
                try:
                    target_results = adapter.sync_all(target_data)
                    results[target] = target_results
                except (AdapterError, OSError) as e:
                    self.logger.error(f"{target}: sync failed: {e}")
                    results[target] = {
                        'error': SyncResult(failed=1, failed_files=[str(e)])
                    }
                except Exception as e:
                    self.logger.error(f"{target}: unexpected sync failure: {e}")
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

        # --- POST-SYNC PIPELINE ---
        post = PostSyncPipeline(
            project_dir=self.project_dir,
            cc_home=self.cc_home,
            scope=self.scope,
            dry_run=self.dry_run,
            account=self.account,
            logger=self.logger,
        )

        post.restore_annotations(_captured_annotations)
        post.cleanup_symlinks()
        post.generate_compatibility_report(results, source_data)

        # Model routing summary
        if _model_routing_summary:
            results['_model_routing_summary'] = (
                "Model Preference Sync:\n" + "\n".join(_model_routing_summary)
            )

        # State update
        if not self.dry_run:
            self._update_state(results, reader, source_data)

        post.record_changelog(results)
        post.record_audit_log(results)

        # Webhook + notifications
        if not self.dry_run:
            try:
                self._send_webhook(results)
            except (OSError, SyncError) as e:
                self.logger.warn(f"Webhook notification failed: {e}")
            except Exception as e:
                self.logger.warn(f"Unexpected webhook notification failure: {e}")

        if not self.dry_run:
            send_desktop_notification(results)

        post.cleanup_backups(targets, backup_manager)
        post.sign_integrity(results)
        post.verify_post_sync(results)

        # Add conflicts to results if any were found
        if any(conflicts.values()):
            results['_conflicts'] = conflicts

        post.check_harness_upgrades(results)
        post.generate_capability_report(results)
        post.compute_health_scores(results)

        # Ambient summary notification
        if not self.dry_run:
            send_ambient_summary(results)

        return results

    def _build_target_data(
        self,
        adapter_data: dict,
        target: str,
        reader: SourceReader,
        rules_have_tags: bool,
        rules_have_annotations: bool,
        ann_filter_cls,
        transform_engine,
        model_routing_hints,
        model_routing_summary: list[str],
    ) -> dict:
        """Build target-specific data (backward-compat delegate)."""
        return build_target_data(
            adapter_data=adapter_data,
            target=target,
            reader=reader,
            project_dir=self.project_dir,
            harness_env=self.harness_env,
            rules_have_tags=rules_have_tags,
            rules_have_annotations=rules_have_annotations,
            ann_filter_cls=ann_filter_cls,
            transform_engine=transform_engine,
            model_routing_hints=model_routing_hints,
            model_routing_summary=model_routing_summary,
            logger=self.logger,
        )

    def _apply_section_filter(self, data: dict, target: str = "") -> dict:
        """Apply --only and --skip section filters to adapter data.

        Sections: rules, skills, agents, commands, mcp, settings.
        If only_sections is set, zero out all sections not in it.
        Then zero out any sections in skip_sections.

        Per-target overrides (item 3) are applied on top.

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
                effective_only = (effective_only & tgt_only) if effective_only else tgt_only
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
            "plugins": {},
        }

        filtered = dict(data)

        for section, default in section_defaults.items():
            # Normalize: mcp_scoped tracks with mcp
            section_key = "mcp" if section == "mcp_scoped" else section

            # If only_sections specified and this section is not in it -> zero out
            if effective_only and section_key not in effective_only:
                filtered[section] = default
            # If skip_sections specified and this section is in it -> zero out
            elif section_key in effective_skip:
                filtered[section] = default

        return filtered

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

        except ImportError as e:
            self.logger.warn(f"Account manager unavailable, falling back to v1: {e}")
            return self.sync_all()
        except (ConfigError, OSError) as e:
            self.logger.warn(f"Multi-account sync failed, falling back to v1: {e}")
            return self.sync_all()
        except Exception as e:
            self.logger.warn(f"Unexpected multi-account sync failure, falling back to v1: {e}")
            return self.sync_all()

    def canary_sync(
        self,
        canary_target: str,
        remaining_targets: list[str] | None = None,
        confirm_fn=None,
    ) -> dict[str, dict]:
        """Incremental sync rollout: sync one canary target first, then the rest.

        Syncs ``canary_target`` first as a trial. If ``confirm_fn`` approves
        (or is None), proceeds to sync remaining targets.

        Args:
            canary_target: The first target to sync as the canary.
            remaining_targets: Targets to sync after canary succeeds. If None,
                               syncs all registered targets except the canary.
            confirm_fn: Optional callable(canary_result) -> bool. If it returns
                        False, the rollout is aborted after the canary.

        Returns:
            Dict mapping target_name -> {success, phase, error}
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
            self.logger.warn(f"[canary] Canary sync to '{canary_target}' failed -- aborting rollout.")
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
            try:
                all_targets = list(AdapterRegistry.list_targets())
                remaining_targets = [t for t in all_targets if t != canary_target]
            except ImportError:
                remaining_targets = []
            except Exception as e:
                self.logger.warn(f"[canary] Failed to list targets for rollout: {e}")
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
