from __future__ import annotations

import re
from pathlib import Path

import pytest

from roman_agenten.config import Role
from roman_agenten.prompts import (
    BASIS_PLATZHALTER,
    PLACEHOLDER_RE,
    ROLE_PROMPT_FILES,
    PromptError,
    PromptLoader,
    placeholders,
    render,
)

REPO = Path(__file__).resolve().parents[1]
PROMPTS = REPO / "prompts"
BASIS_WERTE = {k: f"<{k}>" for k in BASIS_PLATZHALTER}


def test_alle_dateien_aus_anhang_a_vorhanden() -> None:
    for name in (*ROLE_PROMPT_FILES, "zusaetze/systemprotokoll.md"):
        assert (PROMPTS / name).is_file(), name


def test_prompts_wortgetreu_aus_anhang_a() -> None:
    claude = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    anhang = claude[claude.index("## Anhang A") :]
    blocks = re.findall(r"### A\.\d+ `(prompts/[^`]+)`.*?\n~~~~markdown\n(.*?)\n~~~~", anhang, re.S)
    assert len(blocks) == 10
    for pfad, inhalt in blocks:
        assert (REPO / pfad).read_text(encoding="utf-8") == inhalt + "\n", pfad


def test_basis_nutzt_nur_bekannte_platzhalter() -> None:
    assert placeholders((PROMPTS / "_basis.md").read_text()) == BASIS_PLATZHALTER


@pytest.mark.parametrize("role", list(Role))
def test_system_prompt_ohne_ungefuellte_platzhalter(role: Role) -> None:
    text = PromptLoader(PROMPTS).system_prompt(role, BASIS_WERTE)
    assert not PLACEHOLDER_RE.search(text)
    assert "<bible>\n<bible_auszug>\n</bible>" in text


def test_render_fehlt_platzhalter() -> None:
    with pytest.raises(PromptError, match="kapitel_nr"):
        render("Kapitel {{kapitel_nr}}", {})
    with pytest.raises(PromptError):
        render("{{x}}", {"x": None})


def test_render_setzt_werte_nicht_rekursiv_ein() -> None:
    assert render("{{a}}", {"a": "{{b}}"}) == "{{b}}"


def test_zusatz_wird_an_autor_angehaengt() -> None:
    loader = PromptLoader(PROMPTS)
    text = loader.system_prompt(Role.CHAPTER_WRITER, BASIS_WERTE, kapitel_typ="systemprotokoll")
    assert "## Zusatz: Systemprotokoll" in text
    assert "Zusatz" not in loader.system_prompt(
        Role.CONTINUITY, BASIS_WERTE, kapitel_typ="systemprotokoll"
    )


def test_projekt_ueberschreibung_greift(tmp_path: Path) -> None:
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "guardrails.md").write_text("# Eigene Leitplanken\n")
    loader = PromptLoader(PROMPTS, tmp_path)
    assert "# Eigene Leitplanken" in loader.system_prompt(Role.GUARDRAILS, BASIS_WERTE)
    assert "# Rolle: Showrunner" in loader.system_prompt(Role.SHOWRUNNER, BASIS_WERTE)


def test_fehlende_zusaetze(projects_dir: Path) -> None:
    loader = PromptLoader(PROMPTS, projects_dir / "dummy_projekt")
    assert loader.missing_zusaetze(["prosa", "notiz", "systemprotokoll"]) == []
    assert loader.missing_zusaetze(["prosa", "brief"]) == ["brief"]


def test_auftraege_rendern() -> None:
    loader = PromptLoader(PROMPTS)
    for p in (PROMPTS / "auftraege").glob("*.md"):
        werte = {k: "x" for k in placeholders(p.read_text())}
        assert loader.auftrag(p.stem, werte)
