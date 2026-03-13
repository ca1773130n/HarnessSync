from __future__ import annotations

"""Community Adapter Plugin SDK (item 25).

Provides the public interface and development tools for building third-party
HarnessSync adapters. A community adapter is a Python file that drops into
the adapters/ directory and is auto-discovered at runtime.

Quickstart
----------
Create ``adapters/myadapter.py`` with:

    from src.adapter_sdk import community_adapter
    from src.adapters.base import AdapterBase
    from src.adapters.result import SyncResult
    from pathlib import Path

    @community_adapter("myadapter")
    class MyAdapter(AdapterBase):
        @property
        def target_name(self) -> str:
            return "myadapter"

        def sync_rules(self, rules: list[dict]) -> SyncResult:
            result = SyncResult()
            for rule in rules:
                content = rule.get("content", "")
                out = self.project_dir / "MYADAPTER.md"
                out.write_text(content)
                result.synced += 1
            return result

        def sync_skills(self, skills: dict[str, Path]) -> SyncResult:
            return SyncResult(skipped=len(skills))

        def sync_agents(self, agents: list[dict]) -> SyncResult:
            return SyncResult(skipped=len(agents))

        def sync_commands(self, commands: list[dict]) -> SyncResult:
            return SyncResult(skipped=len(commands))

        def sync_mcp(self, mcp_config: dict) -> SyncResult:
            return SyncResult(skipped=1)

        def sync_settings(self, settings: dict) -> SyncResult:
            return SyncResult(skipped=1)

Public surface
--------------
- ``community_adapter(name)``   — registration decorator (wraps AdapterRegistry.register)
- ``AdapterBase``               — re-exported base class
- ``SyncResult``                — re-exported result dataclass
- ``AdapterValidator``          — validates a community adapter before publish
- ``discover_community_adapters(adapters_dir)`` — scan for .py files in adapters/
- ``AdapterManifest``           — optional metadata for a community adapter
"""

import importlib.util
import inspect
import sys
from dataclasses import dataclass, field
from pathlib import Path


# Re-export the essential types so adapter authors only need to import
# from src.adapter_sdk (one import).
from src.adapters.base import AdapterBase  # noqa: F401
from src.adapters.registry import AdapterRegistry
from src.adapters.result import SyncResult  # noqa: F401


# ---------------------------------------------------------------------------
# Registration decorator
# ---------------------------------------------------------------------------

def community_adapter(name: str):
    """Decorator to register a community adapter with HarnessSync.

    Wraps ``AdapterRegistry.register`` with additional checks so that
    community adapters get the same registration behaviour as built-in ones.

    Args:
        name: Unique target identifier (e.g. 'myadapter'). Must be lowercase
              and contain only [a-z0-9_-].

    Returns:
        Class decorator.

    Raises:
        ValueError: If name contains invalid characters or conflicts with a
                    built-in adapter name.

    Example::

        @community_adapter("myadapter")
        class MyAdapter(AdapterBase):
            ...
    """
    _BUILTIN_NAMES = frozenset({
        "codex", "gemini", "opencode", "cursor", "aider",
        "windsurf", "cline", "neovim", "vscode", "zed", "continue_dev",
    })

    import re as _re
    if not _re.match(r"^[a-z0-9][a-z0-9_-]*$", name):
        raise ValueError(
            f"community_adapter name {name!r} is invalid. "
            "Use only lowercase letters, digits, hyphens, and underscores."
        )
    if name in _BUILTIN_NAMES:
        raise ValueError(
            f"community_adapter name {name!r} conflicts with a built-in adapter. "
            f"Built-ins: {', '.join(sorted(_BUILTIN_NAMES))}"
        )

    return AdapterRegistry.register(name)


# ---------------------------------------------------------------------------
# Optional adapter metadata
# ---------------------------------------------------------------------------

