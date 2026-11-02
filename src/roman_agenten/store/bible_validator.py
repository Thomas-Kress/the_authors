"""Bible-Validator (§4.3). Listet alle Verstöße auf, nicht nur den ersten."""

from __future__ import annotations

import re

from roman_agenten.schemas import KAPITEL_NR_PATTERN
from roman_agenten.store.bible_loader import (
    KAPITELTABELLE_ABSCHNITTE,
    KAPITELTABELLE_SPALTEN,
    Bible,
    parse_table,
)
from roman_agenten.store.project import ProjectConfig

HAUPTABSCHNITTE = [str(i) for i in range(11)]
PFLICHT_UNTERABSCHNITTE = [
    "2.1",
    "2.2",
    "3.1",
    "3.2",
    "3.3",
    "4.1",
    "4.2",
    "4.3",
    "4.4",
    "5.1",
    "5.2",
    "5.3",
    "6.1",
    "6.2",
    "6.3",
    "6.4",
    "8.1",
    "8.2",
    "8.3",
    "8.4",
    "10.1",
    "10.2",
    "10.3",
    "10.4",
    "10.5",
]
MIN_EINTRAEGE_10_4 = 8
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S")


def _eintraege(text: str) -> int:
    lines = text.splitlines()[1:]  # Überschrift weglassen
    items = sum(1 for ln in lines if LIST_ITEM_RE.match(ln))
    _, rows = parse_table(text)
    return max(items, len(rows))


def validate_bible(bible: Bible, project: ProjectConfig) -> list[str]:
    fehler: list[str] = []
    for nr in HAUPTABSCHNITTE:
        if not bible.has(nr):
            fehler.append(f"Hauptabschnitt '## {nr}. …' fehlt")
    for nr in PFLICHT_UNTERABSCHNITTE:
        if not bible.has(nr):
            fehler.append(f"Pflicht-Unterabschnitt '### {nr} …' fehlt")
    for t in bible.unbekannte_ueberschriften:
        fehler.append(f"Unbekannte Überschrift '## {t}' (erlaubt: '## N. Titel' oder '## Quellen')")

    gesehen: set[str] = set()
    for nr in KAPITELTABELLE_ABSCHNITTE:
        if not bible.has(nr):
            continue
        header, rows = parse_table(bible.text(nr))
        if not header:
            fehler.append(f"{nr}: keine Kapiteltabelle gefunden")
            continue
        if header != KAPITELTABELLE_SPALTEN:
            fehler.append(
                f"{nr}: Spalten der Kapiteltabelle sind {header}, erwartet {KAPITELTABELLE_SPALTEN}"
            )
            continue
        for row in rows:
            knr = row[0] if row else ""
            if not KAPITEL_NR_PATTERN.match(knr):
                fehler.append(f"{nr}: ungültige Kapitelnummer '{knr}' (Muster P, E, 1…n, SP1, D2)")
            elif knr in gesehen:
                fehler.append(f"{nr}: Kapitelnummer '{knr}' doppelt")
            gesehen.add(knr)
            if len(row) != len(KAPITELTABELLE_SPALTEN):
                fehler.append(
                    f"{nr}: Zeile '{knr}' hat {len(row)} statt {len(KAPITELTABELLE_SPALTEN)} Spalten"
                )

    for nr in ("4.3", "10.3"):
        if bible.has(nr) and project.brief_feld not in bible.text(nr):
            fehler.append(
                f"{nr}: Brief-Feld '{project.brief_feld}' (aus project.yaml) wird nicht genannt"
            )

    if bible.has("10.4"):
        n = _eintraege(bible.text("10.4"))
        if n < MIN_EINTRAEGE_10_4:
            fehler.append(f"10.4: {n} Einträge, mindestens {MIN_EINTRAEGE_10_4} erforderlich")
    return fehler
