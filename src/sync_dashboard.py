from __future__ import annotations

"""Live Sync Dashboard — local HTTP status web UI.

Serves a real-time dashboard on localhost showing:
  - Per-harness sync status (last sync time, success/failure)
  - Drift indicators (files manually edited since last sync)
  - Health scores per harness
  - MCP server reachability

Default: http://127.0.0.1:7842

Configuration in ``~/.harnesssync/dashboard.json``:

    {
        "host": "127.0.0.1",
        "port": 7842,
        "auto_refresh_seconds": 30
    }

Usage::

    # Start dashboard server
    server = SyncDashboard(project_dir=Path.cwd())
    server.start()   # non-blocking, starts background thread
    print(f"Dashboard: http://{server.host}:{server.port}")

    # Stop server
    server.stop()

    # Or run from command line:
    #   python -m src.sync_dashboard

The dashboard serves a self-contained HTML page with embedded CSS/JS.
No external dependencies or CDN requests — works fully offline.
"""

import json
import os
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from src.utils.constants import EXTENDED_TARGETS
from src.utils.logger import Logger

_CONFIG_FILE = Path.home() / ".harnesssync" / "dashboard.json"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7842
_DEFAULT_REFRESH = 30


def _load_dashboard_config() -> dict:
    config: dict = {
        "host": DEFAULT_HOST,
        "port": DEFAULT_PORT,
        "auto_refresh_seconds": _DEFAULT_REFRESH,
    }
    if _CONFIG_FILE.exists():
        try:
            data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
            config.update({k: v for k, v in data.items() if k in config})
        except (OSError, json.JSONDecodeError):
            pass
    # Environment overrides
    if os.environ.get("HARNESSSYNC_DASHBOARD_PORT"):
        try:
            config["port"] = int(os.environ["HARNESSSYNC_DASHBOARD_PORT"])
        except ValueError:
            pass
    return config


def _gather_status(project_dir: Path) -> dict:
    """Gather sync status for all known targets.

    Returns a dict suitable for JSON serialization and HTML rendering.
    """
    status: dict = {
        "project_dir": str(project_dir),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "targets": {},
        "mcp_health": {},
        "drift": [],
        "errors": [],
    }

    # --- State manager: last sync info ---
    try:
        from src.state_manager import StateManager
        sm = StateManager(project_dir=project_dir)
        all_status = sm.get_all_status()
        for target in EXTENDED_TARGETS:
            t_status = all_status.get(target, {})
            last_sync = t_status.get("last_sync")
            last_hash = t_status.get("source_hash", "")
            status["targets"][target] = {
                "last_sync": last_sync,
                "source_hash": last_hash[:8] if last_hash else "",
                "synced": t_status.get("synced_count", 0),
                "skipped": t_status.get("skipped_count", 0),
                "failed": t_status.get("failed_count", 0),
                "health_score": t_status.get("health_score"),
                "health_label": t_status.get("health_label", ""),
            }
    except Exception as e:
        status["errors"].append(f"StateManager: {e}")

    # --- Conflict detector: drift detection ---
    try:
        from src.conflict_detector import ConflictDetector
        cd = ConflictDetector(project_dir=project_dir)
        drift_info = cd.detect_all_drift()
        if isinstance(drift_info, list):
            status["drift"] = [
                {"target": d.get("target", ""), "file": d.get("file", ""), "type": d.get("type", "modified")}
                for d in drift_info
            ]
        elif isinstance(drift_info, dict):
            for target, files in drift_info.items():
                for f in (files if isinstance(files, list) else []):
                    status["drift"].append({"target": target, "file": str(f), "type": "modified"})
    except Exception as e:
        status["errors"].append(f"ConflictDetector: {e}")

    # --- MCP reachability ---
    try:
        from src.mcp_reachability import McpReachabilityChecker
        from src.source_reader import SourceReader
        reader = SourceReader(project_dir=project_dir)
        source_data = reader.discover_all()
        mcp_servers = source_data.get("mcp_servers", {})
        if mcp_servers:
            checker = McpReachabilityChecker()
            reach_results = checker.check_all(mcp_servers)
            for name, result in reach_results.items():
                status["mcp_health"][name] = {
                    "reachable": getattr(result, "reachable", True),
                    "latency_ms": getattr(result, "latency_ms", None),
                    "error": getattr(result, "error", ""),
                }
    except Exception as e:
        status["errors"].append(f"McpReachability: {e}")

    # --- Capability matrix ---
    try:
        from src.capability_matrix import build_matrix, STATUS_FULL, STATUS_APPROX, STATUS_NONE
        from src.source_reader import SourceReader
        try:
            reader  # reuse if already defined above
        except NameError:
            reader = SourceReader(project_dir=project_dir)
        try:
            source_data  # reuse if already defined above
        except NameError:
            source_data = reader.discover_all()
        matrix = build_matrix(source_data, project_dir=project_dir)
        status["capability_matrix"] = {
            "targets": matrix.targets,
            "rows": [
                {
                    "category": row.category,
                    "item_name": row.item_name,
                    "cells": {
                        t: {"status": cell.status, "note": cell.note}
                        for t, cell in row.cells.items()
                    },
                }
                for row in matrix.rows
            ],
        }
    except Exception as e:
        status["errors"].append(f"CapabilityMatrix: {e}")

    return status


