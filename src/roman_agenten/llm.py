"""Modell-Factory und zentraler Modellaufruf (§6, §10).

Alle Agenten rufen Modelle ausschließlich hierüber auf. Modelle kommen aus `get_model(role)`,
Preise aus `config/preise.yaml`. Enthält Retry/Backoff, Budgetprüfung, Prompt-Caching,
Kostenerfassung und das Weglassen abgelehnter Parameter.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx
import yaml
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage

from roman_agenten.config import (
    ConfigError,
    ModelConfig,
    Role,
    Settings,
    get_model,
    parse_model_spec,
)
from roman_agenten.observability import RunLog, new_id

log = logging.getLogger("roman_agenten.llm")

TRANSIENT_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504, 529})
WEB_SEARCH_TOOL_TYPE = "web_search_20260209"
DROPPABLE_PARAMS = ("temperature",)


class BudgetExceeded(RuntimeError):
    """MAX_BUDGET_USD erreicht – Lauf pausiert (fortsetzen mit `roman resume`)."""


class LLMUnavailable(RuntimeError):
    """API nach LLM_MAX_RETRIES nicht erreichbar – Lauf pausiert."""


@dataclass
class LLMResult:
    text: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    kosten_usd: float = 0.0
    dauer_s: float = 0.0


class LLMClient(Protocol):
    def invoke(
        self,
        role: Role,
        messages: list[BaseMessage],
        *,
        json_mode: bool,
        span_id: str | None = None,
        kapitel_nr: str | None = None,
    ) -> LLMResult: ...


# ------------------------------------------------------------------ Preise


class Preise:
    """USD pro 1 Mio. Tokens, je `<provider>:<modell>`; Provider-Default (z. B. ollama = 0)."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.modelle: dict[str, dict[str, float]] = data.get("modelle", {}) or {}
        self.provider_default: dict[str, dict[str, float]] = data.get("provider_default", {}) or {}
        self._gewarnt: set[str] = set()

    @classmethod
    def load(cls, path: Path) -> Preise:
        if not path.is_file():
            log.warning("Preisdatei %s fehlt – Kosten werden mit 0 erfasst", path)
            return cls({})
        return cls(yaml.safe_load(path.read_text(encoding="utf-8")) or {})

    def kosten(self, spec: str, usage: dict[str, int]) -> float:
        provider = spec.split(":", 1)[0]
        p = self.modelle.get(spec) or self.provider_default.get(provider)
        if p is None:
            if spec not in self._gewarnt:
                log.warning("Kein Preis für %s in preise.yaml – Kosten werden mit 0 erfasst", spec)
                self._gewarnt.add(spec)
            return 0.0
        uncached = max(
            usage.get("input_tokens", 0) - usage.get("cache_read", 0) - usage.get("cache_write", 0),
            0,
        )
        return (
            uncached * p.get("input", 0.0)
            + usage.get("output_tokens", 0) * p.get("output", 0.0)
            + usage.get("cache_read", 0) * p.get("cache_read", 0.0)
            + usage.get("cache_write", 0) * p.get("cache_write", 0.0)
        ) / 1_000_000


# ------------------------------------------------------------------ Hilfen


def extract_text(msg: BaseMessage) -> str:
    c = msg.content
    if isinstance(c, str):
        return c
    parts = []
    for block in c:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "".join(parts)


def extract_usage(msg: BaseMessage) -> dict[str, int]:
    um = getattr(msg, "usage_metadata", None) or {}
    details = um.get("input_token_details", {}) or {}
    return {
        "input_tokens": int(um.get("input_tokens", 0) or 0),
        "output_tokens": int(um.get("output_tokens", 0) or 0),
        "cache_read": int(details.get("cache_read", 0) or 0),
        "cache_write": int(details.get("cache_creation", 0) or 0),
    }


