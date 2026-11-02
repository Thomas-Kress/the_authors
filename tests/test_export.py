from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from roman_agenten.state import NovelState
from roman_agenten.store.bible_loader import load_bible
from roman_agenten.store.export import (
    ExportError,
    export,
    fehlende_kapitel,
    parse_inline,
    parse_markdown,
)
from roman_agenten.store.project import load_project

TEXT = "# 1 Anfang\n\n*Ort, Datum*\n\nEin **fetter** Satz.\nZweite Zeile.\n\n***\n\nNeue Szene."


@pytest.fixture
def setup(projects_dir: Path):  # type: ignore[no-untyped-def]
    project = load_project(projects_dir, "dummy_projekt")
    bible = load_bible(project.bible_dir)
    nr = bible.kapiteltabelle()[0].nr
    state: NovelState = {"kapitel": {nr: {"status": "freigegeben", "endfassung": TEXT}}}  # type: ignore[typeddict-item]
    return project, bible, state


def test_parse_markdown() -> None:
    arten = [b.art for b in parse_markdown(TEXT)]
    assert arten == ["h1", "p", "p", "trenner", "p"]
    assert parse_markdown(TEXT)[2].text == "Ein **fetter** Satz. Zweite Zeile."


def test_parse_inline() -> None:
    assert parse_inline("a *b* **c**") == [
        ("a ", False, False),
        ("b", False, True),
        (" ", False, False),
        ("c", True, False),
    ]


@pytest.mark.parametrize(
    ("fmt", "magic"),
    [("md", None), ("docx", b"PK"), ("epub", b"PK"), ("pdf", b"%PDF")],
)
def test_export_formate(setup, fmt: str, magic: bytes | None) -> None:  # type: ignore[no-untyped-def]
    project, bible, state = setup
    path = export(project, bible, state, fmt)
    assert path.suffix == f".{fmt}" and path.stat().st_size > 0
    if magic:
        assert path.read_bytes().startswith(magic)


def test_epub_struktur(setup) -> None:  # type: ignore[no-untyped-def]
    project, bible, state = setup
    with zipfile.ZipFile(export(project, bible, state, "epub")) as z:
        assert z.namelist()[0] == "mimetype"
        assert z.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
        assert "<strong>fetter</strong>" in z.read("OEBPS/kap001.xhtml").decode()


def test_docx_inhalt(setup) -> None:  # type: ignore[no-untyped-def]
    from docx import Document

    project, bible, state = setup
    doc = Document(str(export(project, bible, state, "docx")))
    assert any("Neue Szene." in p.text for p in doc.paragraphs)


def test_unbekanntes_format_und_leer(setup) -> None:  # type: ignore[no-untyped-def]
    project, bible, _ = setup
    with pytest.raises(ExportError, match="Unbekanntes Format"):
        export(project, bible, {"kapitel": {}}, "odt")  # type: ignore[typeddict-item]
    for fmt in ("md", "docx", "epub", "pdf"):
        with pytest.raises(ExportError, match="Keine freigegebenen"):
            export(project, bible, {"kapitel": {}}, fmt)  # type: ignore[typeddict-item]


def test_fehlende_kapitel(setup) -> None:  # type: ignore[no-untyped-def]
    _, bible, state = setup
    assert len(fehlende_kapitel(bible, state)) == len(bible.kapiteltabelle()) - 1
