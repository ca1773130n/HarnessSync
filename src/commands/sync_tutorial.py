from __future__ import annotations

"""
/sync-tutorial slash command implementation.

Interactive tutorial engine that walks users through configuring
a real Python project (TaskFlow) with every Claude Code config layer:
CLAUDE.md, rules, settings, commands, skills, agents, MCP, hooks,
and harness annotations.

9 steps total. Each step adds real config files and explains what they do.
"""

import argparse
import json
import shutil
import sys
import textwrap
from pathlib import Path

PLUGIN_ROOT = str(Path(__file__).resolve().parent.parent.parent)
sys.path.insert(0, PLUGIN_ROOT)

STATE_FILE = ".tutorial-state.json"
TOTAL_STEPS = 9

# Step number -> sentinel file that proves the step was completed
STEP_MARKERS = {
    1: "taskflow/__init__.py",
    2: "CLAUDE.md",
    3: ".claude/rules/python.md",
    4: ".claude/settings.json",
    5: ".claude/commands/check.md",
    6: ".claude/skills/add-feature.md",
    7: ".mcp.json",
    8: "hooks.json",
}

STEP_NAMES = {
    1: "Project Scaffolding",
    2: "CLAUDE.md",
    3: "Scoped Rules",
    4: "Settings / Permissions",
    5: "Custom Commands",
    6: "Skills & Agents",
    7: "MCP Servers",
    8: "Hooks & Annotations",
    9: "Tutorial Complete",
}