def _render_html(status: dict, refresh_seconds: int) -> str:
    """Render a self-contained HTML dashboard page."""
    targets = status.get("targets", {})
    drift = status.get("drift", [])
    mcp_health = status.get("mcp_health", {})
    generated_at = status.get("generated_at", "")
    project_dir = status.get("project_dir", "")
    errors = status.get("errors", [])

    capability_matrix_data = status.get("capability_matrix", {})
    drift_targets: set[str] = {d["target"] for d in drift}

    def _capability_matrix_section() -> str:
        """Render the capability matrix as an HTML table section."""
        if not capability_matrix_data or not capability_matrix_data.get("rows"):
            return ""
        cap_targets = capability_matrix_data.get("targets", [])
        rows = capability_matrix_data.get("rows", [])
        _STATUS_SYMBOL = {"full": "✓", "approx": "~", "none": "✗"}
        _STATUS_CLASS = {"full": "cap-full", "approx": "cap-approx", "none": "cap-none"}
        header_cols = "".join(f"<th>{t}</th>" for t in cap_targets)
        html_rows = []
        current_cat = None
        for row in rows:
            if row["category"] != current_cat:
                current_cat = row["category"]
                span = len(cap_targets) + 1
                html_rows.append(
                    f'<tr class="cat-header"><td colspan="{span}">'
                    f'[{current_cat.upper()}]</td></tr>'
                )
            cells = "".join(
                f'<td class="{_STATUS_CLASS.get(row["cells"].get(t, {}).get("status", "none"), "cap-none")}"'
                f' title="{row["cells"].get(t, {}).get("note", "")}">'
                f'{_STATUS_SYMBOL.get(row["cells"].get(t, {}).get("status", "none"), "✗")}'
                f'</td>'
                for t in cap_targets
            )
            html_rows.append(
                f"<tr><td class='item-name'>{row['item_name']}</td>{cells}</tr>"
            )
        table_html = "\n".join(html_rows)
        return f"""
<h2>Capability Matrix</h2>
<p style="color:var(--muted);font-size:0.8rem;margin-bottom:0.5rem">
  ✓ Full &nbsp; ~ Approximate &nbsp; ✗ Not supported — hover cells for details
</p>
<div style="overflow-x:auto">
<table class="cap-table">
<thead><tr><th>Config Item</th>{header_cols}</tr></thead>
<tbody>{table_html}</tbody>
</table>
</div>"""

    def _target_rows() -> str:
        rows = []
        for target in EXTENDED_TARGETS:
            info = targets.get(target, {})
            last_sync = info.get("last_sync") or "—"
            if last_sync and last_sync != "—":
                try:
                    dt = datetime.fromisoformat(last_sync)
                    last_sync = dt.strftime("%Y-%m-%d %H:%M")
                except ValueError:
                    pass
            score = info.get("health_score")
            label = info.get("health_label", "")
            score_cell = f"{score}/100 {label}" if score is not None else "—"

            has_drift = target in drift_targets
            drift_cell = '<span class="drift-badge">DRIFT</span>' if has_drift else '<span class="ok-badge">ok</span>'

            synced = info.get("synced", 0)
            failed = info.get("failed", 0)
            rows.append(
                f"<tr>"
                f'<td class="target-name">{target}</td>'
                f"<td>{last_sync}</td>"
                f"<td>{score_cell}</td>"
                f'<td class="count-cell">{synced}</td>'
                f'<td class="count-cell fail-count">{failed}</td>'
                f"<td>{drift_cell}</td>"
                f"</tr>"
            )
        return "\n".join(rows)

    def _mcp_rows() -> str:
        if not mcp_health:
            return '<tr><td colspan="3">No MCP servers configured</td></tr>'
        rows = []
        for name, info in sorted(mcp_health.items()):
            reachable = info.get("reachable", True)
            latency = info.get("latency_ms")
            error = info.get("error", "")
            status_cell = (
                '<span class="ok-badge">✓ reachable</span>'
                if reachable
                else f'<span class="drift-badge">✗ unreachable</span>'
            )
            lat_cell = f"{latency:.0f} ms" if latency is not None else "—"
            rows.append(
                f"<tr><td>{name}</td><td>{status_cell}</td>"
                f"<td>{lat_cell}</td></tr>"
            )
            if error:
                rows.append(f'<tr><td colspan="3" class="error-row">{error}</td></tr>')
        return "\n".join(rows)

    def _drift_rows() -> str:
        if not drift:
            return '<tr><td colspan="3"><span class="ok-badge">No drift detected</span></td></tr>'
        rows = []
        for d in drift:
            rows.append(
                f"<tr>"
                f'<td>{d.get("target", "")}</td>'
                f'<td>{d.get("file", "")}</td>'
                f'<td>{d.get("type", "modified")}</td>'
                f"</tr>"
            )
        return "\n".join(rows)

    errors_html = ""
    if errors:
        items = "".join(f"<li>{e}</li>" for e in errors)
        errors_html = f'<div class="error-box"><b>Errors gathering status:</b><ul>{items}</ul></div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{refresh_seconds}">
