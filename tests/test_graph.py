from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from conftest import FakeLLM, antwort, modus_von, responder_mit, standard_responder
from langchain_core.messages import BaseMessage
from langgraph.checkpoint.sqlite import SqliteSaver

from roman_agenten.config import Role, Settings
from roman_agenten.graph.novel_graph import Pipeline, open_checkpointer, open_runtime
from roman_agenten.store.project import ProjectError


def make_pipeline(settings: Settings, llm: FakeLLM, **ov: object) -> Pipeline:
    s = settings.model_copy(
        update={
            "human_checkpoints": False,
            "max_revision_rounds": 3,
            "word_count_tolerance": 0.15,
            **ov,
        }
    )
    rt = open_runtime(s, "dummy_projekt", llm=llm)
    return Pipeline(rt, open_checkpointer(s, rt))


def kdir(settings: Settings, nr: str) -> Path:
    return next((settings.projects_dir / "dummy_projekt" / "output" / "kapitel").glob(f"{nr}_*"))


def folge(*namen: str) -> Iterator[str]:
    """Liefert die Namen nacheinander, danach immer den letzten."""
    yield from namen
    while True:
        yield namen[-1]


def test_end_to_end_bis_freigegeben(settings: Settings) -> None:
    llm = FakeLLM()
    out = make_pipeline(settings, llm).run_kapitel("1")
    ch = out.state["kapitel"]["1"]
    assert ch["status"] == "freigegeben" and out.state["phase"] == "freigegeben"
    assert not out.pausiert
    assert llm.roles() == [
        Role.SHOWRUNNER,
        Role.RESEARCH,
        Role.PLOT_ARCHITECT,
        Role.CHAPTER_WRITER,
        Role.CONTINUITY,
        Role.GUARDRAILS,
        Role.LINE_EDITOR,
        Role.CONTINUITY,
        Role.SHOWRUNNER,
    ] or llm.roles()[4:6] == [Role.GUARDRAILS, Role.CONTINUITY]
    d = kdir(settings, "1")
    for f in (
        "brief.json",
        "faktenblatt.json",
        "szenenplan.json",
        "entwurf_r1.md",
        "pruefungen_r1.json",
        "endfassung.md",
    ):
        assert (d / f).is_file(), f
    assert ch["zusammenfassung"].startswith("Mira bemerkt")
    assert out.state["kontinuitaetsprotokoll"][0]["fakt"] == "Anzeige"
    assert out.state["figurenwissen"] == {"Mira": "TROPF verhält sich seltsam"}
    assert ch["autorennotiz"]["woerter_gemeldet"] == 999 != ch["autorennotiz"]["woerter_gezaehlt"]
    # ohne Websuche ist nichts REAL
    assert {f["status"] for f in ch["faktenblatt"]["fakten"]} == {"UNGEPRUEFT"}


def test_folgekapitel_bekommt_vorkapitel(settings: Settings) -> None:
    llm = FakeLLM()
    p = make_pipeline(settings, llm)
    p.run_kapitel("1")
    p.run_kapitel("2")
    autor_eingaben = [u for r, u in llm.calls if r is Role.CHAPTER_WRITER]
    assert "<vorkapitel>\n# 1 Anzeigen" in autor_eingaben[-1]
    assert p.state()["kapitel"]["2"]["status"] == "freigegeben"


def test_pruefschleife_endet_nach_max_runden(settings: Settings) -> None:
    llm = FakeLLM(responder_mit(guardrails="guardrails_ueberarbeitung.json"))
    out = make_pipeline(settings, llm, max_revision_rounds=3).run_kapitel("1")
    assert llm.roles().count(Role.CHAPTER_WRITER) == 3
    ch = out.state["kapitel"]["1"]
    assert ch["entscheidung"]["entscheidung"] == "lektorat"
    assert ch["status"] == "freigegeben"
    assert [r["datei"] for r in ch["revisionen"]] == [
        "entwurf_r1.md",
        "entwurf_r2.md",
        "entwurf_r3.md",
    ]
    autor = [u for r, u in llm.calls if r is Role.CHAPTER_WRITER]
    assert (
        "<letzter_entwurf>" in autor[1]
        and "<pruefberichte>" in autor[1]
        and "Ändere nur" in autor[1]
    )


