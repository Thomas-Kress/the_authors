"""Konfiguration aus `.env` (bzw. `ROMAN_ENV_FILE`) und Modellauflösung pro Rolle.

Es gibt bewusst keinen hart codierten Modellnamen: `get_model(role)` löst ausschließlich
über `AGENT_<ROLLE>_MODEL` → `DEFAULT_MODEL` auf, sonst `ConfigError`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(RuntimeError):
    """Konfiguration unvollständig oder ungültig."""


class Role(StrEnum):
    SHOWRUNNER = "showrunner"
    RESEARCH = "research"
    PLOT_ARCHITECT = "plot_architect"
    CHAPTER_WRITER = "chapter_writer"
    CONTINUITY = "continuity"
    GUARDRAILS = "guardrails"
    LINE_EDITOR = "line_editor"
    FULL_READ = "full_read"


JSON_ROLES: frozenset[Role] = frozenset(
    {
        Role.SHOWRUNNER,
        Role.RESEARCH,
        Role.PLOT_ARCHITECT,
        Role.CONTINUITY,
        Role.GUARDRAILS,
        Role.FULL_READ,
    }
)

KNOWN_PROVIDERS = frozenset({"anthropic", "openai", "ollama"})


def env_file() -> str:
    return os.environ.get("ROMAN_ENV_FILE", ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file_encoding="utf-8", extra="ignore")

    # --- Keys / Provider ---
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    ollama_base_url: str = "http://localhost:11434"
    ollama_num_ctx: int = 16384
    ollama_think: bool = False

    # --- Defaults ---
    default_model: str | None = None
    default_temperature: float | None = None
    default_max_tokens: int | None = None

    # --- Testprofil ---
    test_fallback_model: str | None = None
    test_fallback: bool = False

    # --- Pro Rolle ---
    agent_showrunner_model: str | None = None
    agent_showrunner_temperature: float | None = None
    agent_showrunner_max_tokens: int | None = None
    agent_research_model: str | None = None
    agent_research_temperature: float | None = None
    agent_research_max_tokens: int | None = None
    agent_research_web_search: bool = False
    agent_research_max_searches: int = 10
    agent_plot_architect_model: str | None = None
    agent_plot_architect_temperature: float | None = None
    agent_plot_architect_max_tokens: int | None = None
    agent_chapter_writer_model: str | None = None
    agent_chapter_writer_temperature: float | None = None
    agent_chapter_writer_max_tokens: int | None = None
    agent_continuity_model: str | None = None
    agent_continuity_temperature: float | None = None
    agent_continuity_max_tokens: int | None = None
    agent_guardrails_model: str | None = None
    agent_guardrails_temperature: float | None = None
    agent_guardrails_max_tokens: int | None = None
    agent_line_editor_model: str | None = None
    agent_line_editor_temperature: float | None = None
    agent_line_editor_max_tokens: int | None = None
    agent_full_read_model: str | None = None
    agent_full_read_temperature: float | None = None
    agent_full_read_max_tokens: int | None = None

    # --- Pipeline ---
    max_revision_rounds: int = 3
    word_count_tolerance: float = 0.15
    human_checkpoints: bool = True

    # --- Kosten & Effizienz ---
    enable_prompt_caching: bool = True
    use_batch_api: bool = False
    max_budget_usd: float = 0.0  # 0 = kein Limit

    # --- Pfade ---
    projects_dir: Path = Path("../roman-projekte")
    prompts_dir: Path = Path("./prompts")
    preise_file: Path = Path("./config/preise.yaml")

    # --- Betrieb ---
    llm_max_retries: int = 5
    llm_timeout_seconds: int = 300
    checkpointer: str = "sqlite"
    postgres_url: SecretStr | None = None
    log_level: str = "INFO"
    log_payloads: bool = False

    def secret_values(self) -> list[str]:
        """Alle gesetzten Geheimwerte – nur für die Log-Schwärzung."""
        out: list[str] = []
        for s in (self.anthropic_api_key, self.openai_api_key, self.postgres_url):
            if s is not None and s.get_secret_value():
                out.append(s.get_secret_value())
        return out

    def key_status(self, provider: str) -> str:
        key = {"anthropic": self.anthropic_api_key, "openai": self.openai_api_key}.get(provider)
        return "gesetzt" if key is not None and key.get_secret_value() else "fehlt"


def load_settings(path: str | None = None) -> Settings:
    file = path or env_file()
    return Settings(_env_file=file if Path(file).exists() else None)  # type: ignore[call-arg]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


@dataclass(frozen=True)
class ModelConfig:
    role: Role
    provider: str
    model: str
    temperature: float
    max_tokens: int

    @property
    def spec(self) -> str:
        return f"{self.provider}:{self.model}"


def parse_model_spec(spec: str) -> tuple[str, str]:
    provider, sep, model = spec.partition(":")
    if not sep or not provider or not model:
        raise ConfigError(f"Modellangabe '{spec}' hat nicht das Format <provider>:<modell>")
    if provider not in KNOWN_PROVIDERS:
        raise ConfigError(f"Unbekannter Provider '{provider}' (erlaubt: {sorted(KNOWN_PROVIDERS)})")
    return provider, model


def get_model(role: Role | str, settings: Settings | None = None) -> ModelConfig:
    """Löst Modell, Temperatur und Token-Limit einer Rolle auf (§6.2)."""
    s = settings or get_settings()
    r = Role(role)
    key = r.value

    spec: str | None = getattr(s, f"agent_{key}_model") or s.default_model
    if not spec:
        raise ConfigError(
            f"Kein Modell für Rolle '{key}': AGENT_{key.upper()}_MODEL oder DEFAULT_MODEL setzen"
        )
    temperature: float | None = getattr(s, f"agent_{key}_temperature")
    if temperature is None:
        temperature = s.default_temperature
    if temperature is None:
        raise ConfigError(
            f"Keine Temperatur für Rolle '{key}': AGENT_{key.upper()}_TEMPERATURE oder DEFAULT_TEMPERATURE setzen"
        )
    max_tokens: int | None = getattr(s, f"agent_{key}_max_tokens") or s.default_max_tokens
    if max_tokens is None:
        raise ConfigError(
            f"Kein Token-Limit für Rolle '{key}': AGENT_{key.upper()}_MAX_TOKENS oder DEFAULT_MAX_TOKENS setzen"
        )
    provider, model = parse_model_spec(spec)
    return ModelConfig(r, provider, model, float(temperature), int(max_tokens))


def all_models(settings: Settings | None = None) -> dict[Role, ModelConfig]:
    return {r: get_model(r, settings) for r in Role}
