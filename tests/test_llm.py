from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from roman_agenten.config import ModelConfig, Role, Settings
from roman_agenten.llm import (
    BudgetExceeded,
    LLMUnavailable,
    ModelGateway,
    Preise,
    is_transient,
    resolve_ollama_model,
    with_cache_breakpoint,
)
from roman_agenten.observability import RunLog, setup_logging

MSGS: list[BaseMessage] = [SystemMessage(content="sys"), HumanMessage(content="hi")]


class StatusError(Exception):
    def __init__(self, status: int, msg: str = "") -> None:
        super().__init__(msg or f"HTTP {status}")
        self.status_code = status


class FakeChat:
    def __init__(self, fehler: list[Exception], temp: bool) -> None:
        self.fehler, self.temp = fehler, temp

    def invoke(self, messages: list[BaseMessage]) -> AIMessage:
        if self.fehler:
            raise self.fehler.pop(0)
        return AIMessage(
            content='{"ok": true}',
            usage_metadata={
                "input_tokens": 1000,
                "output_tokens": 100,
                "total_tokens": 1100,
                "input_token_details": {"cache_read": 200},
            },
        )


def gateway(
    settings: Settings,
    fehler: list[Exception],
    state_dir: Path | None = None,
    builds: list[dict[str, Any]] | None = None,
) -> tuple[ModelGateway, list[float]]:
    sleeps: list[float] = []

    def factory(cfg: ModelConfig, json_mode: bool, dropped: set[str]) -> Any:
        if builds is not None:
            builds.append({"json": json_mode, "dropped": set(dropped)})
        return FakeChat(fehler, "temperature" not in dropped)

    g = ModelGateway(
        settings, RunLog(state_dir, settings), Preise({}), sleep=sleeps.append, factory=factory
    )
    g._ollama_checked = True
    return g, sleeps


def test_backoff_bei_transienten_fehlern(settings: Settings) -> None:
    g, sleeps = gateway(
        settings.model_copy(update={"llm_max_retries": 5}),
        [StatusError(429), StatusError(503), TimeoutError()],
    )
    res = g.invoke(Role.CONTINUITY, MSGS, json_mode=True)
    assert res.text == '{"ok": true}'
    assert len(sleeps) == 3 and sleeps[0] < sleeps[1] < sleeps[2]


def test_gibt_nach_max_retries_auf(settings: Settings) -> None:
    s = settings.model_copy(update={"llm_max_retries": 2})
    g, sleeps = gateway(s, [StatusError(500)] * 5)
    with pytest.raises(LLMUnavailable):
        g.invoke(Role.CONTINUITY, MSGS, json_mode=True)
    assert len(sleeps) == 2


def test_nicht_transient_wird_nicht_wiederholt(settings: Settings) -> None:
    g, sleeps = gateway(settings, [StatusError(401)])
    with pytest.raises(StatusError):
        g.invoke(Role.CONTINUITY, MSGS, json_mode=True)
    assert sleeps == []


