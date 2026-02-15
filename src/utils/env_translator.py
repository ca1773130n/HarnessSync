"""Environment variable translation and transport detection utilities.

Provides translation pipeline for MCP server configs between Claude Code format
and target CLI formats:

- ENV-01: Codex requires literal env maps (no ${VAR} interpolation in config.toml)
- ENV-02: ${VAR:-default} syntax must be expanded at sync time for Codex
- ENV-03: Gemini supports ${VAR} natively, no translation needed

Updates Decision #13: v1.0 preserved ${VAR} in TOML; v2.0 translates for Codex
since Codex doesn't support runtime variable interpolation.

Transport detection validates MCP server compatibility per target CLI:
- Codex: stdio + http (NO SSE)
- Gemini: stdio + http + sse
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
TRANSPORT_SUPPORT = {
    "codex": {"stdio", "http"},
    "gemini": {"stdio", "http", "sse"},
    "opencode": {"stdio", "http"},
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


def preserve_env_vars_for_gemini(config: dict) -> tuple[dict, list[str]]:
    """Pass config through unchanged for Gemini (ENV-03).

    Gemini supports ${VAR} natively in settings.json, so no translation needed.
    Returns a shallow copy for safety (not the same object reference).

    Args:
        config: Claude Code MCP server config dict

    Returns:
        Tuple of (config_copy, empty_warnings)
    """
    return config.copy(), []


def detect_transport_type(config: dict) -> str:
    """Detect MCP server transport type from config.

    Args:
        config: MCP server config dict

    Returns:
        Transport type: "stdio", "sse", "http", or "unknown"
    """
    if 'command' in config:
        return 'stdio'
    elif 'url' in config:
        url = config['url']
        if isinstance(url, str) and (url.endswith('/sse') or 'sse' in url.lower()):
            return 'sse'
        return 'http'
    return 'unknown'


def check_transport_support(server_name: str, config: dict, target: str) -> tuple[bool, str]:
    """Check if target CLI supports the MCP server's transport type.

    Args:
        server_name: MCP server name (for warning messages)
        config: MCP server config dict
        target: Target CLI name ("codex", "gemini", "opencode")

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

    # --- Test preserve_env_vars_for_gemini ---

    # Test 5: Config passed through unchanged
    config = {"command": "server", "args": ["${TEST_KEY}"], "env": {"X": "1"}}
    result, warns = preserve_env_vars_for_gemini(config)
    assert result["args"][0] == "${TEST_KEY}", "Gemini should preserve ${VAR}"
    assert len(warns) == 0, "No warnings for Gemini passthrough"
    assert result is not config, "Should return copy, not same object"

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

    # Test 12: SSE on gemini (supported)
    ok, _ = check_transport_support("sse-server", {"url": "https://x/sse"}, "gemini")
    assert ok, "SSE should be supported on Gemini"

    # Test 13: unknown transport
    ok, msg = check_transport_support("bad-server", {}, "codex")
    assert not ok, "Unknown transport should not be supported"
    assert "unknown" in msg.lower(), f"Message should mention unknown: {msg}"

    # Cleanup
    os.environ.pop("TEST_KEY", None)

    print("All env_translator inline tests passed!")
