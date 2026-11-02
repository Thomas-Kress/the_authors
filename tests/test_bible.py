from __future__ import annotations

import re
from pathlib import Path

import pytest

from roman_agenten.store.bible_loader import BibleError, load_bible, parse_bible
from roman_agenten.store.bible_validator import validate_bible
from roman_agenten.store.project import ProjectConfig, ProjectError, load_project


def bible_text(projects_dir: Path) -> str:
    return (projects_dir / "dummy_projekt" / "bible" / "bible.md").read_text(encoding="utf-8")


def projekt(projects_dir: Path) -> ProjectConfig:
    return load_project(projects_dir, "dummy_projekt").config


def split_in_dateien(text: str, ziel: Path) -> None:
    """Erzeugt die Elf-Dateien-Ablageform aus bible.md."""
    ziel.mkdir(parents=True, exist_ok=True)
    teile = re.split(r"(?m)^(?=## (?:\d+\.|Quellen))", text)
    praeambel, rest = teile[0], teile[1:]
    for i, t in enumerate(rest):
        m = re.match(r"## (\d+)\.", t)
        if m:
            (ziel / f"{int(m.group(1)):02d}_teil.md").write_text((praeambel if i == 0 else "") + t)
        else:  # Quellen an die letzte Datei anhängen
            last = sorted(ziel.glob("*.md"))[-1]
            last.write_text(last.read_text() + "\n" + t)


def test_dummy_bible_ist_gueltig(projects_dir: Path) -> None:
    b = load_bible(projects_dir / "dummy_projekt" / "bible")
    assert validate_bible(b, projekt(projects_dir)) == []
    assert [z.nr for z in b.kapiteltabelle()] == ["P", "1", "2", "E"]
    assert b.kapitel("2").akt == "II"  # type: ignore[union-attr]
    assert b.kapitel("1").woerter == 300  # type: ignore[union-attr]


def test_beide_ablageformen_gleich(projects_dir: Path, tmp_path: Path) -> None:
    text = bible_text(projects_dir)
    split_in_dateien(text, tmp_path / "multi")
    assert len(list((tmp_path / "multi").glob("*.md"))) == 11
    a, b = parse_bible(text), load_bible(tmp_path / "multi")
    assert list(a.abschnitte) == list(b.abschnitte)
    for k in a.abschnitte:
        assert a.text(k) == b.text(k), k
    assert a.quellen == b.quellen


def test_beide_formen_gleichzeitig_verboten(projects_dir: Path) -> None:
    d = projects_dir / "dummy_projekt" / "bible"
    (d / "00_zweck.md").write_text("## 0. Zweck\n")
    with pytest.raises(BibleError):
        load_bible(d)


def test_unterabschnitte_adressierbar(projects_dir: Path) -> None:
    b = parse_bible(bible_text(projects_dir))
    assert b.text("3.3").startswith("### 3.3 Zeitleiste")
    assert "### 3.3" in b.text("3") and "### 3.1" in b.text("3")
    auszug = b.auszug(["3.3", "10.4"])
    assert "Zeitleiste" in auszug and "Feder" in auszug and "Gewächshaus\nGlas" not in auszug
    assert "## Quellen" in b.auszug(["alle"]) and "## Quellen" not in b.auszug(["9"])


def _fehler(projects_dir: Path, text: str) -> list[str]:
    return validate_bible(parse_bible(text), projekt(projects_dir))


def test_fehlender_hauptabschnitt(projects_dir: Path) -> None:
    text = bible_text(projects_dir).replace("## 7. Stil\nKurze Sätze, Präteritum.\n", "")
    assert any("Hauptabschnitt '## 7." in f for f in _fehler(projects_dir, text))


def test_fehlender_pflicht_unterabschnitt(projects_dir: Path) -> None:
    text = bible_text(projects_dir).replace("### 8.3 Wetter\n", "")
    assert any("'### 8.3" in f for f in _fehler(projects_dir, text))


def test_falsche_kapiteltabellen_spalten(projects_dir: Path) -> None:
    text = bible_text(projects_dir).replace("| Nr | Titel | POV |", "| Nr | Name | POV |", 1)
    assert any(f.startswith("6.1: Spalten") for f in _fehler(projects_dir, text))


def test_fehlendes_brief_feld(projects_dir: Path) -> None:
    text = bible_text(projects_dir).replace("Kernfelder plus wachstumsstufe.", "Kernfelder.")
    fehler = _fehler(projects_dir, text)
    assert any(f.startswith("10.3: Brief-Feld") for f in fehler)


def test_ungueltige_kapitelnummer(projects_dir: Path) -> None:
    text = bible_text(projects_dir).replace("| 2 | Trockenheit", "| 2a | Trockenheit")
    assert any("ungültige Kapitelnummer '2a'" in f for f in _fehler(projects_dir, text))


def test_zu_wenige_eintraege_in_10_4(projects_dir: Path) -> None:
    text = bible_text(projects_dir).replace("- Miras Katze heißt Feder\n", "")
    assert any(f.startswith("10.4:") for f in _fehler(projects_dir, text))


def test_alle_verstoesse_werden_gelistet(projects_dir: Path) -> None:
    text = (
        bible_text(projects_dir)
        .replace("### 8.3 Wetter\n", "")
        .replace("| 2 | Trockenheit", "| x | T")
    )
    assert len(_fehler(projects_dir, text)) >= 2


# ------------------------------------------------------------------ project.yaml


def test_project_yaml_pflichtfelder(projects_dir: Path) -> None:
    yml = projects_dir / "dummy_projekt" / "project.yaml"
    yml.write_text(
        "\n".join(
            ln
            for ln in yml.read_text().splitlines()
            if not ln.startswith(("brief_feld", "stichtag_realitaet"))
        )
    )
    with pytest.raises(ProjectError) as ei:
        load_project(projects_dir, "dummy_projekt")
    text = "\n".join(ei.value.fehler)
    assert "brief_feld" in text and "stichtag_realitaet" in text


def test_kapitel_typen_muss_prosa_enthalten(projects_dir: Path) -> None:
    yml = projects_dir / "dummy_projekt" / "project.yaml"
    yml.write_text(yml.read_text().replace("[prosa, notiz]", "[notiz]"))
    with pytest.raises(ProjectError, match="prosa"):
        load_project(projects_dir, "dummy_projekt")


def test_kontext_mapping_ueberschreibbar(projects_dir: Path) -> None:
    yml = projects_dir / "dummy_projekt" / "project.yaml"
    yml.write_text(yml.read_text() + "kontext:\n  guardrails: ['9']\n")
    cfg = load_project(projects_dir, "dummy_projekt").config
    from roman_agenten.config import Role

    assert cfg.abschnitte_fuer(Role.GUARDRAILS) == ["9"]
    assert cfg.abschnitte_fuer(Role.RESEARCH) == ["2", "3", "8", "9"]
