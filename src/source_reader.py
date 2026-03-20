from __future__ import annotations

"""Re-export facade for Claude Code configuration discovery.

This module re-exports SourceReader and related utilities from their
sub-modules to maintain backward compatibility. All existing imports
continue to work:

    from src.source_reader import SourceReader
    from src.source_reader import substitute_config_vars
    from src.source_reader import filter_rules_for_harness

Implementation is split across:
- src/config_discovery.py   -- SourceReader class (rules, discovery, source paths)
- src/mcp_reader.py         -- MCPReaderMixin (MCP servers, plugins)
- src/modular_reader.py     -- ModularReaderMixin (skills, agents, commands, settings, hooks)
- src/harness_annotation.py -- filter_rules_for_harness() and annotation regexes
- src/config_vars.py        -- substitute_config_vars() and variable resolution
"""

# Core class
from src.config_discovery import SourceReader

# Standalone functions
from src.harness_annotation import filter_rules_for_harness
from src.config_vars import substitute_config_vars

__all__ = [
    "SourceReader",
    "filter_rules_for_harness",
    "substitute_config_vars",
]
