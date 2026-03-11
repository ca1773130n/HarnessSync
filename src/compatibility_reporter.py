from __future__ import annotations

"""
Compatibility reporting for sync operations.

Analyzes sync results to produce per-target breakdown of synced/adapted/skipped/failed
items with explanations. Implements SAF-04 from Phase 5 safety validation.

Based on aggregate SyncResult data for compatibility reporting (existing adapter pattern).
"""

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
