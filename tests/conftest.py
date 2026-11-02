from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from langchain_core.messages import BaseMessage

from roman_agenten.config import Role, Settings, load_settings
from roman_agenten.llm import LLMResult, ModelGateway

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures"
ANTWORTEN = FIXTURES / "antworten"
ENV_PREFIXES = (
    "AGENT_",
    "DEFAULT_",
    "ANTHROPIC_",
    "OPENAI_",
    "OLLAMA_",
    "TEST_",
    "MAX_",
    "HUMAN_",
    "WORD_",
    "ENABLE_",
    "USE_",
    "PROJECTS_",
    "PROMPTS_",
    "PREISE_",
    "LLM_",
    "CHECKPOINTER",
    "POSTGRES_",
    "LOG_",
    "ROMAN_",
)


def antwort(name: str) -> str:
    return (ANTWORTEN / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Produktive Werte aus der Umgebung dürfen Tests nie beeinflussen."""
    for k in list(os.environ):
        if k.startswith(ENV_PREFIXES):
            monkeypatch.delenv(k, raising=False)


@pytest.fixture(autouse=True)
def _nur_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test-Guard (§12.1): bricht ab, wenn ein anderer Provider als ollama aufgelöst wird."""
    original = ModelGateway._resolve

    def guarded(self: ModelGateway, role: Role):  # type: ignore[no-untyped-def]
        cfg = original(self, role)
        if cfg.provider != "ollama":
            pytest.fail(f"Test löst Provider '{cfg.provider}' auf – nur ollama erlaubt")
        return cfg

    monkeypatch.setattr(ModelGateway, "_resolve", guarded)


def make_settings(projects_dir: Path, **overrides: object) -> Settings:
    env = REPO / ".env.test"
    base = load_settings(str(env if env.exists() else REPO / ".env.example.test"))
    upd: dict[str, object] = {
        "projects_dir": projects_dir,
        "prompts_dir": REPO / "prompts",
        "preise_file": REPO / "config" / "preise.yaml",
        "log_payloads": False,
    }
    upd.update(overrides)
    return base.model_copy(update=upd)


@pytest.fixture
def projects_dir(tmp_path: Path) -> Path:
    d = tmp_path / "projekte"
    shutil.copytree(
        FIXTURES / "dummy_projekt",
        d / "dummy_projekt",
        ignore=shutil.ignore_patterns("state", "output"),
    )
    return d


@pytest.fixture
def settings(projects_dir: Path) -> Settings:
    return make_settings(projects_dir)


Responder = Callable[[Role, list[BaseMessage]], str]


class FakeLLM:
    """Fake-Modell: liefert feste Antworten je Rolle/Auftrag, zeichnet Aufrufe auf."""

    def __init__(self, responder: Responder | None = None) -> None:
        self.responder = responder or standard_responder
        self.calls: list[tuple[Role, str]] = []

    def invoke(
        self,
        role: Role,
        messages: list[BaseMessage],
        *,
        json_mode: bool,
        span_id: str | None = None,
        kapitel_nr: str | None = None,
    ) -> LLMResult:
        user = str(messages[-1].content)
        self.calls.append((role, user))
        text = self.responder(role, messages)
        return LLMResult(text, "ollama:fake", {"input_tokens": 10, "output_tokens": 5}, 0.0, 0.0)

    def roles(self) -> list[Role]:
        return [r for r, _ in self.calls]


def modus_von(messages: list[BaseMessage]) -> str:
    u = str(messages[-1].content)
    for key, modus in (
        ("Auftrag: Kapitel-Brief", "kapitel_brief"),
        ("Auftrag: Entscheidung", "entscheidung"),
        ("Auftrag: Freigabe", "freigabe"),
        ("Auftrag: Überarbeitungsaufträge", "ueberarbeitung"),
        ("Auftrag: Abschluss", "abschluss"),
        ("Auftrag: Prüfung", "pruefung"),
    ):
        if key in u:
            return modus
    return ""


STANDARD = {
    (Role.SHOWRUNNER, "kapitel_brief"): "showrunner_brief.json",
    (Role.SHOWRUNNER, "entscheidung"): "showrunner_entscheidung_lektorat.json",
    (Role.SHOWRUNNER, "freigabe"): "showrunner_freigabe.json",
    (Role.SHOWRUNNER, "ueberarbeitung"): "showrunner_ueberarbeitung.json",
    (Role.RESEARCH, ""): "research.json",
    (Role.PLOT_ARCHITECT, ""): "plot_architect.md",
    (Role.CHAPTER_WRITER, ""): "chapter_writer.md",
    (Role.CONTINUITY, "pruefung"): "continuity_bestanden.json",
    (Role.CONTINUITY, "abschluss"): "continuity_abschluss.json",
    (Role.GUARDRAILS, ""): "guardrails_freigabe.json",
    (Role.LINE_EDITOR, ""): "line_editor.md",
    (Role.FULL_READ, ""): "full_read.json",
}


def standard_responder(role: Role, messages: list[BaseMessage]) -> str:
    return antwort(STANDARD[(role, modus_von(messages))])


def responder_mit(**ueberschreibungen: str) -> Responder:
    """z. B. responder_mit(guardrails='guardrails_ablehnung.json', showrunner_entscheidung='…')."""

    def r(role: Role, messages: list[BaseMessage]) -> str:
        m = modus_von(messages)
        for key in (f"{role.value}_{m}", role.value):
            if key in ueberschreibungen:
                return antwort(ueberschreibungen[key])
        return standard_responder(role, messages)

    return r


@pytest.fixture
def fake_llm() -> Iterator[FakeLLM]:
    yield FakeLLM()
