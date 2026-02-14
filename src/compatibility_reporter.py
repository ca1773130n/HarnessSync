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
