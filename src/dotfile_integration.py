from __future__ import annotations

"""Dotfile manager integration for HarnessSync.

Generates HarnessSync-aware stanzas for popular dotfile managers so that
synced harness configurations are tracked in the user's dotfile repository.

Supported dotfile managers:
- chezmoi: Generates chezmoi source path entries for each synced target file
- yadm: Lists files as tracked paths for yadm add
- dotbot: Generates a link block for dotbot config (install.conf.yaml)
- bare git repo: Generic list of paths to git add

Solving the "my new machine doesn't have my AI rules" problem by ensuring
synced configs are checked into the user's dotfile repo.
"""

from dataclasses import dataclass, field
from pathlib import Path


# Known synced output files per target (relative to project_dir)
# Grouped by those that are project-specific vs user-global
_TARGET_PROJECT_FILES: dict[str, list[str]] = {
    "codex": ["AGENTS.md", ".codex/config.toml"],
    "gemini": ["GEMINI.md", ".gemini/settings.json"],
    "opencode": ["OPENCODE.md", ".opencode/settings.json"],
    "cursor": [".cursor/rules/claude-code-rules.mdc", ".cursor/mcp.json"],
    "aider": ["CONVENTIONS.md", ".aider.conf.yml"],
    "windsurf": [".windsurfrules"],
    "cline": [".clinerules", ".roo/mcp.json"],
    "continue": [".continue/rules/harnesssync.md", ".continue/config.json"],
    "zed": [".zed/system-prompt.md", ".zed/settings.json"],
    "neovim": [".avante/system-prompt.md", ".codecompanion/system-prompt.md", ".avante/mcp.json"],
}

# Files that are user-global (in $HOME, not project-specific)
# chezmoi/yadm track these differently
_USER_GLOBAL_FILE_PATTERNS: list[str] = [
    ".codex/config.toml",
    ".aider.conf.yml",
]


@dataclass
class DotfileStanza:
    """A generated dotfile manager stanza."""
    manager: str        # "chezmoi" | "yadm" | "dotbot" | "bare-git"
    content: str        # The stanza text to add to dotfile config
    instructions: str   # Human-readable usage instructions


@dataclass
class DotfileIntegrationReport:
    """Report containing stanzas for all requested dotfile managers."""
    stanzas: list[DotfileStanza] = field(default_factory=list)
    tracked_files: list[str] = field(default_factory=list)

    def format(self) -> str:
        """Format all stanzas as a human-readable guide."""
        lines = ["## HarnessSync Dotfile Manager Integration", ""]
        lines.append(
            "Add these stanzas to your dotfile manager to track synced "
            "HarnessSync configs on new machines.\n"
        )
        lines.append(f"Tracked files ({len(self.tracked_files)}):")
        for f in self.tracked_files:
            lines.append(f"  {f}")
        lines.append("")

        for stanza in self.stanzas:
            lines.append(f"### {stanza.manager.upper()}")
            lines.append("")
            lines.append(stanza.instructions)
            lines.append("")
            lines.append("```")
            lines.append(stanza.content)
            lines.append("```")
            lines.append("")

        return "\n".join(lines)


