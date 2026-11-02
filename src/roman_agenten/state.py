"""Graph-Zustand (§7.1). Verschachtelte Pydantic-Ausgaben liegen als JSON-Dicts vor,
damit der Checkpointer sie ohne Sonderbehandlung serialisiert."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

Phase = Literal[
    "brief", "recherche", "szenenplan", "entwurf", "pruefung", "lektorat", "freigegeben"
]
Status = Literal["offen", "in_arbeit", "blockiert", "freigegeben"]


class Revision(TypedDict, total=False):
    runde: int
    grund: str  # erstentwurf | pruefung | unterlaenge
    datei: str
    woerter: int


class ChapterState(TypedDict, total=False):
    brief: dict[str, Any]
    faktenblatt: dict[str, Any]
    szenenplan: dict[str, Any]
    entwurf: str
    autorennotiz: dict[str, Any]
    pruefung_kontinuitaet: dict[str, Any]
    pruefung_leitplanken: dict[str, Any]
    runde: int
    revisionen: list[Revision]
    endfassung: str
    lektoratsnotiz: dict[str, Any]
    zusammenfassung: str
    status: Status
    # Steuerfelder
    ueberarbeitungsgrund: str  # "" | pruefung | unterlaenge
    entscheidung: dict[str, Any]
    freigabe: dict[str, Any]
    bible_vorschlaege: int
    menschliches_feedback: str
    blockiert_grund: str


def merge_kapitel(
    left: dict[str, ChapterState] | None, right: dict[str, ChapterState] | None
) -> dict[str, ChapterState]:
    """Reducer: Felder pro Kapitel zusammenführen (für parallele Prüfer)."""
    out: dict[str, ChapterState] = {k: dict(v) for k, v in (left or {}).items()}  # type: ignore[misc]
    for nr, upd in (right or {}).items():
        merged = dict(out.get(nr, {}))
        merged.update(upd)
        out[nr] = merged  # type: ignore[assignment]
    return out


def add_kosten(left: dict[str, float] | None, right: dict[str, float] | None) -> dict[str, float]:
    out = dict(left or {})
    for k, v in (right or {}).items():
        out[k] = out.get(k, 0.0) + v
    return out


def merge_dict(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    return {**(left or {}), **(right or {})}


class NovelState(TypedDict, total=False):
    projekt_id: str
    bible_version: int
    aktuelles_kapitel: str
    phase: Phase
    kapitel: Annotated[dict[str, ChapterState], merge_kapitel]
    kontinuitaetsprotokoll: Annotated[list[dict[str, Any]], operator.add]
    figurenwissen: Annotated[dict[str, str], merge_dict]
    bible_aenderungen: Annotated[list[dict[str, Any]], operator.add]
    aktberichte: Annotated[dict[str, Any], merge_dict]
    kosten: Annotated[dict[str, float], add_kosten]
    lauf: dict[str, Any]  # {"art": "kapitel"} oder {"art": "akt", "akt": "I"}


def chapter(state: NovelState, nr: str | None = None) -> ChapterState:
    key = nr or state.get("aktuelles_kapitel", "")
    return state.get("kapitel", {}).get(key, {})
