from __future__ import annotations

"""
Compatibility reporting for sync operations.

Analyzes sync results to produce per-target breakdown of synced/adapted/skipped/failed
items with explanations. Implements SAF-04 from Phase 5 safety validation.

Based on aggregate SyncResult data for compatibility reporting (existing adapter pattern).
"""

from dataclasses import dataclass

from src.adapters.result import SyncResult
from src.utils.logger import Logger


class CompatibilityReporter:
    """
    Sync compatibility analyzer and reporter.

    Generates per-target breakdown distinguishing:
    - synced: Items that mapped directly (no translation needed)
    - adapted: Items requiring format translation
    - skipped: Items skipped (already current or incompatible)
    - failed: Items that failed to sync

    Provides formatted output and issue detection for orchestrator.
    """

    # Explanations for adapted items by config_type
    ADAPTATION_REASONS = {
        'rules': 'Rules content concatenated/inlined to target format',
        'agents': 'Agent .md files converted to target skill/agent format',
        'commands': 'Command .md files converted to target format',
        'mcp': 'MCP server config translated from JSON to target format',
        'settings': 'Settings mapped with conservative permission defaults',
        'skills': 'Skills synced via symlinks'
    }

    # Per-field settings translation explanations per target harness.
    # Maps target_name -> {claude_field -> (target_field, translation_note)}
    SETTINGS_FIELD_TRANSLATIONS: dict[str, dict[str, tuple[str, str]]] = {
        "codex": {
            "allowedTools": (
                "allowedCommands",
                "filtered to shell-executable commands only; MCP tool refs dropped",
            ),
            "deniedTools": (
                "deniedCommands",
                "non-shell tool refs silently omitted",
            ),
            "approvalMode": (
                "(inlined as rule)",
                "no native approvalMode; written as a permission note in AGENTS.md",
            ),
            "mcpServers": (
                "agents.json mcpServers",
                "MCP servers written to agents.json, not natively executed by codex",
            ),
        },
        "gemini": {
            "allowedTools": (
                "tools.allowed",
                "list format differs; Gemini uses string glob patterns",
            ),
            "deniedTools": (
                "tools.exclude",
                "list format differs; Gemini uses string glob patterns",
            ),
            "approvalMode": (
                "(inlined as instruction)",
                "no native approvalMode; written as an instruction block in GEMINI.md",
            ),
            "env": (
                "(not synced)",
                "environment vars not forwarded to Gemini config",
            ),
        },
        "opencode": {
            "allowedTools": (
                "(inlined as instruction)",
                "OpenCode has no tool allowlist; written as a rules note",
            ),
            "deniedTools": (
                "(inlined as instruction)",
                "OpenCode has no tool denylist; written as a rules note",
            ),
            "approvalMode": (
                "(inlined as instruction)",
                "no native approvalMode; written as a project rule",
            ),
        },
        "cursor": {
            "allowedTools": (
                "(inlined in .mdc rule)",
                "Cursor has no tool allowlist; written as an .mdc rule block",
            ),
            "deniedTools": (
                "(inlined in .mdc rule)",
                "Cursor has no tool denylist; written as an .mdc rule block",
            ),
            "mcpServers": (
                ".cursor/mcp.json",
                "MCP config written to .cursor/mcp.json (Cursor native format)",
            ),
            "approvalMode": (
                "(not synced)",
                "Cursor manages approval per-request; approvalMode not applicable",
            ),
        },
        "aider": {
            "allowedTools": (
                "(not synced)",
                "Aider has no tool allowlist concept",
            ),
            "deniedTools": (
                "(not synced)",
                "Aider has no tool denylist concept",
            ),
            "mcpServers": (
                "(not synced)",
                "Aider does not support MCP servers",
            ),
            "approvalMode": (
                "--yes / --yes-always",
                "mapped to aider auto-confirm flags in .aider.conf.yml",
            ),
        },
        "windsurf": {
            "allowedTools": (
                "(inlined in .windsurfrules)",
                "Windsurf has no native tool allowlist; written as rule text",
            ),
            "deniedTools": (
                "(inlined in .windsurfrules)",
                "Windsurf has no native tool denylist; written as rule text",
            ),
            "mcpServers": (
                "(not synced)",
                "Windsurf MCP support is IDE-managed; not written to .windsurfrules",
            ),
            "approvalMode": (
                "(not synced)",
                "Windsurf manages approval natively; approvalMode not applicable",
            ),
        },
    }

    def __init__(self):
        """Initialize CompatibilityReporter with Logger instance."""
        self.logger = Logger()

    def generate(self, results: dict) -> dict:
        """
        Analyze sync results from orchestrator.

        Args:
            results: Dict mapping target_name -> {config_type: SyncResult}

        Returns:
            Dict mapping target_name -> report dict with:
                - synced_items: list of {config_type, count, files}
                - adapted_items: list of {config_type, count, explanation}
                - skipped_items: list of {config_type, count, files}
                - failed_items: list of {config_type, count, files, reasons}
                - summary: {total_synced, total_adapted, total_skipped, total_failed, status}
        """
        report = {}

        for target_name, target_results in results.items():
            # Skip special result keys
            if target_name.startswith('_'):
                continue

            if not isinstance(target_results, dict):
                continue

            # Initialize per-target report structure
            target_report = {
                'synced_items': [],
                'adapted_items': [],
                'skipped_items': [],
                'failed_items': [],
                'summary': {
                    'total_synced': 0,
                    'total_adapted': 0,
                    'total_skipped': 0,
                    'total_failed': 0,
                    'status': 'success'
                }
            }

            # Process each config type
            for config_type, result in target_results.items():
                # Skip non-SyncResult entries (e.g., 'preview', 'error')
                if not isinstance(result, SyncResult):
                    continue

                # Synced items (direct map, no translation)
                if result.synced > 0:
                    target_report['synced_items'].append({
                        'config_type': config_type,
                        'count': result.synced,
                        'files': result.synced_files
                    })
                    target_report['summary']['total_synced'] += result.synced

                # Adapted items (format translation required)
                if result.adapted > 0:
                    explanation = self.ADAPTATION_REASONS.get(
                        config_type,
                        f'{config_type} adapted to target format'
                    )
                    target_report['adapted_items'].append({
                        'config_type': config_type,
                        'count': result.adapted,
                        'explanation': explanation
                    })
                    target_report['summary']['total_adapted'] += result.adapted

                # Skipped items
                if result.skipped > 0:
                    target_report['skipped_items'].append({
                        'config_type': config_type,
                        'count': result.skipped,
                        'files': result.skipped_files
                    })
                    target_report['summary']['total_skipped'] += result.skipped

                # Failed items
                if result.failed > 0:
                    target_report['failed_items'].append({
                        'config_type': config_type,
                        'count': result.failed,
                        'files': result.failed_files,
                        'reasons': result.failed_files  # Failed files contain error messages
                    })
                    target_report['summary']['total_failed'] += result.failed

            # Calculate overall status
            summary = target_report['summary']
            if summary['total_failed'] > 0:
                if summary['total_synced'] > 0 or summary['total_adapted'] > 0:
                    summary['status'] = 'partial'
                else:
                    summary['status'] = 'failed'
            elif summary['total_synced'] == 0 and summary['total_adapted'] == 0 and summary['total_skipped'] == 0:
                summary['status'] = 'nothing'
            else:
                summary['status'] = 'success'

            report[target_name] = target_report

        return report

    def format_report(self, report: dict) -> str:
        """
        Format compatibility report for user output.

        Args:
            report: Dict from generate() mapping target -> report dict

        Returns:
            Formatted string with per-target sections and summary
        """
        if not report:
            return ""

        lines = []
        lines.append("\n" + "=" * 60)
        lines.append("Sync Compatibility Report")
        lines.append("=" * 60)

        for target_name, target_report in sorted(report.items()):
            lines.append(f"\n{target_name.upper()}")
            lines.append("-" * 60)

            # Synced items (green checkmark)
            if target_report['synced_items']:
                for item in target_report['synced_items']:
                    lines.append(f"  ✓ {item['config_type']}: {item['count']} synced (direct map)")

            # Adapted items (yellow arrow with explanation)
            if target_report['adapted_items']:
                for item in target_report['adapted_items']:
                    lines.append(f"  → {item['config_type']}: {item['count']} adapted")
                    lines.append(f"     ({item['explanation']})")

            # Skipped items (gray dash)
            if target_report['skipped_items']:
                for item in target_report['skipped_items']:
                    lines.append(f"  - {item['config_type']}: {item['count']} skipped")

            # Failed items (red X with reason)
            if target_report['failed_items']:
                for item in target_report['failed_items']:
                    lines.append(f"  ✗ {item['config_type']}: {item['count']} failed")
                    for reason in item['reasons'][:3]:  # Show first 3 reasons
                        lines.append(f"     Reason: {reason}")

            # Target summary
            summary = target_report['summary']
            lines.append(f"\n  Summary: {summary['total_synced']} synced | {summary['total_adapted']} adapted | {summary['total_skipped']} skipped | {summary['total_failed']} failed")
            lines.append(f"  Status: {summary['status']}")

        # Footer summary
        lines.append("\n" + "=" * 60)
        total_synced = sum(r['summary']['total_synced'] for r in report.values())
        total_adapted = sum(r['summary']['total_adapted'] for r in report.values())
        total_skipped = sum(r['summary']['total_skipped'] for r in report.values())
        total_failed = sum(r['summary']['total_failed'] for r in report.values())
        lines.append(f"Overall: {total_synced} synced | {total_adapted} adapted | {total_skipped} skipped | {total_failed} failed")
        lines.append("=" * 60 + "\n")

        return "\n".join(lines)

    def calculate_fidelity_score(self, results: dict) -> dict:
        """Calculate translation fidelity score (0-100) per target and category.

        A score of 100 means all items synced directly (no translation needed).
        Adapted items score 70. Skipped and failed items score 0.

        Args:
            results: Dict mapping target_name -> {config_type: SyncResult}

        Returns:
            Dict mapping target_name -> {
                "overall": float,          # 0-100 overall score
                "by_category": {           # per config_type scores
                    "rules": float,
                    "skills": float,
                    ...
                },
                "label": str,              # "excellent" | "good" | "fair" | "poor"
            }
        """
        scores: dict = {}

        for target_name, target_results in results.items():
            if target_name.startswith("_") or not isinstance(target_results, dict):
                continue

            category_scores: dict[str, float] = {}
            category_weights: dict[str, float] = {
                "rules": 2.0, "mcp": 1.5, "skills": 1.5,
                "agents": 1.0, "commands": 1.0, "settings": 1.0,
            }

            weighted_sum = 0.0
            weight_total = 0.0

            for config_type, result in target_results.items():
                if not isinstance(result, SyncResult):
                    continue

                total = result.synced + result.adapted + result.skipped + result.failed
                if total == 0:
                    continue

                # Score: synced=100pts, adapted=70pts, skipped=0pts, failed=0pts
                raw_score = (result.synced * 100 + result.adapted * 70) / total
                category_scores[config_type] = round(raw_score, 1)

                w = category_weights.get(config_type, 1.0)
                weighted_sum += raw_score * w
                weight_total += w

            overall = round(weighted_sum / weight_total, 1) if weight_total > 0 else 100.0
            if overall >= 90:
                label = "excellent"
            elif overall >= 75:
                label = "good"
            elif overall >= 50:
                label = "fair"
            else:
                label = "poor"

            scores[target_name] = {
                "overall": overall,
                "by_category": category_scores,
                "label": label,
            }

        return scores

    def format_fidelity_scores(self, scores: dict) -> str:
        """Format fidelity scores for user output.

        Args:
            scores: Dict from calculate_fidelity_score().

        Returns:
            Formatted string.
        """
        if not scores:
            return ""

        lines = ["\nTranslation Fidelity Scores", "=" * 40]
        for target, data in sorted(scores.items()):
            overall = data["overall"]
            label = data["label"]
            bar_len = int(overall / 5)  # 20 chars = 100%
            bar = "█" * bar_len + "░" * (20 - bar_len)
            lines.append(f"\n{target.upper()}: {overall:.0f}/100 [{label}]")
            lines.append(f"  [{bar}]")
            for cat, score in sorted(data["by_category"].items()):
                indicator = "✓" if score >= 90 else ("~" if score >= 60 else "✗")
                lines.append(f"  {indicator} {cat:<10} {score:.0f}%")

        lines.append("")
        lines.append("Score guide: 100=direct sync  70=adapted  0=skipped/failed")
        return "\n".join(lines)

    def generate_gap_report(self, source_data: dict, targets: list[str]) -> str:
        """Generate a capability gap report showing what's lost per harness.

        For each target, lists Claude Code features that have no equivalent
        or require significant translation, with item counts.

        Args:
            source_data: Output of SourceReader.discover_all().
            targets: List of target harness names.

        Returns:
            Formatted gap report string.
        """
        # Feature support levels per target (None=full, "partial", "none")
        _GAP_MATRIX: dict[str, dict[str, str | None]] = {
            "codex": {
                "skills": "partial",
                "agents": "partial",
                "commands": "partial",
                "mcp": "partial",
                "settings": "partial",
            },
            "gemini": {
                "agents": "partial",
                "commands": "partial",
                "settings": "partial",
            },
            "opencode": {
                "agents": "partial",
                "commands": "partial",
                "mcp": "partial",
                "settings": "partial",
            },
            "cursor": {
                "skills": "none",
                "agents": "none",
                "commands": "partial",
                "mcp": "partial",
                "settings": "partial",
            },
            "aider": {
                "skills": "none",
                "agents": "none",
                "commands": "none",
                "mcp": "none",
                "settings": "partial",
            },
            "windsurf": {
                "skills": "none",
                "agents": "none",
                "commands": "none",
                "mcp": "partial",
                "settings": "partial",
            },
        }

        counts = {
            "skills": len(source_data.get("skills", {})),
            "agents": len(source_data.get("agents", {})),
            "commands": len(source_data.get("commands", {})),
            "mcp": len(source_data.get("mcp_servers", {})),
            "settings": 1 if source_data.get("settings") else 0,
        }

        lines = ["Capability Gap Report", "=" * 50, ""]
        lines.append("Shows Claude Code features with no or partial equivalent")
        lines.append("in each target harness.\n")

        any_gap = False
        for target in sorted(targets):
            gaps = _GAP_MATRIX.get(target, {})
            target_lines = []
            for feature, level in gaps.items():
                count = counts.get(feature, 0)
                if count == 0:
                    continue  # Nothing to lose
                if level == "none":
                    target_lines.append(
                        f"  ✗ {feature}: NO equivalent — {count} item(s) will not sync"
                    )
                    any_gap = True
                elif level == "partial":
                    target_lines.append(
                        f"  ~ {feature}: partial support — {count} item(s) may lose fidelity"
                    )
                    any_gap = True

            if target_lines:
                lines.append(f"[{target.upper()}]")
                lines.extend(target_lines)
                lines.append("")

        if not any_gap:
            lines.append("No capability gaps detected for your current feature set.")
        else:
            lines.append(
                "Tip: Use <!-- sync:skip --> to exclude CC-only items from targets\n"
                "that don't support them, or <!-- sync:codex-only --> to restrict\n"
                "content to specific harnesses."
            )

        return "\n".join(lines)

    def calculate_coverage_score(self, results: dict, source_data: dict) -> dict:
        """Calculate per-harness sync coverage score after a sync operation.

        Coverage score answers: "What % of your Claude Code capabilities are
        reflected in each target harness?"

        Formula:
            coverage = (supported_features / total_source_features) * 100
        where supported_features counts non-empty source items that synced
        successfully (synced + adapted > 0).

        Args:
            results: Dict mapping target_name -> {config_type: SyncResult}
            source_data: Output of SourceReader.discover_all(), used to
                         determine total source item counts per category.

        Returns:
            Dict mapping target_name -> {
                "score": float,           # 0–100
                "label": str,             # "high" | "medium" | "low"
                "supported": int,         # categories with coverage
                "total": int,             # total non-empty categories
                "gaps": list[str],        # categories with zero coverage
                "partial": list[str],     # categories with partial coverage
            }
        """
        # Count non-empty source categories
        source_counts: dict[str, int] = {
            "rules": 1 if source_data.get("rules") else 0,
            "skills": len(source_data.get("skills", {})),
            "agents": len(source_data.get("agents", {})),
            "commands": len(source_data.get("commands", {})),
            "mcp": len(source_data.get("mcp_servers", {})),
            "settings": 1 if source_data.get("settings") else 0,
        }
        non_empty_categories = [k for k, v in source_counts.items() if v > 0]
        total_non_empty = len(non_empty_categories)

        coverage: dict = {}

        for target_name, target_results in results.items():
            if target_name.startswith("_") or not isinstance(target_results, dict):
                continue

            gaps: list[str] = []
            partial: list[str] = []
            supported_count = 0

            for category in non_empty_categories:
                result = target_results.get(category)
                if not isinstance(result, SyncResult):
                    gaps.append(category)
                    continue

                if result.failed > 0 and result.synced == 0 and result.adapted == 0:
                    gaps.append(category)
                elif result.skipped > 0 and result.synced == 0 and result.adapted == 0:
                    gaps.append(category)
                elif result.adapted > 0 and result.synced == 0:
                    partial.append(category)
                    supported_count += 1  # partial still counts as coverage
                else:
                    supported_count += 1

            score = (supported_count / total_non_empty * 100) if total_non_empty > 0 else 100.0
            score = round(score, 1)

            if score >= 80:
                label = "high"
            elif score >= 50:
                label = "medium"
            else:
                label = "low"

            coverage[target_name] = {
                "score": score,
                "label": label,
                "supported": supported_count,
                "total": total_non_empty,
                "gaps": gaps,
                "partial": partial,
            }

        return coverage

    def format_coverage_scores(self, coverage: dict) -> str:
        """Format per-harness coverage scores for post-sync output.

        Args:
            coverage: Dict from calculate_coverage_score().

        Returns:
            Formatted string for display after sync completes.
        """
        if not coverage:
            return ""

        lines = ["\nSync Coverage Scores", "=" * 40]
        for target, data in sorted(coverage.items()):
            score = data["score"]
            label = data["label"]
            supported = data["supported"]
            total = data["total"]
            gaps = data.get("gaps", [])
            partial_cats = data.get("partial", [])

            bar_len = int(score / 5)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            lines.append(f"\n{target.upper()}: {score:.0f}% coverage [{label}]")
            lines.append(f"  [{bar}]  {supported}/{total} categories")
            if gaps:
                lines.append(f"  ✗ unsupported: {', '.join(gaps)}")
            if partial_cats:
                lines.append(f"  ~ partial:     {', '.join(partial_cats)}")

        lines.append("")
        return "\n".join(lines)

    def feature_gap_report(self, results: dict, source_config: dict | None = None) -> str:
        """Generate a post-sync Harness Capability Gap Report.

        Shows exactly which Claude Code features have no equivalent in each target,
        with item counts. Example output:

            GEMINI: 3 agent(s) had tool capabilities dropped (no agent-tools support)
            CODEX: MCP servers skipped (1 server) — codex uses agents.json instead

        Args:
            results: Dict from orchestrator mapping target -> {config_type: SyncResult}.
            source_config: Optional raw source config dict for richer gap analysis.

        Returns:
            Formatted gap report string. Empty string if no gaps found.
        """
        # Known per-target capability gaps (static knowledge)
        # Maps target -> {config_type -> human-readable limitation}
        _KNOWN_GAPS: dict[str, dict[str, str]] = {
            "gemini": {
                "agents": "no agent-tool bindings (agent tools are dropped)",
                "commands": "slash commands converted to plain GEMINI.md instructions",
                "settings": "allowedTools / deniedTools map to tools.allowed / tools.exclude",
            },
            "codex": {
                "mcp": "MCP servers written to agents.json, not natively executed",
                "commands": "slash commands have no direct Codex equivalent",
                "skills": "skills inlined into AGENTS.md (no separate skill files)",
            },
            "opencode": {
                "agents": "agents written as OpenCode project files",
                "commands": "commands have no direct OpenCode equivalent",
            },
            "cursor": {
                "mcp": "MCP config written to .cursor/mcp.json",
                "agents": "agents inlined as .mdc rules (no separate agent files)",
                "skills": "skills inlined as rule blocks",
            },
            "aider": {
                "mcp": "MCP servers not supported by aider",
                "agents": "agents have no aider equivalent — skipped",
                "settings": "only base rules synced (allowedTools not supported)",
                "skills": "skills have no aider equivalent — skipped",
            },
            "windsurf": {
                "mcp": "MCP servers not supported in .windsurfrules",
                "agents": "agents inlined as windsurf rules",
                "skills": "skills inlined as rule blocks",
            },
        }

        lines: list[str] = []

        for target_name, target_results in results.items():
            if target_name.startswith("_") or not isinstance(target_results, dict):
                continue

            target_gaps = _KNOWN_GAPS.get(target_name, {})
            target_lines: list[str] = []

            for config_type, result in target_results.items():
                if not isinstance(result, SyncResult):
                    continue

                # Items that failed or were fully skipped = capability gap
                total_items = result.synced + result.adapted + result.failed + result.skipped
                if total_items == 0:
                    continue

                failed_count = getattr(result, "failed", 0)
                adapted_count = getattr(result, "adapted", 0)
                skipped_count = getattr(result, "skipped", 0)
                synced_count = getattr(result, "synced", 0)

                if failed_count > 0 and synced_count == 0 and adapted_count == 0:
                    limitation = target_gaps.get(config_type, "no equivalent in target")
                    target_lines.append(
                        f"  ✗ {config_type}: {failed_count} item(s) dropped — {limitation}"
                    )
                elif adapted_count > 0:
                    limitation = target_gaps.get(config_type, "")
                    note = f" — {limitation}" if limitation else " (format translated)"
                    target_lines.append(
                        f"  ~ {config_type}: {adapted_count} item(s) approximated{note}"
                    )
                elif skipped_count == total_items and total_items > 0:
                    limitation = target_gaps.get(config_type, "no equivalent in target")
                    target_lines.append(
                        f"  · {config_type}: {skipped_count} item(s) skipped — {limitation}"
                    )

            # Add any known gaps for this target even if nothing was synced
            for config_type, limitation in target_gaps.items():
                if config_type not in target_results:
                    target_lines.append(
                        f"  · {config_type}: not synced — {limitation}"
                    )

            if target_lines:
                lines.append(f"\n{target_name.upper()} Capability Gaps:")
                lines.extend(target_lines)

        if not lines:
            return ""

        header = "\nHarness Capability Gap Report"
        footer = "\nRun /sync-matrix for a full feature compatibility matrix."
        return header + "\n" + "\n".join(lines) + footer

    def explain_settings_translation(self, target: str, settings: dict) -> str:
        """Return per-field translation notes for settings synced to a target harness.

        Shows exactly how each Claude Code settings field maps to the target,
        including field renames, format differences, and unsupported fields.

        Args:
            target: Target harness name (e.g., "codex", "gemini").
            settings: Claude Code settings dict (from source_data["settings"]).

        Returns:
            Formatted string with per-field translation notes. Empty if no
            relevant settings or no translation table for this target.
        """
        translations = self.SETTINGS_FIELD_TRANSLATIONS.get(target)
        if not translations or not settings:
            return ""

        lines = [f"\nSettings translation for {target.upper()}:"]
        any_note = False

        for field, value in settings.items():
            if field not in translations:
                continue
            target_field, note = translations[field]
            # Summarise value so the user knows which setting triggered this
            if isinstance(value, list):
                val_summary = f"[{len(value)} item(s)]"
            elif isinstance(value, dict):
                val_summary = f"{{{len(value)} key(s)}}"
            else:
                val_summary = repr(value)

            lines.append(
                f"  {field} {val_summary} → {target_field}: {note}"
            )
            any_note = True

        if not any_note:
            return ""

        return "\n".join(lines)

    def static_coverage_score(self, source_data: dict, targets: list[str]) -> dict[str, dict]:
        """Compute a 0-100 config coverage score per harness without running a sync.

        Uses a static capability matrix to estimate how much of the Claude Code
        config will successfully map to each target. This is the score shown in
        /sync-status to give users a quick fidelity signal without running the
        full sync engine.

        Score formula:
          - full support: 100 pts  (rules → rules, MCP → native MCP config)
          - partial/adapted: 70 pts (section syncs but with format translation)
          - no support: 0 pts      (section is dropped entirely)
        Weighted by section importance (rules=2x, mcp=1.5x, others=1x).

        Args:
            source_data: Output of SourceReader.discover_all().
            targets: List of target harness names to score.

        Returns:
            Dict mapping target_name -> {
                "score": int,        # 0-100
                "label": str,        # "excellent" | "good" | "fair" | "poor"
                "details": dict,     # {section: "full"|"partial"|"none"}
            }
        """
        # Static capability matrix: target -> {section: "full"|"partial"|"none"}
        # "full" = native support, "partial" = adapted, "none" = dropped
        _CAPABILITY: dict[str, dict[str, str]] = {
            "codex":    {"rules": "full",  "skills": "partial", "agents": "partial",
                         "commands": "partial", "mcp": "partial", "settings": "partial"},
            "gemini":   {"rules": "full",  "skills": "partial", "agents": "partial",
                         "commands": "partial", "mcp": "full",    "settings": "partial"},
            "opencode": {"rules": "full",  "skills": "full",    "agents": "partial",
                         "commands": "partial", "mcp": "full",    "settings": "partial"},
            "cursor":   {"rules": "full",  "skills": "partial", "agents": "partial",
                         "commands": "partial", "mcp": "full",    "settings": "none"},
            "aider":    {"rules": "full",  "skills": "none",    "agents": "none",
                         "commands": "none",    "mcp": "none",    "settings": "partial"},
            "windsurf": {"rules": "full",  "skills": "partial", "agents": "partial",
                         "commands": "partial", "mcp": "partial", "settings": "none"},
            "cline":    {"rules": "full",  "skills": "partial", "agents": "none",
                         "commands": "none",    "mcp": "full",    "settings": "partial"},
            "continue": {"rules": "full",  "skills": "none",    "agents": "none",
                         "commands": "none",    "mcp": "full",    "settings": "none"},
            "zed":      {"rules": "full",  "skills": "none",    "agents": "none",
                         "commands": "none",    "mcp": "full",    "settings": "none"},
            "neovim":   {"rules": "full",  "skills": "none",    "agents": "none",
                         "commands": "none",    "mcp": "full",    "settings": "partial"},
        }
        _SECTION_WEIGHTS: dict[str, float] = {
            "rules": 2.0, "mcp": 1.5, "skills": 1.5,
            "agents": 1.0, "commands": 1.0, "settings": 1.0,
        }
        _SUPPORT_POINTS: dict[str, float] = {"full": 100.0, "partial": 70.0, "none": 0.0}

        # Determine which source sections are non-empty
        active_sections = {
            s for s in _SECTION_WEIGHTS
            if source_data.get(s if s != "mcp" else "mcp_servers")
        }

        results: dict[str, dict] = {}
        for target in targets:
            caps = _CAPABILITY.get(target, {})
            weighted_sum = 0.0
            weight_total = 0.0
            details: dict[str, str] = {}

            for section in active_sections:
                support = caps.get(section, "full" if section == "rules" else "none")
                details[section] = support
                w = _SECTION_WEIGHTS.get(section, 1.0)
                weighted_sum += _SUPPORT_POINTS[support] * w
                weight_total += w

            score = round(weighted_sum / weight_total) if weight_total > 0 else 100
            if score >= 90:
                label = "excellent"
            elif score >= 75:
                label = "good"
            elif score >= 50:
                label = "fair"
            else:
                label = "poor"

            results[target] = {"score": score, "label": label, "details": details}

        return results

    def format_static_coverage(self, coverage: dict[str, dict]) -> str:
        """Format static coverage scores as a compact per-target summary.

        Args:
            coverage: Output of static_coverage_score().

        Returns:
            Formatted multi-line string for display in /sync-status.
        """
        if not coverage:
            return ""

        lines = ["\nConfig Coverage Scores", "=" * 40]
        for target, data in sorted(coverage.items()):
            score = data["score"]
            label = data["label"]
            bar_len = int(score / 5)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            lines.append(f"\n{target.upper():<12} {score:>3}/100  [{bar}]  {label}")

            # Show partial/none sections compactly
            partial = [s for s, v in data.get("details", {}).items() if v == "partial"]
            none_secs = [s for s, v in data.get("details", {}).items() if v == "none"]
            if partial:
                lines.append(f"  ~ adapted:  {', '.join(partial)}")
            if none_secs:
                lines.append(f"  ✗ dropped:  {', '.join(none_secs)}")

        lines.append("")
        return "\n".join(lines)

    def format_settings_translation_block(self, targets: list[str], settings: dict) -> str:
        """Format per-target settings translation notes into a single block.

        Args:
            targets: List of target harness names.
            settings: Claude Code settings dict.

        Returns:
            Formatted multi-target settings translation string.
        """
        if not settings:
            return ""

        sections: list[str] = []
        for target in sorted(targets):
            section = self.explain_settings_translation(target, settings)
            if section:
                sections.append(section)

        if not sections:
            return ""

        header = "\n" + "─" * 50 + "\nSettings Field Translation Notes"
        footer = "─" * 50
        return header + "\n".join(sections) + "\n" + footer

    def rank_by_value_lost(self, source_data: dict, targets: list[str]) -> list[dict]:
        """Rank feature×harness combinations by how much value the user is losing.

        Returns a list sorted highest-to-lowest by estimated value loss, so
        users can prioritize which gaps matter most to them. Each entry
        explains the gap and suggests a workaround.

        Value is computed as:
          count_of_items × fidelity_loss_factor × category_importance_weight

        Category importance weights (subjective, user-value focused):
          skills=1.5, agents=1.4, mcp=1.3, commands=1.1, settings=0.8

        Args:
            source_data: Output of SourceReader.discover_all().
            targets: List of target harness names to analyze.

        Returns:
            List of dicts sorted by value_lost descending, each with keys:
              - harness: Target harness name
              - feature: Feature category ("skills", "agents", etc.)
              - item_count: Number of items affected
              - fidelity: "none" | "partial"
              - value_lost: Numeric score (higher = more value lost)
              - headline: One-line description (e.g. "12 skills lost in Codex")
              - suggestion: Actionable tip for closing this gap
        """
        # Gap matrix: harness -> feature -> fidelity ("none" | "partial")
        _GAP_MATRIX: dict[str, dict[str, str]] = {
            "codex":    {"skills": "partial", "agents": "partial", "commands": "partial"},
            "gemini":   {"agents": "partial", "commands": "partial"},
            "opencode": {"agents": "partial", "commands": "partial", "mcp": "partial"},
            "cursor":   {"skills": "none", "agents": "none", "commands": "partial"},
            "aider":    {"skills": "none", "agents": "none", "commands": "none", "mcp": "none"},
            "windsurf": {"skills": "none", "agents": "none", "commands": "none"},
        }

        _IMPORTANCE: dict[str, float] = {
            "skills": 1.5,
            "agents": 1.4,
            "mcp":    1.3,
            "commands": 1.1,
            "settings": 0.8,
            "rules":  0.5,
        }

        _FIDELITY_LOSS: dict[str, float] = {"none": 1.0, "partial": 0.4}

        _SUGGESTIONS: dict[str, dict[str, str]] = {
            "skills": {
                "none":    "Use LLM rule translation (/sync-capabilities) to embed skill intent as rules",
                "partial": "Review translated skills in target — some nuance may be lost",
            },
            "agents": {
                "none":    "Describe agents as prose rules in CLAUDE.md for harnesses without agent support",
                "partial": "Check generated agent descriptions for completeness",
            },
            "commands": {
                "none":    "Document slash commands as workflow notes in CLAUDE.md",
                "partial": "Verify command hints are recognized in the target harness",
            },
            "mcp": {
                "none":    "Add MCP servers manually in the target harness; consider using /sync-mcp-health",
                "partial": "Some MCP fields may be dropped — verify server config after sync",
            },
            "settings": {
                "partial": "Review translated settings; use per-harness overrides for unsupported fields",
            },
        }

        counts: dict[str, int] = {
            "skills":   len(source_data.get("skills", {})),
            "agents":   len(source_data.get("agents", {})),
            "commands": len(source_data.get("commands", {})),
            "mcp":      len(source_data.get("mcp_servers", {})),
            "settings": 1 if source_data.get("settings") else 0,
        }

        entries: list[dict] = []
        for target in targets:
            gaps = _GAP_MATRIX.get(target, {})
            for feature, fidelity in gaps.items():
                count = counts.get(feature, 0)
                if count == 0:
                    continue
                loss_factor = _FIDELITY_LOSS.get(fidelity, 0.0)
                importance = _IMPORTANCE.get(feature, 1.0)
                value_lost = round(count * loss_factor * importance, 2)

                if fidelity == "none":
                    headline = f"{count} {feature} will NOT sync to {target}"
                else:
                    headline = f"{count} {feature} will lose fidelity in {target}"

                suggestion = _SUGGESTIONS.get(feature, {}).get(fidelity, "Review sync output manually")

                entries.append({
                    "harness":    target,
                    "feature":    feature,
                    "item_count": count,
                    "fidelity":   fidelity,
                    "value_lost": value_lost,
                    "headline":   headline,
                    "suggestion": suggestion,
                })

        entries.sort(key=lambda e: e["value_lost"], reverse=True)
        return entries

    def format_value_lost_ranking(self, source_data: dict, targets: list[str]) -> str:
        """Format the ranked value-loss list as a human-readable report.

        Args:
            source_data: Output of SourceReader.discover_all().
            targets: List of target harness names.

        Returns:
            Formatted string showing features ranked by value lost,
            with a suggestion for each gap.
        """
        ranked = self.rank_by_value_lost(source_data, targets)
        if not ranked:
            return "No capability gaps detected — all features sync with full fidelity."

        lines = [
            "Capability Gap Report — Ranked by Value Lost",
            "=" * 50,
            "",
            "Higher score = more CC functionality you lose in that harness.",
            "",
        ]

        for i, entry in enumerate(ranked, start=1):
            score_bar = "█" * min(int(entry["value_lost"] / 2), 20)
            lines.append(
                f"#{i:2d}  [{entry['value_lost']:5.1f}] {score_bar}"
            )
            lines.append(f"      {entry['headline']}")
            lines.append(f"      Tip: {entry['suggestion']}")
            lines.append("")

        total_lost = sum(e["value_lost"] for e in ranked)
        lines.append(f"Total value-loss score: {total_lost:.1f}")
        lines.append(
            "\nRun /sync-capabilities for detailed per-feature translation fidelity."
        )
        return "\n".join(lines)

    def calculate_parity_score(
        self,
        results: dict,
        source_data: dict,
    ) -> dict[str, dict]:
        """Calculate a single parity percentage per target harness.

        The parity score combines:
          - Coverage score (breadth): what fraction of source capability categories
            are represented in the target at all.
          - Fidelity score (depth): how faithfully items within each category
            are translated (direct sync vs adapted vs lost).

        Combined formula:
            parity = (coverage_score * 0.5) + (fidelity_score * 0.5)

        This gives a single 0-100 number per target that answers:
          "How faithfully does this harness reflect your Claude Code setup?"

        Args:
            results:     Dict from SyncOrchestrator.sync_all() (target -> SyncResult map).
            source_data: Output of SourceReader.discover_all().

        Returns:
            Dict mapping target_name -> {
                "parity": float,        # 0-100 combined parity score
                "coverage": float,      # 0-100 coverage sub-score
                "fidelity": float,      # 0-100 fidelity sub-score
                "grade": str,           # "A" | "B" | "C" | "D" | "F"
                "label": str,           # "excellent" | "good" | "fair" | "poor" | "critical"
            }
        """
        coverage_scores = self.calculate_coverage_score(results, source_data)
        fidelity_scores = self.calculate_fidelity_score(results)

        parity: dict[str, dict] = {}
        all_targets = set(coverage_scores) | set(fidelity_scores)

        for target in all_targets:
            cov = coverage_scores.get(target, {}).get("score", 100.0)
            fid = fidelity_scores.get(target, {}).get("overall", 100.0)
            combined = round((cov * 0.5) + (fid * 0.5), 1)

            if combined >= 90:
                grade, label = "A", "excellent"
            elif combined >= 75:
                grade, label = "B", "good"
            elif combined >= 60:
                grade, label = "C", "fair"
            elif combined >= 40:
                grade, label = "D", "poor"
            else:
                grade, label = "F", "critical"

            parity[target] = {
                "parity": combined,
                "coverage": round(cov, 1),
                "fidelity": round(fid, 1),
                "grade": grade,
                "label": label,
            }

        return parity

    def format_parity_scores(self, parity: dict[str, dict]) -> str:
        """Format parity scores as a compact harness comparison table.

        Args:
            parity: Output of calculate_parity_score().

        Returns:
            Formatted multi-line string.
        """
        if not parity:
            return "No parity data available."

        # Sort by parity score descending
        ranked = sorted(parity.items(), key=lambda x: x[1]["parity"], reverse=True)
        lines = [
            "Harness Parity Scores",
            "=" * 50,
            f"  {'Harness':<14} {'Parity':>7}  {'Coverage':>9}  {'Fidelity':>9}  Grade",
            "  " + "-" * 48,
        ]
        for target, scores in ranked:
            pct = scores["parity"]
            cov = scores["coverage"]
            fid = scores["fidelity"]
            grade = scores["grade"]
            bar_len = min(int(pct / 5), 20)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            lines.append(
                f"  {target:<14} {pct:6.1f}%  {cov:8.1f}%  {fid:8.1f}%   {grade}"
            )
        lines.append("")
        lines.append(
            "  Parity = 50% coverage (breadth) + 50% fidelity (translation depth)"
        )
        return "\n".join(lines)

    def has_issues(self, report: dict) -> bool:
        """
        Check if report contains adapted or failed items.

        Args:
            report: Dict from generate()

        Returns:
            True if any target has adapted or failed items (requires user attention)
            False if all items were synced directly or skipped
        """
        for target_report in report.values():
            if not isinstance(target_report, dict):
                continue

            summary = target_report.get('summary', {})
            if summary.get('total_adapted', 0) > 0 or summary.get('total_failed', 0) > 0:
                return True

        return False


