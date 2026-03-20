from __future__ import annotations

"""Pre-sync and post-sync pipeline steps for HarnessSync.

Encapsulates the safety checks, source transformations, and post-sync
reporting that run around the core adapter sync loop. Each step is
best-effort (wrapped in try/except) so it never breaks the sync path.
Extracted from SyncOrchestrator.
"""

from datetime import datetime
from pathlib import Path

from src.adapters.result import SyncResult
from src.utils.hashing import hash_file_sha256
from src.utils.logger import Logger


class PreSyncPipeline:
    """Runs all pre-sync checks and transformations on source data.

    Each method is best-effort: failures are logged but never block sync
    (except secret detection and policy enforcement, which can return
    blocking results).
    """

    def __init__(
        self,
        project_dir: Path | None,
        cc_home: Path | None,
        scope: str,
        dry_run: bool,
        allow_secrets: bool,
        scrub_secrets: bool,
        minimal: bool,
        logger: Logger,
    ):
        self.project_dir = project_dir
        self.cc_home = cc_home
        self.scope = scope
        self.dry_run = dry_run
        self.allow_secrets = allow_secrets
        self.scrub_secrets = scrub_secrets
        self.minimal = minimal
        self.logger = logger

    def check_skill_dependencies(self, source_data: dict) -> None:
        """Warn about circular skill dependencies or missing references."""
        try:
            from src.skill_dependency_graph import SkillDependencyGraph
            skill_graph = SkillDependencyGraph.from_source_data(source_data)
            cycles = skill_graph.find_cycles()
            for cycle in cycles:
                arrow = " \u2192 "
                self.logger.warn(
                    f"Skill dependency cycle detected: {arrow.join(cycle)} "
                    "-- this may cause unexpected behavior when skills are synced"
                )
            # Warn about edges referencing skills that don't exist in the skills dir
            known_skills = set(skill_graph._nodes.keys())
            missing_warned: set[str] = set()
            for edge in skill_graph._edges:
                if (
                    edge.target not in known_skills
                    and edge.kind in ("explicit", "slash")
                    and edge.target not in missing_warned
                ):
                    missing_warned.add(edge.target)
                    self.logger.warn(
                        f"Skill '{edge.source}' references '/{edge.target}' which is "
                        "not in your skills directory -- dependency will be absent on sync targets"
                    )
        except Exception:
            pass  # Dependency check is informational, never blocks sync

    def substitute_config_vars(self, source_data: dict) -> None:
        """Substitute ${VAR} placeholders in rules content (in-place)."""
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

    def normalize_rules(self, source_data: dict) -> None:
        """Convert rules string to list[dict] format and merge rules_files (in-place)."""
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

    def record_rule_attribution(self, source_data: dict) -> None:
        """Record provenance for each source rule file."""
        if self.dry_run or not self.project_dir:
            return
        try:
            from src.rule_source_attribution import RuleAttributor
            attributor = RuleAttributor(project_dir=self.project_dir)
            for rf in source_data.get('rules', []):
                if isinstance(rf, dict):
                    rule_path = rf.get('path')
                    if rule_path:
                        full_path = self.project_dir / rule_path
                        if full_path.is_file():
                            attributor.record_from_file(full_path)
            if attributor.rule_count > 0:
                attributor.save_index()
        except Exception:
            pass  # Attribution recording is best-effort, never blocks sync

    def apply_project_type_detection(self, only_sections: set, skip_sections: set) -> set:
        """Auto-detect project type and return suggested skip_sections.

        Only applied when user hasn't manually set only_sections/skip_sections.

        Returns:
            Updated skip_sections set.
        """
        if only_sections or skip_sections:
            return skip_sections
        try:
            from src.project_detector import ProjectTypeDetector
            detector = ProjectTypeDetector(self.project_dir)
            profile = detector.detect()
            if profile and profile.suggested_skip_sections:
                new_skip = set(profile.suggested_skip_sections)
                self.logger.info(
                    f"Project type '{profile.project_type}' detected -- "
                    f"auto-skipping sections: {', '.join(sorted(new_skip))}"
                )
                return new_skip
        except Exception:
            pass  # Adaptive sync is best-effort, never blocks
        return skip_sections

    def prepare_adapter_data(self, source_data: dict) -> dict:
        """Translate source_data keys for adapter consumption.

        Returns a copy with 'mcp_servers' renamed to 'mcp', minimal MCP filtering
        applied, and 'mcp_scoped' carried through.
        """
        adapter_data = dict(source_data)
        raw_mcp = adapter_data.pop('mcp_servers', {}) or {}

        # Minimal Footprint Mode: strip non-essential MCP servers
        if self.minimal and isinstance(raw_mcp, dict):
            essential_mcp = {
                name: cfg for name, cfg in raw_mcp.items()
                if isinstance(cfg, dict) and cfg.get("essential", False)
            }
            if not essential_mcp:
                essential_mcp = raw_mcp
                self.logger.info(
                    "Minimal mode: no MCP servers marked 'essential' -- syncing all MCP servers. "
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
        adapter_data['mcp_scoped'] = source_data.get('mcp_servers_scoped', {})
        return adapter_data

    def extract_model_routing_hints(self, source_data: dict):
        """Extract model routing hints from settings.

        Returns:
            Model routing hints object or None.
        """
        try:
            from src.model_routing import ModelRoutingAdapter, extract_routing_hints_from_settings_file
            mr_adapter = ModelRoutingAdapter()
            settings_raw = source_data.get('settings', {})
            if isinstance(settings_raw, dict) and settings_raw:
                return mr_adapter.read_from_settings(settings_raw)
            elif self.cc_home:
                settings_path = (self.cc_home or Path.home() / ".claude") / "settings.json"
                if settings_path.exists():
                    return extract_routing_hints_from_settings_file(settings_path)
        except Exception:
            pass  # Model routing extraction is best-effort
        return None

    def predict_sync_impact(self, source_data: dict) -> None:
        """Predict behavioral impact of pending changes (dry-run only)."""
        if not self.dry_run:
            return
        try:
            from src.sync_impact_predictor import SyncImpactPredictor
            from src.state_manager import StateManager
            prev_source: dict = {}
            try:
                sm_prev = StateManager()
                prev_snap = sm_prev.get_all_status().get("last_source_snapshot", {})
                if isinstance(prev_snap, dict):
                    prev_source = prev_snap
            except Exception:
                pass
            predictor = SyncImpactPredictor(self.project_dir)
            impact_report = predictor.predict(source_data, prev_source)
            if not impact_report.is_empty:
                self.logger.info(impact_report.format())
        except Exception:
            pass  # Impact prediction is informational, never blocks

    def check_mcp_reachability(self, source_data: dict) -> None:
        """Warn if any MCP servers are unreachable."""
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

    def check_capability_gaps(self, source_data: dict) -> None:
        """Surface which rules/skills/MCP will be dropped or approximated."""
        try:
            from src.capability_advisor import CapabilityAdvisor
            cap_advisor = CapabilityAdvisor()
            cap_report = cap_advisor.analyze_source_data(source_data)
            if cap_report and not cap_report.is_empty:
                for cap_warning in cap_report.warnings:
                    self.logger.warn(
                        f"Capability gap [{cap_warning.harness}]: {cap_warning.message}"
                    )
        except Exception:
            pass  # Capability gap warnings are informational, never block sync

    def detect_secrets(self, source_data: dict, adapter_data: dict) -> dict | None:
        """Scan for secrets and either scrub, block, or pass.

        Returns:
            A blocking result dict if sync should be stopped, else None.
        """
        try:
            from src.secret_detector import SecretDetector
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
                    # Record to audit log
                    try:
                        from src.audit_log import AuditLog
                        from src.adapters import AdapterRegistry
                        audit = AuditLog(project_dir=self.project_dir)
                        protected = AdapterRegistry.list_targets()
                        audit.record_secret_block(
                            detections=detections,
                            protected_targets=protected,
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
        return None

    def lint_config(self, source_data: dict) -> None:
        """Run config linter on source data."""
        try:
            from src.config_linter import ConfigLinter
            linter = ConfigLinter()
            lint_errors = linter.lint(source_data, self.project_dir, self.cc_home)
            if lint_errors:
                self.logger.warn("Config linter found issues:")
                for err in lint_errors:
                    self.logger.warn(f"  {err}")
        except Exception as e:
            self.logger.warn(f"Config linter failed: {e}")

    def check_harness_version_compat(self) -> None:
        """Check harness version compatibility."""
        try:
            from src.harness_version_compat import format_compat_warnings
            compat_warnings = format_compat_warnings(project_dir=self.project_dir)
            for w in compat_warnings:
                self.logger.warn(f"Version compat: {w}")
        except Exception:
            pass  # Version compat check is informational, never blocks

    def check_permission_escalation(self, source_data: dict) -> None:
        """Detect when sync would grant targets MORE permissions than the source."""
        try:
            from src.permission_escalation_guard import check_escalation
            source_settings = source_data.get('settings', {}) or {}
            if not source_settings:
                return
            esc_report = check_escalation(source_settings)
            if esc_report.has_blocks:
                self.logger.warn("Permission escalation guard: BLOCK-level escalations detected:")
                for esc_w in esc_report.warnings:
                    if esc_w.severity == "block":
                        self.logger.warn(f"  {esc_w.format()}")
                self.logger.warn(
                    "Tip: Use /sync-override to set per-harness restrictions, "
                    "or /sync-permissions to review the full report."
                )
            elif esc_report.has_escalations:
                self.logger.warn("Permission escalation guard: potential permission gaps:")
                for esc_w in esc_report.warnings:
                    self.logger.warn(f"  {esc_w.format()}")
        except Exception:
            pass  # Escalation guard is best-effort, never blocks sync

    def check_policy(self, source_data: dict) -> dict | None:
        """Check org/team policy; returns blocking result or None.

        Returns:
            A blocking result dict if policy violation, else None.
        """
        try:
            from src.sync_policy import PolicyEnforcer
            from src.adapters import AdapterRegistry
            policy = PolicyEnforcer(project_dir=self.project_dir)
            if not policy.has_policy:
                return None
            pre_policy_targets = AdapterRegistry.list_targets()
            policy_result = policy.check_all(source_data, targets=pre_policy_targets)
            if policy_result.any_blocked:
                self.logger.warn("Sync blocked by policy:")
                for pr in policy_result.reports:
                    if pr.blocked:
                        for pv in pr.violations:
                            if pv.severity == "error":
                                self.logger.warn(f"  [{pv.target}] {pv.section}: {pv.message}")
                return {
                    '_blocked': True,
                    '_reason': 'policy_violation',
                    '_warnings': policy_result.format(),
                }
            for pr in policy_result.reports:
                for w in pr.warnings:
                    self.logger.warn(f"Policy [{pr.target}]: {w}")
        except Exception:
            pass  # Policy check is best-effort, never crashes sync
        return None

    def detect_conflicts(self, state_manager) -> dict:
        """Run conflict detection (non-blocking, informational).

        Returns:
            Conflicts dict (may be empty).
        """
        conflicts = {}
        try:
            from src.conflict_detector import ConflictDetector
            conflict_detector = ConflictDetector(state_manager)
            conflicts = conflict_detector.check_all()

            if any(conflicts.values()):
                formatted_conflicts = conflict_detector.format_warnings(conflicts)
                self.logger.warn(formatted_conflicts)
        except ImportError as e:
            self.logger.warn(f"ConflictDetector unavailable: {e}")
        return conflicts

    def take_auto_snapshot(self) -> None:
        """Take a named snapshot before every real sync."""
        if self.dry_run:
            return
        try:
            from src.config_time_machine import ConfigTimeMachine
            ctm = ConfigTimeMachine(self.project_dir)
            snap_name = f"pre-sync-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            ctm.take_snapshot(name=snap_name, cc_home=self.cc_home)
            self.logger.debug(f"Auto-snapshot saved: {snap_name}")
        except Exception:
            pass  # Auto-snapshot is best-effort, never blocks sync

    def capture_annotations(self, targets: list[str]) -> dict:
        """Capture user annotations from target files before overwriting.

        Returns:
            Captured annotations dict (may be empty).
        """
        if self.dry_run:
            return {}
        try:
            from src.annotation_preserver import AnnotationPreserver
            ann_preserver = AnnotationPreserver(self.project_dir)
            return ann_preserver.capture_all(targets)
        except Exception:
            return {}  # Annotation preservation is best-effort


class PostSyncPipeline:
    """Runs all post-sync reporting and cleanup steps.

    Each method is best-effort: failures are logged but never block.
    """

    def __init__(
        self,
        project_dir: Path | None,
        cc_home: Path | None,
        scope: str,
        dry_run: bool,
        account: str | None,
        logger: Logger,
    ):
        self.project_dir = project_dir
        self.cc_home = cc_home
        self.scope = scope
        self.dry_run = dry_run
        self.account = account
        self.logger = logger

    def restore_annotations(self, captured_annotations: dict) -> None:
        """Restore user annotations after sync."""
        if self.dry_run or not captured_annotations:
            return
        try:
            from src.annotation_preserver import AnnotationPreserver
            ann_preserver = AnnotationPreserver(self.project_dir)
            restored = ann_preserver.restore_all(captured_annotations)
            if restored:
                total_restored = sum(restored.values())
                self.logger.info(
                    f"Preserved user annotations in {total_restored} file(s)"
                )
        except Exception:
            pass  # Best-effort

    def cleanup_symlinks(self) -> None:
        """Clean up broken symlinks after sync."""
        if self.dry_run:
            return
        try:
            from src.symlink_cleaner import SymlinkCleaner
            symlink_cleaner = SymlinkCleaner(self.project_dir)
            cleanup_results = symlink_cleaner.cleanup_all()
            total_removed = sum(len(removed) for removed in cleanup_results.values())
            if total_removed > 0:
                self.logger.info(f"Cleaned up {total_removed} broken symlink(s)")
        except ImportError as e:
            self.logger.warn(f"SymlinkCleaner unavailable: {e}")

    def generate_compatibility_report(self, results: dict, source_data: dict) -> None:
        """Generate compatibility report, coverage scores, and fidelity scores."""
        try:
            from src.compatibility_reporter import CompatibilityReporter
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

    def record_changelog(self, results: dict) -> None:
        """Record sync results in changelog."""
        if self.dry_run:
            return
        try:
            from src.changelog_manager import ChangelogManager
            changelog = ChangelogManager(self.project_dir)
            changelog.record(results, scope=self.scope, account=self.account)
        except Exception as e:
            self.logger.warn(f"Changelog update failed: {e}")

    def record_audit_log(self, results: dict) -> None:
        """Write tamper-evident audit log entry."""
        if self.dry_run:
            return
        try:
            from src.audit_log import AuditLog
            audit = AuditLog(project_dir=self.project_dir)
            synced_targets = [
                t for t in results
                if not t.startswith("_") and isinstance(results[t], dict)
            ]
            files_changed: list[str] = []
            for t in synced_targets:
                t_results = results[t]
                for section_result in t_results.values():
                    if hasattr(section_result, "files_written"):
                        files_changed.extend(
                            str(p) for p in (section_result.files_written or [])
                        )
            source_hash = ""
            if self.project_dir:
                claude_md = self.project_dir / "CLAUDE.md"
                if claude_md.is_file():
                    try:
                        source_hash = hash_file_sha256(claude_md)
                    except Exception:
                        pass
            audit.record(
                event="sync",
                targets=synced_targets,
                files_changed=files_changed,
                source_hash=source_hash,
                scope=self.scope or "all",
            )
        except Exception as ae:
            self.logger.warn(f"Audit log update failed: {ae}")

    def cleanup_backups(self, targets: list[str], backup_manager) -> None:
        """Clean up old backups for each target."""
        if self.dry_run or not backup_manager:
            return
        try:
            for target in targets:
                backup_manager.cleanup_old_backups(target, keep_count=10)
        except Exception as e:
            self.logger.warn(f"Backup cleanup failed: {e}")

    def sign_integrity(self, results: dict) -> None:
        """Sign synced output files for integrity verification."""
        if self.dry_run:
            return
        try:
            from src.sync_integrity import SyncIntegrityStore
            integrity_store = SyncIntegrityStore(project_dir=self.project_dir)
            files_to_sign: list[Path] = []
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
        except Exception as ie:
            self.logger.warn(f"Integrity signing failed: {ie}")

    def verify_post_sync(self, results: dict) -> None:
        """Verify written config files are valid."""
        if self.dry_run:
            return
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
                        f"{issue.file_path} -- {issue.message}"
                    )
        except Exception as ve:
            self.logger.warn(f"Post-sync verification failed: {ve}")

    def check_harness_upgrades(self, results: dict) -> None:
        """Detect harness version updates and surface new capabilities."""
        if self.dry_run:
            return
        try:
            from src.harness_version_compat import detect_harness_updates, format_update_report
            updates = detect_harness_updates(acknowledge=True)
            if updates:
                report = format_update_report(updates)
                if report:
                    results['_upgrade_notices'] = report
        except Exception:
            pass  # Upgrade advisor is informational, never blocks

    def generate_capability_report(self, results: dict) -> None:
        """Show which skills/capabilities are missing in synced targets."""
        if self.dry_run:
            return
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

    def compute_health_scores(self, results: dict) -> None:
        """Compute per-harness 0-100 health score and persist trend data."""
        if self.dry_run:
            return
        try:
            from src.config_health import SyncHealthTracker
            tracker = SyncHealthTracker(cc_home=self.cc_home)
            health_scores: dict[str, dict] = {}
            synced_targets_health = [
                t for t in results
                if not t.startswith("_")
                and isinstance(results[t], dict)
                and "error" not in results[t]
            ]
            for ht in synced_targets_health:
                try:
                    ht_results = results[ht]
                    # Estimate fidelity from coverage/fidelity scores if available
                    cov = (results.get("_coverage_scores") or {}).get(ht, 1.0)
                    fid = (results.get("_fidelity_scores") or {}).get(ht, 1.0)
                    if isinstance(cov, (int, float)):
                        cov = min(1.0, max(0.0, cov / 100.0 if cov > 1 else cov))
                    else:
                        cov = 1.0
                    if isinstance(fid, (int, float)):
                        fid = min(1.0, max(0.0, fid / 100.0 if fid > 1 else fid))
                    else:
                        fid = 1.0
                    hs_score = tracker.compute_score(
                        target=ht,
                        rule_fidelity=fid,
                        skills_coverage=cov,
                    )
                    health_scores[ht] = {
                        "score": hs_score.score,
                        "label": hs_score.label,
                        "trend": hs_score.trend,
                    }
                except Exception:
                    pass  # Per-target scoring is best-effort
            if health_scores:
                results["_health_scores"] = health_scores
        except Exception:
            pass  # Health tracking is informational, never blocks
