"""Integrationstests mit dem lokalen Testmodell (§12.1). Nur mit `pytest -m llm`.

Ein 9B-Modell prüft die Mechanik, nicht die literarische Qualität: Asserts nur auf Struktur
und Zustandsübergänge, nie auf Textinhalte.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_settings

from roman_agenten.config import Role, Settings, get_model
from roman_agenten.graph.novel_graph import Pipeline, open_checkpointer, open_runtime
from roman_agenten.llm import ollama_installed, resolve_ollama_model

pytestmark = pytest.mark.llm


@pytest.fixture
def llm_settings(projects_dir: Path) -> Settings:
    s = make_settings(
        projects_dir, max_revision_rounds=1, human_checkpoints=False, max_budget_usd=0
    )
    installed = ollama_installed(s.ollama_base_url)
    if installed is None:
        pytest.skip(f"Ollama unter {s.ollama_base_url} nicht erreichbar")
    haupt = get_model(Role.CHAPTER_WRITER, s).model
    model = resolve_ollama_model(haupt, s, installed)
    if model not in installed:
        pytest.skip("Weder Test- noch Fallback-Modell installiert")
    # kurze Zielumfänge, 2 Szenen
    b = projects_dir / "dummy_projekt" / "bible" / "bible.md"
    b.write_text(b.read_text().replace("| 300 |", "| 150 |"))
    return s


def test_kapitel_mechanik_mit_lokalem_modell(llm_settings: Settings) -> None:
    rt = open_runtime(llm_settings, "dummy_projekt")
    p = Pipeline(rt, open_checkpointer(llm_settings, rt))
    out = p.run_kapitel("1")
    ch = out.state["kapitel"]["1"]
    assert ch["status"] in ("freigegeben", "blockiert")
    if ch["status"] == "freigegeben":
        assert ch["endfassung"] and ch["revisionen"]
    else:
        assert out.interrupts and out.interrupts[0]["art"] == "blockiert"
    assert out.state.get("kosten", {}).get("usd", 0.0) == 0.0
    assert (llm_settings.projects_dir / "dummy_projekt" / "state" / "usage.jsonl").is_file()
