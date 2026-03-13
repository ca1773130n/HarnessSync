from __future__ import annotations

"""Downstream webhook notifier for HarnessSync sync events.

Emits HTTP POST webhook calls or runs local shell commands when a sync
completes. Enables integration with external automation pipelines:
- Slack / Teams / Discord notifications
- Restart dev servers on config change
- Update a team wiki or dashboard
- Trigger CI/CD pipelines

Configuration is stored in ~/.harnesssync/webhooks.json:

    {
        "webhooks": [
            {
                "name": "slack-team",
                "url": "https://hooks.slack.com/services/T.../B.../...",
                "on": ["success", "partial", "failed"],
                "secret": "optional-hmac-secret",
                "headers": {"X-Custom-Header": "value"}
            }
        ],
        "scripts": [
            {
                "name": "restart-dev-server",
                "command": "pkill -HUP node",
                "on": ["success"],
                "cwd": "/path/to/project"
            }
        ]
    }

Webhook payload (application/json):

    {
        "event": "sync_complete",
        "status": "success" | "partial" | "failed",
        "timestamp": "2024-01-01T12:00:00Z",
        "project": "/absolute/path/to/project",
        "targets": ["codex", "gemini"],
        "totals": {"synced": 5, "skipped": 2, "failed": 0},
        "dry_run": false
    }
"""

import hashlib
import hmac
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.utils.logger import Logger


@dataclass
class WebhookResult:
    """Outcome of a single webhook or script dispatch."""

    name: str
    kind: str  # "webhook" | "script"
    success: bool
    status_code: int | None = None  # HTTP status for webhooks
    error: str | None = None


