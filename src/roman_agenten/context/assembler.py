"""Context Assembler (§9): bestimmt als reine Funktion, was welche Rolle sieht.

Ergebnis ist ein `RollenKontext` aus Platzhalterwerten für `_basis.md` und den
getaggten Eingabeblöcken der User-Nachricht. Keine Seiteneffekte, kein I/O.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from roman_agenten.config import Role
from roman_agenten.state import ChapterState, NovelState
from roman_agenten.store.bible_loader import Bible
from roman_agenten.store.project import ProjectConfig

LEER = "– leer –"


@dataclass(frozen=True)
class RollenKontext:
    basis: dict[str, str]
    bloecke: list[tuple[str, str]] = field(default_factory=list)
    kapitel_typ: str | None = None

    def block(self, tag: str) -> str | None:
        return next((v for t, v in self.bloecke if t == tag), None)


def _j(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def reihenfolge(bible: Bible, state: NovelState) -> list[str]:
    order = [z.nr for z in bible.kapiteltabelle()]
    order += [nr for nr in state.get("kapitel", {}) if nr not in order]
    return order


def vorherige(bible: Bible, state: NovelState, nr: str) -> list[str]:
    order = reihenfolge(bible, state)
    return order[: order.index(nr)] if nr in order else []


def freigegebene(bible: Bible, state: NovelState) -> list[str]:
    kap = state.get("kapitel", {})
    return [
        nr for nr in reihenfolge(bible, state) if kap.get(nr, {}).get("status") == "freigegeben"
    ]


def zusammenfassungen(state: NovelState, nrs: list[str]) -> str:
    kap = state.get("kapitel", {})
    zeilen = [
        f"Kapitel {nr}: {kap[nr]['zusammenfassung']}"
        for nr in nrs
        if kap.get(nr, {}).get("zusammenfassung")
    ]
    return "\n\n".join(zeilen) or LEER


def protokoll_text(state: NovelState) -> str:
    eintraege = state.get("kontinuitaetsprotokoll", [])
    if not eintraege:
        return LEER
    return "\n".join(
        f"- {e.get('fakt', '')}: {e.get('wert', '')} (erstmals in {e.get('erstmals_in', '?')})"
        for e in eintraege
    )


def akt_von(bible: Bible, nr: str) -> str:
    z = bible.kapitel(nr)
    return z.akt if z else "–"


def kapitel_der_akte(bible: Bible, akt: str) -> list[str]:
    return [z.nr for z in bible.kapiteltabelle() if z.akt == akt]


def bible_auszug(role: Role, bible: Bible, project: ProjectConfig) -> str:
    return bible.auszug(project.abschnitte_fuer(role))


def pruefberichte(ch: ChapterState) -> str:
    return _j(
        {
            "runde": ch.get("runde", 0),
            "kontinuitaet": ch.get("pruefung_kontinuitaet"),
            "leitplanken": ch.get("pruefung_leitplanken"),
        }
    )


def _basis(
    role: Role,
    state: NovelState,
    nr: str,
    bible: Bible,
    project: ProjectConfig,
    titel: str | None = None,
    akt: str | None = None,
) -> dict[str, str]:
    ch = state.get("kapitel", {}).get(nr, {})
    zeile = bible.kapitel(nr)
    frei = freigegebene(bible, state)
    return {
        "kapitel_nr": nr,
        "kapitel_titel": titel
        or ch.get("brief", {}).get("titel")
        or (zeile.titel if zeile else "")
        or "–",
        "akt": akt or akt_von(bible, nr),
        "freigegeben": ", ".join(frei) if frei else "keine",
        "bible_auszug": bible_auszug(role, bible, project),
        "kontinuitaetsprotokoll": protokoll_text(state),
    }


def assemble(
    role: Role,
    state: NovelState,
    nr: str,
    bible: Bible,
    project: ProjectConfig,
    modus: str | None = None,
) -> RollenKontext:
    """Kontext für eine Rolle in einem Kapitel. `modus` unterscheidet Aufgaben einer Rolle."""
    kap = state.get("kapitel", {})
    ch = kap.get(nr, {})
    brief = ch.get("brief", {})
    vor = vorherige(bible, state, nr)
    vor_frei = [v for v in vor if kap.get(v, {}).get("status") == "freigegeben"]
    b: list[tuple[str, str]] = []

    if role is Role.SHOWRUNNER:
        m = modus or "kapitel_brief"
        if m == "kapitel_brief":
            zeile = bible.kapitel(nr)
            b.append(("kapitelplan", _j(zeile.__dict__) if zeile else LEER))
            b.append(("zusammenfassungen", zusammenfassungen(state, vor_frei)))
            if ch.get("menschliches_feedback"):
                b.append(("feedback", ch["menschliches_feedback"]))
            if state.get("bible_aenderungen"):
                b.append(("offene_bible_aenderungen", _j(state["bible_aenderungen"])))
        elif m == "entscheidung":
            b += [
                ("brief", _j(brief)),
                ("entwurf", ch.get("entwurf", "")),
                ("pruefberichte", pruefberichte(ch)),
            ]
        elif m == "freigabe":
            b += [
                ("brief", _j(brief)),
                ("pruefberichte", pruefberichte(ch)),
                ("lektoratsnotiz", _j(ch.get("lektoratsnotiz", {}))),
                (
                    "wortzahl",
                    _j(
                        {
                            "ziel": brief.get("zielumfang_woerter"),
                            "gezaehlt": ch.get("lektoratsnotiz", {}).get(
                                "woerter_nachher_gezaehlt"
                            ),
                        }
                    ),
                ),
            ]
            if ch.get("entscheidung"):
                b.append(("entscheidung", _j(ch["entscheidung"])))
        elif m == "ueberarbeitungsauftrag":
            akt = akt_von(bible, nr)
            b.append(("aktbericht", _j(state.get("aktberichte", {}).get(akt, {}))))
        return RollenKontext(_basis(role, state, nr, bible, project), b)

    if role is Role.RESEARCH:
        b += [("brief", _j(brief)), ("stichtag", project.stichtag_realitaet.isoformat())]

    elif role is Role.PLOT_ARCHITECT:
        b += [
            ("brief", _j(brief)),
            ("faktenblatt", _j(ch.get("faktenblatt", {}))),
            ("zusammenfassungen", zusammenfassungen(state, vor_frei[-3:])),
        ]

    elif role is Role.CHAPTER_WRITER:
        letztes = vor_frei[-1] if vor_frei else None
        aeltere = vor_frei[:-1]
        b += [
            ("brief", _j(brief)),
            ("szenenplan", _j(ch.get("szenenplan", {}))),
            ("faktenblatt", _j(ch.get("faktenblatt", {}))),
            (
                "figurenwissen",
                _j(state.get("figurenwissen", {})) if state.get("figurenwissen") else LEER,
            ),
            ("vorkapitel", kap[letztes].get("endfassung", LEER) if letztes else LEER),
            ("zusammenfassungen", zusammenfassungen(state, aeltere)),
        ]
        if (modus or ch.get("ueberarbeitungsgrund")) in ("pruefung", "unterlaenge"):
            letzter = (
                ch.get("endfassung") if ch.get("ueberarbeitungsgrund") == "unterlaenge" else None
            )
            b.append(("letzter_entwurf", letzter or ch.get("entwurf", "")))
            if ch.get("ueberarbeitungsgrund") == "pruefung":
                b.append(("pruefberichte", pruefberichte(ch)))
        return RollenKontext(
            _basis(role, state, nr, bible, project), b, brief.get("kapitel_typ", "prosa")
        )

    elif role is Role.CONTINUITY:
        if (modus or "pruefung") == "abschluss":
            b.append(("endfassung", ch.get("endfassung", "")))
        else:
            b += [("brief", _j(brief)), ("entwurf", ch.get("entwurf", ""))]
        b.append(("zusammenfassungen", zusammenfassungen(state, vor_frei)))

    elif role is Role.GUARDRAILS:
        b += [("entwurf", ch.get("entwurf", "")), ("faktenblatt", _j(ch.get("faktenblatt", {})))]

    elif role is Role.LINE_EDITOR:
        b += [
            ("brief", _j(brief)),
            ("entwurf", ch.get("entwurf", "")),
            ("pruefberichte", pruefberichte(ch)),
        ]
        if ch.get("entscheidung"):
            b.append(("entscheidung", _j(ch["entscheidung"])))

    elif role is Role.FULL_READ:
        akt = modus or akt_von(bible, nr)
        texte = [
            kap[k]["endfassung"]
            for k in kapitel_der_akte(bible, akt)
            if kap.get(k, {}).get("endfassung")
        ]
        b.append(("endfassungen", "\n\n---\n\n".join(texte) or LEER))
        return RollenKontext(
            _basis(role, state, nr, bible, project, titel=f"Akt {akt}", akt=akt), b
        )

    return RollenKontext(_basis(role, state, nr, bible, project), b)
