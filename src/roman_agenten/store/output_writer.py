"""Ablage der Kapitelartefakte unter `output/kapitel/<nr>_<slug>/` (§11.2).

Revisionen werden nie überschrieben: `entwurf_r1.md`, `entwurf_r2.md`, …
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from roman_agenten.store.project import Project


def slugify(text: str) -> str:
    text = text.replace("ß", "ss").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    text = text.replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "kapitel"


class OutputWriter:
    def __init__(self, project: Project) -> None:
        self.project = project

    def kapitel_dir(self, nr: str, titel: str = "") -> Path:
        base = self.project.output_dir / "kapitel"
        existing = sorted(base.glob(f"{nr}_*")) if base.exists() else []
        d = existing[0] if existing else base / f"{nr}_{slugify(titel)}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _write_new(self, path: Path, content: str) -> Path:
        if path.exists() and path.read_text(encoding="utf-8") != content:
            raise FileExistsError(
                f"{path} existiert bereits – Revisionen werden nicht überschrieben"
            )
        path.write_text(content, encoding="utf-8")
        return path

    def json(self, nr: str, titel: str, name: str, data: Any) -> Path:
        p = self.kapitel_dir(nr, titel) / name
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    def entwurf(self, nr: str, titel: str, runde: int, text: str) -> Path:
        return self._write_new(self.kapitel_dir(nr, titel) / f"entwurf_r{runde}.md", text)

    def pruefungen(self, nr: str, titel: str, runde: int, data: dict[str, Any]) -> Path:
        p = self.kapitel_dir(nr, titel) / f"pruefungen_r{runde}.json"
        return self._write_new(p, json.dumps(data, ensure_ascii=False, indent=2))

    def endfassung(self, nr: str, titel: str, text: str) -> Path:
        p = self.kapitel_dir(nr, titel) / "endfassung.md"
        p.write_text(text, encoding="utf-8")
        return p

    def bible_aenderung(self, nr: str, data: dict[str, Any]) -> Path:
        """Bible-Änderungsvorschläge werden nur abgelegt – die Bible selbst bleibt unverändert."""
        d = self.project.output_dir / "berichte" / "bible_aenderungen"
        d.mkdir(parents=True, exist_ok=True)
        n = len(list(d.glob("*.json"))) + 1
        p = d / f"{n:03d}_kapitel_{nr}.json"
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    def aktbericht(self, akt: str, data: dict[str, Any]) -> Path:
        d = self.project.output_dir / "berichte"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"aktbericht_{akt}.json"
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return p