# ============================================================================
# CLI Parsing
# ============================================================================

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse tutorial command arguments."""
    parser = argparse.ArgumentParser(
        prog="sync-tutorial",
        description="Interactive HarnessSync tutorial engine",
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    # Each subparser inherits --dir so it can appear before or after the action
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--dir",
        default=None,
        help="Tutorial project directory (default: /tmp/taskflow-playground)",
    )

    subparsers.add_parser("start", parents=[parent], help="Start the tutorial from step 1")
    subparsers.add_parser("next", parents=[parent], help="Advance to the next step")
    subparsers.add_parser("reset", parents=[parent], help="Reset tutorial state (keeps app code)")
    subparsers.add_parser("status", parents=[parent], help="Show current tutorial progress")
    subparsers.add_parser("cleanup", parents=[parent], help="Remove the tutorial directory entirely")

    goto_parser = subparsers.add_parser("goto", parents=[parent], help="Jump to a specific step")
    goto_parser.add_argument("step_num", type=int, help="Step number to jump to (1-9)")

    parsed = parser.parse_args(argv)
    # Merge: top-level --dir is the fallback, subparser --dir overrides
    top_dir = getattr(parsed, "dir", None)
    if top_dir is None:
        parsed.dir = "/tmp/taskflow-playground"
    return parsed


# ============================================================================
# State Management
# ============================================================================

def save_state(target_dir: Path | str, current_step: int, completed_steps: list[int]) -> None:
    """Persist tutorial state to .tutorial-state.json."""
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "current_step": current_step,
        "completed_steps": sorted(set(completed_steps)),
    }
    (target_dir / STATE_FILE).write_text(json.dumps(state, indent=2) + "\n")


def load_state(target_dir: Path | str) -> dict | None:
    """Load tutorial state. Returns None if no state file exists."""
    state_path = Path(target_dir) / STATE_FILE
    if not state_path.exists():
        return None
    try:
        return json.loads(state_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def reconstruct_state(target_dir: Path | str) -> dict | None:
    """Detect tutorial progress from existing files when state file is missing."""
    target_dir = Path(target_dir)
    if not target_dir.exists():
        return None

    completed = []
    for step, marker in STEP_MARKERS.items():
        if (target_dir / marker).exists():
            completed.append(step)

    if not completed:
        return None

    current = max(completed)
    return {"current_step": current, "completed_steps": completed}


# ============================================================================
# TaskFlow Project Scaffolding
# ============================================================================

def scaffold_project(target_dir: Path | str) -> None:
    """Create a fully working TaskFlow Python CLI application."""
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    pkg = target_dir / "taskflow"
    pkg.mkdir(exist_ok=True)
    tests = target_dir / "tests"
    tests.mkdir(exist_ok=True)

    # --- taskflow/__init__.py ---
    (pkg / "__init__.py").write_text(textwrap.dedent('''\
        """TaskFlow — a lightweight CLI task manager."""

        __version__ = "0.1.0"
    '''))

    # --- taskflow/__main__.py ---
    (pkg / "__main__.py").write_text(textwrap.dedent('''\
        """Allow running as `python -m taskflow`."""
        from taskflow.cli import main

        main()
    '''))

    # --- taskflow/models.py ---
    (pkg / "models.py").write_text(textwrap.dedent('''\
        """Data models for TaskFlow."""
        from __future__ import annotations

        import json
        from dataclasses import dataclass, field, asdict
        from datetime import date
        from typing import Optional


        @dataclass
        class Task:
            """Represents a single task."""
            id: int = 0
            title: str = ""
            priority: str = "medium"  # low, medium, high
            tags: list[str] = field(default_factory=list)
            due_date: Optional[str] = None  # ISO format YYYY-MM-DD
            completed: bool = False

            def to_dict(self) -> dict:
                """Serialize to dictionary."""
                return asdict(self)

            @classmethod
            def from_dict(cls, data: dict) -> Task:
                """Deserialize from dictionary."""
                return cls(
                    id=data.get("id", 0),
                    title=data.get("title", ""),
                    priority=data.get("priority", "medium"),
                    tags=data.get("tags", []),
                    due_date=data.get("due_date"),
                    completed=data.get("completed", False),
                )

            def validate(self) -> list[str]:
                """Return a list of validation errors (empty if valid)."""
                errors = []
                if not self.title.strip():
                    errors.append("Title cannot be empty")
                if self.priority not in ("low", "medium", "high"):
                    errors.append(f"Invalid priority: {self.priority}")
                if self.due_date is not None:
                    try:
                        date.fromisoformat(self.due_date)
                    except ValueError:
                        errors.append(f"Invalid due_date format: {self.due_date}")
                return errors
    '''))

    # --- taskflow/storage.py ---
    (pkg / "storage.py").write_text(textwrap.dedent('''\
        """SQLite-backed task storage."""
        from __future__ import annotations

        import json
        import sqlite3
        from pathlib import Path
        from taskflow.models import Task


        class TaskStore:
            """CRUD operations for tasks in a SQLite database."""

            def __init__(self, db_path: str | Path = "tasks.db"):
                self.db_path = str(db_path)
                self._conn = sqlite3.connect(self.db_path)
                self._conn.row_factory = sqlite3.Row
                self._create_table()

            def _create_table(self) -> None:
                self._conn.execute("""
                    CREATE TABLE IF NOT EXISTS tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        priority TEXT NOT NULL DEFAULT 'medium',
                        tags TEXT NOT NULL DEFAULT '[]',
                        due_date TEXT,
                        completed INTEGER NOT NULL DEFAULT 0
                    )
                """)
                self._conn.commit()

            def add(self, task: Task) -> Task:
                """Insert a task and return it with the assigned id."""
                cursor = self._conn.execute(
                    "INSERT INTO tasks (title, priority, tags, due_date, completed) VALUES (?, ?, ?, ?, ?)",
                    (task.title, task.priority, json.dumps(task.tags), task.due_date, int(task.completed)),
                )
                self._conn.commit()
                task.id = cursor.lastrowid
                return task

            def list_all(self, include_completed: bool = True) -> list[Task]:
                """Return all tasks, optionally filtering out completed ones."""
                if include_completed:
                    rows = self._conn.execute("SELECT * FROM tasks ORDER BY id").fetchall()
                else:
                    rows = self._conn.execute(
                        "SELECT * FROM tasks WHERE completed = 0 ORDER BY id"
                    ).fetchall()
                return [self._row_to_task(r) for r in rows]

            def complete(self, task_id: int) -> bool:
                """Mark a task as completed. Returns True if found."""
                cursor = self._conn.execute(
                    "UPDATE tasks SET completed = 1 WHERE id = ?", (task_id,)
                )
                self._conn.commit()
                return cursor.rowcount > 0

            def delete(self, task_id: int) -> bool:
                """Delete a task. Returns True if found."""
                cursor = self._conn.execute(
                    "DELETE FROM tasks WHERE id = ?", (task_id,)
                )
                self._conn.commit()
                return cursor.rowcount > 0

            def search(self, query: str) -> list[Task]:
                """Search tasks by title (case-insensitive substring match)."""
                rows = self._conn.execute(
                    "SELECT * FROM tasks WHERE title LIKE ? ORDER BY id",
                    (f"%{query}%",),
                ).fetchall()
                return [self._row_to_task(r) for r in rows]

            def _row_to_task(self, row: sqlite3.Row) -> Task:
                return Task(
                    id=row["id"],
                    title=row["title"],
                    priority=row["priority"],
                    tags=json.loads(row["tags"]),
                    due_date=row["due_date"],
                    completed=bool(row["completed"]),
                )

            def close(self) -> None:
                self._conn.close()
    '''))

    # --- taskflow/cli.py ---
    (pkg / "cli.py").write_text(textwrap.dedent('''\
        """Command-line interface for TaskFlow."""
        from __future__ import annotations

        import argparse
        import sys
        import tempfile
        import os
        from pathlib import Path

        from taskflow.models import Task
        from taskflow.storage import TaskStore
        from taskflow.formatters import format_task_list, format_task_detail


        def _get_db_path() -> str:
            """Determine database path from env or default."""
            return os.environ.get("TASKFLOW_DB", "tasks.db")


        def cmd_add(args: argparse.Namespace) -> None:
            store = TaskStore(_get_db_path())
            tags = [t.strip() for t in args.tags.split(",")] if args.tags else []
            task = Task(title=args.title, priority=args.priority, tags=tags, due_date=args.due_date)
            errors = task.validate()
            if errors:
                print(f"Validation error: {'; '.join(errors)}", file=sys.stderr)
                sys.exit(1)
            task = store.add(task)
            print(f"Added task #{task.id}: {task.title}")
            store.close()


        def cmd_list(args: argparse.Namespace) -> None:
            store = TaskStore(_get_db_path())
            tasks = store.list_all(include_completed=args.all)
            print(format_task_list(tasks))
            store.close()


        def cmd_complete(args: argparse.Namespace) -> None:
            store = TaskStore(_get_db_path())
            if store.complete(args.id):
                print(f"Completed task #{args.id}")
            else:
                print(f"Task #{args.id} not found", file=sys.stderr)
                sys.exit(1)
            store.close()


        def cmd_delete(args: argparse.Namespace) -> None:
            store = TaskStore(_get_db_path())
            if store.delete(args.id):
                print(f"Deleted task #{args.id}")
            else:
                print(f"Task #{args.id} not found", file=sys.stderr)
                sys.exit(1)
            store.close()


        def cmd_search(args: argparse.Namespace) -> None:
            store = TaskStore(_get_db_path())
            tasks = store.search(args.query)
            print(format_task_list(tasks))
            store.close()


        def main(argv: list[str] | None = None) -> None:
            parser = argparse.ArgumentParser(prog="taskflow", description="TaskFlow CLI task manager")
            sub = parser.add_subparsers(dest="command")

            # add
            add_p = sub.add_parser("add", help="Add a new task")
            add_p.add_argument("title", help="Task title")
            add_p.add_argument("--priority", "-p", default="medium", choices=["low", "medium", "high"])
            add_p.add_argument("--tags", "-t", default="", help="Comma-separated tags")
            add_p.add_argument("--due-date", "-d", default=None, help="Due date (YYYY-MM-DD)")

            # list
            list_p = sub.add_parser("list", help="List tasks")
            list_p.add_argument("--all", "-a", action="store_true", help="Include completed tasks")

            # complete
            comp_p = sub.add_parser("complete", help="Mark a task as completed")
            comp_p.add_argument("id", type=int, help="Task ID")

            # delete
            del_p = sub.add_parser("delete", help="Delete a task")
            del_p.add_argument("id", type=int, help="Task ID")

            # search
            srch_p = sub.add_parser("search", help="Search tasks by title")
            srch_p.add_argument("query", help="Search query")

            args = parser.parse_args(argv)

            if args.command is None:
                parser.print_help()
                return

            dispatch = {
                "add": cmd_add,
                "list": cmd_list,
                "complete": cmd_complete,
                "delete": cmd_delete,
                "search": cmd_search,
            }
            dispatch[args.command](args)
    '''))

    # --- taskflow/api.py ---
    (pkg / "api.py").write_text(textwrap.dedent('''\
        """Minimal REST API for TaskFlow using stdlib http.server."""
        from __future__ import annotations

        import json
        from http.server import HTTPServer, BaseHTTPRequestHandler
        from taskflow.models import Task
        from taskflow.storage import TaskStore


        class TaskHandler(BaseHTTPRequestHandler):
            """Simple JSON API handler for tasks."""

            store: TaskStore | None = None

            def _send_json(self, data: dict | list, status: int = 200) -> None:
                body = json.dumps(data, indent=2).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                if self.path == "/tasks":
                    tasks = self.store.list_all()
                    self._send_json([t.to_dict() for t in tasks])
                elif self.path == "/health":
                    self._send_json({"status": "ok"})
                else:
                    self._send_json({"error": "not found"}, 404)

            def do_POST(self) -> None:
                if self.path == "/tasks":
                    length = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(length))
                    task = Task.from_dict(body)
                    errors = task.validate()
                    if errors:
                        self._send_json({"errors": errors}, 400)
                        return
                    task = self.store.add(task)
                    self._send_json(task.to_dict(), 201)
                else:
                    self._send_json({"error": "not found"}, 404)

            def log_message(self, format, *args):
                pass  # Suppress default logging


        def run_server(host: str = "127.0.0.1", port: int = 8080, db_path: str = "tasks.db") -> None:
            """Start the API server."""
            store = TaskStore(db_path)
            TaskHandler.store = store
            server = HTTPServer((host, port), TaskHandler)
            print(f"TaskFlow API running at http://{host}:{port}")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                store.close()
                server.server_close()
    '''))

    # --- taskflow/formatters.py ---
    (pkg / "formatters.py").write_text(textwrap.dedent('''\
        """Terminal formatting helpers for TaskFlow."""
        from __future__ import annotations

        from taskflow.models import Task


        # ANSI color codes
        RESET = "\\033[0m"
        BOLD = "\\033[1m"
        GREEN = "\\033[32m"
        YELLOW = "\\033[33m"
        RED = "\\033[31m"
        DIM = "\\033[2m"

        PRIORITY_COLORS = {
            "high": RED,
            "medium": YELLOW,
            "low": GREEN,
        }


        def format_task_line(task: Task) -> str:
            """Format a single task as a one-line summary."""
            check = "[x]" if task.completed else "[ ]"
            color = PRIORITY_COLORS.get(task.priority, "")
            priority_tag = f"{color}{task.priority.upper()}{RESET}"
            tags_str = ""
            if task.tags:
                tags_str = f" {DIM}[{', '.join(task.tags)}]{RESET}"
            due_str = ""
            if task.due_date:
                due_str = f" {DIM}due:{task.due_date}{RESET}"
            return f"  {check} #{task.id} {BOLD}{task.title}{RESET} ({priority_tag}){tags_str}{due_str}"


        def format_task_list(tasks: list[Task]) -> str:
            """Format a list of tasks for terminal display."""
            if not tasks:
                return "  No tasks found."
            lines = [f"  {BOLD}Tasks ({len(tasks)}):{RESET}"]
            for task in tasks:
                lines.append(format_task_line(task))
            return "\\n".join(lines)


        def format_task_detail(task: Task) -> str:
            """Format a single task with full details."""
            lines = [
                f"{BOLD}Task #{task.id}{RESET}",
                f"  Title:    {task.title}",
                f"  Priority: {task.priority}",
                f"  Tags:     {', '.join(task.tags) if task.tags else 'none'}",
                f"  Due:      {task.due_date or 'none'}",
                f"  Status:   {'completed' if task.completed else 'pending'}",
            ]
            return "\\n".join(lines)
    '''))

    # --- tests/__init__.py ---
    (tests / "__init__.py").write_text("")

    # --- tests/test_models.py ---
    (tests / "test_models.py").write_text(textwrap.dedent('''\
        """Unit tests for TaskFlow models."""
        from taskflow.models import Task


        class TestTask:
            def test_defaults(self):
                t = Task()
                assert t.id == 0
                assert t.title == ""
                assert t.priority == "medium"
                assert t.tags == []
                assert t.due_date is None
                assert t.completed is False

            def test_to_dict_roundtrip(self):
                t = Task(id=1, title="Buy milk", priority="high", tags=["shopping"], due_date="2025-12-31")
                d = t.to_dict()
                t2 = Task.from_dict(d)
                assert t2.title == t.title
                assert t2.priority == t.priority
                assert t2.tags == t.tags
                assert t2.due_date == t.due_date

            def test_validate_empty_title(self):
                t = Task(title="")
                errors = t.validate()
                assert any("Title" in e for e in errors)

            def test_validate_bad_priority(self):
                t = Task(title="Test", priority="critical")
                errors = t.validate()
                assert any("priority" in e.lower() for e in errors)

            def test_validate_bad_date(self):
                t = Task(title="Test", due_date="not-a-date")
                errors = t.validate()
                assert any("due_date" in e for e in errors)

            def test_validate_valid(self):
                t = Task(title="Valid task", priority="high", due_date="2025-06-15")
                assert t.validate() == []
    '''))

    # --- tests/test_storage.py ---
    (tests / "test_storage.py").write_text(textwrap.dedent('''\
        """Integration tests for TaskFlow storage (real SQLite)."""
        import tempfile
        import os
        from pathlib import Path
        from taskflow.models import Task
        from taskflow.storage import TaskStore


        class TestTaskStore:
            def setup_method(self):
                self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
                self._tmp.close()
                self.store = TaskStore(self._tmp.name)

            def teardown_method(self):
                self.store.close()
                os.unlink(self._tmp.name)

            def test_add_and_list(self):
                task = Task(title="Write tests", priority="high")
                added = self.store.add(task)
                assert added.id > 0
                tasks = self.store.list_all()
                assert len(tasks) == 1
                assert tasks[0].title == "Write tests"

            def test_complete(self):
                task = self.store.add(Task(title="Do thing"))
                assert self.store.complete(task.id)
                tasks = self.store.list_all()
                assert tasks[0].completed is True

            def test_complete_nonexistent(self):
                assert not self.store.complete(9999)

            def test_delete(self):
                task = self.store.add(Task(title="Temp"))
                assert self.store.delete(task.id)
                assert self.store.list_all() == []

            def test_delete_nonexistent(self):
                assert not self.store.delete(9999)

            def test_search(self):
                self.store.add(Task(title="Buy groceries"))
                self.store.add(Task(title="Buy flowers"))
                self.store.add(Task(title="Read book"))
                results = self.store.search("Buy")
                assert len(results) == 2

            def test_list_excludes_completed(self):
                t1 = self.store.add(Task(title="Done task"))
                self.store.add(Task(title="Pending task"))
                self.store.complete(t1.id)
                active = self.store.list_all(include_completed=False)
                assert len(active) == 1
                assert active[0].title == "Pending task"

            def test_tags_roundtrip(self):
                task = self.store.add(Task(title="Tagged", tags=["a", "b"]))
                fetched = self.store.list_all()[0]
                assert fetched.tags == ["a", "b"]
    '''))

    # --- tests/test_cli.py ---
    (tests / "test_cli.py").write_text(textwrap.dedent('''\
        """CLI smoke tests for TaskFlow (via subprocess)."""
        import os
        import sys
        import subprocess
        import tempfile


        class TestCLI:
            def setup_method(self):
                self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
                self._tmp.close()
                self._env = os.environ.copy()
                self._env["TASKFLOW_DB"] = self._tmp.name

            def teardown_method(self):
                os.unlink(self._tmp.name)

            def _run(self, *args: str) -> subprocess.CompletedProcess:
                return subprocess.run(
                    [sys.executable, "-m", "taskflow"] + list(args),
                    capture_output=True,
                    text=True,
                    env=self._env,
                    cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    timeout=10,
                )

            def test_list_empty(self):
                r = self._run("list")
                assert r.returncode == 0
                assert "No tasks" in r.stdout

            def test_add_and_list(self):
                r = self._run("add", "Test task", "--priority", "high")
                assert r.returncode == 0
                assert "Added" in r.stdout
                r = self._run("list")
                assert r.returncode == 0
                assert "Test task" in r.stdout

            def test_complete_task(self):
                self._run("add", "To complete")
                r = self._run("complete", "1")
                assert r.returncode == 0
                assert "Completed" in r.stdout

            def test_delete_task(self):
                self._run("add", "To delete")
                r = self._run("delete", "1")
                assert r.returncode == 0
                assert "Deleted" in r.stdout

            def test_search(self):
                self._run("add", "Find me")
                self._run("add", "Other")
                r = self._run("search", "Find")
                assert r.returncode == 0
                assert "Find me" in r.stdout

            def test_help(self):
                r = self._run("--help")
                assert r.returncode == 0
                assert "taskflow" in r.stdout.lower()
    '''))

    # --- README.md ---
    (target_dir / "README.md").write_text(textwrap.dedent("""\
        # TaskFlow

        A lightweight CLI task manager built with Python. Uses SQLite for storage
        and provides both a CLI and a minimal REST API.

        ## Quick Start

        ```bash
        # List tasks
        python -m taskflow list

        # Add a task
        python -m taskflow add "Buy groceries" --priority high --tags "shopping,food"

        # Complete a task
        python -m taskflow complete 1

        # Search tasks
        python -m taskflow search "groceries"

        # Run tests
        python -m pytest tests/ -v
        ```

        ## Architecture

        - `taskflow/models.py` — Task dataclass with validation
        - `taskflow/storage.py` — SQLite CRUD via TaskStore
        - `taskflow/cli.py` — argparse CLI
        - `taskflow/api.py` — REST API (http.server)
        - `taskflow/formatters.py` — Terminal color output
    """))


# ============================================================================
# Step File Templates
# ============================================================================

def add_step_files(target_dir: Path | str, step: int) -> None:
    """Add configuration files for the given tutorial step.

    Steps:
        1: (scaffolding only, handled by scaffold_project)
        2: CLAUDE.md
        3: .claude/rules/python.md, .claude/rules/testing.md
        4: .claude/settings.json
        5: .claude/commands/check.md
        6: .claude/skills/add-feature.md, .claude/agents/reviewer.md
        7: .mcp.json
        8: hooks.json + harness annotations in CLAUDE.md
        9: (no-op, victory lap)
    """
    target_dir = Path(target_dir)
    writers = {
        2: _write_step2, 3: _write_step3, 4: _write_step4,
        5: _write_step5, 6: _write_step6, 7: _write_step7,
        8: _write_step8,
    }
    writer = writers.get(step)
    if writer:
        writer(target_dir)


def _write_step2(target_dir: Path) -> None:
    """Step 2: Write CLAUDE.md with architecture rules."""
    (target_dir / "CLAUDE.md").write_text(textwrap.dedent("""\
        # TaskFlow

        A CLI task manager with SQLite storage and a REST API.

        ## Commands

        ```bash
        python -m pytest tests/             # run all tests
        python -m taskflow list              # list tasks
        python -m taskflow add "title"       # add a task
        python -m taskflow search "query"    # search tasks
        ```

        ## Architecture

        - `taskflow/models.py` — Task dataclass with validation; all fields have defaults
        - `taskflow/storage.py` — SQLite CRUD via TaskStore class; one connection per instance
        - `taskflow/cli.py` — argparse-based CLI; dispatches to storage layer
        - `taskflow/api.py` — minimal REST API using http.server; JSON in/out
        - `taskflow/formatters.py` — ANSI color helpers for terminal output

        ## Database Conventions

        - SQLite database file defaults to `tasks.db` in working directory
        - Override with `TASKFLOW_DB` environment variable
        - Tags stored as JSON arrays in TEXT columns
        - Boolean fields stored as INTEGER (0/1)
        - All queries use parameterized statements (never string interpolation)

        ## API Patterns

        - All endpoints return JSON with appropriate status codes
        - GET /tasks — list all tasks
        - POST /tasks — create a task (validates before insert)
        - GET /health — returns {"status": "ok"}
        - Validation errors return 400 with {"errors": [...]}

        ## Code Style

        - Pure Python 3.10+, stdlib only, no external dependencies
        - Type hints on all function signatures
        - Dataclasses for data transfer objects
        - Module-level functions for stateless operations
        - Classes only when managing state (e.g., DB connections)
    """))


def _write_step3(target_dir: Path) -> None:
    """Step 3: Write scoped rules for Python style and testing."""
    rules_dir = target_dir / ".claude" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)

    (rules_dir / "python.md").write_text(textwrap.dedent("""\
        # Python Style Rules

        ## Imports
        - Always use `from __future__ import annotations` as the first import
        - Group imports: stdlib, then third-party, then local — separated by blank lines
        - Prefer explicit imports over wildcard imports

        ## Type Hints
        - Use `str | None` instead of `Optional[str]` (Python 3.10+)
        - Use `list[str]` instead of `List[str]`
        - Annotate all function parameters and return types

        ## Naming
        - snake_case for functions and variables
        - PascalCase for classes
        - UPPER_SNAKE for constants
        - Private helpers prefixed with underscore

        ## Error Handling
        - Return error lists from validation functions (never raise for user input)
        - Use specific exception types (ValueError, KeyError), not bare Exception
        - Wrap I/O operations in try/except with meaningful messages

        ## Documentation
        - Docstrings on all public functions and classes
        - Use triple-double-quote style
        - First line is a concise summary; details follow a blank line
    """))

    (rules_dir / "testing.md").write_text(textwrap.dedent("""\
        # Testing Philosophy

        ## Test Structure
        - One test file per module: `test_models.py` tests `models.py`
        - Use class-based test grouping with `Test` prefix
        - Test method names describe the behavior: `test_add_returns_task_with_id`

        ## Test Types
        - Unit tests: pure logic, no I/O, no database
        - Integration tests: use real SQLite (tempfile), test actual queries
        - CLI smoke tests: run via subprocess, verify exit codes and output

        ## Assertions
        - One logical assertion per test (multiple physical asserts are fine if testing one concept)
        - Use pytest's plain `assert` — avoid unittest-style methods
        - Test both happy path and error cases

        ## Database Tests
        - Each test gets a fresh temporary database (setup_method/teardown_method)
        - Clean up temp files in teardown
        - Test round-trip: write then read back and verify

        ## CLI Tests
        - Use subprocess.run with capture_output=True
        - Set TASKFLOW_DB env var to a temp file
        - Verify return codes AND output content
    """))


def _write_step4(target_dir: Path) -> None:
    """Step 4: Write settings.json with permissions."""
    claude_dir = target_dir / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)

    settings = {
        "permissions": {
            "allow": [
                "Bash(python3 -m pytest*)",
                "Bash(python3 -m taskflow*)",
                "Bash(sqlite3 tasks.db*)",
                "Bash(ruff check*)",
                "Bash(ruff format*)",
            ],
            "deny": [
                "Bash(rm -rf*)",
                "Bash(*DROP TABLE*)",
                "Bash(*DELETE FROM tasks*)",
                "Bash(curl*)",
                "Bash(wget*)",
            ],
        },
    }
    (claude_dir / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")


def _write_step5(target_dir: Path) -> None:
    """Step 5: Write custom command — check.md."""
    cmd_dir = target_dir / ".claude" / "commands"
    cmd_dir.mkdir(parents=True, exist_ok=True)

    (cmd_dir / "check.md").write_text(textwrap.dedent("""\
        # /check — Run linting and tests

        Run the full quality check pipeline for TaskFlow.

        ## Steps

        1. Run ruff linter (if available):
           ```bash
           ruff check taskflow/ tests/ --fix 2>/dev/null || echo "ruff not installed, skipping lint"
           ```

        2. Run the test suite:
           ```bash
           python3 -m pytest tests/ -v --tb=short
           ```

        3. Verify the CLI works:
           ```bash
           python3 -m taskflow list
           ```

        ## Expected Outcome

        - All ruff checks pass (or ruff is skipped if not installed)
        - All pytest tests pass
        - The CLI returns exit code 0

        ## If Something Fails

        - Lint errors: fix the style issues ruff reports, then re-run
        - Test failures: read the traceback, fix the code, re-run
        - CLI errors: check that taskflow/ package structure is intact
    """))


def _write_step6(target_dir: Path) -> None:
    """Step 6: Write skill and agent definitions."""
    skills_dir = target_dir / ".claude" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    agents_dir = target_dir / ".claude" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    (skills_dir / "add-feature.md").write_text(textwrap.dedent("""\
        # Skill: Add Feature to TaskFlow

        ## When to Use
        When the user asks to add a new feature, capability, or command to TaskFlow.

        ## Process

        1. **Understand the requirement**: Clarify what the feature does and how users will interact with it.

        2. **Plan the changes**:
           - Does it need a new model field? Update `models.py` and the storage schema.
           - Does it need a new CLI command? Add a subparser in `cli.py`.
           - Does it need a new API endpoint? Add a handler in `api.py`.

        3. **Implement in order**:
           a. Model changes first (if any)
           b. Storage layer changes (new queries, schema migrations)
           c. Business logic
           d. CLI or API surface
           e. Formatter updates for display

        4. **Write tests**:
           - Unit tests for any new model logic
           - Integration tests for new storage operations
           - CLI smoke test for new commands

        5. **Verify**: Run `/check` to ensure all tests pass.

        ## Rules
        - Keep backward compatibility: never remove existing fields
        - All new fields must have defaults
        - Every new CLI command needs a help string
        - Every new feature needs at least one test
    """))

    (agents_dir / "reviewer.md").write_text(textwrap.dedent("""\
        # Agent: Code Reviewer

        ## Role
        You are a code reviewer for the TaskFlow project. Review changes for
        correctness, style, and test coverage.

        ## Review Checklist

        1. **Correctness**
           - Does the code do what it claims?
           - Are edge cases handled (empty input, None values, missing records)?
           - Are SQL queries parameterized (no string interpolation)?

        2. **Style**
           - Type hints on all function signatures?
           - Docstrings on public functions?
           - Consistent naming (snake_case functions, PascalCase classes)?
           - `from __future__ import annotations` at top of each module?

        3. **Testing**
           - New code has tests?
           - Tests cover both happy path and error cases?
           - Database tests use temp files and clean up?

        4. **Architecture**
           - Changes respect the layer boundaries (models -> storage -> cli)?
           - No direct SQL in CLI or API code (always go through TaskStore)?
           - No external dependencies added?

        ## Output Format
        Provide review as a numbered list of findings, each marked:
        - **MUST FIX**: Bugs, security issues, missing tests
        - **SHOULD FIX**: Style violations, missing docs
        - **CONSIDER**: Suggestions for improvement
    """))


def _write_step7(target_dir: Path) -> None:
    """Step 7: Write .mcp.json with demo MCP server config."""
    mcp_config = {
        "mcpServers": {
            "taskflow-sqlite": {
                "command": "npx",
                "args": [
                    "-y",
                    "@anthropic/mcp-server-sqlite",
                    "--db-path",
                    "./tasks.db",
                ],
                "description": "SQLite MCP server for direct database access to TaskFlow's task store",
            },
        },
    }
    (target_dir / ".mcp.json").write_text(json.dumps(mcp_config, indent=2) + "\n")


def _write_step8(target_dir: Path) -> None:
    """Step 8: Write hooks.json and append harness annotations to CLAUDE.md."""
    hooks = {
        "hooks": [
            {
                "matcher": "PostToolUse",
                "tools": ["Edit", "Write", "MultiEdit"],
                "command": "ruff format --quiet ${file} 2>/dev/null || true",
                "description": "Auto-format Python files after edits",
            },
        ],
    }
    (target_dir / "hooks.json").write_text(json.dumps(hooks, indent=2) + "\n")

    # Append harness annotations to CLAUDE.md
    annotations = textwrap.dedent("""\

        ## Harness-Specific Instructions

        <!-- @harness: cursor, windsurf -->
        Use integrated terminal for testing. Prefer the built-in terminal panel
        for running pytest and taskflow commands so output is visible inline.

        <!-- @harness: codex -->
        All tests must be fully automated. Never rely on interactive input or
        manual verification steps. Use TASKFLOW_DB env var for test isolation.

        <!-- @harness: * -->
        All endpoints return JSON. When adding new API endpoints, always return
        a JSON object with appropriate status codes and Content-Type headers.
    """)

    claude_md_path = target_dir / "CLAUDE.md"
    if claude_md_path.exists():
        existing = claude_md_path.read_text()
        claude_md_path.write_text(existing + annotations)
    else:
        # If CLAUDE.md doesn't exist yet, create a minimal one with annotations
        claude_md_path.write_text("# TaskFlow\n" + annotations)


# ============================================================================
# Step Guide Text
# ============================================================================

def get_step_guide(step: int, target_dir: str = "") -> str:
    """Return the markdown guide for a tutorial step.

    Raises ValueError for step numbers outside 1-9.
    If target_dir is provided, replaces {dir} placeholders.
    """
    if step < 1 or step > TOTAL_STEPS:
        raise ValueError(f"Invalid step number: {step}. Must be between 1 and 9.")

    guides = {
        1: textwrap.dedent("""\
            ## Step 1: Project Scaffolding

            Welcome to the HarnessSync tutorial! We've created **TaskFlow**, a real
            Python CLI task manager that you'll configure with every Claude Code
            config layer.

            ### What was created

            - `taskflow/` — Python package with models, storage, CLI, API, formatters
            - `tests/` — Unit, integration, and CLI smoke tests
            - `README.md` — Project overview

            ### Try it out

            ```bash
            cd {dir}
            python3 -m taskflow list           # list tasks (empty for now)
            python3 -m taskflow add "Learn Claude Code config" --priority high
            python3 -m taskflow list
            python3 -m pytest tests/ -v        # run the test suite
            ```

            ### What's next

            Run `/sync-tutorial next` to add a CLAUDE.md file that teaches Claude
            about TaskFlow's architecture.
        """),

        2: textwrap.dedent("""\
            ## Step 2: CLAUDE.md — Project Context

            The `CLAUDE.md` file is the **most important** config file for Claude Code.
            It's the first thing Claude reads when it enters your project.

            ### What was added

            - `CLAUDE.md` — Architecture overview, database conventions, API patterns,
              code style rules, and common commands

            ### Explore it

            ```bash
            cat CLAUDE.md
            ```

            Notice how it documents:
            - **Commands** to run (test, lint, build)
            - **Architecture** (which file does what)
            - **Conventions** (DB patterns, API patterns, code style)

            ### Why it matters

            Without CLAUDE.md, Claude has to guess your project's conventions.
            With it, Claude follows your patterns from the first interaction.

            ### What's next

            Run `/sync-tutorial next` to add scoped rules for Python style and testing.
        """),

        3: textwrap.dedent("""\
            ## Step 3: Scoped Rules — Modular Instructions

            Rules in `.claude/rules/` let you organize instructions into focused files
            instead of putting everything in CLAUDE.md.

            ### What was added

            - `.claude/rules/python.md` — Python style rules (imports, type hints, naming)
            - `.claude/rules/testing.md` — Testing philosophy (structure, assertions, DB tests)

            ### Explore them

            ```bash
            cat .claude/rules/python.md
            cat .claude/rules/testing.md
            ```

            ### When to use rules vs CLAUDE.md

            - **CLAUDE.md**: Project overview, architecture, commands — things every
              interaction needs
            - **Rules files**: Detailed guidelines for specific topics — loaded when relevant

            ### What's next

            Run `/sync-tutorial next` to configure permissions (allow/deny lists).
        """),

        4: textwrap.dedent("""\
            ## Step 4: Settings — Permissions

            The `.claude/settings.json` file controls what Claude is allowed to do
            in your project.

            ### What was added

            - `.claude/settings.json` — Allow/deny lists for shell commands

            ### Explore it

            ```bash
            cat .claude/settings.json
            ```

            Notice the permission structure:
            - **allow**: pytest, taskflow CLI, sqlite3, ruff — safe development tools
            - **deny**: `rm -rf`, `DROP TABLE`, `DELETE FROM` — destructive operations

            ### How permissions work

            - `allow` patterns are auto-approved (no confirmation prompt)
            - `deny` patterns are blocked entirely
            - Everything else prompts for confirmation

            ### What's next

            Run `/sync-tutorial next` to add a custom slash command.
        """),

        5: textwrap.dedent("""\
            ## Step 5: Commands — Custom Slash Commands

            Custom commands in `.claude/commands/` create project-specific slash
            commands that appear in Claude Code's command palette.

            ### What was added

            - `.claude/commands/check.md` — A `/check` command that runs linting + tests

            ### Explore it

            ```bash
            cat .claude/commands/check.md
            ```

            ### How commands work

            - Files in `.claude/commands/` become slash commands
            - The filename (minus `.md`) is the command name
            - The file content is the prompt Claude receives

            ### Try it

            The `/check` command tells Claude to run ruff and pytest. In a real
            Claude Code session, you'd type `/check` and Claude would execute the
            quality pipeline.

            ### What's next

            Run `/sync-tutorial next` to add skills and agent definitions.
        """),

        6: textwrap.dedent("""\
            ## Step 6: Skills & Agents — Specialized Behaviors

            Skills teach Claude **how** to do specific tasks. Agents define
            **roles** with review checklists and output formats.

            ### What was added

            - `.claude/skills/add-feature.md` — Step-by-step process for adding features
            - `.claude/agents/reviewer.md` — Code reviewer role with checklist

            ### Explore them

            ```bash
            cat .claude/skills/add-feature.md
            cat .claude/agents/reviewer.md
            ```

            ### Skills vs Agents vs Commands

            - **Commands**: User-triggered actions (like `/check`)
            - **Skills**: Reusable procedures Claude follows when relevant
            - **Agents**: Personas with specific roles and output formats

            ### What's next

            Run `/sync-tutorial next` to configure MCP servers for database access.
        """),

        7: textwrap.dedent("""\
            ## Step 7: MCP Servers — Tool Integration

            The `.mcp.json` file configures Model Context Protocol servers that
            give Claude access to external tools and data sources.

            ### What was added

            - `.mcp.json` — SQLite MCP server config for direct database access

            ### Explore it

            ```bash
            cat .mcp.json
            ```

            ### How MCP servers work

            - Claude Code reads `.mcp.json` on startup
            - Each server provides tools Claude can call
            - The SQLite server lets Claude query your task database directly

            ### Why this matters

            Without MCP, Claude can only interact with your DB through the CLI.
            With the SQLite MCP server, Claude can run queries, inspect schema,
            and debug data issues directly.

            ### What's next

            Run `/sync-tutorial next` to add hooks and harness annotations.
        """),

        8: textwrap.dedent("""\
            ## Step 8: Hooks & Harness Annotations

            Hooks run commands automatically after Claude performs actions.
            Harness annotations let you write instructions that only apply to
            specific AI coding tools.

            ### What was added

            - `hooks.json` — Auto-format Python files after edits (PostToolUse hook)
            - Updated `CLAUDE.md` with `<!-- @harness -->` annotations

            ### Explore them

            ```bash
            cat hooks.json
            cat CLAUDE.md   # scroll to the bottom for annotations
            ```

            ### How hooks work

            The `PostToolUse` hook fires after Edit/Write/MultiEdit and runs
            `ruff format` on the changed file. This keeps code formatted without
            manual intervention.

            ### How harness annotations work

            ```markdown
            <!-- @harness: cursor, windsurf -->
            Instructions only for Cursor and Windsurf.

            <!-- @harness: codex -->
            Instructions only for Codex.

            <!-- @harness: * -->
            Instructions for all harnesses.
            ```

            HarnessSync reads these annotations and includes/excludes them when
            syncing to each target harness.

            ### What's next

            Run `/sync-tutorial next` to see the tutorial completion summary.
        """),

        9: textwrap.dedent("""\
            ## Step 9: Tutorial Complete!

            Congratulations! You've configured TaskFlow with every Claude Code
            config layer:

            | Step | Config Layer | File(s) |
            |------|-------------|---------|
            | 1 | Project | `taskflow/`, `tests/`, `README.md` |
            | 2 | CLAUDE.md | `CLAUDE.md` |
            | 3 | Rules | `.claude/rules/python.md`, `.claude/rules/testing.md` |
            | 4 | Settings | `.claude/settings.json` |
            | 5 | Commands | `.claude/commands/check.md` |
            | 6 | Skills & Agents | `.claude/skills/add-feature.md`, `.claude/agents/reviewer.md` |
            | 7 | MCP Servers | `.mcp.json` |
            | 8 | Hooks & Annotations | `hooks.json`, harness annotations in `CLAUDE.md` |

            ### What you've learned

            - **CLAUDE.md** gives Claude project context and conventions
            - **Rules** organize detailed guidelines into focused files
            - **Settings** control permissions (allow/deny)
            - **Commands** create custom slash commands
            - **Skills** teach Claude how to do specific tasks
            - **Agents** define specialized roles
            - **MCP servers** integrate external tools
            - **Hooks** automate actions after Claude's edits
            - **Harness annotations** customize behavior per AI tool

            ### Next steps

            - Run `python3 -m pytest tests/ -v` to verify everything still works
            - Try `sync-status` to see how HarnessSync would sync this config
            - Explore the files and customize them for your own projects

            ### Cleanup

            When you're done exploring, run `/sync-tutorial cleanup` to remove
            the tutorial directory.
        """),
    }

    guide = guides[step]
    if target_dir:
        guide = guide.replace("{dir}", target_dir)
    return guide


# ============================================================================
# Action Handlers
# ============================================================================

def handle_start(target_dir: Path | str) -> str:
    """Start the tutorial: scaffold project, save state at step 1."""
    target_dir = Path(target_dir)

    if target_dir.exists() and load_state(target_dir) is not None:
        # Already started — clean up config files before re-scaffolding
        handle_reset(target_dir)

    scaffold_project(target_dir)
    save_state(target_dir, current_step=1, completed_steps=[1])
    return get_step_guide(1, str(target_dir))


def handle_next(target_dir: Path | str) -> str:
    """Advance to the next step."""
    target_dir = Path(target_dir)
    state = load_state(target_dir) or reconstruct_state(target_dir)

    if state is None:
        return (
            "No tutorial in progress. Run `/sync-tutorial start` to begin.\n\n"
            "If you have an existing tutorial directory, try `/sync-tutorial start` "
            "to set it up."
        )

    current = state["current_step"]
    completed = state["completed_steps"]

    if current >= TOTAL_STEPS:
        return (
            "You've already completed all 9 steps! The tutorial is finished.\n\n"
            "Run `/sync-tutorial status` to review your progress, or "
            "`/sync-tutorial cleanup` to remove the tutorial directory."
        )

    next_step = current + 1
    add_step_files(target_dir, next_step)
    completed.append(next_step)
    save_state(target_dir, current_step=next_step, completed_steps=completed)
    return get_step_guide(next_step, str(target_dir))


def handle_status(target_dir: Path | str) -> str:
    """Show current tutorial progress."""
    target_dir = Path(target_dir)
    state = load_state(target_dir)

    if state is None:
        return "No tutorial in progress. Run `/sync-tutorial start` to begin."

    current = state["current_step"]
    completed = sorted(state["completed_steps"])

    lines = [
        f"## Tutorial Progress: Step {current} of {TOTAL_STEPS}\n",
        f"**Directory:** `{target_dir}`\n",
    ]

    for step in range(1, TOTAL_STEPS + 1):
        if step in completed:
            marker = "[x]"
        elif step == current + 1:
            marker = "[ ] <-- next"
        else:
            marker = "[ ]"
        lines.append(f"  {marker} Step {step}: {STEP_NAMES[step]}")

    if current < TOTAL_STEPS:
        lines.append(f"\nRun `/sync-tutorial next` to proceed to Step {current + 1}.")
    else:
        lines.append("\nAll steps completed!")

    return "\n".join(lines)


def handle_goto(target_dir: Path | str, step_num: int) -> str:
    """Jump to a specific step, ensuring all prerequisite steps have files."""
    target_dir = Path(target_dir)

    if step_num < 1 or step_num > TOTAL_STEPS:
        return f"Invalid step number: {step_num}. Must be between 1 and {TOTAL_STEPS}."

    state = load_state(target_dir)
    if state is None:
        # Auto-start if needed
        scaffold_project(target_dir)
        completed = [1]
    else:
        completed = list(state["completed_steps"])
        if 1 not in completed:
            completed.append(1)

    # Ensure all steps up to step_num have their files
    for s in range(2, step_num + 1):
        add_step_files(target_dir, s)
        if s not in completed:
            completed.append(s)

    save_state(target_dir, current_step=step_num, completed_steps=completed)
    return get_step_guide(step_num, str(target_dir))


def handle_reset(target_dir: Path | str) -> str:
    """Remove tutorial state and config files, but keep the app code."""
    target_dir = Path(target_dir)

    if not target_dir.exists():
        return f"Directory does not exist: {target_dir}"

    # Remove state file
    state_path = target_dir / STATE_FILE
    if state_path.exists():
        state_path.unlink()

    # Remove config files added by tutorial steps
    config_paths = [
        target_dir / "CLAUDE.md",
        target_dir / ".claude",
        target_dir / ".mcp.json",
        target_dir / "hooks.json",
    ]
    for p in config_paths:
        if p.is_dir():
            shutil.rmtree(p)
        elif p.is_file():
            p.unlink()

    return (
        "Tutorial state and config files removed.\n"
        "The TaskFlow app code is still intact.\n\n"
        "Run `/sync-tutorial start` to begin again."
    )


def handle_cleanup(target_dir: Path | str) -> str:
    """Remove the entire tutorial directory."""
    target_dir = Path(target_dir)

    if not target_dir.exists():
        return f"Directory does not exist: {target_dir}"

    shutil.rmtree(target_dir)
    return f"Removed tutorial directory: {target_dir}"


# ============================================================================
# Main
# ============================================================================

def main(argv: list[str] | None = None) -> None:
    """Parse args and dispatch to the appropriate handler."""
    args = parse_args(argv)
    target_dir = Path(args.dir)

    dispatch = {
        "start": lambda: handle_start(target_dir),
        "next": lambda: handle_next(target_dir),
        "status": lambda: handle_status(target_dir),
        "reset": lambda: handle_reset(target_dir),
        "cleanup": lambda: handle_cleanup(target_dir),
        "goto": lambda: handle_goto(target_dir, args.step_num),
    }

    output = dispatch[args.action]()
    print(output)


if __name__ == "__main__":
    main()
