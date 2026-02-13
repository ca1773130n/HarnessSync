"""Decorator-based adapter registry.

AdapterRegistry enables self-registering adapters using the decorator pattern.
This follows the Open/Closed Principle: adding new adapters requires no changes
to core engine code, only writing a new adapter class with the decorator.

Example usage:
    @AdapterRegistry.register('codex')
    class CodexAdapter(AdapterBase):
        @property
        def target_name(self) -> str:
            return 'codex'

        def sync_rules(self, rules: list[dict]) -> SyncResult:
            # Implementation
            pass

        # ... implement other sync methods ...

    # Later, in engine code:
    adapter = AdapterRegistry.get_adapter('codex', Path('/project'))
    result = adapter.sync_rules([...])

The registry validates adapter inheritance at registration time (not instantiation),
catching errors early during module import.
"""

from pathlib import Path
from .base import AdapterBase


class AdapterRegistry:
    """Registry for target adapters with decorator-based registration."""

    _adapters: dict[str, type[AdapterBase]] = {}

    @classmethod
    def register(cls, target_name: str):
        """Decorator to register an adapter class.

        Args:
            target_name: Target CLI identifier (e.g., 'codex', 'gemini')

        Returns:
            Decorator function that validates and registers the adapter

        Raises:
            TypeError: If adapter class does not inherit from AdapterBase
        """
        def decorator(adapter_class: type[AdapterBase]):
            # Validate inheritance at registration time
            if not issubclass(adapter_class, AdapterBase):
                raise TypeError(
                    f"{adapter_class.__name__} must inherit from AdapterBase"
                )

            # Register the adapter
            cls._adapters[target_name] = adapter_class

            # Return class unchanged for normal class usage
            return adapter_class

        return decorator

    @classmethod
    def get_adapter(cls, target_name: str, project_dir: Path) -> AdapterBase:
        """Instantiate and return a registered adapter.

        Args:
            target_name: Target CLI identifier
            project_dir: Project directory to pass to adapter

        Returns:
            Instantiated adapter

        Raises:
            ValueError: If target_name is not registered
        """
        adapter_class = cls._adapters.get(target_name)
        if not adapter_class:
            raise ValueError(
                f"No adapter registered for '{target_name}'. "
                f"Available: {', '.join(cls.list_targets())}"
            )

        return adapter_class(project_dir)

    @classmethod
    def list_targets(cls) -> list[str]:
        """List all registered target names.

        Returns:
            Sorted list of registered target identifiers
        """
        return sorted(cls._adapters.keys())

    @classmethod
    def has_target(cls, target_name: str) -> bool:
        """Check if a target is registered.

        Args:
            target_name: Target CLI identifier to check

        Returns:
            True if target is registered, False otherwise
        """
        return target_name in cls._adapters
