from __future__ import annotations

"""Incoming webhook HTTP server for remote sync triggering.

Exposes an HTTP endpoint that triggers a HarnessSync sync operation when
called — enabling integration with CI systems, Zapier, or custom tooling
without SSH access to the developer's machine.

The server listens on a configurable port (default: 8765) and accepts:

    POST /sync
    Content-Type: application/json
    X-HarnessSync-Token: <shared-secret>

    {
        "scope": "all",          // optional: "user" | "project" | "all"
        "project_dir": "/path",  // optional: defaults to cwd at startup
        "dry_run": false          // optional: preview without writing
    }

Response (200 OK):
    {
        "status": "success" | "partial" | "failed",
        "targets_synced": ["codex", "gemini"],
        "totals": {"synced": 5, "skipped": 2, "failed": 0}
    }

Authentication:
    Set HARNESSSYNC_WEBHOOK_TOKEN env var or pass --token to set the shared secret.
    Requests without a matching X-HarnessSync-Token header are rejected (403).
    If no token is configured, authentication is disabled (development mode only).

Configuration in ~/.harnesssync/webhook_server.json:
    {
        "host": "127.0.0.1",
        "port": 8765,
        "token": "your-shared-secret",
        "allowed_project_dirs": ["/path/to/project"]
    }
"""

import hashlib
import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from src.utils.logger import Logger


# Default server configuration
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
_CONFIG_FILE = Path.home() / ".harnesssync" / "webhook_server.json"


def _load_server_config() -> dict:
    """Load webhook server configuration from file or environment.

    Returns:
        Dict with host, port, token, and allowed_project_dirs.
    """
    config: dict = {
        "host": DEFAULT_HOST,
        "port": DEFAULT_PORT,
        "token": os.environ.get("HARNESSSYNC_WEBHOOK_TOKEN", ""),
        "allowed_project_dirs": [],
    }
    if _CONFIG_FILE.exists():
        try:
            data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
            config.update({k: v for k, v in data.items() if k in config})
        except (OSError, json.JSONDecodeError):
            pass
    return config