<title>HarnessSync Dashboard</title>
<style>
  :root {{
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #c9d1d9; --muted: #8b949e; --accent: #58a6ff;
    --ok: #3fb950; --warn: #d29922; --fail: #f85149;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; padding: 1.5rem; }}
  h1 {{ color: var(--accent); margin-bottom: 0.25rem; font-size: 1.4rem; }}
  .meta {{ color: var(--muted); font-size: 0.8rem; margin-bottom: 1.5rem; }}
  h2 {{ font-size: 1rem; color: var(--muted); margin: 1.5rem 0 0.5rem; text-transform: uppercase; letter-spacing: 0.05em; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--surface); border-radius: 6px; overflow: hidden; }}
  th, td {{ padding: 0.55rem 0.75rem; text-align: left; border-bottom: 1px solid var(--border); font-size: 0.88rem; }}
  th {{ color: var(--muted); font-weight: 600; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; }}
  tr:last-child td {{ border-bottom: none; }}
  .target-name {{ font-weight: 600; color: var(--accent); }}
  .count-cell {{ text-align: center; }}
  .fail-count {{ color: var(--fail); }}
  .ok-badge {{ color: var(--ok); font-weight: 600; }}
  .drift-badge {{ color: var(--fail); font-weight: 600; }}
  .error-box {{ background: #2d1515; border: 1px solid var(--fail); border-radius: 4px; padding: 0.75rem; margin-bottom: 1rem; font-size: 0.85rem; }}
  .error-row {{ color: var(--muted); font-size: 0.8rem; }}
  .refresh-note {{ color: var(--muted); font-size: 0.75rem; margin-top: 1.5rem; }}
  .cap-table td, .cap-table th {{ text-align: center; padding: 0.45rem 0.6rem; }}
  .cap-table td.item-name {{ text-align: left; font-size: 0.83rem; }}
  .cap-table tr.cat-header td {{ text-align: left; background: #1c2230; color: var(--accent); font-size: 0.78rem; font-weight: 600; padding: 0.3rem 0.75rem; }}
  .cap-full {{ color: var(--ok); font-weight: 700; }}
  .cap-approx {{ color: var(--warn); font-weight: 700; }}
  .cap-none {{ color: var(--muted); }}
</style>
</head>
<body>
<h1>HarnessSync Live Dashboard</h1>
<p class="meta">Project: {project_dir} &nbsp;·&nbsp; Generated: {generated_at}</p>
{errors_html}

<h2>Harness Sync Status</h2>
<table>
<thead><tr>
  <th>Harness</th><th>Last Sync</th><th>Health</th>
  <th>Synced</th><th>Failed</th><th>Drift</th>
</tr></thead>
<tbody>
{_target_rows()}
</tbody>
</table>

<h2>MCP Server Health</h2>
<table>
<thead><tr><th>Server</th><th>Status</th><th>Latency</th></tr></thead>
<tbody>{_mcp_rows()}</tbody>
</table>

<h2>Drift Details</h2>
<table>
<thead><tr><th>Harness</th><th>File</th><th>Type</th></tr></thead>
<tbody>{_drift_rows()}</tbody>
</table>

{_capability_matrix_section()}

<p class="refresh-note">Auto-refresh every {refresh_seconds} seconds &nbsp;·&nbsp;
<a href="/" style="color:var(--accent)">Refresh now</a></p>
</body>
</html>"""


class _DashboardHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the sync dashboard."""

    project_dir: Path = Path.cwd()
    refresh_seconds: int = _DEFAULT_REFRESH

    def do_GET(self) -> None:  # noqa: N802
        from urllib.parse import urlparse
        parsed = urlparse(self.path)

        if parsed.path == "/status.json":
            status = _gather_status(self.project_dir)
            body = json.dumps(status, indent=2, default=str).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif parsed.path in ("/", "/index.html"):
            status = _gather_status(self.project_dir)
            html = _render_html(status, self.refresh_seconds)
            body = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: N802
        pass  # Suppress default HTTP server logs


class SyncDashboard:
    """Local HTTP dashboard server for real-time sync status.

    Args:
        project_dir: Project root to gather status from.
        host: Bind address (default: 127.0.0.1).
        port: Port to listen on (default: from config or 7842).
        auto_refresh_seconds: HTML meta-refresh interval.
    """

    def __init__(
        self,
        project_dir: Path | None = None,
        host: str | None = None,
        port: int | None = None,
        auto_refresh_seconds: int | None = None,
    ) -> None:
        cfg = _load_dashboard_config()
        self.project_dir = project_dir or Path.cwd()
        self.host = host or cfg["host"]
        self.port = port or cfg["port"]
        self.refresh_seconds = auto_refresh_seconds or cfg["auto_refresh_seconds"]
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.logger = Logger()

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        """Start the dashboard in a background daemon thread."""
        if self._server is not None:
            return

        # Build a handler class with project_dir baked in
        project_dir = self.project_dir
        refresh = self.refresh_seconds

        class Handler(_DashboardHandler):
            pass

        Handler.project_dir = project_dir
        Handler.refresh_seconds = refresh

        self._server = HTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="harnesssync-dashboard",
        )
        self._thread.start()
        self.logger.info(f"HarnessSync dashboard running at {self.url}")

    def stop(self) -> None:
        """Stop the dashboard server."""
        if self._server:
            self._server.shutdown()
            self._server = None
        self._thread = None

    def is_running(self) -> bool:
        return self._server is not None and (
            self._thread is not None and self._thread.is_alive()
        )


def run_dashboard(
    project_dir: Path | None = None,
    host: str | None = None,
    port: int | None = None,
    auto_refresh_seconds: int = _DEFAULT_REFRESH,
) -> None:
    """Start the dashboard and block until KeyboardInterrupt.

    Intended for CLI usage: ``python -m src.sync_dashboard``.
    """
    import signal
    import sys

    dashboard = SyncDashboard(
        project_dir=project_dir,
        host=host,
        port=port,
        auto_refresh_seconds=auto_refresh_seconds,
    )
    dashboard.start()
    print(f"HarnessSync Dashboard: {dashboard.url}")
    print("Press Ctrl+C to stop.")

    def _handle_signal(sig: int, frame: object) -> None:
        print("\nShutting down dashboard...")
        dashboard.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Block main thread
    if dashboard._thread:
        dashboard._thread.join()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="HarnessSync Live Sync Dashboard")
    parser.add_argument("--host", default=None, help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="Port (default: 7842)")
    parser.add_argument("--refresh", type=int, default=_DEFAULT_REFRESH, help="Auto-refresh interval in seconds")
    parser.add_argument("--project-dir", default=".", help="Project root directory")
    args = parser.parse_args()

    run_dashboard(
        project_dir=Path(args.project_dir).resolve(),
        host=args.host,
        port=args.port,
        auto_refresh_seconds=args.refresh,
    )
