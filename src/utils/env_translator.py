from __future__ import annotations

"""Environment variable translation and transport detection utilities.

Provides translation pipeline for MCP server configs between Claude Code format
and target CLI formats:

- ENV-01: Codex requires literal env maps (no ${VAR} interpolation in config.toml)
- ENV-02: ${VAR:-default} syntax must be expanded at sync time for Codex
- ENV-03: Cursor supports ${VAR} natively, no translation needed

Updates Decision #13: v0.0.1 preserved ${VAR} in TOML; v0.0.2 translates for Codex
since Codex doesn't support runtime variable interpolation.

Transport detection validates MCP server compatibility per target CLI:
- Codex: stdio + http (NO SSE)
- Cursor: stdio + http + sse
- OpenCode: stdio + http (NO SSE)
"""

import copy
import os
import re


# Regex pattern for bash-style environment variable references
# Matches: ${VAR_NAME} and ${VAR_NAME:-default_value}
# Only uppercase + underscore convention per research recommendation
VAR_PATTERN = re.compile(r'\$\{([A-Z_][A-Z0-9_]*)(:-([^}]+))?\}')

# Transport support matrix per target CLI
# Covers all harnesses HarnessSync syncs to.
# Empty set means the harness writes config but never executes MCP servers.
TRANSPORT_SUPPORT = {
    "codex":    {"stdio", "http"},
    "opencode": {"stdio", "http"},
    "cursor":   {"stdio", "http", "sse"},
    "aider":    set(),               # Name written to .aider.conf.yml only
    "windsurf": {"stdio", "http", "sse"},
    "cline":    {"stdio", "http", "sse"},
    "continue": {"stdio", "http"},
    "zed":      {"stdio", "http"},
    "neovim":   {"stdio", "http", "sse"},
    "vscode":   set(),               # No MCP support in VS Code AI extensions
}


def translate_env_vars_for_codex(config: dict) -> tuple[dict, list[str]]:
    """Extract ${VAR} references from config and resolve to Codex env map.

    Codex does not support ${VAR} interpolation in config.toml. This function:
    1. Scans all string values in command, url, args, and env fields
    2. Resolves ${VAR} from os.environ, ${VAR:-default} uses default when unset
    3. Replaces references with resolved values in the config
    4. Merges extracted vars into config's env dict (existing entries win on conflict)

    Args:
        config: Claude Code MCP server config dict (NOT mutated)

    Returns:
        Tuple of (translated_config, warnings)
        - translated_config: Deep copy with resolved values and merged env map
        - warnings: List of warning messages for undefined vars
    """
    config = copy.deepcopy(config)
    env_map = {}
    warnings = []

    def _resolve(text: str) -> str:
        """Replace ${VAR} references in text with resolved values."""
        def replacer(match):
            var_name = match.group(1)
            default_value = match.group(3)  # May be None

            env_value = os.environ.get(var_name)

            if env_value is not None:
                env_map[var_name] = env_value
                return env_value
            elif default_value is not None:
                warnings.append(
                    f"ENV var ${{{var_name}}} not set, using default: {default_value}"
                )
                return default_value
            else:
                warnings.append(
                    f"ENV var ${{{var_name}}} not set and no default provided"
                )
                return ""

        return VAR_PATTERN.sub(replacer, text)

    # Process command field
    if 'command' in config and isinstance(config['command'], str):
        config['command'] = _resolve(config['command'])

    # Process url field
    if 'url' in config and isinstance(config['url'], str):
        config['url'] = _resolve(config['url'])

    # Process args list
    if 'args' in config and isinstance(config['args'], list):
        config['args'] = [
            _resolve(arg) if isinstance(arg, str) else arg
            for arg in config['args']
        ]

    # Process env dict values
    if 'env' in config and isinstance(config['env'], dict):
        for k, v in config['env'].items():
            if isinstance(v, str):
                config['env'][k] = _resolve(v)

    # Merge extracted env vars into config's env dict
    # Existing env entries win on conflict (user-specified values take priority)
    if env_map:
        existing_env = config.get('env', {})
        config['env'] = {**env_map, **existing_env}

    return config, warnings