def _sequenz_responder(guardrails_folge: Iterator[str], **ueber: str):  # type: ignore[no-untyped-def]
    basis = responder_mit(**ueber)

    def r(role: Role, messages: list[BaseMessage]) -> str:
        if role is Role.GUARDRAILS:
            return antwort(next(guardrails_folge))
        return basis(role, messages)

    return r


@pytest.mark.parametrize("max_runden", [1, 2, 3])
@pytest.mark.parametrize("ablehnung_ab_runde", [1, 2, 3])
@pytest.mark.parametrize(
    "entscheidung",
    ["showrunner_entscheidung_lektorat.json", "showrunner_entscheidung_blockiert.json"],
)
def test_ablehnung_nie_zu_lektor_oder_freigabe(
    settings: Settings, max_runden: int, ablehnung_ab_runde: int, entscheidung: str
) -> None:
    if ablehnung_ab_runde > max_runden:
        pytest.skip("Ablehnung käme nach Rundenende")
    vor = ["guardrails_ueberarbeitung.json"] * (ablehnung_ab_runde - 1)
    llm = FakeLLM(
        _sequenz_responder(
            folge(*vor, "guardrails_ablehnung.json"),
            showrunner_entscheidung=entscheidung,
            showrunner_freigabe="showrunner_freigabe.json",
        )
    )
    p = make_pipeline(settings, llm, max_revision_rounds=max_runden)
    out = p.run_kapitel("1")
    assert Role.LINE_EDITOR not in llm.roles()
    assert out.interrupts and out.interrupts[0]["art"] == "blockiert"
    out = p.approve(kommentar="gesehen")
    ch = out.state["kapitel"]["1"]
    assert ch["status"] == "blockiert"
    assert not (kdir(settings, "1") / "endfassung.md").exists()


def test_ablehnung_blockiert_auch_ohne_kontrollpunkte(settings: Settings) -> None:
    llm = FakeLLM(responder_mit(guardrails="guardrails_ablehnung.json"))
    out = make_pipeline(settings, llm, max_revision_rounds=1, human_checkpoints=False).run_kapitel(
        "1"
    )
    assert out.interrupts[0]["art"] == "blockiert"


def test_showrunner_blockiert(settings: Settings) -> None:
    llm = FakeLLM(
        responder_mit(
            continuity_pruefung="continuity_funde.json",
            showrunner_entscheidung="showrunner_entscheidung_blockiert.json",
        )
    )
    out = make_pipeline(settings, llm, max_revision_rounds=1).run_kapitel("1")
    assert out.interrupts[0]["art"] == "blockiert"
    assert Role.LINE_EDITOR not in llm.roles()


def test_freigabe_verweigert(settings: Settings) -> None:
    llm = FakeLLM(responder_mit(showrunner_freigabe="showrunner_freigabe_nein.json"))
    out = make_pipeline(settings, llm).run_kapitel("1")
    assert out.interrupts[0]["art"] == "blockiert"


def test_format_retry_einmal(settings: Settings) -> None:
    antworten = folge("chapter_writer_ohne_trenner.md", "chapter_writer.md")

    def r(role: Role, messages: list[BaseMessage]) -> str:
        if role is Role.CHAPTER_WRITER:
            return antwort(next(antworten))
        return standard_responder(role, messages)

    llm = FakeLLM(r)
    out = make_pipeline(settings, llm).run_kapitel("1")
    assert out.state["kapitel"]["1"]["status"] == "freigegeben"
    autor = [u for role, u in llm.calls if role is Role.CHAPTER_WRITER]
    assert len(autor) == 2 and "Halte das Ausgabeformat exakt ein" in autor[1]


