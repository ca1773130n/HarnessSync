"""MCP tool definitions with inputSchema and manual validation functions.

Defines three tools (sync_all, sync_target, get_status) with JSON Schema
compliant inputSchema dicts and manual validation functions since Python
stdlib has no JSON Schema validator.
"""

SYNC_ALL_TOOL = {
    "name": "sync_all",
    "description": "Sync all Claude Code configuration to all registered target CLIs (Codex, Gemini, OpenCode). Returns structured results with per-target sync counts and any errors.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "dry_run": {
                "type": "boolean",
                "description": "Preview changes without writing files",
                "default": False,
            },
            "allow_secrets": {
                "type": "boolean",
                "description": "Allow sync even when secrets detected in env vars",
                "default": False,
            },
        },
        "required": [],
    },
}

SYNC_TARGET_TOOL = {
    "name": "sync_target",
    "description": "Sync Claude Code configuration to a specific target CLI. Returns structured sync results for the specified target.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Target CLI to sync to",
                "enum": ["codex", "gemini", "opencode"],
            },
            "dry_run": {
                "type": "boolean",
                "description": "Preview changes without writing files",
                "default": False,
            },
            "allow_secrets": {
                "type": "boolean",
                "description": "Allow sync even when secrets detected in env vars",
                "default": False,
            },
        },
        "required": ["target"],
    },
}

GET_STATUS_TOOL = {
    "name": "get_status",
    "description": "Get sync status for all targets including last sync time, file counts, and drift detection (config modified outside HarnessSync).",
    "inputSchema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

TOOLS = [SYNC_ALL_TOOL, SYNC_TARGET_TOOL, GET_STATUS_TOOL]


def validate_sync_all_params(arguments: dict) -> dict:
    """Validate sync_all tool arguments.

    Args:
        arguments: Raw arguments dict (may be None).

    Returns:
        Normalized dict with dry_run and allow_secrets booleans.

    Raises:
        ValueError: If arguments are invalid.
    """
    if arguments is None:
        arguments = {}

    if not isinstance(arguments, dict):
        raise ValueError("Arguments must be an object")

    dry_run = arguments.get("dry_run", False)
    if not isinstance(dry_run, bool):
        raise ValueError("Parameter 'dry_run' must be a boolean")

    allow_secrets = arguments.get("allow_secrets", False)
    if not isinstance(allow_secrets, bool):
        raise ValueError("Parameter 'allow_secrets' must be a boolean")

    return {"dry_run": dry_run, "allow_secrets": allow_secrets}


def validate_sync_target_params(arguments: dict) -> dict:
    """Validate sync_target tool arguments.

    Args:
        arguments: Raw arguments dict.

    Returns:
        Normalized dict with target, dry_run, and allow_secrets.

    Raises:
        ValueError: If arguments are invalid or target is missing/invalid.
    """
    if arguments is None or not isinstance(arguments, dict):
        raise ValueError("Arguments must be an object")

    if "target" not in arguments:
        raise ValueError("Missing required parameter: target")

    target = arguments["target"]
    if not isinstance(target, str):
        raise ValueError("Parameter 'target' must be a string")

    valid_targets = ["codex", "gemini", "opencode"]
    if target not in valid_targets:
        raise ValueError(f"Invalid target: {target}. Must be one of: {', '.join(valid_targets)}")

    dry_run = arguments.get("dry_run", False)
    if not isinstance(dry_run, bool):
        raise ValueError("Parameter 'dry_run' must be a boolean")

    allow_secrets = arguments.get("allow_secrets", False)
    if not isinstance(allow_secrets, bool):
        raise ValueError("Parameter 'allow_secrets' must be a boolean")

    return {"target": target, "dry_run": dry_run, "allow_secrets": allow_secrets}


def validate_get_status_params(arguments: dict) -> dict:
    """Validate get_status tool arguments.

    Args:
        arguments: Raw arguments dict (ignored, no required params).

    Returns:
        Empty dict.
    """
    return {}


VALIDATORS = {
    "sync_all": validate_sync_all_params,
    "sync_target": validate_sync_target_params,
    "get_status": validate_get_status_params,
}