class WebhookNotifier:
    """Dispatches webhook calls and local scripts after sync events.

    Args:
        config_dir: Directory containing webhooks.json (default: ~/.harnesssync).
        logger: Optional Logger instance.
        timeout: HTTP request timeout in seconds.
    """

    CONFIG_FILE = "webhooks.json"

    def __init__(
        self,
        config_dir: Path | None = None,
        logger: Logger | None = None,
        timeout: float = 10.0,
    ):
        self.config_dir = config_dir or (Path.home() / ".harnesssync")
        self.logger = logger or Logger()
        self.timeout = timeout
        self._config = self._load_config()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def notify(
        self,
        results: dict,
        project_dir: Path | None = None,
        dry_run: bool = False,
    ) -> list[WebhookResult]:
        """Dispatch all configured webhooks and scripts for this sync event.

        Args:
            results: Sync results dict from ``SyncOrchestrator.sync_all()``.
            project_dir: Project directory that was synced.
            dry_run: True if this was a preview run (no files written).

        Returns:
            List of WebhookResult for each dispatched webhook/script.
        """
        if not self._config:
            return []

        payload = self._build_payload(results, project_dir=project_dir, dry_run=dry_run)
        status = payload["status"]
        dispatch_results: list[WebhookResult] = []

        for webhook in self._config.get("webhooks", []):
            if status in webhook.get("on", ["success", "partial", "failed"]):
                result = self._send_webhook(webhook, payload)
                dispatch_results.append(result)
                if not result.success:
                    self.logger.warning(
                        f"Webhook '{result.name}' failed: {result.error}"
                    )

        for script in self._config.get("scripts", []):
            if status in script.get("on", ["success"]):
                result = self._run_script(script, payload, project_dir=project_dir)
                dispatch_results.append(result)
                if not result.success:
                    self.logger.warning(
                        f"Script '{result.name}' failed: {result.error}"
                    )

        return dispatch_results

    def add_webhook(
        self,
        name: str,
        url: str,
        on: list[str] | None = None,
        secret: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Add a webhook to the configuration.

        Args:
            name: Friendly name for this webhook.
            url: HTTP POST endpoint URL.
            on: List of statuses that trigger this webhook (default: all).
            secret: Optional HMAC-SHA256 signing secret.
            headers: Optional extra HTTP headers.
        """
        entry: dict = {"name": name, "url": url, "on": on or ["success", "partial", "failed"]}
        if secret:
            entry["secret"] = secret
        if headers:
            entry["headers"] = headers

        webhooks = self._config.setdefault("webhooks", [])
        # Replace existing webhook with same name
        webhooks[:] = [w for w in webhooks if w.get("name") != name]
        webhooks.append(entry)
        self._save_config()

    def add_script(
        self,
        name: str,
        command: str,
        on: list[str] | None = None,
        cwd: str | None = None,
    ) -> None:
        """Add a local script to run after sync.

        Args:
            name: Friendly name for this script.
            command: Shell command to execute.
            on: List of statuses that trigger this script (default: success only).
            cwd: Working directory for the command.
        """
        entry: dict = {"name": name, "command": command, "on": on or ["success"]}
        if cwd:
            entry["cwd"] = cwd

        scripts = self._config.setdefault("scripts", [])
        scripts[:] = [s for s in scripts if s.get("name") != name]
        scripts.append(entry)
        self._save_config()

    def remove(self, name: str) -> bool:
        """Remove a webhook or script by name.

        Args:
            name: Name of the webhook or script to remove.

        Returns:
            True if something was removed, False if name not found.
        """
        removed = False
        for key in ("webhooks", "scripts"):
            before = len(self._config.get(key, []))
            self._config[key] = [e for e in self._config.get(key, []) if e.get("name") != name]
            if len(self._config.get(key, [])) < before:
                removed = True
        if removed:
            self._save_config()
        return removed

    def list_configured(self) -> str:
        """Return a formatted list of all configured webhooks and scripts."""
        lines = ["Configured downstream notifications:", ""]
        webhooks = self._config.get("webhooks", [])
        scripts = self._config.get("scripts", [])

        if not webhooks and not scripts:
            return "No webhooks or scripts configured. Use add_webhook() or add_script()."

        if webhooks:
            lines.append("Webhooks:")
            for w in webhooks:
                url = w.get("url", "?")
                on = ", ".join(w.get("on", []))
                lines.append(f"  {w.get('name', '?'):<20} {url[:50]}  (on: {on})")

        if scripts:
            lines.append("")
            lines.append("Scripts:")
            for s in scripts:
                cmd = s.get("command", "?")
                on = ", ".join(s.get("on", []))
                lines.append(f"  {s.get('name', '?'):<20} {cmd[:50]}  (on: {on})")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_config(self) -> dict:
        """Load webhooks.json from config directory."""
        path = self.config_dir / self.CONFIG_FILE
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_config(self) -> None:
        """Atomically write webhooks.json."""
        import tempfile
        self.config_dir.mkdir(parents=True, exist_ok=True)
        path = self.config_dir / self.CONFIG_FILE
        tmp = None
        try:
            fd = tempfile.NamedTemporaryFile(
                mode="w", dir=self.config_dir, suffix=".tmp", delete=False, encoding="utf-8"
            )
            tmp = fd.name
            json.dump(self._config, fd, indent=2, ensure_ascii=False)
            fd.write("\n")
            fd.flush()
            os.fsync(fd.fileno())
            fd.close()
            os.replace(tmp, str(path))
        except Exception:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            raise

    def _build_payload(
        self,
        results: dict,
        project_dir: Path | None,
        dry_run: bool,
    ) -> dict:
        """Build the JSON payload to send in webhook POST body."""
        from src.adapters.result import SyncResult

        total_synced = total_skipped = total_failed = 0
        targets_synced: list[str] = []

        for target_name, target_results in results.items():
            if target_name.startswith("_"):
                continue
            if isinstance(target_results, dict):
                t_synced = t_failed = 0
                for result in target_results.values():
                    if isinstance(result, SyncResult):
                        total_synced += result.synced
                        total_skipped += result.skipped
                        total_failed += result.failed
                        t_synced += result.synced
                        t_failed += result.failed
                if t_synced > 0 or t_failed > 0:
                    targets_synced.append(target_name)

        if total_failed == 0:
            status = "success"
        elif total_synced > 0:
            status = "partial"
        else:
            status = "failed"

        return {
            "event": "sync_complete",
            "status": status,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "project": str(project_dir or Path.cwd()),
            "targets": sorted(targets_synced),
            "totals": {
                "synced": total_synced,
                "skipped": total_skipped,
                "failed": total_failed,
            },
            "dry_run": dry_run,
        }

    def _sign_payload(self, body: bytes, secret: str) -> str:
        """Return HMAC-SHA256 hex digest of the payload body."""
        return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    def _send_webhook(self, webhook: dict, payload: dict) -> WebhookResult:
        """Send HTTP POST with JSON payload to a webhook URL.

        Args:
            webhook: Webhook config dict.
            payload: Event payload dict.

        Returns:
            WebhookResult with success status and HTTP code.
        """
        name = webhook.get("name", "unnamed")
        url = webhook.get("url", "")
        if not url:
            return WebhookResult(name=name, kind="webhook", success=False, error="no URL configured")

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "HarnessSync/1.0",
        }

        # Merge custom headers
        for k, v in webhook.get("headers", {}).items():
            headers[k] = str(v)

        # HMAC signature
        secret = webhook.get("secret")
        if secret:
            sig = self._sign_payload(body, secret)
            headers["X-HarnessSync-Signature"] = f"sha256={sig}"

        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                code = resp.getcode()
                return WebhookResult(name=name, kind="webhook", success=200 <= code < 300, status_code=code)
        except urllib.error.HTTPError as e:
            return WebhookResult(name=name, kind="webhook", success=False, status_code=e.code, error=str(e))
        except Exception as e:
            return WebhookResult(name=name, kind="webhook", success=False, error=str(e))

    def notify_drift_event(
        self,
        target: str,
        file_path: str,
        detected_at: str,
        deleted: bool = False,
        project_dir: Path | None = None,
    ) -> list[WebhookResult]:
        """Dispatch drift-specific webhook notifications to subscribed endpoints.

        Sends a structured drift alert payload to all configured webhooks that
        subscribe to ``drift`` or ``success`` events. Teams can route drift
        alerts to dedicated Slack channels or monitoring dashboards.

        Payload schema::

            {
                "event": "drift_detected",
                "target": "codex",
                "file": "AGENTS.md",
                "file_path": "/path/to/AGENTS.md",
                "status": "modified" | "deleted",
                "detected_at": "2024-01-15T12:00:00",
                "project": "/path/to/project"
            }

        Args:
            target: Harness target name (e.g. "codex").
            file_path: Absolute path to the drifted file.
            detected_at: ISO 8601 timestamp of when drift was detected.
            deleted: True if the file was deleted, False if modified.
            project_dir: Project directory for context in the payload.

        Returns:
            List of WebhookResult for each dispatched webhook/script.
        """
        import os as _os

        payload = {
            "event": "drift_detected",
            "target": target,
            "file": _os.path.basename(file_path),
            "file_path": file_path,
            "status": "deleted" if deleted else "modified",
            "detected_at": detected_at,
            "project": str(project_dir or Path.cwd()),
        }

        dispatch_results: list[WebhookResult] = []
        for webhook in self._config.get("webhooks", []):
            on_events = webhook.get("on", ["success", "partial", "failed"])
            # Send drift events to webhooks opting into "drift" or general "success"
            if "drift" in on_events or "success" in on_events:
                result = self._send_webhook(webhook, payload)
                dispatch_results.append(result)
                if not result.success:
                    self.logger.warning(
                        f"Drift webhook '{result.name}' failed: {result.error}"
                    )

        for script in self._config.get("scripts", []):
            on_events = script.get("on", ["success"])
            if "drift" in on_events or "success" in on_events:
                result = self._run_script(script, payload, project_dir)
                dispatch_results.append(result)

        return dispatch_results

    def _run_script(
        self, script: dict, payload: dict, project_dir: Path | None
    ) -> WebhookResult:
        """Run a local shell script/command.

        The sync payload is passed as JSON in the HARNESSSYNC_EVENT environment variable.

        Args:
            script: Script config dict.
            payload: Event payload dict.
            project_dir: Project directory (used as default cwd).

        Returns:
            WebhookResult with success status.
        """
        name = script.get("name", "unnamed")
        command = script.get("command", "")
        if not command:
            return WebhookResult(name=name, kind="script", success=False, error="no command configured")

        cwd = script.get("cwd") or str(project_dir or Path.cwd())
        env = os.environ.copy()
        env["HARNESSSYNC_EVENT"] = json.dumps(payload)

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                env=env,
                timeout=30,
                capture_output=True,
                text=True,
            )
            success = result.returncode == 0
            error = result.stderr.strip() if not success else None
            return WebhookResult(name=name, kind="script", success=success, error=error)
        except subprocess.TimeoutExpired:
            return WebhookResult(name=name, kind="script", success=False, error="script timed out (30s)")
        except Exception as e:
            return WebhookResult(name=name, kind="script", success=False, error=str(e))