@dataclass
class AdapterManifest:
    """Optional metadata for a community adapter.

    Not required for registration, but used by ``AdapterValidator`` and
    displayed in ``/sync-matrix``.

    Attributes:
        name: Target identifier (matches community_adapter name).
        display_name: Human-readable name (e.g. "My Harness").
        version: Semantic version string (e.g. "1.0.0").
        author: Author name or GitHub handle.
        description: One-line description.
        supported_transports: MCP transport protocols this adapter handles.
        config_files: List of files/dirs this adapter creates (relative to project_dir).
        homepage: URL to adapter documentation or repository.
    """

    name: str
    display_name: str = ""
    version: str = "0.1.0"
    author: str = ""
    description: str = ""
    supported_transports: list[str] = field(default_factory=lambda: ["stdio"])
    config_files: list[str] = field(default_factory=list)
    homepage: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name or self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "supported_transports": self.supported_transports,
            "config_files": self.config_files,
            "homepage": self.homepage,
        }


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Result of adapter validation."""

    adapter_name: str
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def format(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        lines = [f"Adapter '{self.adapter_name}': {status}"]
        for e in self.errors:
            lines.append(f"  ERROR: {e}")
        for w in self.warnings:
            lines.append(f"  WARN:  {w}")
        if self.passed and not self.warnings:
            lines.append("  All checks passed — adapter is ready to publish.")
        return "\n".join(lines)


class AdapterValidator:
    """Validates that a community adapter correctly implements AdapterBase.

    Checks:
    - Inherits from AdapterBase
    - Implements all required abstract methods
    - target_name property returns a non-empty string
    - sync_* methods accept expected argument signatures
    - Methods return SyncResult instances (runtime test with empty inputs)

    Usage::

        validator = AdapterValidator()
        result = validator.validate(MyAdapter)
        print(result.format())
    """

    # Required abstract methods and their expected first parameter name (after self)
    _REQUIRED_METHODS: dict[str, str] = {
        "sync_rules": "rules",
        "sync_skills": "skills",
        "sync_agents": "agents",
        "sync_commands": "commands",
        "sync_mcp": "mcp_config",
        "sync_settings": "settings",
    }

    def validate(self, adapter_class: type, tmp_dir: Path | None = None) -> ValidationResult:
        """Validate a community adapter class.

        Args:
            adapter_class: The adapter class to validate.
            tmp_dir: Optional temp directory for runtime smoke tests.
                     If None, runtime tests are skipped.

        Returns:
            ValidationResult with errors and warnings.
        """
        name = getattr(adapter_class, "__name__", str(adapter_class))
        errors: list[str] = []
        warnings: list[str] = []

        # 1. Inheritance check
        if not issubclass(adapter_class, AdapterBase):
            errors.append(f"{name} must inherit from AdapterBase (from src.adapters.base)")
            return ValidationResult(adapter_name=name, passed=False, errors=errors)

        # 2. Check all required methods exist
        for method_name in self._REQUIRED_METHODS:
            if not hasattr(adapter_class, method_name):
                errors.append(f"Missing required method: {method_name}()")
            else:
                method = getattr(adapter_class, method_name)
                if not callable(method):
                    errors.append(f"{method_name} must be callable")
                    continue
                # Check it's not still abstract
                if getattr(method, "__isabstractmethod__", False):
                    errors.append(f"{method_name}() is not implemented (still abstract)")

        # 3. Check target_name property
        try:
            if tmp_dir:
                instance = adapter_class(tmp_dir)
                tname = instance.target_name
            else:
                tname = adapter_class.__dict__.get("target_name")
                if isinstance(tname, property):
                    # Can't call without instance; check fget exists
                    if tname.fget is None:
                        errors.append("target_name property has no getter")
                    tname = None
            if tname is not None and not tname:
                errors.append("target_name must return a non-empty string")
        except Exception as e:
            warnings.append(f"Could not inspect target_name: {e}")

        # 4. Signature hints check
        for method_name, expected_param in self._REQUIRED_METHODS.items():
            method = getattr(adapter_class, method_name, None)
            if method is None:
                continue
            try:
                sig = inspect.signature(method)
                params = list(sig.parameters.keys())
                # First param is 'self'; second should be the data param
                if len(params) >= 2 and params[1] != expected_param:
                    warnings.append(
                        f"{method_name}() first param should be '{expected_param}' "
                        f"(got {params[1]!r}) — not blocking, but may confuse SDK users"
                    )
            except (ValueError, TypeError):
                pass  # Can't inspect; non-blocking

        # 5. Runtime smoke test (only if tmp_dir provided)
        if tmp_dir and not errors:
            try:
                instance = adapter_class(tmp_dir)
                smoke_errors = self._smoke_test(instance)
                errors.extend(smoke_errors)
            except Exception as e:
                errors.append(f"Could not instantiate adapter: {e}")

        # 6. Manifest check (optional)
        if not hasattr(adapter_class, "MANIFEST"):
            warnings.append(
                "No MANIFEST class attribute found. "
                "Consider adding an AdapterManifest for better discoverability."
            )

        passed = len(errors) == 0
        return ValidationResult(
            adapter_name=name,
            passed=passed,
            errors=errors,
            warnings=warnings,
        )

    def _smoke_test(self, instance: AdapterBase) -> list[str]:
        """Run sync methods with empty/minimal inputs and check return types."""
        errors: list[str] = []

        tests = [
            ("sync_rules", [], SyncResult),
            ("sync_skills", {}, SyncResult),
            ("sync_agents", [], SyncResult),
            ("sync_commands", [], SyncResult),
            ("sync_mcp", {}, SyncResult),
            ("sync_settings", {}, SyncResult),
        ]

        for method_name, arg, expected_type in tests:
            method = getattr(instance, method_name, None)
            if method is None:
                continue
            try:
                result = method(arg)
                if not isinstance(result, expected_type):
                    errors.append(
                        f"{method_name}() returned {type(result).__name__}, "
                        f"expected SyncResult"
                    )
            except Exception as e:
                errors.append(f"{method_name}() raised {type(e).__name__}: {e}")

        return errors


# ---------------------------------------------------------------------------
# Community adapter discovery
# ---------------------------------------------------------------------------

def discover_community_adapters(adapters_dir: Path) -> list[str]:
    """Scan an adapters/ directory for community adapter Python files.

    Files that match:
    - End with .py
    - Are not __init__.py, base.py, registry.py, result.py
    - Are not already registered as built-in adapters

    Returns:
        List of file paths (as strings) found. The adapters are NOT auto-imported
        — call load_community_adapter() for each one.

    Args:
        adapters_dir: Directory to scan.
    """
    _SKIP_FILES = frozenset({
        "__init__.py", "base.py", "registry.py", "result.py",
        "codex.py", "gemini.py", "opencode.py", "cursor.py",
        "aider.py", "windsurf.py", "cline.py", "neovim.py",
        "vscode.py", "zed.py", "continue_dev.py",
    })

    if not adapters_dir.is_dir():
        return []

    discovered = []
    for path in sorted(adapters_dir.glob("*.py")):
        if path.name not in _SKIP_FILES:
            discovered.append(str(path))
    return discovered


def load_community_adapter(path: str | Path) -> type | None:
    """Dynamically import and return the adapter class from a file.

    The file must define exactly one subclass of AdapterBase decorated with
    ``@community_adapter(name)`` (which auto-registers it).

    Args:
        path: Path to the adapter Python file.

    Returns:
        The adapter class if found and loaded successfully, else None.
    """
    path = Path(path)
    if not path.is_file():
        return None

    module_name = f"harnesssync_community_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[attr-defined]
    except Exception:
        return None

    # Find the adapter class defined in this module
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, AdapterBase) and obj is not AdapterBase:
            if obj.__module__ == module_name:
                return obj

    return None


# ---------------------------------------------------------------------------
# Community Adapter Generator (Item 12)
# ---------------------------------------------------------------------------

class AdapterWizard:
    """Interactive wizard that generates adapter stub code for new community harnesses.

    Item 12: Community Adapter Generator — produces a working adapter stub
    from user-provided harness metadata (config format, file locations).
    """

    def generate_stub(
        self,
        harness_name: str,
        config_file: str,
        config_format: str = "json",
        display_name: str = "",
        author: str = "",
        supports_mcp: bool = True,
        supports_skills: bool = False,
        rules_key: str = "rules",
    ) -> str:
        """Generate a complete adapter stub as a Python source string.

        Args:
            harness_name: Canonical name (lowercase, e.g. 'plandex').
            config_file: Relative path to the target config file (e.g. '.plandex/config.json').
            config_format: 'json', 'toml', or 'markdown'.
            display_name: Human-readable name (e.g. 'Plandex').
            author: Author/handle for the MANIFEST.
            supports_mcp: Whether the harness supports MCP servers.
            supports_skills: Whether the harness has native skill/prompt support.
            rules_key: JSON key for rules in the config file (if json format).

        Returns:
            Python source code string for the adapter module.
        """
        import re as _re
        if not _re.match(r'^[a-z0-9][a-z0-9_-]*$', harness_name):
            raise ValueError(f"Invalid harness_name: {harness_name!r}")

        display = display_name or harness_name.capitalize()
        class_name = "".join(w.capitalize() for w in _re.split(r'[-_]', harness_name)) + "Adapter"

        # Generate format-specific write logic
        if config_format == "json":
            write_logic = f'''        import json
        config_path = self.project_dir / {config_file!r}
        config_path.parent.mkdir(parents=True, exist_ok=True)
        existing = {{}}
        if config_path.exists():
            try:
                existing = json.loads(config_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        combined = "\\n\\n".join(r.get("content", str(r)) for r in rules)
        existing[{rules_key!r}] = combined
        config_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        result.files_written.append(str(config_path))'''
        elif config_format == "toml":
            write_logic = f'''        config_path = self.project_dir / {config_file!r}
        config_path.parent.mkdir(parents=True, exist_ok=True)
        combined = "\\n\\n".join(r.get("content", str(r)) for r in rules)
        lines = [f"# {display} rules — synced by HarnessSync\\n"]
        lines.append(f'[{harness_name}]\\n')
        lines.append(f'rules = """\\n{{combined}}\\n"""\\n')
        config_path.write_text("".join(lines), encoding="utf-8")
        result.files_written.append(str(config_path))'''
        else:  # markdown
            write_logic = f'''        config_path = self.project_dir / {config_file!r}
        config_path.parent.mkdir(parents=True, exist_ok=True)
        combined = "\\n\\n".join(r.get("content", str(r)) for r in rules)
        config_path.write_text(combined, encoding="utf-8")
        result.files_written.append(str(config_path))'''

        mcp_impl = f'''    def sync_mcp(self, mcp_config: dict) -> SyncResult:
        result = SyncResult()
        # TODO: write MCP server config to {config_file}
        # Example: merge mcp_config["mcpServers"] into the config file
        result.skipped = len(mcp_config.get("mcpServers", {{}}))
        return result''' if supports_mcp else f'''    def sync_mcp(self, mcp_config: dict) -> SyncResult:
        # {display} does not support MCP servers
        return SyncResult(skipped=len(mcp_config.get("mcpServers", {{}})))'''

        skills_impl = f'''    def sync_skills(self, skills: dict[str, Path]) -> SyncResult:
        result = SyncResult()
        # TODO: implement skill sync for {display}
        # skills is a dict mapping skill_name -> path to SKILL.md
        result.skipped = len(skills)
        return result''' if supports_skills else f'''    def sync_skills(self, skills: dict[str, Path]) -> SyncResult:
        # {display} has no native skill system — skip
        return SyncResult(skipped=len(skills))'''

        transports_str = '["stdio", "http"]' if supports_mcp else '[]'

        stub = f'''from __future__ import annotations
"""HarnessSync adapter for {display}.