class DotfileIntegrationGenerator:
    """Generates dotfile manager integration stanzas for HarnessSync.

    Args:
        project_dir: Project root directory.
    """

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir

    def generate(
        self,
        managers: list[str] = None,
        targets: list[str] = None,
    ) -> DotfileIntegrationReport:
        """Generate dotfile manager stanzas.

        Args:
            managers: Dotfile managers to generate for. Defaults to all known:
                      ["chezmoi", "yadm", "dotbot", "bare-git"].
            targets: Targets to include files for (None = auto-detect from disk).

        Returns:
            DotfileIntegrationReport with stanzas and tracked file list.
        """
        if managers is None:
            managers = ["chezmoi", "yadm", "dotbot", "bare-git"]

        if targets is None:
            targets = self._detect_active_targets()

        # Collect all tracked files
        tracked_files = self._collect_tracked_files(targets)

        report = DotfileIntegrationReport(tracked_files=tracked_files)

        for manager in managers:
            stanza = self._generate_stanza(manager, tracked_files)
            if stanza:
                report.stanzas.append(stanza)

        return report

    def _detect_active_targets(self) -> list[str]:
        """Detect targets that have been synced by checking for output files."""
        active = []
        for target, files in _TARGET_PROJECT_FILES.items():
            for rel in files:
                if (self.project_dir / rel).is_file():
                    active.append(target)
                    break
        return active

    def _collect_tracked_files(self, targets: list[str]) -> list[str]:
        """Collect all synced output file paths that exist on disk."""
        files = []
        seen = set()
        for target in targets:
            for rel in _TARGET_PROJECT_FILES.get(target, []):
                if rel in seen:
                    continue
                p = self.project_dir / rel
                if p.is_file():
                    files.append(rel)
                    seen.add(rel)
        return sorted(files)

    def _generate_stanza(self, manager: str, tracked_files: list[str]) -> DotfileStanza | None:
        """Generate a stanza for a specific dotfile manager."""
        if manager == "chezmoi":
            return self._chezmoi_stanza(tracked_files)
        if manager == "yadm":
            return self._yadm_stanza(tracked_files)
        if manager == "dotbot":
            return self._dotbot_stanza(tracked_files)
        if manager == "bare-git":
            return self._bare_git_stanza(tracked_files)
        return None

    def _chezmoi_stanza(self, tracked_files: list[str]) -> DotfileStanza:
        """Generate chezmoi add commands."""
        commands = []
        for rel in tracked_files:
            commands.append(f"chezmoi add ~/{rel}")

        content = "\n".join(commands) if commands else "# No tracked files found"
        return DotfileStanza(
            manager="chezmoi",
            content=content,
            instructions=(
                "Run these commands to add HarnessSync output files to chezmoi. "
                "After syncing on a new machine, run: chezmoi apply"
            ),
        )

    def _yadm_stanza(self, tracked_files: list[str]) -> DotfileStanza:
        """Generate yadm add commands."""
        commands = ["# Add HarnessSync tracked files to yadm"]
        for rel in tracked_files:
            commands.append(f"yadm add ~/{rel}")
        commands.append("yadm commit -m 'Track HarnessSync config files'")

        return DotfileStanza(
            manager="yadm",
            content="\n".join(commands),
            instructions=(
                "Run these commands to add HarnessSync output files to yadm. "
                "After cloning on a new machine, run: yadm checkout"
            ),
        )

    def _dotbot_stanza(self, tracked_files: list[str]) -> DotfileStanza:
        """Generate a dotbot link block."""
        lines = [
            "# HarnessSync config files — add to install.conf.yaml",
            "- link:",
        ]
        for rel in tracked_files:
            # dotbot: target (home): source (dotfiles dir)
            lines.append(f"    ~/{rel}:")
            lines.append(f"      path: {rel}")
            lines.append(f"      create: true")

        return DotfileStanza(
            manager="dotbot",
            content="\n".join(lines),
            instructions=(
                "Add this block to your install.conf.yaml dotbot configuration. "
                "Dotbot will create symlinks from your dotfiles repo to these paths."
            ),
        )

    def _bare_git_stanza(self, tracked_files: list[str]) -> DotfileStanza:
        """Generate bare git repo add commands."""
        alias = "config"  # Common alias for bare git dotfile repos
        commands = [
            f"# Add to bare git dotfile repo (assuming alias: {alias}='git --git-dir=$HOME/.cfg --work-tree=$HOME')",
        ]
        for rel in tracked_files:
            commands.append(f"{alias} add ~/{rel}")
        commands.append(f"{alias} commit -m 'Track HarnessSync config files'")
        commands.append(f"{alias} push")

        return DotfileStanza(
            manager="bare-git",
            content="\n".join(commands),
            instructions=(
                "If you use a bare git repo for dotfiles (the atlassian method), "
                "run these commands to track HarnessSync output files."
            ),
        )
