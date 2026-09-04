"""Flight worker architecture tests — Phase 5.6."""

import ast
from pathlib import Path


def _read_source(relative_path: str) -> str:
    return Path(relative_path).read_text(encoding="utf-8")


def _imported_modules(source: str) -> set[str]:
    tree = ast.parse(source)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
    return modules


def test_flight_worker_does_not_import_provider_clients() -> None:
    modules = _imported_modules(_read_source("app/agent/workers/flight_worker.py"))

    assert "app.tools.adapters" in modules
    assert "app.tools.flight_service" not in modules
    assert not any("lufthansa" in module for module in modules)


def test_flight_service_does_not_import_lufthansa_client() -> None:
    modules = _imported_modules(_read_source("app/tools/flight_service.py"))

    assert "app.tools.flight_client" in modules
    assert not any("lufthansa" in module for module in modules)


def test_lufthansa_client_is_the_only_provider_specific_module() -> None:
    tool_modules = sorted(Path("app/tools").glob("*.py"))
    provider_markers = (
        "/operations/schedules/",
        "/operations/flightstatus/",
        "LufthansaClient",
    )

    files_with_provider_details = [
        path.name
        for path in tool_modules
        if any(marker in path.read_text(encoding="utf-8") for marker in provider_markers)
    ]

    assert files_with_provider_details == ["lufthansa_client.py"]