def is_transient(e: BaseException) -> bool:
    status = getattr(e, "status_code", None) or getattr(
        getattr(e, "response", None), "status_code", None
    )
    if isinstance(status, int):
        return status in TRANSIENT_STATUS
    if isinstance(
        e, TimeoutError | ConnectionError | httpx.TimeoutException | httpx.TransportError
    ):
        return True
    name = type(e).__name__
    return any(
        k in name for k in ("Timeout", "Connection", "RateLimit", "Overloaded", "InternalServer")
    )


def rejected_param(e: BaseException, dropped: set[str]) -> str | None:
    """Erkennt, dass der Provider einen Parameter ablehnt (z. B. Temperatur bei erweitertem Denken)."""
    status = getattr(e, "status_code", None)
    text = str(e).lower()
    if status not in (None, 400) or "temperature" not in text:
        return None
    return next((p for p in DROPPABLE_PARAMS if p in text and p not in dropped), None)


def with_cache_breakpoint(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Setzt `cache_control` hinter den (statischen) Systemblock."""
    out: list[BaseMessage] = []
    for i, m in enumerate(messages):
        if i == 0 and isinstance(m, SystemMessage) and isinstance(m.content, str):
            out.append(
                SystemMessage(
                    content=[
                        {"type": "text", "text": m.content, "cache_control": {"type": "ephemeral"}}
                    ]
                )
            )
        else:
            out.append(m)
    return out


def ollama_installed(base_url: str, timeout: float = 3.0) -> list[str] | None:
    try:
        r = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=timeout)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except (httpx.HTTPError, ValueError, KeyError):
        return None


def resolve_ollama_model(model: str, settings: Settings, installed: list[str] | None) -> str:
    """Wendet den Test-Fallback an (§12.1) – nie stillschweigend."""
    fb = settings.test_fallback_model
    if not fb:
        return model
    _, fb_model = parse_model_spec(fb)
    if settings.test_fallback:
        log.warning("TEST_FALLBACK=true: verwende Fallback-Modell %s statt %s", fb_model, model)
        return fb_model
    if installed is not None and model not in installed and fb_model in installed:
        log.warning("Ollama-Modell %s nicht installiert – verwende Fallback %s", model, fb_model)
        return fb_model
    return model


# ------------------------------------------------------------------ Gateway


class ModelGateway:
    """Echte Modellaufrufe über LangChain."""

    def __init__(
        self,
        settings: Settings,
        runlog: RunLog,
        preise: Preise,
        sleep: Callable[[float], None] = time.sleep,
        factory: Callable[[ModelConfig, bool, set[str]], BaseChatModel] | None = None,
    ) -> None:
        self.settings = settings
        self.runlog = runlog
        self.preise = preise
        self.sleep = sleep
        self.factory = factory or self._build
        self.spent = runlog.total_cost()
        self._ollama_installed: list[str] | None = None
        self._ollama_checked = False

    def _resolve(self, role: Role) -> ModelConfig:
        cfg = get_model(role, self.settings)
        if cfg.provider == "ollama":
            if not self._ollama_checked:
                self._ollama_installed = ollama_installed(self.settings.ollama_base_url)
                self._ollama_checked = True
            model = resolve_ollama_model(cfg.model, self.settings, self._ollama_installed)
            cfg = ModelConfig(cfg.role, cfg.provider, model, cfg.temperature, cfg.max_tokens)
        elif (
            cfg.provider in ("anthropic", "openai")
            and self.settings.key_status(cfg.provider) == "fehlt"
        ):
            raise ConfigError(f"{cfg.provider.upper()}_API_KEY fehlt für Rolle {role.value}")
        return cfg

    def _build(self, cfg: ModelConfig, json_mode: bool, dropped: set[str]) -> BaseChatModel:
        s = self.settings
        temp: dict[str, Any] = {} if "temperature" in dropped else {"temperature": cfg.temperature}
        if cfg.provider == "ollama":
            from langchain_ollama import ChatOllama

            return ChatOllama(
                model=cfg.model,
                base_url=s.ollama_base_url,
                num_ctx=s.ollama_num_ctx,
                reasoning=s.ollama_think,
                num_predict=cfg.max_tokens,
                format="json" if json_mode else None,
                client_kwargs={"timeout": s.llm_timeout_seconds},
                **temp,
            )
        from langchain.chat_models import init_chat_model

        model: BaseChatModel = init_chat_model(
            cfg.spec,
            max_tokens=cfg.max_tokens,
            timeout=s.llm_timeout_seconds,
            max_retries=0,
            **temp,
        )
        if (
            cfg.role is Role.RESEARCH
            and s.agent_research_web_search
            and cfg.provider == "anthropic"
        ):
            tool = {
                "type": WEB_SEARCH_TOOL_TYPE,
                "name": "web_search",
                "max_uses": s.agent_research_max_searches,
            }
            return model.bind_tools([tool])  # type: ignore[return-value]
        return model

    def _check_budget(self) -> None:
        b = self.settings.max_budget_usd
        if b > 0 and self.spent >= b:
            raise BudgetExceeded(
                f"Budget erreicht: {self.spent:.2f} von {b:.2f} USD – Lauf pausiert"
            )

    def invoke(
        self,
        role: Role,
        messages: list[BaseMessage],
        *,
        json_mode: bool,
        span_id: str | None = None,
        kapitel_nr: str | None = None,
    ) -> LLMResult:
        self._check_budget()
        cfg = self._resolve(role)
        span = span_id or new_id()
        if self.settings.enable_prompt_caching and cfg.provider == "anthropic":
            messages = with_cache_breakpoint(messages)
        dropped: set[str] = set()
        attempt = 0
        start = time.monotonic()
        while True:
            try:
                msg = self.factory(cfg, json_mode, dropped).invoke(messages)
                break
            except Exception as e:
                if (p := rejected_param(e, dropped)) is not None:
                    log.warning(
                        "%s lehnt Parameter '%s' ab – Aufruf ohne ihn wiederholt", cfg.spec, p
                    )
                    dropped.add(p)
                    continue
                if not is_transient(e):
                    self.runlog.usage(
                        span_id=span,
                        rolle=role.value,
                        modell=cfg.spec,
                        kapitel=kapitel_nr,
                        status="fehler",
                        fehler=type(e).__name__,
                        kosten_usd=0.0,
                    )
                    raise
                if attempt >= self.settings.llm_max_retries:
                    self.runlog.usage(
                        span_id=span,
                        rolle=role.value,
                        modell=cfg.spec,
                        kapitel=kapitel_nr,
                        status="nicht_erreichbar",
                        fehler=type(e).__name__,
                        kosten_usd=0.0,
                    )
                    raise LLMUnavailable(
                        f"{cfg.spec} nach {attempt} Wiederholungen nicht erreichbar ({type(e).__name__})"
                    ) from e
                delay = min(2.0**attempt, 60.0) + random.uniform(0, 0.5)
                log.warning("%s: %s – neuer Versuch in %.1fs", cfg.spec, type(e).__name__, delay)
                self.sleep(delay)
                attempt += 1
        dauer = time.monotonic() - start
        assert isinstance(msg, AIMessage | BaseMessage)
        text = extract_text(msg)
        usage = extract_usage(msg)
        kosten = self.preise.kosten(cfg.spec, usage)
        self.spent += kosten
        self.runlog.usage(
            span_id=span,
            rolle=role.value,
            modell=cfg.spec,
            kapitel=kapitel_nr,
            status="ok",
            dauer_s=round(dauer, 3),
            kosten_usd=kosten,
            **usage,
        )
        self.runlog.payload(
            span,
            {
                "rolle": role.value,
                "modell": cfg.spec,
                "eingabe": [{"typ": m.type, "inhalt": m.content} for m in messages],
                "ausgabe": text,
            },
        )
        return LLMResult(text, cfg.spec, usage, kosten, dauer)
