"""Bible-Loader (§4.3): adressiert Abschnitte ausschließlich über ihre Nummer.

Akzeptiert `bible/bible.md` oder elf Dateien `00_*.md` … `10_*.md`; beide Formen ergeben
dieselbe Abschnittsstruktur. Die Bible wird nur gelesen, nie geschrieben.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

MAIN_RE = re.compile(r"^##\s+(\d{1,2})\.\s+(.+?)\s*$")
SUB_RE = re.compile(r"^###\s+(\d{1,2})\.(\d{1,2})\.?\s+(.+?)\s*$")
QUELLEN_RE = re.compile(r"^##\s+Quellen\s*$", re.I)
OTHER_H2_RE = re.compile(r"^##\s+(?!#)(.+?)\s*$")
FILE_RE = re.compile(r"^(\d{2})_[\w-]+\.md$")

KAPITELTABELLE_SPALTEN = [
    "Nr",
    "Titel",
    "POV",
    "Ort / Zeit",
    "Wörter",
    "Funktion",
    "Pflicht-Ereignisse",
    "Stufe/Wirkung (4.3)",
    "Schlussbild",
]
KAPITELTABELLE_ABSCHNITTE = {"6.1": "I", "6.2": "II", "6.3": "III"}


class BibleError(RuntimeError):
    pass


@dataclass
class Abschnitt:
    nr: str
    titel: str
    zeilen: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.zeilen).strip()


@dataclass(frozen=True)
class KapitelZeile:
    nr: str
    titel: str
    pov: str
    ort_zeit: str
    woerter: int | None
    funktion: str
    pflicht_ereignisse: str
    stufe_wirkung: str
    schlussbild: str
    akt: str


@dataclass
class Bible:
    abschnitte: dict[str, Abschnitt]  # "0".."10" und "3.3" usw.
    quellen: str | None = None
    unbekannte_ueberschriften: list[str] = field(default_factory=list)
    praeambel: str = ""

    def hauptabschnitte(self) -> list[str]:
        return [k for k in self.abschnitte if "." not in k]

    def has(self, nr: str) -> bool:
        return nr in self.abschnitte

    def text(self, nr: str) -> str:
        if nr not in self.abschnitte:
            raise BibleError(f"Bible-Abschnitt {nr} existiert nicht")
        return self.abschnitte[nr].text

    def auszug(self, nrs: list[str]) -> str:
        """Bible-Auszug in Dokumentreihenfolge; `alle` liefert die ganze Bible inkl. Quellen."""
        if "alle" in nrs:
            teile = [self.abschnitte[k].text for k in self.hauptabschnitte()]
            if self.quellen:
                teile.append(self.quellen)
            return "\n\n".join(teile)
        wanted = set(nrs)
        teile = []
        for k in self.abschnitte:
            main = k.split(".")[0]
            if k in wanted and not ("." in k and main in wanted):
                teile.append(self.abschnitte[k].text)
        fehlend = wanted - set(self.abschnitte)
        if fehlend:
            raise BibleError(f"Bible-Abschnitte fehlen: {', '.join(sorted(fehlend))}")
        return "\n\n".join(teile)

    def kapiteltabelle(self) -> list[KapitelZeile]:
        zeilen: list[KapitelZeile] = []
        for nr, akt in KAPITELTABELLE_ABSCHNITTE.items():
            if nr not in self.abschnitte:
                continue
            header, rows = parse_table(self.abschnitte[nr].text)
            if header != KAPITELTABELLE_SPALTEN:
                continue
            for r in rows:
                r = (r + [""] * 9)[:9]
                w = re.sub(r"[^\d]", "", r[4])
                zeilen.append(
                    KapitelZeile(
                        r[0], r[1], r[2], r[3], int(w) if w else None, r[5], r[6], r[7], r[8], akt
                    )
                )
        return zeilen

    def kapitel(self, nr: str) -> KapitelZeile | None:
        return next((z for z in self.kapiteltabelle() if z.nr == nr), None)


def parse_table(text: str) -> tuple[list[str], list[list[str]]]:
    """Erste Markdown-Tabelle im Text: (Kopfzeile, Datenzeilen)."""
    lines = [ln.strip() for ln in text.splitlines()]
    for i, ln in enumerate(lines):
        if ln.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1]):
            header = _cells(ln)
            rows = []
            for row in lines[i + 2 :]:
                if not row.startswith("|"):
                    break
                rows.append(_cells(row))
            return header, rows
    return [], []


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_bible(markdown: str) -> Bible:
    abschnitte: dict[str, Abschnitt] = {}
    main: Abschnitt | None = None
    sub: Abschnitt | None = None
    quellen: list[str] | None = None
    praeambel: list[str] = []
    unbekannt: list[str] = []
    for line in markdown.splitlines():
        if m := MAIN_RE.match(line):
            main = Abschnitt(m.group(1).lstrip("0") or "0", m.group(2), [line])
            abschnitte[main.nr] = main
            sub, quellen = None, None
            continue
        if QUELLEN_RE.match(line):
            main, sub, quellen = None, None, [line]
            continue
        if (m2 := OTHER_H2_RE.match(line)) and not line.startswith("###"):
            unbekannt.append(m2.group(1))
            main, sub, quellen = None, None, None
            continue
        if (m3 := SUB_RE.match(line)) and main is not None:
            nr = f"{m3.group(1).lstrip('0') or '0'}.{m3.group(2)}"
            sub = Abschnitt(nr, m3.group(3), [line])
            abschnitte[nr] = sub
            main.zeilen.append(line)
            continue
        if quellen is not None:
            quellen.append(line)
        elif main is not None:
            main.zeilen.append(line)
            if sub is not None:
                sub.zeilen.append(line)
        else:
            praeambel.append(line)
    return Bible(
        abschnitte,
        "\n".join(quellen).strip() if quellen else None,
        unbekannt,
        "\n".join(praeambel).strip(),
    )


def bible_dateien(bible_dir: Path) -> list[Path]:
    single = bible_dir / "bible.md"
    multi = sorted(p for p in bible_dir.glob("*.md") if FILE_RE.match(p.name))
    if single.is_file() and multi:
        raise BibleError(
            f"{bible_dir}: bible.md und Einzeldateien gleichzeitig – nur eine Ablageform erlaubt"
        )
    if single.is_file():
        return [single]
    if multi:
        return multi
    raise BibleError(f"{bible_dir}: weder bible.md noch 00_*.md … 10_*.md gefunden")


def load_bible(bible_dir: Path) -> Bible:
    teile = [p.read_text(encoding="utf-8") for p in bible_dateien(bible_dir)]
    return parse_bible("\n\n".join(teile))
