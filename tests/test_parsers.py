from __future__ import annotations

import pytest
from conftest import antwort

from roman_agenten.agents import (
    chapter_writer,
    continuity,
    full_read,
    guardrails,
    line_editor,
    plot_architect,
    research,
    showrunner,
)
from roman_agenten.agents.parsing import OutputFormatError, count_words, extract_json, strip_think
from roman_agenten.schemas import (
    KapitelBrief,
    ShowrunnerBibleAenderung,
    ShowrunnerBrief,
    ShowrunnerFreigabe,
    export_json_schemas,
)


def test_showrunner_brief_gueltig() -> None:
    out = showrunner.parse(
        antwort("showrunner_brief.json"),
        modus="kapitel_brief",
        brief_feld="wachstumsstufe",
        kapitel_typen=["prosa"],
    )
    assert isinstance(out, ShowrunnerBrief)
    assert out.inhalt.model_extra == {"wachstumsstufe": 1}


def test_brief_ohne_brief_feld_ungueltig() -> None:
    with pytest.raises(OutputFormatError, match="wachstumsstufe"):
        showrunner.parse(
            antwort("showrunner_brief_ohne_feld.json"),
            brief_feld="wachstumsstufe",
            kapitel_typen=["prosa"],
        )


def test_brief_feldname_aus_konfiguration_ohne_codeaenderung() -> None:
    raw = antwort("showrunner_brief.json").replace('"wachstumsstufe"', '"wirkungen"')
    out = showrunner.parse(raw, brief_feld="wirkungen", kapitel_typen=["prosa"])
    assert isinstance(out, ShowrunnerBrief)
    with pytest.raises(OutputFormatError):
        showrunner.parse(raw, brief_feld="wachstumsstufe", kapitel_typen=["prosa"])


def test_brief_mit_unbekanntem_kapitel_typ_ungueltig() -> None:
    with pytest.raises(OutputFormatError, match="gedicht"):
        showrunner.parse(
            antwort("showrunner_brief_falscher_typ.json"),
            brief_feld="wachstumsstufe",
            kapitel_typen=["prosa", "notiz"],
        )


def test_kapitelbrief_prueft_projekt() -> None:
    import json

    b = KapitelBrief.model_validate(json.loads(antwort("showrunner_brief.json"))["inhalt"])
    assert b.pruefe_projekt("wachstumsstufe", ["prosa"]) == []
    assert len(b.pruefe_projekt("andere", ["notiz"])) == 2


def test_showrunner_typen() -> None:
    assert isinstance(
        showrunner.parse(antwort("showrunner_freigabe.json"), modus="freigabe"), ShowrunnerFreigabe
    )
    assert isinstance(
        showrunner.parse(antwort("showrunner_bible_aenderung.json"), modus="kapitel_brief"),
        ShowrunnerBibleAenderung,
    )
    with pytest.raises(OutputFormatError, match="nicht erlaubt"):
        showrunner.parse(antwort("showrunner_freigabe.json"), modus="entscheidung")


def test_json_in_codeblock() -> None:
    plan = plot_architect.parse(antwort("plot_architect.md"))
    assert plan.szenen[0].woerter == 60


@pytest.mark.parametrize(
    "parser",
    [
        research.parse,
        guardrails.parse,
        continuity.parse,
        full_read.parse,
        plot_architect.parse,
        showrunner.parse,
    ],
)
def test_ungueltige_antwort(parser) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(OutputFormatError):
        parser(antwort("ungueltig.txt"))


def test_schemaverletzung_wird_gemeldet() -> None:
    with pytest.raises(OutputFormatError, match="ergebnis"):
        guardrails.parse('{"kapitel_nr": "1", "ergebnis": "VIELLEICHT"}')


def test_guardrails_und_continuity() -> None:
    assert guardrails.parse(antwort("guardrails_ablehnung.json")).ergebnis == "ABLEHNUNG"
    k = continuity.parse(antwort("continuity_funde.json"))
    assert not k.bestanden_effektiv
    # gemeldetes "bestanden" wird durch MITTEL-Fund überstimmt
    k2 = continuity.parse(
        antwort("continuity_funde.json").replace('"bestanden": false', '"bestanden": true')
    )
    assert not k2.bestanden_effektiv
    assert continuity.parse(antwort("continuity_bestanden.json")).bestanden_effektiv


def test_research_ohne_suche() -> None:
    fb = research.ohne_suche(research.parse(antwort("research.json")))
    assert {f.status for f in fb.fakten} == {"UNGEPRUEFT"}


def test_aktbericht_kapitelnummern_als_string() -> None:
    assert full_read.parse(antwort("full_read.json")).probleme[0].kapitel == ["P", "1"]


def test_autor_parser_zaehlt_selbst() -> None:
    e = chapter_writer.parse(antwort("chapter_writer.md"))
    assert e.notiz.woerter_gemeldet == 999
    assert e.notiz.woerter_gezaehlt == count_words(e.text) != 999
    assert "<think>" not in e.text and e.text.startswith("# 1 Anzeigen")
    assert e.notiz.abweichungen_vom_plan == []
    assert e.notiz.neue_details == ["Die Anzeige hat einen Knopf"]
    assert e.notiz.annahmen == ["Morgen ist kühl", "Feder ist im Gewächshaus"]


def test_lektor_parser() -> None:
    f = line_editor.parse(antwort("line_editor.md"))
    assert f.notiz.woerter_vorher_gemeldet == 80
    assert f.notiz.wichtigste_aenderungen == ["Rhythmus gestrafft", "Füllwörter gestrichen"]


@pytest.mark.parametrize(
    ("parser", "datei"),
    [
        (chapter_writer.parse, "chapter_writer_ohne_trenner.md"),
        (line_editor.parse, "line_editor_ohne_trenner.md"),
    ],
)
def test_fehlender_trennblock(parser, datei: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(OutputFormatError, match="Trennblock") as ei:
        parser(antwort(datei))
    assert ei.value.kind == "format"


def test_think_block_wird_entfernt() -> None:
    assert strip_think('<think>{"a": 1}</think>{"b": 2}') == '{"b": 2}'
    assert extract_json('<think>nachdenken {"falsch": 1}</think>\n{"b": 2}') == {"b": 2}


def test_wortzaehlung() -> None:
    assert count_words("Mira ging – schnell, sehr schnell. Bäume-Reihen!") == 6


def test_schema_export() -> None:
    data = export_json_schemas()
    assert {"ShowrunnerOutput", "KapitelBrief", "Aktbericht"} <= set(data)
