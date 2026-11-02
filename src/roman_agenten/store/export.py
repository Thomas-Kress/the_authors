"""Manuskript-Export: Markdown, DOCX, EPUB und PDF (§5.2, §11.1)."""

from __future__ import annotations

import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from html import escape
from pathlib import Path

from roman_agenten.state import NovelState
from roman_agenten.store.bible_loader import Bible
from roman_agenten.store.project import Project

FORMATE = ("md", "docx", "epub", "pdf")


class ExportError(RuntimeError):
    pass


@dataclass(frozen=True)
class Block:
    """Ein Absatz des Manuskripts. `art`: h1 | h2 | h3 | p | trenner."""

    art: str
    text: str = ""


# Inline-Auszeichnung: (text, fett, kursiv)
Span = tuple[str, bool, bool]

_TRENNER = re.compile(r"^\s*(\*\s*\*\s*\*[\s*]*|-{3,}|_{3,})\s*$")
_UEBERSCHRIFT = re.compile(r"^(#{1,3})\s+(.*?)\s*#*\s*$")
_INLINE = re.compile(r"\*\*\*(.+?)\*\*\*|\*\*(.+?)\*\*|\*(.+?)\*|_(.+?)_")


def fehlende_kapitel(bible: Bible, state: NovelState) -> list[str]:
    kapitel = state.get("kapitel", {})
    return [
        z.nr
        for z in bible.kapiteltabelle()
        if not (
            kapitel.get(z.nr, {}).get("status") == "freigegeben"
            and kapitel.get(z.nr, {}).get("endfassung")
        )
    ]


def _endfassungen(bible: Bible, state: NovelState) -> list[str]:
    kapitel = state.get("kapitel", {})
    texte = []
    for zeile in bible.kapiteltabelle():
        ch = kapitel.get(zeile.nr, {})
        if ch.get("status") == "freigegeben" and ch.get("endfassung"):
            texte.append(ch["endfassung"].strip())
    if not texte:
        raise ExportError("Keine freigegebenen Kapitel vorhanden")
    return texte


def parse_markdown(text: str) -> list[Block]:
    """Minimaler Parser für die Kapitelfassungen: Überschriften, Absätze, Szenentrenner."""
    blocks: list[Block] = []
    absatz: list[str] = []

    def flush() -> None:
        if absatz:
            blocks.append(Block("p", " ".join(s.strip() for s in absatz)))
            absatz.clear()

    for zeile in text.splitlines():
        if not zeile.strip():
            flush()
        elif _TRENNER.match(zeile):
            flush()
            blocks.append(Block("trenner"))
        elif m := _UEBERSCHRIFT.match(zeile):
            flush()
            blocks.append(Block(f"h{len(m.group(1))}", m.group(2)))
        else:
            absatz.append(zeile)
    flush()
    return blocks


def parse_inline(text: str) -> list[Span]:
    spans: list[Span] = []
    pos = 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            spans.append((text[pos : m.start()], False, False))
        if m.group(1) is not None:
            spans.append((m.group(1), True, True))
        elif m.group(2) is not None:
            spans.append((m.group(2), True, False))
        else:
            spans.append((m.group(3) or m.group(4), False, True))
        pos = m.end()
    if pos < len(text):
        spans.append((text[pos:], False, False))
    return spans


def _kapitel_blocks(texte: list[str]) -> list[list[Block]]:
    return [parse_markdown(t) for t in texte]


def _ziel(project: Project, endung: str) -> Path:
    out = project.output_dir / "manuskript" / f"{project.id}.{endung}"
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


# ------------------------------------------------------------------ Markdown


def export_markdown(project: Project, bible: Bible, state: NovelState) -> Path:
    teile = [f"# {project.config.titel}\n", *_endfassungen(bible, state)]
    out = _ziel(project, "md")
    out.write_text("\n\n---\n\n".join(teile) + "\n", encoding="utf-8")
    return out


# ------------------------------------------------------------------ DOCX