def test_doppelter_formatfehler_blockiert(settings: Settings) -> None:
    llm = FakeLLM(responder_mit(research="ungueltig.txt"))
    out = make_pipeline(settings, llm).run_kapitel("1")
    assert llm.roles().count(Role.RESEARCH) == 2
    assert out.interrupts[0]["art"] == "blockiert"
    assert "research" in out.interrupts[0]["grund"]
    forderung = [u for role, u in llm.calls if role is Role.RESEARCH][1]
    assert "Antworte nur mit gültigem JSON nach Schema" in forderung


def test_unterlaenge_zaehlt_als_runde(settings: Settings) -> None:
    kurz = (
        "# 1 Anzeigen\n\nZu kurz.\n\n---LEKTORATSNOTIZ---\nwoerter_vorher: 3\nwoerter_nachher: 3\n"
    )
    lekt = iter([kurz])

    def r(role: Role, messages: list[BaseMessage]) -> str:
        if role is Role.LINE_EDITOR:
            return next(lekt, antwort("line_editor.md"))
        return standard_responder(role, messages)

    llm = FakeLLM(r)
    out = make_pipeline(settings, llm).run_kapitel("1")
    ch = out.state["kapitel"]["1"]
    assert ch["runde"] == 2 and ch["revisionen"][1]["grund"] == "unterlaenge"
    assert "Auftrag: Unterlänge" in [u for role, u in llm.calls if role is Role.CHAPTER_WRITER][1]
    assert ch["status"] == "freigegeben"


def test_kontrollpunkt_nach_kapitel_1(settings: Settings) -> None:
    p = make_pipeline(settings, FakeLLM(), human_checkpoints=True)
    out = p.run_kapitel("1")
    assert out.interrupts[0]["art"] == "kapitel_abnahme"
    assert out.state["kapitel"]["1"]["status"] == "in_arbeit"
    out = p.approve()
    assert out.state["kapitel"]["1"]["status"] == "freigegeben"


def test_kontrollpunkt_ablehnen(settings: Settings) -> None:
    p = make_pipeline(settings, FakeLLM(), human_checkpoints=True)
    p.run_kapitel("1")
    out = p.approve(genehmigt=False, kommentar="Ton zu kühl")
    ch = out.state["kapitel"]["1"]
    assert ch["status"] == "blockiert" and ch["menschliches_feedback"] == "Ton zu kühl"
    # Neustart des Kapitels gibt das Feedback an den Showrunner
    llm2 = FakeLLM()
    p2 = make_pipeline(settings, llm2, human_checkpoints=False)
    p2.run_kapitel("1")
    assert "<feedback>\nTon zu kühl" in llm2.calls[0][1]


def test_bible_aenderung_wird_abgelegt_nicht_angewendet(settings: Settings) -> None:
    bible = settings.projects_dir / "dummy_projekt" / "bible" / "bible.md"
    vorher = bible.read_text()
    briefe = folge("showrunner_bible_aenderung.json", "showrunner_brief.json")

    def r(role: Role, messages: list[BaseMessage]) -> str:
        if role is Role.SHOWRUNNER and modus_von(messages) == "kapitel_brief":
            return antwort(next(briefe))
        return standard_responder(role, messages)

    p = make_pipeline(settings, FakeLLM(r), human_checkpoints=True)
    out = p.run_kapitel("1")
    assert out.interrupts[0]["art"] == "bible_aenderung"
    out = p.approve()
    assert out.interrupts[0]["art"] == "kapitel_abnahme"
    assert bible.read_text() == vorher
    vorschlaege = list(
        (
            settings.projects_dir / "dummy_projekt" / "output" / "berichte" / "bible_aenderungen"
        ).glob("*.json")
    )
    assert len(vorschlaege) == 1
    assert out.state["bible_aenderungen"][0]["status"] == "wartet_auf_freigabe"


