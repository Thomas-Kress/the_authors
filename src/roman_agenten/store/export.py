"""Manuskript-Export. Markdown ist implementiert; DOCX/EPUB sind optional (§5.2)."""

from __future__ import annotations

from pathlib import Path

from roman_agenten.state import NovelState
from roman_agenten.store.bible_loader import Bible
from roman_agenten.store.project import Project


class ExportError(RuntimeError):
    pass


def export_markdown(project: Project, bible: Bible, state: NovelState) -> Path:
    kapitel = state.get("kapitel", {})
    teile = [f"# {project.config.titel}\n"]
    fehlend = []
    for zeile in bible.kapiteltabelle():
        ch = kapitel.get(zeile.nr, {})
        if ch.get("status") == "freigegeben" and ch.get("endfassung"):
            teile.append(ch["endfassung"].strip())
        else:
            fehlend.append(zeile.nr)
    if len(teile) == 1:
        raise ExportError("Keine freigegebenen Kapitel vorhanden")
    out = project.output_dir / "manuskript" / f"{project.id}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n\n---\n\n".join(teile) + "\n", encoding="utf-8")
    return out


def export(project: Project, bible: Bible, state: NovelState, fmt: str) -> Path:
    if fmt == "md":
        return export_markdown(project, bible, state)
    if fmt in ("docx", "epub"):
        raise ExportError(f"Export als {fmt} ist noch nicht implementiert (optional, §5.2)")
    raise ExportError(f"Unbekanntes Format '{fmt}'")
