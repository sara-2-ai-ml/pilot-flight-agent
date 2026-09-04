"""Worker architecture tests — Phase 6.1."""

import ast
from pathlib import Path


def _imported_modules(relative_path: str) -> set[str]:
    source = Path(relative_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
    return modules


def test_workers_use_tool_adapters_not_services() -> None:
    worker_modules = (
        "app/agent/workers/flight_worker.py",
        "app/agent/workers/booking_worker.py",
    )
    forbidden = (
        "app.tools.flight_service",
        "app.tools.booking_service",
        "app.tools.lufthansa_client",
        "app.mcp.client",
    )

    for path in worker_modules:
        modules = _imported_modules(path)
        assert "app.tools.adapters" in modules
        assert not any(module in modules for module in forbidden)
