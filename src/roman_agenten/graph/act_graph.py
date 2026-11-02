"""Akt-Abschluss (§5.2): full_read → Aktbericht → Kontrollpunkt → showrunner(ueberarbeitungsauftrag).

Die Kapitel eines Akts laufen vorher sequenziell durch den Kapitelgraphen (siehe `novel_graph`).
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from roman_agenten.agents import full_read, showrunner
from roman_agenten.context.assembler import kapitel_der_akte
from roman_agenten.graph.runtime import AgentFormatError, Runtime
from roman_agenten.state import NovelState


def _akt(state: NovelState) -> str:
    return str(state["lauf"]["akt"])


def add_act_nodes(g: StateGraph, rt: Runtime) -> None:  # type: ignore[type-arg]
    def letztes(akt: str) -> str:
        kap = kapitel_der_akte(rt.bible, akt)
        if not kap:
            raise ValueError(f"Akt {akt} hat keine Kapitel in der Kapiteltabelle")
        return kap[-1]

    def bericht(state: NovelState, akt: str) -> dict[str, Any]:
        return dict((state.get("aktberichte") or {}).get(akt, {}))

    def full_read_node(state: NovelState) -> dict[str, Any]:
        akt = _akt(state)
        try:
            ab, k = rt.call(full_read, state, rt.ctx(letztes(akt), akt))
        except AgentFormatError as e:
            return {"aktberichte": {akt: {"status": "fehler", "fehler": str(e)}}}
        data = ab.model_dump(mode="json")
        rt.writer.aktbericht(akt, data)
        return {
            "kosten": k,
            "aktberichte": {akt: {"bericht": data, "status": "wartet_auf_freigabe"}},
        }

    def kontrollpunkt_akt(state: NovelState) -> dict[str, Any]:
        akt = _akt(state)
        b = bericht(state, akt)
        if b.get("status") == "fehler":
            interrupt({"art": "blockiert", "akt": akt, "grund": b.get("fehler")})
            return {}
        if not rt.settings.human_checkpoints:
            return {"aktberichte": {akt: {**b, "status": "freigegeben"}}}
        antwort = interrupt({"art": "aktbericht", "akt": akt, "bericht": b.get("bericht")})
        ok = not (isinstance(antwort, dict) and antwort.get("genehmigt") is False)
        kommentar = antwort.get("kommentar", "") if isinstance(antwort, dict) else ""
        return {
            "aktberichte": {
                akt: {**b, "status": "freigegeben" if ok else "abgelehnt", "kommentar": kommentar}
            }
        }

    def route_akt(state: NovelState) -> str:
        return (
            "showrunner_ueberarbeitung"
            if bericht(state, _akt(state)).get("status") == "freigegeben"
            else END
        )

    def showrunner_ueberarbeitung(state: NovelState) -> dict[str, Any]:
        akt = _akt(state)
        b = bericht(state, akt)
        try:
            out, k = rt.call(
                showrunner,
                state,
                rt.ctx(letztes(akt), "ueberarbeitungsauftrag"),
                modus="ueberarbeitungsauftrag",
            )
        except AgentFormatError as e:
            return {"aktberichte": {akt: {**b, "status": "fehler", "fehler": str(e)}}}
        auftraege = [a.model_dump(mode="json") for a in out.inhalt.auftraege]
        rt.writer.aktbericht(f"{akt}_auftraege", {"auftraege": auftraege})
        return {
            "kosten": k,
            "aktberichte": {akt: {**b, "auftraege": auftraege, "status": "auftraege_erstellt"}},
        }

    g.add_node("full_read", full_read_node)
    g.add_node("kontrollpunkt_akt", kontrollpunkt_akt)
    g.add_node("showrunner_ueberarbeitung", showrunner_ueberarbeitung)
    g.add_edge("full_read", "kontrollpunkt_akt")
    g.add_conditional_edges("kontrollpunkt_akt", route_akt, ["showrunner_ueberarbeitung", END])
    g.add_edge("showrunner_ueberarbeitung", END)
