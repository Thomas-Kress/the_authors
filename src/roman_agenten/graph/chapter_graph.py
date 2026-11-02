"""Kapitelgraph (§5.1).

START → showrunner(brief) → research → plot_architect → chapter_writer
      → Send: continuity ∥ guardrails → gate_pruefung → (writer | line_editor | showrunner(entscheidung) | blockiert)
      → line_editor → gate_wortzahl → continuity(abschluss) → showrunner(freigabe)
      → kontrollpunkt_kapitel → freigegeben → END

Knoten mit `interrupt()` tun nichts anderes als unterbrechen, damit bei der Fortsetzung
kein Modellaufruf wiederholt wird.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.types import Send, interrupt

from roman_agenten.agents import (
    chapter_writer,
    continuity,
    guardrails,
    line_editor,
    plot_architect,
    research,
    showrunner,
)
from roman_agenten.graph import gates
from roman_agenten.graph.runtime import AgentFormatError, Runtime
from roman_agenten.schemas import ShowrunnerBibleAenderung
from roman_agenten.state import ChapterState, NovelState, chapter

MAX_BIBLE_VORSCHLAEGE = 2
Node = Callable[[NovelState], dict[str, Any]]


def _nr(state: NovelState) -> str:
    return state["aktuelles_kapitel"]


def _kap(nr: str, **fields: Any) -> dict[str, Any]:
    return {"kapitel": {nr: fields}}


def _titel(ch: ChapterState) -> str:
    return str((ch.get("brief") or {}).get("titel", ""))


def _safe(fn: Node) -> Node:
    """Formatfehler nach automatischer Wiederholung → Kapitel blockiert (Kontrollpunkt)."""

    def wrapped(state: NovelState) -> dict[str, Any]:
        try:
            return fn(state)
        except AgentFormatError as e:
            return _kap(_nr(state), status="blockiert", blockiert_grund=f"Ungültige Ausgabe – {e}")

    wrapped.__name__ = fn.__name__
    return wrapped


def _blockiert_oder(nxt: str) -> Callable[[NovelState], str]:
    def route(state: NovelState) -> str:
        return "markiere_blockiert" if chapter(state).get("status") == "blockiert" else nxt

    return route


def ist_erstes_kapitel(rt: Runtime, nr: str) -> bool:
    tabelle = rt.bible.kapiteltabelle()
    return nr == "1" or (bool(tabelle) and tabelle[0].nr == nr)


def add_chapter_nodes(g: StateGraph, rt: Runtime) -> None:  # type: ignore[type-arg]
    s = rt.settings
    cfg = rt.project.config

    # ---------------------------------------------------------------- Brief
    @_safe
    def showrunner_brief(state: NovelState) -> dict[str, Any]:
        nr = _nr(state)
        ch = chapter(state)
        out, k = rt.call(
            showrunner,
            state,
            rt.ctx(nr, "kapitel_brief"),
            modus="kapitel_brief",
            brief_feld=cfg.brief_feld,
            kapitel_typen=cfg.kapitel_typen,
        )
        if isinstance(out, ShowrunnerBibleAenderung):
            vorschlag = {
                "kapitel_nr": nr,
                **out.inhalt.model_dump(),
                "begruendung_showrunner": out.begruendung,
                "status": "wartet_auf_freigabe",
            }
            rt.writer.bible_aenderung(nr, vorschlag)
            return {
                "bible_aenderungen": [vorschlag],
                "kosten": k,
                **_kap(
                    nr,
                    brief={},
                    status="in_arbeit",
                    bible_vorschlaege=ch.get("bible_vorschlaege", 0) + 1,
                ),
            }
        brief = out.inhalt.model_dump(mode="json")
        rt.writer.json(nr, brief["titel"], "brief.json", brief)
        return {
            "phase": "brief",
            "kosten": k,
            **_kap(
                nr,
                brief=brief,
                status="in_arbeit",
                runde=0,
                ueberarbeitungsgrund="",
                entscheidung={},
                freigabe={},
                pruefung_kontinuitaet={},
                pruefung_leitplanken={},
                blockiert_grund="",
                revisionen=ch.get("revisionen", []),
            ),
        }

    def route_brief(state: NovelState) -> str:
        ch = chapter(state)
        if ch.get("status") == "blockiert":
            return "markiere_blockiert"
        return "research" if ch.get("brief") else "kontrollpunkt_bible"

    def kontrollpunkt_bible(state: NovelState) -> dict[str, Any]:
        nr = _nr(state)
        ch = chapter(state)
        if ch.get("bible_vorschlaege", 0) > MAX_BIBLE_VORSCHLAEGE:
            return _kap(
                nr,
                status="blockiert",
                blockiert_grund="Showrunner liefert wiederholt Bible-Änderungen statt eines Briefs",
            )
        if s.human_checkpoints:
            antwort = interrupt(
                {
                    "art": "bible_aenderung",
                    "kapitel": nr,
                    "vorschlag": (state.get("bible_aenderungen") or [{}])[-1],
                    "hinweis": "Die Bible wird nicht automatisch geändert.",
                }
            )
            rt.runlog.event("kontrollpunkt", art="bible_aenderung", kapitel=nr, antwort=antwort)
        return {}

    # ---------------------------------------------------------------- Vorbereitung
    @_safe
    def research_node(state: NovelState) -> dict[str, Any]:
        nr = _nr(state)
        fb, k = rt.call(research, state, rt.ctx(nr))
        if not rt.web_search_aktiv():
            fb = research.ohne_suche(fb)
        data = fb.model_dump(mode="json")
        rt.writer.json(nr, _titel(chapter(state)), "faktenblatt.json", data)
        return {"phase": "recherche", "kosten": k, **_kap(nr, faktenblatt=data)}

    @_safe
    def plot_architect_node(state: NovelState) -> dict[str, Any]:
        nr = _nr(state)
        plan, k = rt.call(plot_architect, state, rt.ctx(nr))
        data = plan.model_dump(mode="json")
        rt.writer.json(nr, _titel(chapter(state)), "szenenplan.json", data)
        return {"phase": "szenenplan", "kosten": k, **_kap(nr, szenenplan=data)}

    # ---------------------------------------------------------------- Schreiben & Prüfen
    @_safe
    def chapter_writer_node(state: NovelState) -> dict[str, Any]:
        nr = _nr(state)
        ch = chapter(state)
        entwurf, k = rt.call(chapter_writer, state, rt.ctx(nr))
        runde = ch.get("runde", 0) + 1
        revisionen = list(ch.get("revisionen", []))
        idx = len(revisionen) + 1
        pfad = rt.writer.entwurf(nr, _titel(ch), idx, entwurf.text)
        revisionen.append(
            {
                "runde": runde,
                "grund": ch.get("ueberarbeitungsgrund") or "erstentwurf",
                "datei": pfad.name,
                "woerter": entwurf.notiz.woerter_gezaehlt,
            }
        )
        return {
            "phase": "entwurf",
            "kosten": k,
            **_kap(
                nr,
                entwurf=entwurf.text,
                autorennotiz=entwurf.notiz.model_dump(mode="json"),
                runde=runde,
                revisionen=revisionen,
                pruefung_kontinuitaet={},
                pruefung_leitplanken={},
            ),
        }

    def fan_out(state: NovelState) -> Any:
        if chapter(state).get("status") == "blockiert":
            return "markiere_blockiert"
        return [Send("continuity_pruefung", state), Send("guardrails", state)]

    @_safe
    def continuity_pruefung(state: NovelState) -> dict[str, Any]:
        nr = _nr(state)
        pr, k = rt.call(continuity, state, rt.ctx(nr, "pruefung"))
        data = pr.model_dump(mode="json")
        data["bestanden"] = pr.bestanden_effektiv
        return {"kosten": k, **_kap(nr, pruefung_kontinuitaet=data)}

    @_safe
    def guardrails_node(state: NovelState) -> dict[str, Any]:
        nr = _nr(state)
        pr, k = rt.call(guardrails, state, rt.ctx(nr))
        return {"kosten": k, **_kap(nr, pruefung_leitplanken=pr.model_dump(mode="json"))}

    def gate_pruefung(state: NovelState) -> dict[str, Any]:
        nr = _nr(state)
        ch = chapter(state)
        if ch.get("status") == "blockiert":
            return {}
        rt.writer.pruefungen(
            nr,
            _titel(ch),
            len(ch.get("revisionen", [])),
            {
                "runde": ch.get("runde"),
                "kontinuitaet": ch.get("pruefung_kontinuitaet"),
                "leitplanken": ch.get("pruefung_leitplanken"),
            },
        )
        route = gates.route_pruefung(ch, s.max_revision_rounds)
        rt.runlog.event(
            "gate_pruefung",
            kapitel=nr,
            runde=ch.get("runde"),
            route=route,
            leitplanken=gates.leitplanken_ergebnis(ch),
        )
        upd: dict[str, Any] = {
            "ueberarbeitungsgrund": "pruefung" if route == "chapter_writer" else ""
        }
        if route == "blockiert":
            upd |= {
                "status": "blockiert",
                "blockiert_grund": "Leitplanken-ABLEHNUNG nach Ausschöpfen aller Überarbeitungsrunden",
            }
        return {"phase": "pruefung", **_kap(nr, **upd)}

    def route_pruefung(state: NovelState) -> str:
        r = gates.route_pruefung(chapter(state), s.max_revision_rounds)
        return "markiere_blockiert" if r == "blockiert" else r

    @_safe
    def showrunner_entscheidung(state: NovelState) -> dict[str, Any]:
        nr = _nr(state)
        out, k = rt.call(showrunner, state, rt.ctx(nr, "entscheidung"), modus="entscheidung")
        ent = {**out.inhalt.model_dump(mode="json"), "begruendung": out.begruendung}
        upd: dict[str, Any] = {"entscheidung": ent}
        if gates.route_entscheidung({**chapter(state), "entscheidung": ent}) == "blockiert":
            upd |= {
                "status": "blockiert",
                "blockiert_grund": "Showrunner-Entscheidung: blockiert"
                if not gates.veto(chapter(state))
                else "Leitplanken-ABLEHNUNG",
            }
        return {"kosten": k, **_kap(nr, **upd)}

    def route_entscheidung(state: NovelState) -> str:
        r = gates.route_entscheidung(chapter(state))
        return "markiere_blockiert" if r == "blockiert" else r

    # ---------------------------------------------------------------- Lektorat & Abschluss
    @_safe
    def line_editor_node(state: NovelState) -> dict[str, Any]:
        nr = _nr(state)
        gates.assert_kein_veto(chapter(state), "line_editor")
        end, k = rt.call(line_editor, state, rt.ctx(nr))
        return {
            "phase": "lektorat",
            "kosten": k,
            **_kap(
                nr,
                endfassung=end.text,
                lektoratsnotiz=end.notiz.model_dump(mode="json"),
                ueberarbeitungsgrund="",
            ),
        }

    def gate_wortzahl(state: NovelState) -> dict[str, Any]:
        nr = _nr(state)
        ch = chapter(state)
        route = gates.route_wortzahl(ch, s.word_count_tolerance, s.max_revision_rounds)
        if route == "chapter_writer":
            rt.runlog.event("gate_wortzahl", kapitel=nr, route=route)
            return _kap(nr, ueberarbeitungsgrund="unterlaenge")
        if gates.unterlaenge(ch, s.word_count_tolerance):
            rt.runlog.event(
                "gate_wortzahl", kapitel=nr, route=route, warnung="Unterlänge, Runden erschöpft"
            )
        return {}

    def route_wortzahl(state: NovelState) -> str:
        return gates.route_wortzahl(chapter(state), s.word_count_tolerance, s.max_revision_rounds)

    @_safe
    def continuity_abschluss(state: NovelState) -> dict[str, Any]:
        nr = _nr(state)
        ch = chapter(state)
        pr, k = rt.call(continuity, state, rt.ctx(nr, "abschluss"))
        neu = [
            {**e.model_dump(mode="json"), "erstmals_in": e.erstmals_in or nr}
            for e in pr.protokoll_neu
        ]
        return {
            "kosten": k,
            "kontinuitaetsprotokoll": neu,
            "figurenwissen": dict((ch.get("szenenplan") or {}).get("figurenwissen_ende", {})),
            **_kap(nr, zusammenfassung=continuity.kuerze_zusammenfassung(pr.zusammenfassung)),
        }

    @_safe
    def showrunner_freigabe(state: NovelState) -> dict[str, Any]:
        nr = _nr(state)
        out, k = rt.call(showrunner, state, rt.ctx(nr, "freigabe"), modus="freigabe")
        fr = {**out.inhalt.model_dump(mode="json"), "begruendung": out.begruendung}
        upd: dict[str, Any] = {"freigabe": fr}
        if gates.route_freigabe({**chapter(state), "freigabe": fr}) == "blockiert":
            upd |= {
                "status": "blockiert",
                "blockiert_grund": f"Showrunner verweigert Freigabe: {fr.get('anmerkungen')}",
            }
        return {"kosten": k, **_kap(nr, **upd)}

    def route_freigabe(state: NovelState) -> str:
        r = gates.route_freigabe(chapter(state))
        return "markiere_blockiert" if r == "blockiert" else r

    def kontrollpunkt_kapitel(state: NovelState) -> dict[str, Any]:
        nr = _nr(state)
        noetig = s.human_checkpoints and (
            ist_erstes_kapitel(rt, nr) or cfg.kontrollpunkt_nach_kapitel(nr)
        )
        if not noetig:
            return {}
        antwort = interrupt(
            {
                "art": "kapitel_abnahme",
                "kapitel": nr,
                "frage": "Ton und Stimme abnehmen (roman approve / --ablehnen)",
            }
        )
        rt.runlog.event("kontrollpunkt", art="kapitel_abnahme", kapitel=nr, antwort=antwort)
        if isinstance(antwort, dict) and antwort.get("genehmigt") is False:
            return _kap(
                nr,
                status="blockiert",
                blockiert_grund="Kontrollpunkt abgelehnt",
                menschliches_feedback=str(antwort.get("kommentar", "")),
            )
        return {}

    def route_kontrollpunkt(state: NovelState) -> str:
        return END if chapter(state).get("status") == "blockiert" else "freigegeben"

    def freigegeben(state: NovelState) -> dict[str, Any]:
        nr = _nr(state)
        ch = chapter(state)
        gates.assert_kein_veto(ch, "freigegeben")
        rt.writer.endfassung(nr, _titel(ch), ch.get("endfassung", ""))
        rt.runlog.event("kapitel_freigegeben", kapitel=nr, runde=ch.get("runde"))
        return {"phase": "freigegeben", **_kap(nr, status="freigegeben", menschliches_feedback="")}

    # ---------------------------------------------------------------- Blockade
    def markiere_blockiert(state: NovelState) -> dict[str, Any]:
        nr = _nr(state)
        grund = chapter(state).get("blockiert_grund") or "unbekannt"
        rt.runlog.event("kapitel_blockiert", kapitel=nr, grund=grund)
        return _kap(nr, status="blockiert", blockiert_grund=grund)

    def kontrollpunkt_blockiert(state: NovelState) -> dict[str, Any]:
        # Gilt immer – auch bei HUMAN_CHECKPOINTS=false.
        nr = _nr(state)
        antwort = interrupt(
            {"art": "blockiert", "kapitel": nr, "grund": chapter(state).get("blockiert_grund")}
        )
        kommentar = (
            antwort.get("kommentar", "") if isinstance(antwort, dict) else str(antwort or "")
        )
        return _kap(nr, menschliches_feedback=kommentar)

    # ---------------------------------------------------------------- Verdrahtung
    nodes: dict[str, Node] = {
        "showrunner_brief": showrunner_brief,
        "kontrollpunkt_bible": kontrollpunkt_bible,
        "research": research_node,
        "plot_architect": plot_architect_node,
        "chapter_writer": chapter_writer_node,
        "continuity_pruefung": continuity_pruefung,
        "guardrails": guardrails_node,
        "gate_pruefung": gate_pruefung,
        "showrunner_entscheidung": showrunner_entscheidung,
        "line_editor": line_editor_node,
        "gate_wortzahl": gate_wortzahl,
        "continuity_abschluss": continuity_abschluss,
        "showrunner_freigabe": showrunner_freigabe,
        "kontrollpunkt_kapitel": kontrollpunkt_kapitel,
        "freigegeben": freigegeben,
        "markiere_blockiert": markiere_blockiert,
        "kontrollpunkt_blockiert": kontrollpunkt_blockiert,
    }
    for name, fn in nodes.items():
        g.add_node(name, fn)  # type: ignore[call-overload]

    g.add_conditional_edges(
        "showrunner_brief", route_brief, ["research", "kontrollpunkt_bible", "markiere_blockiert"]
    )
    g.add_conditional_edges(
        "kontrollpunkt_bible",
        _blockiert_oder("showrunner_brief"),
        ["showrunner_brief", "markiere_blockiert"],
    )
    g.add_conditional_edges(
        "research", _blockiert_oder("plot_architect"), ["plot_architect", "markiere_blockiert"]
    )
    g.add_conditional_edges(
        "plot_architect",
        _blockiert_oder("chapter_writer"),
        ["chapter_writer", "markiere_blockiert"],
    )
    g.add_conditional_edges(
        "chapter_writer", fan_out, ["continuity_pruefung", "guardrails", "markiere_blockiert"]
    )
    g.add_edge("continuity_pruefung", "gate_pruefung")
    g.add_edge("guardrails", "gate_pruefung")
    g.add_conditional_edges(
        "gate_pruefung",
        route_pruefung,
        ["chapter_writer", "line_editor", "showrunner_entscheidung", "markiere_blockiert"],
    )
    g.add_conditional_edges(
        "showrunner_entscheidung", route_entscheidung, ["line_editor", "markiere_blockiert"]
    )
    g.add_conditional_edges(
        "line_editor", _blockiert_oder("gate_wortzahl"), ["gate_wortzahl", "markiere_blockiert"]
    )
    g.add_conditional_edges(
        "gate_wortzahl", route_wortzahl, ["chapter_writer", "continuity_abschluss"]
    )
    g.add_conditional_edges(
        "continuity_abschluss",
        _blockiert_oder("showrunner_freigabe"),
        ["showrunner_freigabe", "markiere_blockiert"],
    )
    g.add_conditional_edges(
        "showrunner_freigabe", route_freigabe, ["kontrollpunkt_kapitel", "markiere_blockiert"]
    )
    g.add_conditional_edges("kontrollpunkt_kapitel", route_kontrollpunkt, ["freigegeben", END])
    g.add_edge("freigegeben", END)
    g.add_edge("markiere_blockiert", "kontrollpunkt_blockiert")
    g.add_edge("kontrollpunkt_blockiert", END)