# ---------------------------------------------------------------------------
# Harness Feature Gap Tracker (item 24)
# ---------------------------------------------------------------------------

import json as _json
import time as _time


@dataclass
class _TrackedGap:
    """A single tracked capability gap for a harness."""
    target: str
    feature: str
    description: str
    upstream_url: str
    logged_at: str   # ISO 8601 timestamp
    resolved: bool = False

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "feature": self.feature,
            "description": self.description,
            "upstream_url": self.upstream_url,
            "logged_at": self.logged_at,
            "resolved": self.resolved,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "_TrackedGap":
        return cls(
            target=d["target"],
            feature=d["feature"],
            description=d["description"],
            upstream_url=d.get("upstream_url", ""),
            logged_at=d.get("logged_at", ""),
            resolved=d.get("resolved", False),
        )


class GapTracker:
    """Track and persist harness capability gaps with upstream issue links.

    When HarnessSync detects a capability that can't be fully synced, users
    can log it here as a tracked gap. Gaps are stored in
    ``~/.harnesssync/gaps.json`` and can be reviewed, filtered, and marked
    resolved as upstream harnesses add feature support.

    Usage::

        tracker = GapTracker()
        tracker.log_gap(
            target="codex",
            feature="skills",
            description="Codex has no native skill/command system — skills are dropped",
            upstream_url="https://github.com/openai/codex/issues/1234",
        )
        print(tracker.format_gap_report())
    """

    def __init__(self, gaps_dir: Path | None = None) -> None:
        self._gaps_path = (gaps_dir or (Path.home() / ".harnesssync")) / "gaps.json"

    def _load(self) -> list[_TrackedGap]:
        try:
            data = _json.loads(self._gaps_path.read_text(encoding="utf-8"))
            return [_TrackedGap.from_dict(d) for d in data]
        except (OSError, _json.JSONDecodeError, KeyError):
            return []

    def _save(self, gaps: list[_TrackedGap]) -> None:
        self._gaps_path.parent.mkdir(parents=True, exist_ok=True)
        self._gaps_path.write_text(
            _json.dumps([g.to_dict() for g in gaps], indent=2),
            encoding="utf-8",
        )

    def log_gap(
        self,
        target: str,
        feature: str,
        description: str,
        upstream_url: str = "",
    ) -> _TrackedGap:
        """Log a new capability gap.

        If a gap with the same (target, feature) already exists and is not
        resolved, returns the existing entry rather than creating a duplicate.

        Args:
            target:       Target harness name (e.g. "codex").
            feature:      Feature category (e.g. "skills", "mcp", "agents").
            description:  Human-readable description of what's missing.
            upstream_url: Link to upstream issue tracker (optional).

        Returns:
            The new or existing _TrackedGap entry.
        """
        gaps = self._load()
        # Avoid duplicates for active (unresolved) gaps
        for existing in gaps:
            if existing.target == target and existing.feature == feature and not existing.resolved:
                return existing

        gap = _TrackedGap(
            target=target,
            feature=feature,
            description=description,
            upstream_url=upstream_url,
            logged_at=_time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
        gaps.append(gap)
        self._save(gaps)
        return gap

    def get_gaps(
        self,
        target: str | None = None,
        include_resolved: bool = False,
    ) -> list[_TrackedGap]:
        """Retrieve tracked gaps, optionally filtered by target.

        Args:
            target:           Filter by harness name (None = all targets).
            include_resolved: Include resolved gaps (default: active only).

        Returns:
            List of _TrackedGap entries.
        """
        gaps = self._load()
        if not include_resolved:
            gaps = [g for g in gaps if not g.resolved]
        if target:
            gaps = [g for g in gaps if g.target == target]
        return gaps

    def resolve_gap(self, target: str, feature: str) -> bool:
        """Mark a tracked gap as resolved.

        Args:
            target:  Target harness name.
            feature: Feature category.

        Returns:
            True if a gap was found and marked resolved; False if not found.
        """
        gaps = self._load()
        found = False
        for gap in gaps:
            if gap.target == target and gap.feature == feature and not gap.resolved:
                gap.resolved = True
                found = True
        if found:
            self._save(gaps)
        return found

    def format_gap_report(
        self,
        target: str | None = None,
        include_resolved: bool = False,
    ) -> str:
        """Format tracked gaps as a readable report.

        Args:
            target:           Filter by harness (None = all).
            include_resolved: Show resolved gaps too.

        Returns:
            Formatted multi-line report.
        """
        gaps = self.get_gaps(target=target, include_resolved=include_resolved)
        if not gaps:
            label = f"for {target}" if target else "across all targets"
            return f"No active capability gaps tracked {label}."

        by_target: dict[str, list[_TrackedGap]] = {}
        for gap in gaps:
            by_target.setdefault(gap.target, []).append(gap)

        lines = [
            f"Tracked Capability Gaps — {len(gaps)} active",
            "=" * 50,
        ]
        for tgt, tgt_gaps in sorted(by_target.items()):
            lines.append(f"\n  {tgt.upper()} ({len(tgt_gaps)} gap{'s' if len(tgt_gaps) != 1 else ''}):")
            for g in tgt_gaps:
                status = "[resolved]" if g.resolved else "[open]"
                lines.append(f"    {status} {g.feature}: {g.description}")
                if g.upstream_url:
                    lines.append(f"      ↳ {g.upstream_url}")
                if g.logged_at:
                    lines.append(f"      logged: {g.logged_at}")
        return "\n".join(lines)