def translate_env_vars_for_opencode_headers(headers: dict) -> tuple[dict, list[str]]:
    """Translate ${VAR} references in MCP headers to OpenCode {env:VAR} syntax.

    OpenCode uses {env:VAR_NAME} for environment variable interpolation in headers,
    not the ${VAR_NAME} syntax used by Claude Code. This function translates header
    string values only -- do NOT apply to url, command, or environment fields.

    Args:
        headers: Dict of header name -> header value

    Returns:
        Tuple of (translated_headers, warnings)
        - translated_headers: New dict with ${VAR} replaced by {env:VAR}
        - warnings: List of warnings for default value stripping
    """
    translated = {}
    warnings = []

    for key, value in headers.items():
        if isinstance(value, str):
            def _replacer(match, _key=key):
                var_name = match.group(1)
                default_part = match.group(2)  # e.g., ":-fallback" or None
                if default_part is not None:
                    # Strip the leading ":-" to get the default value
                    default_value = default_part[2:]
                    warnings.append(
                        f"Header '{_key}': default value '{default_value}' "
                        f"stripped (OpenCode {{env:VAR}} does not support defaults)"
                    )
                return f'{{env:{var_name}}}'

            translated[key] = VAR_PATTERN.sub(_replacer, value)
        else:
            translated[key] = value

    return translated, warnings


def detect_transport_type(config: dict) -> str:
    """Detect MCP server transport type from config.

    Args:
        config: MCP server config dict

    Returns:
        Transport type: "stdio", "sse", "http", or "unknown"

    Notes:
        - An explicit ``type`` field (Claude Code ``.mcp.json``) takes precedence.
        - ``streamable-http`` (and variants) is normalized to ``http`` — it is the
          modern streamable HTTP transport, of which ``http`` is the canonical name.
        - ``sse`` is recognized but deprecated (see ``transport_deprecation``).
    """
    explicit = config.get('type')
    if isinstance(explicit, str):
        t = explicit.strip().lower().replace('_', '-')
        if t in ('streamable-http', 'streamablehttp', 'http'):
            return 'http'
        if t == 'sse':
            return 'sse'
        if t == 'stdio':
            return 'stdio'

    if 'command' in config:
        return 'stdio'
    elif 'url' in config:
        url = config['url']
        if isinstance(url, str) and (url.endswith('/sse') or 'sse' in url.lower()):
            return 'sse'
        return 'http'
    return 'unknown'


def transport_deprecation(server_name: str, config: dict) -> str:
    """Return a deprecation warning if a server uses the deprecated SSE transport.

    Claude Code deprecated the standalone ``sse`` MCP transport in favor of the
    streamable ``http`` transport. This returns a non-empty advisory string for
    SSE servers so callers can surface it; empty string otherwise.
    """
    if detect_transport_type(config) == 'sse':
        return (
            f"MCP server '{server_name}': SSE transport is deprecated; "
            f"prefer the streamable 'http' transport."
        )
    return ""


def check_transport_support(server_name: str, config: dict, target: str) -> tuple[bool, str]:
    """Check if target CLI supports the MCP server's transport type.

    Args:
        server_name: MCP server name (for warning messages)
        config: MCP server config dict
        target: Target CLI name ("codex", "cursor", "opencode")

    Returns:
        Tuple of (is_supported, warning_message)
        - (True, "") if supported
        - (False, warning_message) if unsupported or unknown
    """
    transport = detect_transport_type(config)

    if transport == 'unknown':
        return False, (
            f"MCP server '{server_name}': unknown transport "
            f"(no command or url field)"
        )

    supported = TRANSPORT_SUPPORT.get(target, set())
    if transport in supported:
        return True, ""

    return False, (
        f"MCP server '{server_name}': {transport.upper()} transport not supported "
        f"by {target}. Supported: {', '.join(sorted(supported))}"
    )


# ---------------------------------------------------------------------------
# Cross-Harness Env Var Name Mapping (Item 25)
# ---------------------------------------------------------------------------
#
# Different AI coding harnesses use different environment variable names for
# the same semantic purpose. When syncing rules or instructions that mention
# specific env var names, we can translate them to the correct name for each
# target harness so the synced output is immediately actionable.
#
# Format: {canonical_name: {harness: harness_specific_name}}
# Canonical names follow Claude Code / Anthropic conventions.

