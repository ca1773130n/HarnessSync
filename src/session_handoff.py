from __future__ import annotations

"""Cross-harness session handoff (item 23).

Generates a context-rich handoff prompt that lets users seamlessly continue
a Claude Code conversation in another harness (Gemini CLI, Codex, OpenCode,
Cursor, etc.) with full context about what was discussed and what needs to
happen next.

Problem: switching harnesses mid-task means starting over — users lose
conversation history and have to re-explain the problem, the files involved,
the constraints, and where they left off.

Solution: produce a compact, structured prompt that encodes:
  * The task description and current status
  * Files read / modified during the session
  * Key decisions made and why
  * Pending work items
  * A paste-ready intro line for the target harness

Usage::

    from src.session_handoff import SessionHandoff

    handoff = SessionHandoff(project_dir=Path("."))
    handoff.set_task("Refactoring auth module to use JWT")
    handoff.add_file_context("src/auth/middleware.py", role="modified")
    handoff.add_file_context("src/auth/tokens.py", role="read")
    handoff.add_decision("Chose HS256 over RS256 because no PKI infra is available")
    handoff.add_todo("Write unit tests for refresh-token endpoint")
    prompt = handoff.render(target_harness="gemini")
    print(prompt)

Or via the /sync-handoff command::

    /sync-handoff --task "Refactoring auth module" --files src/auth/ --target gemini
"""

import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Data types
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FileContext:
    """A file referenced in the session."""
    path: str
    role: str = "read"          # "read" | "modified" | "created" | "deleted"
    summary: str = ""           # Optional one-line description of what was done


@dataclass
class HandoffContext:
    """All context collected during a session to hand off."""
    task: str = ""
    status: str = "in-progress"      # "in-progress" | "blocked" | "done"
    files: list[FileContext] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    todos: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    notes: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Harness intro lines
# ─────────────────────────────────────────────────────────────────────────────

_HARNESS_INTROS: dict[str, str] = {
    "gemini":    "I'm continuing work from a Claude Code session. Please pick up where I left off.",
    "codex":     "Continuing from a Claude Code session. Context below — please continue the work.",
    "opencode":  "I'm handing off from Claude Code. Use the context below to continue this task.",
    "cursor":    "Resuming a Claude Code session in Cursor. Full context is provided below.",
    "aider":     "Handing off from Claude Code to Aider. Task context follows.",
    "windsurf":  "Continuing from Claude Code. The task context is below — please continue.",
    "vscode":    "Picking up a Claude Code session. Context provided below.",
    "default":   "Continuing from a previous AI coding session. Context is below.",
}

# Prompt template skeleton
_TEMPLATE = """\
{intro}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TASK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{task}

Status: {status}
{project_line}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FILES INVOLVED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{files_section}

{decisions_section}{todos_section}{constraints_section}{notes_section}\
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NEXT STEP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{next_step}
"""


# ─────────────────────────────────────────────────────────────────────────────
# SessionHandoff builder
# ─────────────────────────────────────────────────────────────────────────────