def _constant_time_compare(a: str, b: str) -> bool:
    """Compare two strings in constant time to prevent timing attacks."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _build_handler(project_dir: Path, token: str, allowed_dirs: list[str], logger: Logger):
    """Factory that creates a request handler class with injected config.

    Using a factory avoids BaseHTTPRequestHandler's requirement that handlers
    be instantiated per-request without constructor arguments.

    Args:
        project_dir: Default project directory for syncs.
        token: Required auth token (empty = disabled).
        allowed_dirs: Whitelist of allowed project directories.
        logger: Logger instance.

    Returns:
        A BaseHTTPRequestHandler subclass.
    """

    class SyncRequestHandler(BaseHTTPRequestHandler):
        """Handles incoming /sync webhook requests."""

        _project_dir = project_dir
        _token = token
        _allowed_dirs = allowed_dirs
        _logger = logger

        def log_message(self, format, *args) -> None:  # noqa: A002
            """Suppress default HTTP server request logging (use our logger)."""
            self._logger.info(f"webhook: {format % args}")

        def _send_json(self, status: int, data: dict) -> None:
            body = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authenticate(self) -> bool:
            """Return True if the request is authenticated."""
            if not self._token:
                return True  # Auth disabled
            provided = self.headers.get("X-HarnessSync-Token", "")
            return _constant_time_compare(provided, self._token)

        def do_GET(self) -> None:
            """Handle GET /health for liveness checks."""
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._send_json(200, {"status": "ok", "service": "harnesssync-webhook"})
            else:
                self._send_json(404, {"error": "Not found"})

        def do_POST(self) -> None:
            """Handle POST /sync to trigger a sync operation."""
            parsed = urlparse(self.path)
            if parsed.path != "/sync":
                self._send_json(404, {"error": "Not found"})
                return

            if not self._authenticate():
                self._send_json(403, {"error": "Unauthorized — missing or invalid token"})
                return

            # Read request body
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length > 0 else b"{}"
            try:
                params = json.loads(body)
            except json.JSONDecodeError:
                self._send_json(400, {"error": "Invalid JSON body"})
                return

            # Resolve project directory
            requested_dir = params.get("project_dir")
            if requested_dir:
                req_path = Path(requested_dir).resolve()
                # Security: only allow explicitly whitelisted directories
                if self._allowed_dirs:
                    allowed_resolved = [Path(d).resolve() for d in self._allowed_dirs]
                    if req_path not in allowed_resolved:
                        self._send_json(403, {
                            "error": f"Project directory not in allowed list: {req_path}"
                        })
                        return
                sync_dir = req_path
            else:
                sync_dir = self._project_dir

            scope = params.get("scope", "all")
            dry_run = bool(params.get("dry_run", False))

            # Run sync
            try:
                from src.orchestrator import SyncOrchestrator
                orchestrator = SyncOrchestrator(
                    project_dir=sync_dir,
                    scope=scope,
                    dry_run=dry_run,
                )
                results = orchestrator.sync_all()
                self._send_json(200, _summarize_results(results, dry_run=dry_run))
            except Exception as exc:
                self._logger.warn(f"Webhook sync failed: {exc}")
                self._send_json(500, {"error": str(exc), "status": "failed"})

    return SyncRequestHandler


def _summarize_results(results: dict, dry_run: bool = False) -> dict:
    """Build a JSON-serializable summary of sync results.

    Args:
        results: Dict from SyncOrchestrator.sync_all().
        dry_run: Whether this was a dry-run.

    Returns:
        Summary dict with status, targets_synced, and totals.
    """
    from src.adapters.result import SyncResult

    totals = {"synced": 0, "skipped": 0, "failed": 0}
    targets_synced: list[str] = []

    for target, target_results in results.items():
        if target.startswith("_") or not isinstance(target_results, dict):
            continue
        t_synced = t_failed = 0
        for config_type, result in target_results.items():
            if isinstance(result, SyncResult):
                totals["synced"] += result.synced
                totals["skipped"] += result.skipped
                totals["failed"] += result.failed
                t_synced += result.synced
                t_failed += result.failed
        if t_synced > 0 or (t_synced == 0 and t_failed == 0):
            targets_synced.append(target)

    status = "failed" if totals["failed"] > 0 and totals["synced"] == 0 else (
        "partial" if totals["failed"] > 0 else "success"
    )

    return {
        "status": status,
        "dry_run": dry_run,
        "targets_synced": targets_synced,
        "totals": totals,
    }


class WebhookServer:
    """HTTP server that triggers HarnessSync on incoming webhook calls.

    Usage:
        server = WebhookServer(project_dir=Path("."))
        server.start()          # Runs in background thread
        server.stop()           # Graceful shutdown
    """

    def __init__(
        self,
        project_dir: Path | None = None,
        host: str | None = None,
        port: int | None = None,
        token: str | None = None,
        logger: Logger | None = None,
    ):
        """Initialize the webhook server.

        Args:
            project_dir: Default project directory for syncs (uses cwd if None).
            host: Bind address (default: 127.0.0.1 — loopback only for security).
            port: Port to listen on (default: 8765).
            token: Auth token (default: HARNESSSYNC_WEBHOOK_TOKEN env var).
            logger: Logger instance.
        """
        file_config = _load_server_config()
        self.project_dir = project_dir or Path.cwd()
        self.host = host or file_config["host"]
        self.port = port or file_config["port"]
        self.token = token if token is not None else file_config["token"]
        self.allowed_dirs = file_config["allowed_project_dirs"]
        self.logger = logger or Logger()
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self, background: bool = True) -> None:
        """Start the webhook server.

        Args:
            background: If True (default), runs in a daemon thread.
                        If False, blocks the calling thread.
        """
        handler_class = _build_handler(
            project_dir=self.project_dir,
            token=self.token,
            allowed_dirs=self.allowed_dirs,
            logger=self.logger,
        )
        self._server = HTTPServer((self.host, self.port), handler_class)
        auth_status = "token auth enabled" if self.token else "WARNING: no auth token set"
        self.logger.info(
            f"HarnessSync webhook server listening on {self.host}:{self.port} "
            f"({auth_status})"
        )

        if background:
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                daemon=True,
                name="harnesssync-webhook",
            )
            self._thread.start()
        else:
            try:
                self._server.serve_forever()
            except KeyboardInterrupt:
                pass

    def stop(self) -> None:
        """Gracefully stop the webhook server."""
        if self._server:
            self._server.shutdown()
            self._server = None
        self.logger.info("HarnessSync webhook server stopped.")

    @property
    def url(self) -> str:
        """Return the base URL for this server."""
        return f"http://{self.host}:{self.port}"