HARNESS_ENV_VAR_REMAP: dict[str, dict[str, str]] = {
    # Primary API authentication key
    "ANTHROPIC_API_KEY": {
        "codex":    "ANTHROPIC_API_KEY",   # Codex supports Anthropic directly
        "opencode": "ANTHROPIC_API_KEY",
        "cursor":   "ANTHROPIC_API_KEY",
        "aider":    "ANTHROPIC_API_KEY",
        "windsurf": "ANTHROPIC_API_KEY",
    },
    # Default model selection
    "CLAUDE_MODEL": {
        "codex":    "OPENAI_DEFAULT_MODEL",
        "opencode": "OPENCODE_MODEL",
        "cursor":   "CURSOR_DEFAULT_MODEL",
        "aider":    "AIDER_MODEL",
        "windsurf": "WINDSURF_MODEL",
    },
    # Base URL for API proxy / custom endpoints
    "ANTHROPIC_BASE_URL": {
        "codex":    "OPENAI_BASE_URL",
        "opencode": "ANTHROPIC_BASE_URL",
        "cursor":   "OPENAI_API_BASE",
        "aider":    "OPENAI_API_BASE",
        "windsurf": "ANTHROPIC_BASE_URL",
    },
    # Disable streaming (useful in CI)
    "ANTHROPIC_STREAMING": {
        "codex":    "OPENAI_STREAM",
        "opencode": "ANTHROPIC_STREAMING",
        "cursor":   "CURSOR_STREAMING",
        "aider":    "AIDER_STREAM",
        "windsurf": "WINDSURF_STREAMING",
    },
    # Max token budget
    "ANTHROPIC_MAX_TOKENS": {
        "codex":    "OPENAI_MAX_TOKENS",
        "opencode": "ANTHROPIC_MAX_TOKENS",
        "cursor":   "CURSOR_MAX_TOKENS",
        "aider":    "AIDER_MAX_TOKENS",
        "windsurf": "WINDSURF_MAX_TOKENS",
    },
}

# Reverse map: harness-specific name -> canonical name
_REVERSE_REMAP: dict[str, dict[str, str]] = {}
for _canonical, _per_harness in HARNESS_ENV_VAR_REMAP.items():
    for _harness, _name in _per_harness.items():
        _REVERSE_REMAP.setdefault(_harness, {})[_name] = _canonical


def translate_env_var_names_in_text(text: str, target: str) -> tuple[str, list[str]]:
    """Rewrite canonical env var names in text content for a specific target harness.

    When CLAUDE.md instructions mention environment variable names (e.g.,
    "set ANTHROPIC_API_KEY"), this function rewrites them to the name the
    target harness expects, so the synced output is immediately actionable.

    Only rewrites names that appear as standalone tokens (word boundaries) to
    avoid false positives in code examples or prose.

    Args:
        text: Rules/instructions text that may mention env var names.
        target: Target harness name (e.g. "cursor", "codex").

    Returns:
        Tuple of (translated_text, list_of_replacements_made).
        replacements_made contains human-readable strings describing each change.
    """
    if not text:
        return text, []

    replacements: list[str] = []
    result = text

    for canonical, per_harness in HARNESS_ENV_VAR_REMAP.items():
        target_name = per_harness.get(target)
        if not target_name or target_name == canonical:
            continue  # No rename needed for this target

        # Replace whole-word occurrences only (avoid partial matches)
        pattern = re.compile(r'\b' + re.escape(canonical) + r'\b')
        if pattern.search(result):
            result = pattern.sub(target_name, result)
            replacements.append(f"{canonical} -> {target_name}")

    return result, replacements


def get_canonical_env_var_name(harness_name: str, harness: str) -> str | None:
    """Return the canonical (Claude Code) name for a harness-specific env var.

    Useful for reverse-translating harness configs back to CLAUDE.md format.

    Args:
        harness_name: Env var name as used in the target harness.
        harness: Target harness name.

    Returns:
        Canonical name if found, or None if not in the mapping.
    """
    return _REVERSE_REMAP.get(harness, {}).get(harness_name)