def test_absturz_und_resume(settings: Settings) -> None:
    abgestuerzt = {"ja": False}

    def r(role: Role, messages: list[BaseMessage]) -> str:
        if role is Role.LINE_EDITOR and not abgestuerzt["ja"]:
            abgestuerzt["ja"] = True
            raise RuntimeError("Simulierter Absturz")
        return standard_responder(role, messages)

    llm = FakeLLM(r)
    p = make_pipeline(settings, llm)
    with pytest.raises(RuntimeError, match="Absturz"):
        p.run_kapitel("1")

    # neuer Prozess: frische Pipeline auf demselben Checkpoint
    llm2 = FakeLLM()
    p2 = make_pipeline(settings, llm2)
    assert p2.snapshot().next == ("line_editor",)
    assert p2.state()["kapitel"]["1"]["entwurf"]
    out = p2.resume()
    assert out.state["kapitel"]["1"]["status"] == "freigegeben"
    assert Role.RESEARCH not in llm2.roles() and Role.CHAPTER_WRITER not in llm2.roles()


def test_akt_mit_aktbericht(settings: Settings) -> None:
    llm = FakeLLM()
    out = make_pipeline(settings, llm).run_akt("I")
    kap = out.state["kapitel"]
    assert kap["P"]["status"] == kap["1"]["status"] == "freigegeben"
    bericht = out.state["aktberichte"]["I"]
    assert bericht["status"] == "auftraege_erstellt"
    assert bericht["auftraege"] == [{"kapitel_nr": "P", "auftrag": "Einstieg straffen"}]
    assert Role.FULL_READ in llm.roles()


def test_akt_kontrollpunkt(settings: Settings) -> None:
    p = make_pipeline(settings, FakeLLM(), human_checkpoints=True)
    # Abnahme nach Prolog (erstes Kapitel) und nach Kapitel 1 (project.yaml), dann Aktbericht
    arten = []
    out = p.run_akt("I")
    while out.interrupts and out.interrupts[0]["art"] == "kapitel_abnahme":
        arten.append(out.interrupts[0]["kapitel"])
        p.approve()
        out = p.run_akt("I")
    assert arten == ["P", "1"]
    assert out.interrupts[0]["art"] == "aktbericht"
    out = p.approve()
    assert out.state["aktberichte"]["I"]["status"] == "auftraege_erstellt"


def test_offener_kontrollpunkt_blockiert_neuen_lauf(settings: Settings) -> None:
    from roman_agenten.graph.novel_graph import PipelineBusy

    p = make_pipeline(settings, FakeLLM(), human_checkpoints=True)
    p.run_kapitel("1")
    with pytest.raises(PipelineBusy):
        p.run_kapitel("2")
    with pytest.raises(PipelineBusy):
        p.resume()


def test_unbekannter_kapitel_typ_ohne_zusatz(settings: Settings) -> None:
    yml = settings.projects_dir / "dummy_projekt" / "project.yaml"
    yml.write_text(yml.read_text().replace("[prosa, notiz]", "[prosa, notiz, brief]"))
    with pytest.raises(ProjectError, match="brief"):
        open_runtime(settings, "dummy_projekt", llm=FakeLLM())


def test_kein_api_key_in_logs(settings: Settings, caplog: pytest.LogCaptureFixture) -> None:
    from pydantic import SecretStr

    geheim = "sk-test-GEHEIM-0123456789"
    p = make_pipeline(settings, FakeLLM(), anthropic_api_key=SecretStr(geheim), log_payloads=True)
    p.rt.runlog.event("test", info=f"key={geheim}")
    p.run_kapitel("1")
    state_dir = settings.projects_dir / "dummy_projekt" / "state"
    for f in state_dir.rglob("*"):
        if f.is_file() and f.suffix in (".jsonl", ".json"):
            assert geheim not in f.read_text(encoding="utf-8"), f
    assert geheim not in caplog.text


def test_checkpoint_liegt_im_projekt(settings: Settings) -> None:
    make_pipeline(settings, FakeLLM()).run_kapitel("P")
    db = settings.projects_dir / "dummy_projekt" / "state" / "checkpoints.sqlite"
    assert db.is_file()
    saver = SqliteSaver(sqlite3.connect(db, check_same_thread=False))
    assert saver.get_tuple({"configurable": {"thread_id": "dummy_projekt"}}) is not None
