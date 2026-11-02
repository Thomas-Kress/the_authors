from __future__ import annotations

import re
from pathlib import Path

import pytest
from test_bible import bible_text, split_in_dateien

from roman_agenten.config import Role
from roman_agenten.context.assembler import assemble
from roman_agenten.state import NovelState
from roman_agenten.store.bible_loader import Bible, load_bible, parse_bible
from roman_agenten.store.project import DEFAULT_KONTEXT, load_project

ALLE = [str(i) for i in range(11)]


def enthaltene_abschnitte(auszug: str) -> set[str]:
    haupt = set(re.findall(r"(?m)^## (\d+)\.", auszug))
    sub = set(re.findall(r"(?m)^### (\d+\.\d+)", auszug))
    return haupt | {s for s in sub if s.split(".")[0] not in haupt}


@pytest.fixture(params=["eine_datei", "elf_dateien"])
def bible(request: pytest.FixtureRequest, projects_dir: Path, tmp_path: Path) -> Bible:
    if request.param == "eine_datei":
        return load_bible(projects_dir / "dummy_projekt" / "bible")
    split_in_dateien(bible_text(projects_dir), tmp_path / "multi")
    return load_bible(tmp_path / "multi")


@pytest.mark.parametrize("role", list(Role))
def test_rolle_bekommt_exakt_ihre_abschnitte(role: Role, bible: Bible, projects_dir: Path) -> None:
    cfg = load_project(projects_dir, "dummy_projekt").config
    rk = assemble(role, NovelState(kapitel={}), "1", bible, cfg)
    erwartet = set(DEFAULT_KONTEXT[role.value])
    if erwartet == {"alle"}:
        erwartet = set(ALLE)
        assert "## Quellen" in rk.basis["bible_auszug"]
    else:
        assert "## Quellen" not in rk.basis["bible_auszug"]
    assert enthaltene_abschnitte(rk.basis["bible_auszug"]) == erwartet


def _state() -> NovelState:
    return NovelState(
        kapitel={
            "P": {"status": "freigegeben", "endfassung": "VOLLTEXT-P", "zusammenfassung": "ZUS-P"},
            "1": {"status": "freigegeben", "endfassung": "VOLLTEXT-1", "zusammenfassung": "ZUS-1"},
            "2": {"status": "in_arbeit", "brief": {"titel": "Trockenheit"}, "entwurf": "ENTWURF-2"},
        },
        kontinuitaetsprotokoll=[{"fakt": "Mira", "wert": "41", "erstmals_in": "P"}],
    )


def test_autor_bekommt_vorkapitel_voll_und_aeltere_als_zusammenfassung(projects_dir: Path) -> None:
    p = load_project(projects_dir, "dummy_projekt")
    rk = assemble(Role.CHAPTER_WRITER, _state(), "2", load_bible(p.bible_dir), p.config)
    assert rk.block("vorkapitel") == "VOLLTEXT-1"
    assert rk.block("zusammenfassungen") == "Kapitel P: ZUS-P"
    alles = str(rk.bloecke)
    assert "VOLLTEXT-P" not in alles


def test_continuity_nie_volltexte(projects_dir: Path) -> None:
    p = load_project(projects_dir, "dummy_projekt")
    rk = assemble(Role.CONTINUITY, _state(), "2", load_bible(p.bible_dir), p.config)
    alles = str(rk.bloecke) + rk.basis["bible_auszug"]
    assert "VOLLTEXT" not in alles
    assert "ZUS-P" in alles and "ZUS-1" in alles
    assert "Mira: 41" in rk.basis["kontinuitaetsprotokoll"]


def test_plot_architect_letzte_drei(projects_dir: Path) -> None:
    p = load_project(projects_dir, "dummy_projekt")
    rk = assemble(Role.PLOT_ARCHITECT, _state(), "2", load_bible(p.bible_dir), p.config)
    assert "ZUS-P" in (rk.block("zusammenfassungen") or "")


def test_research_stichtag(projects_dir: Path) -> None:
    p = load_project(projects_dir, "dummy_projekt")
    rk = assemble(Role.RESEARCH, _state(), "2", load_bible(p.bible_dir), p.config)
    assert rk.block("stichtag") == "2026-01-01"


def test_full_read_alle_endfassungen_des_akts(projects_dir: Path) -> None:
    p = load_project(projects_dir, "dummy_projekt")
    rk = assemble(Role.FULL_READ, _state(), "1", load_bible(p.bible_dir), p.config, modus="I")
    assert "VOLLTEXT-P" in (rk.block("endfassungen") or "") and "VOLLTEXT-1" in (
        rk.block("endfassungen") or ""
    )
    assert rk.basis["akt"] == "I"


def test_basis_platzhalter(projects_dir: Path) -> None:
    p = load_project(projects_dir, "dummy_projekt")
    rk = assemble(Role.GUARDRAILS, _state(), "2", load_bible(p.bible_dir), p.config)
    assert rk.basis["kapitel_titel"] == "Trockenheit"
    assert rk.basis["akt"] == "II"
    assert rk.basis["freigegeben"] == "P, 1"


def test_assembler_ist_rein(projects_dir: Path) -> None:
    p = load_project(projects_dir, "dummy_projekt")
    b = parse_bible(bible_text(projects_dir))
    s = _state()
    vorher = repr(s)
    a1 = assemble(Role.CHAPTER_WRITER, s, "2", b, p.config)
    a2 = assemble(Role.CHAPTER_WRITER, s, "2", b, p.config)
    assert a1 == a2 and repr(s) == vorher
