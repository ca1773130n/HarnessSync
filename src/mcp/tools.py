"""Tool handler bridge between MCP protocol and SyncOrchestrator.

Each handler validates input, invokes orchestrator, and formats
MCP tool results. Uses deferred imports for SyncOrchestrator
to match project convention (Decision #38).
"""

import json
import logging
import os
from pathlib import Path

from src.mcp.schemas import VALIDATORS

logger = logging.getLogger(__name__)

# Dispatch dict mapping tool names to handler method names
TOOL_HANDLERS = {
    "sync_all": "handle_sync_all",
    "sync_target": "handle_sync_target",
    "get_status": "handle_get_status",
}


class ToolHandlers:
    """Bridge layer between MCP protocol and SyncOrchestrator."""

    def __init__(self, project_dir: Path = None):
        """Initialize tool handlers.

        Args:
            project_dir: Project root directory. Defaults to
                CLAUDE_PROJECT_DIR env var or current working directory.
        """
        if project_dir is None:
            project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
        self.project_dir = project_dir

    def handle_sync_all(self, arguments: dict) -> dict:
        """Handle sync_all tool invocation.

        Args:
            arguments: Raw tool arguments (may be None).

        Returns:
            MCP tool result dict with content and isError flag.
        """
        try:
            params = VALIDATORS["sync_all"](arguments)
        except ValueError as e:
            return _tool_error(str(e))

        try:
            from src.orchestrator import SyncOrchestrator

            orchestrator = SyncOrchestrator(
                project_dir=self.project_dir,
                scope="all",
                dry_run=params["dry_run"],
                allow_secrets=params["allow_secrets"],
            )
            results = orchestrator.sync_all()
            structured = _format_results(results)
            return _tool_success(json.dumps(structured, indent=2))
        except Exception as e:
            logger.exception("sync_all failed")
            return _tool_error(f"Sync failed: {type(e).__name__}: {e}")

    def handle_sync_target(self, arguments: dict) -> dict:
        """Handle sync_target tool invocation.

        Runs full sync but filters results to the requested target only.

        Args:
            arguments: Raw tool arguments with required 'target' field.

        Returns:
            MCP tool result dict with content and isError flag.
        """
        try:
            params = VALIDATORS["sync_target"](arguments)
        except ValueError as e:
            return _tool_error(str(e))

        try:
            from src.orchestrator import SyncOrchestrator

            orchestrator = SyncOrchestrator(
                project_dir=self.project_dir,
                scope="all",
                dry_run=params["dry_run"],
                allow_secrets=params["allow_secrets"],
            )
            results = orchestrator.sync_all()
            structured = _format_results(results, filter_target=params["target"])
            return _tool_success(json.dumps(structured, indent=2))
        except Exception as e:
            logger.exception("sync_target failed")
            return _tool_error(f"Sync failed: {type(e).__name__}: {e}")

    def handle_get_status(self, arguments: dict) -> dict:
        """Handle get_status tool invocation.

        Executes immediately without queuing (no sync lock needed).

        Args:
            arguments: Raw tool arguments (ignored).

        Returns:
            MCP tool result dict with content and isError flag.
        """
        try:
            VALIDATORS["get_status"](arguments)
        except ValueError as e:
            return _tool_error(str(e))

        try:
            from src.orchestrator import SyncOrchestrator

            orchestrator = SyncOrchestrator(
                project_dir=self.project_dir,
                scope="all",
            )
            status = orchestrator.get_status()
            return _tool_success(json.dumps(status, indent=2, default=str))
        except Exception as e:
            logger.exception("get_status failed")
            return _tool_error(f"Status check failed: {type(e).__name__}: {e}")


def _format_results(results: dict, filter_target: str = None) -> dict:
    """Format orchestrator results into structured JSON.

    Args:
        results: Raw orchestrator results dict.
        filter_target: If set, only include this target's results.

    Returns:
        Structured result dict with status, targets, warnings.
    """
    from src.adapters.result import SyncResult

    # Check for blocked sync
    if results.get("_blocked"):
        return {
            "status": "blocked",
            "blocked_reason": results.get("_reason", "unknown"),
            "warnings": [results.get("_warnings", "Sync blocked")],
            "targets": {},
        }

    targets = {}
    warnings = []

    for target, target_results in results.items():
        if target.startswith("_"):
            continue
        if filter_target and target != filter_target:
            continue

        synced = 0
        skipped = 0
        failed = 0
        errors = []

        if isinstance(target_results, dict):
            for config_type, result in target_results.items():
                if isinstance(result, SyncResult):
                    synced += result.synced
                    skipped += result.skipped
                    failed += result.failed
                    errors.extend(result.failed_files)

        targets[target] = {
            "synced": synced,
            "skipped": skipped,
            "failed": failed,
            "errors": errors,
        }

    # Determine overall status
    total_failed = sum(t["failed"] for t in targets.values())
    total_synced = sum(t["synced"] for t in targets.values())

    if total_failed == 0:
        status = "success"
    elif total_synced > 0 and total_failed > 0:
        status = "partial"
    else:
        status = "error"

    # Collect warnings
    if "_conflicts" in results:
        warnings.append("Manual edits detected in target configs (conflicts)")
    if "_compatibility_report" in results:
        warnings.append(results["_compatibility_report"])

    return {
        "status": status,
        "targets": targets,
        "warnings": warnings,
        "compatibility_report": results.get("_compatibility_report"),
    }


def _tool_success(text: str) -> dict:
    """Create MCP tool success result."""
    return {
        "content": [{"type": "text", "text": text}],
        "isError": False,
    }


def _tool_error(text: str) -> dict:
    """Create MCP tool error result."""
    return {
        "content": [{"type": "text", "text": text}],
        "isError": True,
    }
