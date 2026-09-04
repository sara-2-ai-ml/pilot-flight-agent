"""Coordinator architecture tests — Phase 4.5."""

import ast
from pathlib import Path


def test_coordinator_does_not_import_tools_or_api_clients() -> None:
    source = Path("app/agent/coordinator.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden_prefixes = (
        "app.tools",
        "app.mcp",
    )
    forbidden_modules = (
        "lufthansa",
        "anthropic",
        "httpx",
    )

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            module = node.module
            assert not any(module.startswith(prefix) for prefix in forbidden_prefixes)
            assert not any(name in module for name in forbidden_modules)
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                assert not any(name.startswith(prefix) for prefix in forbidden_prefixes)
                assert not any(part in name for part in forbidden_modules)


def test_coordinator_only_delegates_through_workers() -> None:
    source = Path("app/agent/coordinator.py").read_text(encoding="utf-8")

    assert "get_worker" in source
    assert "worker.execute" in source
    assert "FlightSearchService" not in source
    assert "BookingService" not in source
    assert "lufthansa_client" not in source
