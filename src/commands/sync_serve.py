from __future__ import annotations

"""
/sync-serve slash command implementation.

Starts an HTTP webhook server that triggers a sync when called with a POST
request. Enables remote sync triggering from CI, Zapier, or any HTTP client
without SSH access to the developer's machine.

Usage:
    /sync-serve [--port PORT] [--host HOST] [--token TOKEN] [--project-dir PATH]

Options:
    --port PORT           Port to listen on (default: 8765)
    --host HOST           Bind address (default: 127.0.0.1)
    --token TOKEN         Shared auth token (default: HARNESSSYNC_WEBHOOK_TOKEN env)
    --project-dir PATH    Project directory for syncs (default: cwd)

Trigger a sync:
    curl -X POST http://localhost:8765/sync \\
         -H 'X-HarnessSync-Token: <token>' \\
         -H 'Content-Type: application/json' \\
         -d '{"scope": "all"}'

Check liveness:
    curl http://localhost:8765/health
"""

import os
import sys
import shlex
import argparse

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.webhook_server import WebhookServer
from src.utils.logger import Logger


def main() -> None:
    """Entry point for /sync-serve command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-serve",
        description="Start an HTTP webhook server for remote sync triggering"
    )
    parser.add_argument("--port", type=int, default=None, metavar="PORT",
                        help="Port to listen on (default: 8765)")
    parser.add_argument("--host", type=str, default=None, metavar="HOST",
                        help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--token", type=str, default=None, metavar="TOKEN",
                        help="Shared auth token for incoming requests")
    parser.add_argument("--project-dir", type=str, default=None, metavar="PATH",
                        help="Default project directory (default: cwd)")

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    logger = Logger()

    server = WebhookServer(
        project_dir=project_dir,
        host=args.host,
        port=args.port,
        token=args.token,
        logger=logger,
    )

    print(f"Starting HarnessSync webhook server...")
    print(f"  Endpoint:    {server.url}/sync")
    print(f"  Health:      {server.url}/health")
    print(f"  Project dir: {project_dir}")
    auth_hint = "Set X-HarnessSync-Token header" if server.token else "No auth (set --token for security)"
    print(f"  Auth:        {auth_hint}")
    print()
    print("Press Ctrl+C to stop.")
    print()

    try:
        server.start(background=False)
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
