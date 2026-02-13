"""Adapter framework for syncing Claude Code config to different target CLIs.

This package provides the core adapter infrastructure:
- AdapterBase: Abstract base class defining the sync interface
- AdapterRegistry: Decorator-based registry for adapter discovery
- SyncResult: Structured dataclass for tracking sync outcomes

Target adapters (Codex, Gemini, OpenCode) implement AdapterBase and register
themselves using @AdapterRegistry.register('target-name').

Example usage:
    from src.adapters import AdapterRegistry, SyncResult
    from pathlib import Path

    # Get adapter for target CLI
    adapter = AdapterRegistry.get_adapter('codex', Path('/project'))

    # Sync configuration
    results = adapter.sync_all({
        'rules': [...],
        'skills': {...},
        'agents': {...},
        'commands': {...},
        'mcp': {...},
        'settings': {...},
    })

    # Check results
    for config_type, result in results.items():
        print(f"{config_type}: {result.status} - {result.synced} synced")
"""

from .base import AdapterBase
from .registry import AdapterRegistry
from .result import SyncResult

# Import adapter modules to trigger @AdapterRegistry.register() decorators
from . import codex  # noqa: F401
from . import gemini  # noqa: F401
from . import opencode  # noqa: F401

__all__ = [
    'AdapterBase',
    'AdapterRegistry',
    'SyncResult',
]
