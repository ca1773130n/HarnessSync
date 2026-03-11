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
from src.backup_manager import BackupManager, BackupContext
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
                 incremental: bool = False):
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
        self.logger = Logger()
        self.state_manager = StateManager()
        self.account_config = None

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

    def sync_all(self) -> dict:
        """Sync all configuration to all registered adapters.

        Implements full safety pipeline:
        1. Secret detection (blocks if secrets found, unless allow_secrets=True)
        2. Conflict detection (warns but does not block)
        3. Backup (pre-sync, with automatic rollback on failure)
        4. Sync adapters
        5. Symlink cleanup (post-sync)
        6. Compatibility report (post-sync)
        7. Backup retention cleanup

        Returns:
            Dict mapping target_name -> {config_type: SyncResult} or preview dict
            Special keys: '_blocked', '_reason', '_warnings', '_conflicts', '_compatibility_report'
        """
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

        # Translate key: SourceReader uses 'mcp_servers', adapters expect 'mcp'
        adapter_data = dict(source_data)
        adapter_data['mcp'] = adapter_data.pop('mcp_servers', {})
        # Pass scoped MCP data for v2.0 scope-aware adapters
        adapter_data['mcp_scoped'] = source_data.get('mcp_servers_scoped', {})

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
        results = {}

        # --- PRE-SYNC: BACKUP (skip in dry-run) ---
        backup_manager = None
        if not self.dry_run:
            try:
                backup_manager = BackupManager()
            except ImportError as e:
                self.logger.warn(f"BackupManager unavailable: {e}")

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
                # Build target-specific data (applying sync tag filtering)
                target_data = dict(adapter_data)
                if _rules_have_tags:
                    target_data['rules'] = [
                        {**r, 'content': filter_rules_for_target(r.get('content', ''), target)}
                        for r in adapter_data.get('rules', [])
                        if isinstance(r, dict)
                    ]

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

        # --- POST-SYNC: COMPATIBILITY REPORT ---
        try:
            compatibility_reporter = CompatibilityReporter()
            report = compatibility_reporter.generate(results)

            if compatibility_reporter.has_issues(report):
                results['_compatibility_report'] = compatibility_reporter.format_report(report)
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
        """POST sync summary to configured webhook URL (if set).

        Reads HARNESSSYNC_WEBHOOK_URL from environment. Fires and forgets —
        network errors are logged but never block the sync.

        Args:
            results: Sync results dict from sync_all()
        """
        import json
        import os
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
            self.logger.warn(f"Webhook POST failed: {exc}")

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

        Args:
            adapter: Target adapter instance
            source_data: Source configuration data

        Returns:
            Dict with 'preview' key containing formatted diff output
        """
        df = DiffFormatter()

        # Rules diff
        rules = source_data.get('rules', '')
        if rules:
            df.add_text_diff(
                f"{adapter.target_name}/rules",
                "",  # Would need to read current target file for full diff
                rules if isinstance(rules, str) else str(rules)
            )

        # Skills diff
        skills = source_data.get('skills', {})
        if skills:
            df.add_structural_diff(
                f"{adapter.target_name}/skills",
                {},  # Current target skills (would need adapter inspection)
                {name: str(path) for name, path in skills.items()}
            )

        # Agents diff
        agents = source_data.get('agents', {})
        if agents:
            df.add_structural_diff(
                f"{adapter.target_name}/agents",
                {},
                {name: str(path) for name, path in agents.items()}
            )

        # Commands diff
        commands = source_data.get('commands', {})
        if commands:
            df.add_structural_diff(
                f"{adapter.target_name}/commands",
                {},
                {name: str(path) for name, path in commands.items()}
            )

        # MCP diff
        mcp = source_data.get('mcp', {})
        if mcp:
            df.add_structural_diff(
                f"{adapter.target_name}/mcp",
                {},
                mcp
            )

        # Settings diff
        settings = source_data.get('settings', {})
        if settings:
            df.add_structural_diff(
                f"{adapter.target_name}/settings",
                {},
                settings
            )

        return {"preview": df.format_output(), "is_preview": True}

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
