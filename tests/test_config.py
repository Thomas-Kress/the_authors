from __future__ import annotations

import re
from pathlib import Path

import pytest

from roman_agenten.config import ConfigError, Role, Settings, all_models, get_model

SRC = Path(__file__).resolve().parents[1] / "src"
MODELLNAMEN = re.compile(
    r"(claude-\w|gpt-\d|\bo[134]-|qwen\d|\bllama\d|mistral|gemini|\bsonnet\b|\bopus\b|\bhaiku\b)",
    re.I,
)


def test_get_model_ohne_konfiguration_scheitert() -> None:
    with pytest.raises(ConfigError):
        get_model(Role.CHAPTER_WRITER, Settings())


def test_get_model_ohne_temperatur_scheitert() -> None:
    with pytest.raises(ConfigError, match="Temperatur"):
        get_model(Role.SHOWRUNNER, Settings(default_model="ollama:x", default_max_tokens=10))


def test_rollen_ueberschreibung_vor_default() -> None:
    s = Settings(
        default_model="ollama:basis",
        default_temperature=0.3,
        default_max_tokens=100,
        agent_chapter_writer_model="ollama:autor",
        agent_chapter_writer_temperature=0.85,
        agent_chapter_writer_max_tokens=900,
    )
    w = get_model(Role.CHAPTER_WRITER, s)
    assert (w.provider, w.model, w.temperature, w.max_tokens) == ("ollama", "autor", 0.85, 900)
    c = get_model(Role.CONTINUITY, s)
    assert (c.model, c.temperature, c.max_tokens) == ("basis", 0.3, 100)


def test_ungueltige_modellangabe() -> None:
    with pytest.raises(ConfigError):
        get_model(
            Role.RESEARCH,
            Settings(default_model="ohne-provider", default_temperature=0, default_max_tokens=1),
        )
    with pytest.raises(ConfigError):
        get_model(
            Role.RESEARCH,
            Settings(default_model="foo:bar", default_temperature=0, default_max_tokens=1),
        )


def test_testprofil_alle_rollen_ollama(settings: Settings) -> None:
    assert {m.provider for m in all_models(settings).values()} == {"ollama"}


def test_kein_hart_codierter_modellname_in_src() -> None:
    treffer = []
    for p in SRC.rglob("*.py"):
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if MODELLNAMEN.search(line):
                treffer.append(f"{p.relative_to(SRC)}:{i}: {line.strip()}")
    assert not treffer, "Modellnamen im Code:\n" + "\n".join(treffer)


def test_env_example_listet_alle_settings() -> None:
    root = Path(__file__).resolve().parents[1]
    example = (root / ".env.example").read_text(encoding="utf-8")
    keys = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", example, re.M))
    fehlend = sorted(f.upper() for f in Settings.model_fields if f.upper() not in keys)
    assert not fehlend, f"In .env.example fehlen: {fehlend}"