def list_env_var_mappings(target: str) -> list[tuple[str, str]]:
    """Return all env var name changes that would apply when syncing to target.

    Args:
        target: Target harness name.

    Returns:
        List of (canonical_name, target_name) tuples for vars that change names.
        Empty list if no renames are needed for this target.
    """
    result = []
    for canonical, per_harness in HARNESS_ENV_VAR_REMAP.items():
        target_name = per_harness.get(target)
        if target_name and target_name != canonical:
            result.append((canonical, target_name))
    return result


if __name__ == "__main__":
    # Inline sanity tests

    # --- Test translate_env_vars_for_codex ---

    # Test 1: Basic ${VAR} resolution
    os.environ["TEST_KEY"] = "resolved_value"
    result, warns = translate_env_vars_for_codex({
        "command": "server",
        "args": ["--key", "${TEST_KEY}"],
        "env": {"EXISTING": "kept"}
    })
    assert result["args"][1] == "resolved_value", f"Expected resolved_value, got {result['args'][1]}"
    assert result["env"]["TEST_KEY"] == "resolved_value", "TEST_KEY should be in env map"
    assert result["env"]["EXISTING"] == "kept", "Existing env should be preserved"
    assert len(warns) == 0, f"No warnings expected, got {warns}"

    # Test 2: ${VAR:-default} with unset var
    os.environ.pop("MISSING_VAR", None)
    result, warns = translate_env_vars_for_codex({
        "command": "server",
        "args": ["--port", "${MISSING_VAR:-fallback}"]
    })
    assert result["args"][1] == "fallback", f"Expected fallback, got {result['args'][1]}"
    assert len(warns) > 0, "Should have warning for missing var"
    assert "MISSING_VAR" in warns[0], f"Warning should mention MISSING_VAR: {warns[0]}"

    # Test 3: ${VAR} with no default and unset
    os.environ.pop("UNDEFINED_VAR", None)
    result, warns = translate_env_vars_for_codex({
        "command": "server",
        "args": ["${UNDEFINED_VAR}"]
    })
    assert result["args"][0] == "", f"Expected empty string, got {result['args'][0]}"
    assert len(warns) > 0, "Should have warning for undefined var"
    assert "not set" in warns[0], f"Warning should say not set: {warns[0]}"

    # Test 4: Input config not mutated
    original = {"command": "server", "args": ["${TEST_KEY}"]}
    original_copy = copy.deepcopy(original)
    translate_env_vars_for_codex(original)
    assert original == original_copy, "Original config should not be mutated"

    # --- Test detect_transport_type ---

    # Test 6: stdio
    assert detect_transport_type({"command": "npx", "args": ["-y", "server"]}) == "stdio"

    # Test 7: SSE URL
    assert detect_transport_type({"url": "https://example.com/mcp/sse"}) == "sse"

    # Test 8: HTTP URL
    assert detect_transport_type({"url": "https://api.example.com/mcp"}) == "http"

    # Test 9: unknown
    assert detect_transport_type({}) == "unknown"

    # --- Test check_transport_support ---

    # Test 10: stdio on codex (supported)
    ok, _ = check_transport_support("test", {"command": "x"}, "codex")
    assert ok, "Stdio should be supported on Codex"

    # Test 11: SSE on codex (NOT supported)
    ok, msg = check_transport_support("sse-server", {"url": "https://x/sse"}, "codex")
    assert not ok, "SSE should NOT be supported on Codex"
    assert "SSE" in msg, f"Message should mention SSE: {msg}"

    # Test 12: SSE on cursor (supported)
    ok, _ = check_transport_support("sse-server", {"url": "https://x/sse"}, "cursor")
    assert ok, "SSE should be supported on Cursor"

    # Test 13: unknown transport
    ok, msg = check_transport_support("bad-server", {}, "codex")
    assert not ok, "Unknown transport should not be supported"
    assert "unknown" in msg.lower(), f"Message should mention unknown: {msg}"

    # Cleanup
    os.environ.pop("TEST_KEY", None)

    print("All env_translator inline tests passed!")