def test_abgelehnte_temperatur_wird_weggelassen(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    builds: list[dict[str, Any]] = []
    g, _ = gateway(
        settings, [StatusError(400, "temperature is not supported with thinking")], builds=builds
    )
    with caplog.at_level(logging.WARNING):
        g.invoke(Role.CHAPTER_WRITER, MSGS, json_mode=False)
    assert builds[-1]["dropped"] == {"temperature"} and builds[0]["dropped"] == set()
    assert "temperature" in caplog.text


def test_budget_pausiert(settings: Settings, tmp_path: Path) -> None:
    (tmp_path / "usage.jsonl").write_text(json.dumps({"kosten_usd": 5.0}) + "\n")
    s = settings.model_copy(update={"max_budget_usd": 4.0})
    g, _ = gateway(s, [], state_dir=tmp_path)
    with pytest.raises(BudgetExceeded):
        g.invoke(Role.CONTINUITY, MSGS, json_mode=True)


def test_budget_null_heisst_unbegrenzt(settings: Settings, tmp_path: Path) -> None:
    (tmp_path / "usage.jsonl").write_text(json.dumps({"kosten_usd": 5.0}) + "\n")
    g, _ = gateway(settings.model_copy(update={"max_budget_usd": 0}), [], state_dir=tmp_path)
    g.invoke(Role.CONTINUITY, MSGS, json_mode=True)


def test_usage_wird_protokolliert(settings: Settings, tmp_path: Path) -> None:
    g, _ = gateway(settings, [], state_dir=tmp_path)
    g.invoke(Role.GUARDRAILS, MSGS, json_mode=True, kapitel_nr="1")
    rec = json.loads((tmp_path / "usage.jsonl").read_text().splitlines()[0])
    assert rec["rolle"] == "guardrails" and rec["input_tokens"] == 1000 and rec["cache_read"] == 200
    assert (
        rec["kosten_usd"] == 0.0
        and rec["status"] == "ok"
        and "trace_id" in rec
        and "span_id" in rec
    )
    assert "hi" not in json.dumps(rec)  # kein Prompttext im Standard-Log


def test_kosten_aus_preisdatei() -> None:
    p = Preise(
        {
            "modelle": {
                "x:y": {"input": 2.0, "output": 10.0, "cache_read": 0.2, "cache_write": 2.5}
            },
            "provider_default": {"ollama": {"input": 0, "output": 0}},
        }
    )
    usage = {
        "input_tokens": 1_000_000,
        "output_tokens": 100_000,
        "cache_read": 500_000,
        "cache_write": 0,
    }
    assert p.kosten("x:y", usage) == pytest.approx(0.5 * 2.0 + 0.1 * 10.0 + 0.5 * 0.2)
    assert p.kosten("ollama:irgendwas", usage) == 0.0
    assert p.kosten("unbekannt:z", usage) == 0.0


def test_preisdatei_im_repo_ladbar() -> None:
    p = Preise.load(Path(__file__).resolve().parents[1] / "config" / "preise.yaml")
    assert p.modelle and p.provider_default["ollama"]["input"] == 0


def test_cache_breakpoint_nach_systemblock() -> None:
    out = with_cache_breakpoint(MSGS)
    assert out[0].content[0]["cache_control"] == {"type": "ephemeral"}  # type: ignore[index]
    assert out[1] is MSGS[1]


def test_ollama_parameter_werden_durchgereicht(settings: Settings) -> None:
    g = ModelGateway(settings, RunLog(None, settings), Preise({}))
    m = g._build(ModelConfig(Role.CONTINUITY, "ollama", "testmodell", 0.0, 123), True, set())
    assert m.base_url == settings.ollama_base_url  # type: ignore[attr-defined]
    assert m.num_ctx == settings.ollama_num_ctx == 16384  # type: ignore[attr-defined]
    assert m.reasoning is False and m.format == "json" and m.num_predict == 123  # type: ignore[attr-defined]
    m2 = g._build(
        ModelConfig(Role.CHAPTER_WRITER, "ollama", "testmodell", 0.85, 123), False, {"temperature"}
    )
    assert m2.format is None and m2.temperature is None  # type: ignore[attr-defined]


def test_ollama_fallback_nur_mit_warnung(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    fb = settings.test_fallback_model.split(":", 1)[1]  # type: ignore[union-attr]
    haupt = settings.default_model.split(":", 1)[1]  # type: ignore[union-attr]
    with caplog.at_level(logging.WARNING):
        assert resolve_ollama_model(haupt, settings, [haupt, fb]) == haupt
        assert caplog.text == ""
        assert resolve_ollama_model(haupt, settings, [fb]) == fb
        assert "Fallback" in caplog.text
    s = settings.model_copy(update={"test_fallback": True})
    assert resolve_ollama_model(haupt, s, [haupt, fb]) == fb


def test_transient_erkennung() -> None:
    assert is_transient(StatusError(529)) and not is_transient(StatusError(400))
    assert is_transient(ConnectionError())


def test_log_filter_schwaerzt_keys(settings: Settings, caplog: pytest.LogCaptureFixture) -> None:
    from pydantic import SecretStr

    s = settings.model_copy(update={"openai_api_key": SecretStr("sk-ABCDEF-geheim")})
    setup_logging(s)
    logger = logging.getLogger("roman_agenten.test")
    logger.propagate = True
    with caplog.at_level(logging.INFO, logger="roman_agenten"):
        for h in logging.getLogger("roman_agenten").handlers:
            caplog.handler.filters = h.filters
        logger.warning("Fehler mit Key %s", "sk-ABCDEF-geheim")
    assert "sk-ABCDEF-geheim" not in caplog.text
    assert s.key_status("openai") == "gesetzt" and s.key_status("anthropic") == "fehlt"