def export_docx(project: Project, bible: Bible, state: NovelState) -> Path:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    kapitel = _kapitel_blocks(_endfassungen(bible, state))
    doc = Document()
    doc.core_properties.title = project.config.titel
    doc.core_properties.language = project.config.sprache
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)

    doc.add_heading(project.config.titel, level=0)

    def runs(par: object, text: str) -> None:
        for t, fett, kursiv in parse_inline(text):
            r = par.add_run(t)  # type: ignore[attr-defined]
            r.bold = fett or None
            r.italic = kursiv or None

    for blocks in kapitel:
        doc.add_page_break()  # type: ignore[no-untyped-call]
        for b in blocks:
            if b.art in ("h1", "h2", "h3"):
                doc.add_heading(b.text, level=int(b.art[1]))
            elif b.art == "trenner":
                par = doc.add_paragraph("*")
                par.alignment = WD_ALIGN_PARAGRAPH.CENTER
            else:
                par = doc.add_paragraph()
                par.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                runs(par, b.text)
    out = _ziel(project, "docx")
    doc.save(str(out))
    return out


# ------------------------------------------------------------------ EPUB


_EPUB_CSS = (
    "body{font-family:serif;line-height:1.4}"
    "p{margin:0;text-indent:1.2em;text-align:justify}"
    "h1,h2,h3{text-align:center;margin:1.5em 0 1em}"
    "p.trenner{text-indent:0;text-align:center;margin:1em 0}"
)


def _html_inline(text: str) -> str:
    out = []
    for t, fett, kursiv in parse_inline(text):
        s = escape(t)
        if fett:
            s = f"<strong>{s}</strong>"
        if kursiv:
            s = f"<em>{s}</em>"
        out.append(s)
    return "".join(out)


def _xhtml(titel: str, sprache: str, body: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<!DOCTYPE html>\n"
        f'<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{escape(sprache)}" '
        f'lang="{escape(sprache)}"><head><meta charset="utf-8"/>'
        f"<title>{escape(titel)}</title>"
        '<link rel="stylesheet" type="text/css" href="style.css"/></head>'
        f"<body>{body}</body></html>"
    )


def _html_blocks(blocks: list[Block]) -> str:
    teile = []
    for b in blocks:
        if b.art in ("h1", "h2", "h3"):
            teile.append(f"<{b.art}>{_html_inline(b.text)}</{b.art}>")
        elif b.art == "trenner":
            teile.append('<p class="trenner">*</p>')
        else:
            teile.append(f"<p>{_html_inline(b.text)}</p>")
    return "\n".join(teile)


