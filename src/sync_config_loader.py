from __future__ import annotations

"""Project-level configuration loading and merging for HarnessSync.

Handles .harnesssync file parsing, conditional sync rules evaluation,
profile application, and branch-aware profile overrides. Extracted from
SyncOrchestrator to keep the orchestrator focused on sync coordination.
"""

import json
import os
from pathlib import Path

from src.utils.logger import Logger


def load_project_config(project_dir: Path | None) -> dict:
    """Load per-project .harnesssync config file overrides.

    The file at <project_dir>/.harnesssync (JSON) can override global
    sync options for this specific project:

    {
        "profile": "minimal",         // activate a named profile
        "skip_sections": ["mcp"],     // sections to skip (all targets)
        "only_sections": ["rules"],   // only these sections (all targets)
        "skip_targets": ["aider"],    // harness targets to exclude
        "only_targets": ["codex"],    // only these harness targets
        "targets": {                  // per-target section overrides (item 3)
            "cursor": {"skip_sections": ["skills"]},
            "aider":  {"only_sections": ["rules"]}
        }
    }

    Returns:
        Dict with project-level overrides (empty if file not found/invalid)
    """
    if not project_dir:
        return {}
    config_path = project_dir / ".harnesssync"
    if not config_path.exists():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


class ProjectConfigApplier:
    """Applies project-level .harnesssync overrides to orchestrator settings.

    This class encapsulates all the logic for merging project config with
    CLI flags, evaluating conditional sync rules, and applying branch profiles.
    """

    def __init__(
        self,
        project_dir: Path | None,
        scope: str,
        only_sections: set,
        skip_sections: set,
        logger: Logger | None = None,
    ):
        self.project_dir = project_dir
        self.scope = scope
        self.only_sections = set(only_sections)
        self.skip_sections = set(skip_sections)
        self.logger = logger or Logger()

        # Outputs set by apply()
        self.project_skip_targets: set[str] = set()
        self.project_only_targets: set[str] = set()
        self.profile_targets: list[str] | None = None
        self.per_target_skip: dict[str, set] = {}
        self.per_target_only: dict[str, set] = {}

    def apply(self, project_cfg: dict) -> None:
        """Merge project-level .harnesssync overrides into settings.

        After calling this method, read back the modified attributes:
        - scope, only_sections, skip_sections
        - project_skip_targets, project_only_targets
        - profile_targets
        - per_target_skip, per_target_only

        Args:
            project_cfg: Dict from load_project_config()
        """
        if not project_cfg:
            return

        self._apply_profile(project_cfg)
        self._apply_section_overrides(project_cfg)
        self._apply_target_overrides(project_cfg)
        self._apply_per_target_section_overrides(project_cfg)
        self._evaluate_conditional_rules(project_cfg)
        self._apply_branch_profile(project_cfg)

    def _apply_profile(self, project_cfg: dict) -> None:
        """Apply named profile if specified."""
        profile_name = project_cfg.get("profile")
        if not profile_name:
            return
        try:
            from src.profile_manager import ProfileManager
            pm = ProfileManager()
            base = {
                "scope": self.scope,
                "only_sections": self.only_sections,
                "skip_sections": self.skip_sections,
            }
            merged = pm.apply_to_kwargs(profile_name, base)
            self.scope = merged.get("scope", self.scope)
            self.only_sections = merged.get("only_sections", self.only_sections)
            self.skip_sections = merged.get("skip_sections", self.skip_sections)
            self.profile_targets = merged.get("profile_targets")
        except (KeyError, Exception):
            pass  # Profile not found or error -- proceed without it

    def _apply_section_overrides(self, project_cfg: dict) -> None:
        """Apply section-level skip/only overrides."""
        cfg_skip = set(project_cfg.get("skip_sections", []))
        if cfg_skip:
            self.skip_sections = self.skip_sections | cfg_skip

        cfg_only = set(project_cfg.get("only_sections", []))
        if cfg_only:
            # Intersect: only sync sections that both caller AND project want
            if self.only_sections:
                self.only_sections = self.only_sections & cfg_only
            else:
                self.only_sections = cfg_only

    def _apply_target_overrides(self, project_cfg: dict) -> None:
        """Apply target-level skip/only overrides."""
        self.project_skip_targets = set(project_cfg.get("skip_targets", []))
        self.project_only_targets = set(project_cfg.get("only_targets", []))

    def _apply_per_target_section_overrides(self, project_cfg: dict) -> None:
        """Apply per-target section overrides (Per-Feature Sync Toggles).

        Config format in .harnesssync:
          "targets": {
            "cursor": {"skip_sections": ["skills"]},
            "aider":  {"only_sections": ["rules"]}
          }
        """
        self.per_target_skip = {}
        self.per_target_only = {}
        for tgt, tgt_cfg in project_cfg.get("targets", {}).items():
            tgt = tgt.lower()
            tgt_skip = set(tgt_cfg.get("skip_sections", []))
            tgt_only = set(tgt_cfg.get("only_sections", []))
            if tgt_skip:
                self.per_target_skip[tgt] = tgt_skip
            if tgt_only:
                self.per_target_only[tgt] = tgt_only

    def _evaluate_conditional_rules(self, project_cfg: dict) -> None:
        """Evaluate sync_conditions entries and apply their actions.

        Supported predicate keys:
          "if_file_exists": "<relative-path>"        -- true when file present
          "if_file_missing": "<relative-path>"       -- true when file absent
          "if_file_size_gt": {"<path>": <bytes>}     -- true when file exceeds size
          "if_env_set": "<VAR_NAME>"                 -- true when env var is non-empty

        Supported action keys:
          "then_skip_targets": [...]              -- add targets to skip list
          "then_only_targets": [...]              -- restrict to these targets only
          "then_skip_sections": [...]             -- add sections to skip
          "then_only_sections": [...]             -- restrict to these sections
        """
        try:
            conditions = project_cfg.get("sync_conditions", [])
            if not conditions or not self.project_dir:
                return

            for cond in conditions:
                if not isinstance(cond, dict):
                    continue

                # --- Evaluate predicate ---
                satisfied = False

                if "if_file_exists" in cond:
                    fp = self.project_dir / cond["if_file_exists"]
                    satisfied = fp.exists()
                elif "if_file_missing" in cond:
                    fp = self.project_dir / cond["if_file_missing"]
                    satisfied = not fp.exists()
                elif "if_file_size_gt" in cond:
                    size_map = cond["if_file_size_gt"]
                    if isinstance(size_map, dict):
                        for rel, thresh in size_map.items():
                            fp = self.project_dir / rel
                            if fp.exists():
                                try:
                                    if fp.stat().st_size > int(thresh):
                                        satisfied = True
                                        break
                                except OSError:
                                    pass
                elif "if_env_set" in cond:
                    env_name = cond["if_env_set"]
                    satisfied = bool(os.environ.get(str(env_name), "").strip())

                if not satisfied:
                    continue

                # --- Apply actions ---
                skip_tgts = cond.get("then_skip_targets", [])
                if skip_tgts:
                    self.project_skip_targets = self.project_skip_targets | set(skip_tgts)

                only_tgts = cond.get("then_only_targets", [])
                if only_tgts:
                    existing = self.project_only_targets
                    if existing:
                        self.project_only_targets = existing & set(only_tgts)
                    else:
                        self.project_only_targets = set(only_tgts)

                skip_secs = cond.get("then_skip_sections", [])
                if skip_secs:
                    self.skip_sections = self.skip_sections | set(skip_secs)

                only_secs = cond.get("then_only_sections", [])
                if only_secs:
                    if self.only_sections:
                        self.only_sections = self.only_sections & set(only_secs)
                    else:
                        self.only_sections = set(only_secs)

                self.logger.info(f"Conditional sync rule applied: {cond}")

        except Exception as cond_err:
            self.logger.warn(f"Conditional sync rules evaluation failed: {cond_err}")

    def _apply_branch_profile(self, project_cfg: dict) -> None:
        """Apply git branch-aware profile overrides (most specific branch match wins)."""
        try:
            from src.branch_aware_sync import resolve_branch_profile, apply_branch_profile, describe_active_profile
            branch_profile = resolve_branch_profile(self.project_dir, project_cfg)
            if not branch_profile or branch_profile.is_empty:
                return

            import subprocess as _sp
            branch_name = ""
            try:
                r = _sp.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    capture_output=True, text=True,
                    cwd=str(self.project_dir), timeout=3,
                )
                branch_name = r.stdout.strip() if r.returncode == 0 else ""
            except Exception:
                pass

            (
                self.skip_sections,
                self.only_sections,
                self.project_skip_targets,
                self.project_only_targets,
                self.scope,
            ) = apply_branch_profile(
                branch_profile,
                self.skip_sections,
                self.only_sections,
                self.project_skip_targets,
                self.project_only_targets,
                self.scope,
            )
            if branch_name:
                self.logger.info(describe_active_profile(branch_profile, branch_name))
        except Exception as e:
            self.logger.warn(f"Branch profile resolution failed: {e}")
