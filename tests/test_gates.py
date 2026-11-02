from __future__ import annotations

import itertools

import pytest

from roman_agenten.graph import gates
from roman_agenten.state import ChapterState

KONT = [{"bestanden": True, "funde": []}, {"bestanden": False, "funde": [{"schwere": "MITTEL"}]}]
ENTSCHEIDUNGEN = [{"entscheidung": "lektorat"}, {"entscheidung": "blockiert"}, {}]
FREIGABEN = [{"freigegeben": True}, {"freigegeben": False}, {}]


def ch(ergebnis: str, runde: int, kont: dict, **kw: object) -> ChapterState:  # type: ignore[type-arg]
    return ChapterState(
        pruefung_leitplanken={"ergebnis": ergebnis},
        pruefung_kontinuitaet=kont,  # type: ignore[typeddict-item]
        runde=runde,
        brief={"zielumfang_woerter": 100},
        **kw,
    )


@pytest.mark.parametrize(
    ("runde", "kont", "ent", "frei"),
    list(itertools.product(range(0, 5), KONT, ENTSCHEIDUNGEN, FREIGABEN)),
)
def test_ablehnung_fuehrt_nie_zu_lektorat_oder_freigabe(
    runde: int, kont: dict, ent: dict, frei: dict
) -> None:  # type: ignore[type-arg]
    c = ch("ABLEHNUNG", runde, kont, entscheidung=ent, freigabe=frei)
    assert gates.route_pruefung(c, 3) in ("chapter_writer", "blockiert")
    assert gates.route_entscheidung(c) == "blockiert"
    assert gates.route_freigabe(c) == "blockiert"
    with pytest.raises(gates.VetoVerletzung):
        gates.assert_kein_veto(c, "line_editor")


def test_ablehnung_schleife_dann_blockiert() -> None:
    assert gates.route_pruefung(ch("ABLEHNUNG", 2, KONT[0]), 3) == "chapter_writer"
    assert gates.route_pruefung(ch("ABLEHNUNG", 3, KONT[0]), 3) == "blockiert"


def test_bestanden_geht_ins_lektorat() -> None:
    assert gates.route_pruefung(ch("FREIGABE", 1, KONT[0]), 3) == "line_editor"


@pytest.mark.parametrize("ergebnis", ["UEBERARBEITUNG", "FREIGABE"])
def test_schleife_endet_nach_max_runden(ergebnis: str) -> None:
    kont = KONT[1] if ergebnis == "FREIGABE" else KONT[0]
    routen = [gates.route_pruefung(ch(ergebnis, r, kont), 3) for r in range(1, 5)]
    assert routen == [
        "chapter_writer",
        "chapter_writer",
        "showrunner_entscheidung",
        "showrunner_entscheidung",
    ]


def test_entscheidung_ohne_veto() -> None:
    assert (
        gates.route_entscheidung(
            ch("UEBERARBEITUNG", 3, KONT[1], entscheidung={"entscheidung": "lektorat"})
        )
        == "line_editor"
    )
    assert (
        gates.route_entscheidung(
            ch("UEBERARBEITUNG", 3, KONT[1], entscheidung={"entscheidung": "blockiert"})
        )
        == "blockiert"
    )


def test_wortzahl_gate() -> None:
    kurz = ch("FREIGABE", 1, KONT[0], lektoratsnotiz={"woerter_nachher_gezaehlt": 50})
    ok = ch("FREIGABE", 1, KONT[0], lektoratsnotiz={"woerter_nachher_gezaehlt": 90})
    assert gates.route_wortzahl(kurz, 0.15, 3) == "chapter_writer"
    assert gates.route_wortzahl(ok, 0.15, 3) == "continuity_abschluss"
    assert gates.route_wortzahl({**kurz, "runde": 3}, 0.15, 3) == "continuity_abschluss"