def export_epub(project: Project, bible: Bible, state: NovelState) -> Path:
    cfg = project.config
    kapitel = _kapitel_blocks(_endfassungen(bible, state))
    dateien: list[tuple[str, str, str]] = []  # (dateiname, titel, xhtml)
    for i, blocks in enumerate(kapitel, 1):
        titel = next((b.text for b in blocks if b.art.startswith("h")), f"Kapitel {i}")
        dateien.append(
            (f"kap{i:03d}.xhtml", titel, _xhtml(titel, cfg.sprache, _html_blocks(blocks)))
        )

    uid = f"urn:roman-agenten:{project.id}"
    manifest = "".join(
        f'<item id="k{i}" href="{n}" media-type="application/xhtml+xml"/>'
        for i, (n, _, _) in enumerate(dateien, 1)
    )
    spine = "".join(f'<itemref idref="k{i}"/>' for i in range(1, len(dateien) + 1))
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:identifier id="uid">{escape(uid)}</dc:identifier>'
        f"<dc:title>{escape(cfg.titel)}</dc:title>"
        f"<dc:language>{escape(cfg.sprache)}</dc:language>"
        '<meta property="dcterms:modified">2000-01-01T00:00:00Z</meta>'
        "</metadata><manifest>"
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        '<item id="css" href="style.css" media-type="text/css"/>'
        f"{manifest}</manifest><spine>{spine}</spine></package>"
    )
    toc = "".join(f'<li><a href="{n}">{escape(t)}</a></li>' for n, t, _ in dateien)
    nav = (
        '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
        f'<head><meta charset="utf-8"/><title>{escape(cfg.titel)}</title></head><body>'
        f'<nav epub:type="toc"><h1>{escape(cfg.titel)}</h1><ol>{toc}</ol></nav></body></html>'
    )
    container = (
        '<?xml version="1.0"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    out = _ziel(project, "epub")
    with zipfile.ZipFile(out, "w") as z:
        # mimetype muss als erster Eintrag unkomprimiert abgelegt werden
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", container, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/nav.xhtml", nav, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/style.css", _EPUB_CSS, compress_type=zipfile.ZIP_DEFLATED)
        for name, _, xhtml in dateien:
            z.writestr(f"OEBPS/{name}", xhtml, compress_type=zipfile.ZIP_DEFLATED)
    return out


# ------------------------------------------------------------------ PDF


def _pdf_inline(text: str) -> str:
    out = []
    for t, fett, kursiv in parse_inline(text):
        s = escape(t)
        if fett:
            s = f"<b>{s}</b>"
        if kursiv:
            s = f"<i>{s}</i>"
        out.append(s)
    return "".join(out)


def export_pdf(project: Project, bible: Bible, state: NovelState) -> Path:
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
    from reportlab.lib.pagesizes import A5
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    kapitel = _kapitel_blocks(_endfassungen(bible, state))
    cfg = project.config
    basis = ParagraphStyle("basis", fontName="Times-Roman", fontSize=11, leading=15)
    stile = {
        "p": ParagraphStyle("p", parent=basis, alignment=TA_JUSTIFY, firstLineIndent=12),
        "h1": ParagraphStyle(
            "h1",
            parent=basis,
            fontName="Times-Bold",
            fontSize=18,
            leading=22,
            alignment=TA_CENTER,
            spaceBefore=30,
            spaceAfter=14,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=basis,
            fontName="Times-Bold",
            fontSize=14,
            leading=18,
            alignment=TA_CENTER,
            spaceBefore=12,
            spaceAfter=8,
        ),
        "h3": ParagraphStyle(
            "h3",
            parent=basis,
            fontName="Times-Bold",
            fontSize=12,
            leading=16,
            spaceBefore=8,
            spaceAfter=6,
        ),
        "trenner": ParagraphStyle(
            "trenner", parent=basis, alignment=TA_CENTER, spaceBefore=8, spaceAfter=8
        ),
        "titel": ParagraphStyle(
            "titel",
            parent=basis,
            fontName="Times-Bold",
            fontSize=28,
            leading=34,
            alignment=TA_CENTER,
        ),
    }

    story: list[object] = [Spacer(1, 70 * mm), Paragraph(escape(cfg.titel), stile["titel"])]
    for blocks in kapitel:
        story.append(PageBreak())
        for b in blocks:
            if b.art == "trenner":
                story.append(Paragraph("*", stile["trenner"]))
            else:
                story.append(Paragraph(_pdf_inline(b.text), stile[b.art]))

    def seitenzahl(canvas: object, doc: object) -> None:
        nr = doc.page  # type: ignore[attr-defined]
        if nr > 1:
            canvas.setFont("Times-Roman", 9)  # type: ignore[attr-defined]
            canvas.drawCentredString(A5[0] / 2, 10 * mm, str(nr - 1))  # type: ignore[attr-defined]

    out = _ziel(project, "pdf")
    SimpleDocTemplate(
        str(out),
        pagesize=A5,
        title=cfg.titel,
        author="",
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=20 * mm,
    ).build(story, onFirstPage=seitenzahl, onLaterPages=seitenzahl)
    return out


# ------------------------------------------------------------------ Dispatch

_EXPORTER: dict[str, Callable[[Project, Bible, NovelState], Path]] = {
    "md": export_markdown,
    "docx": export_docx,
    "epub": export_epub,
    "pdf": export_pdf,
}


def export(project: Project, bible: Bible, state: NovelState, fmt: str) -> Path:
    exporter = _EXPORTER.get(fmt.lower())
    if exporter is None:
        raise ExportError(f"Unbekanntes Format '{fmt}' (erlaubt: {', '.join(FORMATE)})")
    return exporter(project, bible, state)
