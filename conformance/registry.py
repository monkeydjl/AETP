"""Central registry for executable Conformance fixtures."""

from typing import Any, Callable, Dict

# Registry of executable fixture handlers: test_id -> callable(store, project_id) -> dict
FIXTURE_HANDLERS: Dict[str, Callable[..., Dict[str, Any]]] = {}


def register_fixture(test_id: str):
    """Decorator to register a conformance fixture handler."""
    def decorator(fn: Callable[..., Dict[str, Any]]):
        FIXTURE_HANDLERS[test_id] = fn
        return fn
    return decorator
