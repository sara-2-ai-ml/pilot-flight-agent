"""Application configuration and environment settings."""

import os
import re
from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(".env")
_DOTENV_OVERRIDE_KEYS = ("NLU_USE_MOCK", "PLANNER_USE_MOCK")


def _read_dotenv_value(key: str) -> str | None:
    """Return a single key's value from the project .env file when present."""
    if not _ENV_FILE.is_file():
        return None
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(.*?)\s*$")
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = pattern.match(line)
        if match:
            raw = match.group(1).strip().strip('"').strip("'")
            return raw or None
    return None


def _sync_dotenv_over_shell_env() -> None:
    """Prefer explicit .env values for dev flags over inherited shell env vars."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    for key in _DOTENV_OVERRIDE_KEYS:
        file_value = _read_dotenv_value(key)
        if file_value is None:
            continue
        shell_value = os.environ.get(key)
        if shell_value != file_value:
            os.environ[key] = file_value


class ToolsMode(str, Enum):
    """How workers invoke external capabilities."""

    DIRECT = "direct"
    MCP = "mcp"


class FlightApiProvider(str, Enum):
    """External flight data provider."""

    LUFTHANSA = "lufthansa"
    AVIATIONSTACK = "aviationstack"


class Settings(BaseSettings):
    """Central configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = "Pilot Flight Agent"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # LLM (Phase 2+)
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-20250514"
    planner_use_mock: bool = True
    nlu_use_mock: bool = True

    # Flight API (Phase 5)
    flight_api_provider: FlightApiProvider = FlightApiProvider.LUFTHANSA
    flight_api_key: str | None = None
    flight_api_client_secret: str | None = None
    flight_api_base_url: str = "https://api.lufthansa.com/v1"
    flight_api_use_mock: bool = True

    # Tool integration (Phase 6)
    tools_mode: ToolsMode = ToolsMode.DIRECT
    mcp_use_inprocess: bool = False
    mcp_python_executable: str | None = None

    # Booking store (Phase 5)
    booking_db_path: str = "data/bookings.db"

    # Input guardrails (Phase 8)
    min_user_message_length: int = Field(default=1, ge=1)
    max_user_message_length: int = Field(default=2_000, ge=1)
    prompt_injection_guard_enabled: bool = True
    prompt_injection_block: bool = True
    rate_limit_enabled: bool = True
    rate_limit_window_seconds: float = Field(default=60.0, gt=0)
    rate_limit_ip_requests: int = Field(default=30, ge=1)
    rate_limit_conversation_requests: int = Field(default=10, ge=1)
    output_guard_enabled: bool = True
    pii_redaction_enabled: bool = True

    # Reliability (Phase 9)
    retry_enabled: bool = True
    retry_max_attempts: int = Field(default=3, ge=1)
    retry_base_delay_seconds: float = Field(default=0.5, gt=0)
    retry_max_delay_seconds: float = Field(default=4.0, gt=0)
    external_http_timeout_seconds: float = Field(default=10.0, gt=0)
    external_mcp_timeout_seconds: float = Field(default=15.0, gt=0)
    external_llm_timeout_seconds: float = Field(default=30.0, gt=0)
    circuit_breaker_enabled: bool = True
    circuit_breaker_failure_threshold: int = Field(default=5, ge=1)
    circuit_breaker_window_seconds: float = Field(default=60.0, gt=0)
    circuit_breaker_open_seconds: float = Field(default=30.0, gt=0)

    # Agent budget (Phase 1+)
    max_iterations: int = Field(default=8, ge=1)
    max_llm_calls: int = Field(default=6, ge=0)
    max_tool_calls: int = Field(default=10, ge=0)
    max_latency_seconds: float = Field(default=20.0, gt=0)
    max_tokens: int = Field(default=10_000, ge=1)
    max_step_retries: int = Field(default=3, ge=1)
    max_replan_attempts: int = Field(default=2, ge=0)


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    _sync_dotenv_over_shell_env()
    return Settings()