Generated by AdapterWizard. Edit sync_* methods to match {display}'s config format.

Config file: {config_file}
Format: {config_format}

To register: place this file in the adapters/ directory and restart HarnessSync.
"""

from pathlib import Path
from src.adapter_sdk import community_adapter, AdapterBase, SyncResult, AdapterManifest


@community_adapter("{harness_name}")
class {class_name}(AdapterBase):

    MANIFEST = AdapterManifest(
        name="{harness_name}",
        display_name="{display}",
        version="0.1.0",
        author={author!r},
        description="{display} adapter for HarnessSync",
        supported_transports={transports_str},
        config_files=[{config_file!r}],
    )

    @property
    def target_name(self) -> str:
        return "{harness_name}"

    def sync_rules(self, rules: list[dict]) -> SyncResult:
        result = SyncResult()
        if not rules:
            return result
{write_logic}
        result.synced = len(rules)
        return result

{skills_impl}

    def sync_agents(self, agents: list[dict]) -> SyncResult:
        # TODO: translate agents to {display} format if supported
        return SyncResult(skipped=len(agents))

    def sync_commands(self, commands: list[dict]) -> SyncResult:
        # TODO: translate slash commands to {display} format if supported
        return SyncResult(skipped=len(commands))

{mcp_impl}

    def sync_settings(self, settings: dict) -> SyncResult:
        # TODO: map Claude Code settings to {display} equivalents
        return SyncResult(skipped=1)
'''
        return stub

    def write_stub(
        self,
        harness_name: str,
        output_dir: Path,
        **kwargs,
    ) -> Path:
        """Write the generated stub to output_dir/<harness_name>.py.

        Args:
            harness_name: Canonical harness name.
            output_dir: Directory to write the stub file into.
            **kwargs: Additional args forwarded to generate_stub().

        Returns:
            Path to the written stub file.
        """
        stub = self.generate_stub(harness_name, **kwargs)
        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / f"{harness_name}.py"
        out.write_text(stub, encoding="utf-8")
        return out

    def generate_pr_files(
        self,
        harness_name: str,
        output_dir: Path,
        **kwargs,
    ) -> dict[str, Path]:
        """Generate a PR-ready directory structure for a new community adapter.

        Creates three files in ``output_dir/`` ready for a GitHub pull request:
          - ``src/adapters/<harness_name>.py``  — the adapter implementation stub
          - ``tests/test_adapter_<harness_name>.py`` — a pytest test module stub
          - ``ADAPTER_CONTRIBUTION.md``          — contribution notes/checklist

        This lowers the barrier for community contributors: they get a working
        directory structure, not just a single code file.

        Args:
            harness_name: Canonical harness name (e.g. 'plandex').
            output_dir: Root directory to write the PR structure into.
            **kwargs: Additional args forwarded to generate_stub() (config_file,
                      config_format, display_name, author, supports_mcp, etc.).

        Returns:
            Dict mapping role -> Path for each written file:
            ``{"adapter": ..., "test": ..., "notes": ...}``
        """
        import re as _re
        display = kwargs.get("display_name") or harness_name.capitalize()

        # 1. Adapter stub
        adapter_dir = output_dir / "src" / "adapters"
        adapter_path = self.write_stub(harness_name, adapter_dir, **kwargs)

        # 2. Test stub
        test_dir = output_dir / "tests"
        test_dir.mkdir(parents=True, exist_ok=True)
        test_path = test_dir / f"test_adapter_{harness_name}.py"
        test_content = f'''from __future__ import annotations
"""Tests for the {display} community adapter.