class SessionHandoff:
    """Build and render a cross-harness session handoff prompt.

    Args:
        project_dir: Project root directory (used to shorten absolute paths
                     in the rendered output).
    """

    def __init__(self, project_dir: Path | None = None) -> None:
        self.project_dir = project_dir
        self._ctx = HandoffContext()

    # ── Context setters ────────────────────────────────────────────────────

    def set_task(self, task: str) -> "SessionHandoff":
        """Set the primary task description."""
        self._ctx.task = task.strip()
        return self

    def set_status(self, status: str) -> "SessionHandoff":
        """Set task status: 'in-progress', 'blocked', or 'done'."""
        self._ctx.status = status.strip()
        return self

    def set_notes(self, notes: str) -> "SessionHandoff":
        """Set free-form session notes."""
        self._ctx.notes = notes.strip()
        return self

    def add_file_context(
        self,
        path: str,
        role: str = "read",
        summary: str = "",
    ) -> "SessionHandoff":
        """Add a file that was involved in the session.

        Args:
            path: File path (absolute or relative to project_dir).
            role: One of "read", "modified", "created", "deleted".
            summary: Optional description of what was done with this file.
        """
        # Shorten to project-relative path when possible
        display_path = path
        if self.project_dir:
            try:
                display_path = str(Path(path).relative_to(self.project_dir))
            except ValueError:
                pass
        self._ctx.files.append(FileContext(path=display_path, role=role, summary=summary))
        return self

    def add_decision(self, decision: str) -> "SessionHandoff":
        """Record a key design or implementation decision made during the session."""
        self._ctx.decisions.append(decision.strip())
        return self

    def add_todo(self, todo: str) -> "SessionHandoff":
        """Add a pending work item that the next session should tackle."""
        self._ctx.todos.append(todo.strip())
        return self

    def add_constraint(self, constraint: str) -> "SessionHandoff":
        """Add a constraint or gotcha the receiving harness should know about."""
        self._ctx.constraints.append(constraint.strip())
        return self

    # ── Rendering ─────────────────────────────────────────────────────────

    def render(self, target_harness: str = "default") -> str:
        """Render the handoff prompt for *target_harness*.

        Args:
            target_harness: Name of the receiving harness (e.g. "gemini").

        Returns:
            A paste-ready prompt string.
        """
        ctx = self._ctx
        intro = _HARNESS_INTROS.get(target_harness.lower(), _HARNESS_INTROS["default"])

        project_line = ""
        if self.project_dir:
            project_line = f"Project: {self.project_dir}"

        # Files section
        if ctx.files:
            file_lines = []
            role_icons = {"modified": "✎", "created": "+", "deleted": "✗", "read": "·"}
            for fc in ctx.files:
                icon = role_icons.get(fc.role, "·")
                line = f"  {icon} {fc.path} ({fc.role})"
                if fc.summary:
                    line += f" — {fc.summary}"
                file_lines.append(line)
            files_section = "\n".join(file_lines)
        else:
            files_section = "  (no specific files recorded)"

        # Decisions section
        if ctx.decisions:
            decisions_section = (
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "KEY DECISIONS\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                + "\n".join(f"  • {d}" for d in ctx.decisions)
                + "\n\n"
            )
        else:
            decisions_section = ""

        # Todos section
        if ctx.todos:
            todos_section = (
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "PENDING WORK\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                + "\n".join(f"  ☐ {t}" for t in ctx.todos)
                + "\n\n"
            )
            next_step = ctx.todos[0]
        else:
            todos_section = ""
            next_step = "Continue the task described above."

        # Constraints section
        if ctx.constraints:
            constraints_section = (
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "CONSTRAINTS & GOTCHAS\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                + "\n".join(f"  ⚠ {c}" for c in ctx.constraints)
                + "\n\n"
            )
        else:
            constraints_section = ""

        # Notes section
        notes_section = ""
        if ctx.notes:
            notes_section = (
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "NOTES\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                + textwrap.indent(ctx.notes, "  ")
                + "\n\n"
            )

        task_text = ctx.task or "(no task description provided)"

        prompt = _TEMPLATE.format(
            intro=intro,
            task=task_text,
            status=ctx.status,
            project_line=project_line,
            files_section=files_section,
            decisions_section=decisions_section,
            todos_section=todos_section,
            constraints_section=constraints_section,
            notes_section=notes_section,
            next_step=next_step,
        )

        # Collapse excessive blank lines
        prompt = re.sub(r"\n{3,}", "\n\n", prompt)
        return prompt.strip()

    def to_dict(self) -> dict:
        """Serialise the handoff context to a plain dict (for JSON export)."""
        ctx = self._ctx
        return {
            "task": ctx.task,
            "status": ctx.status,
            "files": [
                {"path": f.path, "role": f.role, "summary": f.summary}
                for f in ctx.files
            ],
            "decisions": ctx.decisions,
            "todos": ctx.todos,
            "constraints": ctx.constraints,
            "notes": ctx.notes,
        }

    @classmethod
    def from_dict(cls, data: dict, project_dir: Path | None = None) -> "SessionHandoff":
        """Reconstruct a SessionHandoff from a previously serialised dict."""
        h = cls(project_dir=project_dir)
        h._ctx.task = data.get("task", "")
        h._ctx.status = data.get("status", "in-progress")
        h._ctx.notes = data.get("notes", "")
        for f in data.get("files", []):
            h._ctx.files.append(FileContext(**f))
        h._ctx.decisions = list(data.get("decisions", []))
        h._ctx.todos = list(data.get("todos", []))
        h._ctx.constraints = list(data.get("constraints", []))
        return h
