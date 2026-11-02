"""Gates des Kapitelgraphen (§5.1) als reine Funktionen.

Hier – und nur hier – beeinflussen LLM-Ausgaben den Kontrollfluss. Das Leitplanken-Veto
ist absolut: Bei `ABLEHNUNG` führt kein Pfad zu `line_editor` oder `freigegeben`.
"""

from __future__ import annotations

from typing import Literal

from roman_agenten.state import ChapterState

ABLEHNUNG = "ABLEHNUNG"


class VetoVerletzung(RuntimeError):
    """Ein Codepfad hat versucht, eine Leitplanken-Ablehnung zu überstimmen."""


def leitplanken_ergebnis(ch: ChapterState) -> str | None:
    return (ch.get("pruefung_leitplanken") or {}).get("ergebnis")


def veto(ch: ChapterState) -> bool:
    return leitplanken_ergebnis(ch) == ABLEHNUNG


def assert_kein_veto(ch: ChapterState, schritt: str) -> None:
    if veto(ch):
        raise VetoVerletzung(f"{schritt} trotz Leitplanken-ABLEHNUNG aufgerufen")


def kontinuitaet_bestanden(ch: ChapterState) -> bool:
    k = ch.get("pruefung_kontinuitaet") or {}
    if not k.get("bestanden", False):
        return False
    return not any(f.get("schwere") in ("KRITISCH", "MITTEL") for f in k.get("funde", []))


PruefRoute = Literal["chapter_writer", "blockiert", "line_editor", "showrunner_entscheidung"]


def route_pruefung(ch: ChapterState, max_rounds: int) -> PruefRoute:
    runde = ch.get("runde", 0)
    if ch.get("status") == "blockiert":
        return "blockiert"
    if veto(ch):
        return "chapter_writer" if runde < max_rounds else "blockiert"
    if kontinuitaet_bestanden(ch) and leitplanken_ergebnis(ch) == "FREIGABE":
        return "line_editor"
    return "chapter_writer" if runde < max_rounds else "showrunner_entscheidung"


def route_entscheidung(ch: ChapterState) -> Literal["line_editor", "blockiert"]:
    if veto(ch):  # durch keinen Showrunner-Entscheid überstimmbar
        return "blockiert"
    if (ch.get("entscheidung") or {}).get("entscheidung") == "lektorat":
        return "line_editor"
    return "blockiert"


def unterlaenge(ch: ChapterState, tolerance: float) -> bool:
    ziel = (ch.get("brief") or {}).get("zielumfang_woerter")
    ist = (ch.get("lektoratsnotiz") or {}).get("woerter_nachher_gezaehlt")
    if not ziel or ist is None:
        return False
    return bool(ist < ziel * (1 - tolerance))


def route_wortzahl(
    ch: ChapterState, tolerance: float, max_rounds: int
) -> Literal["chapter_writer", "continuity_abschluss"]:
    if unterlaenge(ch, tolerance) and ch.get("runde", 0) < max_rounds:
        return "chapter_writer"
    return "continuity_abschluss"


def route_freigabe(ch: ChapterState) -> Literal["kontrollpunkt_kapitel", "blockiert"]:
    if veto(ch):
        return "blockiert"
    if (ch.get("freigabe") or {}).get("freigegeben") is True:
        return "kontrollpunkt_kapitel"
    return "blockiert"