Generated by AdapterWizard. Replace the placeholder assertions with real
behaviour checks for the {display} config format.
"""

import json
import sys
from pathlib import Path

import pytest

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.adapters.{harness_name} import {_to_class_name(harness_name)}


@pytest.fixture
def adapter(tmp_path):
    return {_to_class_name(harness_name)}(tmp_path)


def test_target_name(adapter):
    assert adapter.target_name == {harness_name!r}


def test_sync_rules_writes_file(adapter, tmp_path):
    rules = [{{"content": "Always write tests.", "name": "test-rule"}}]
    result = adapter.sync_rules(rules)
    assert result.synced > 0 or result.skipped >= 0  # basic smoke test


def test_sync_mcp_no_error(adapter):
    mcp = {{"mcpServers": {{"test": {{"command": "npx", "args": []}}}}}}
    result = adapter.sync_mcp(mcp)
    # Should not raise; skipped is acceptable if harness doesn't support MCP
    assert result is not None


def test_sync_settings_no_error(adapter):
    result = adapter.sync_settings({{"env": {{}}}})
    assert result is not None
'''
        test_path.write_text(test_content, encoding="utf-8")

        # 3. Contribution notes checklist
        notes_path = output_dir / "ADAPTER_CONTRIBUTION.md"
        notes_content = f'''# {display} Adapter Contribution

Generated by HarnessSync AdapterWizard. Complete the checklist before opening a PR.

## Files

| File | Purpose |
|------|---------|
| `src/adapters/{harness_name}.py` | Adapter implementation |
| `tests/test_adapter_{harness_name}.py` | pytest test suite |

## Pre-PR Checklist

- [ ] Implement all `sync_*` methods in `src/adapters/{harness_name}.py`
- [ ] Verify config is written to the correct path for {display}
- [ ] All tests in `tests/test_adapter_{harness_name}.py` pass (`pytest tests/test_adapter_{harness_name}.py`)
- [ ] Run `python -c "from src.adapter_sdk import AdapterValidator, {_to_class_name(harness_name)}; \\
       from src.adapters.{harness_name} import {_to_class_name(harness_name)}; \\
       print(AdapterValidator().validate({_to_class_name(harness_name)}).format())"` — must show PASS
- [ ] Test against a real {display} installation (not just tmp_path)
- [ ] Update `README.md` to list {display} in the supported harnesses table
- [ ] Add entry to `src/adapters/registry.py` if auto-discovery doesn\'t cover it

## Notes

Add any {display}-specific integration notes here (config schema quirks, version
constraints, known limitations, etc.).
'''
        notes_path.write_text(notes_content, encoding="utf-8")

        return {"adapter": adapter_path, "test": test_path, "notes": notes_path}


def _to_class_name(harness_name: str) -> str:
    """Convert 'my-harness' or 'my_harness' to 'MyHarnessAdapter'."""
    import re as _re
    return "".join(w.capitalize() for w in _re.split(r"[-_]", harness_name)) + "Adapter"
