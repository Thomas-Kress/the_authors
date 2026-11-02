"""Prompt-Loader (§8): Lookup Projektordner → Repo-`prompts/`, Platzhalter `{{name}}`."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from roman_agenten.config import Role

PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
BASIS_PLATZHALTER = frozenset(
    {"kapitel_nr", "kapitel_titel", "akt", "freigegeben", "bible_auszug", "kontinuitaetsprotokoll"}
)
ROLE_PROMPT_FILES: tuple[str, ...] = ("_basis.md", *(f"{r.value}.md" for r in Role))


class PromptError(RuntimeError):
    pass


def placeholders(template: str) -> set[str]:
    return set(PLACEHOLDER_RE.findall(template))


def render(template: str, values: Mapping[str, object]) -> str:
    """Füllt Platzhalter. Unbekannte oder ungefüllte Platzhalter sind ein Fehler."""
    needed = placeholders(template)
    missing = sorted(n for n in needed if n not in values or values[n] is None)
    if missing:
        raise PromptError(f"Ungefüllte/unbekannte Platzhalter: {', '.join(missing)}")
    # Werte werden in einem Durchgang eingesetzt – Text in Werten wird nicht erneut ersetzt.
    return PLACEHOLDER_RE.sub(lambda m: str(values[m.group(1)]), template)


class PromptLoader:
    def __init__(self, prompts_dir: Path, project_dir: Path | None = None) -> None:
        self.prompts_dir = prompts_dir
        self.override_dir = project_dir / "prompts" if project_dir else None

    def path(self, name: str) -> Path | None:
        for base in (self.override_dir, self.prompts_dir):
            if base is not None and (base / name).is_file():
                return base / name
        return None

    def load(self, name: str) -> str:
        p = self.path(name)
        if p is None:
            raise PromptError(
                f"Prompt '{name}' weder im Projekt noch in {self.prompts_dir} gefunden"
            )
        return p.read_text(encoding="utf-8")

    def has_zusatz(self, kapitel_typ: str) -> bool:
        return self.path(f"zusaetze/{kapitel_typ}.md") is not None

    def missing_zusaetze(self, kapitel_typen: list[str]) -> list[str]:
        return [t for t in kapitel_typen if t != "prosa" and not self.has_zusatz(t)]

    def system_prompt(
        self, role: Role, basis_values: Mapping[str, object], kapitel_typ: str | None = None
    ) -> str:
        unknown = placeholders(self.load("_basis.md")) - BASIS_PLATZHALTER
        if unknown:
            raise PromptError(f"Unbekannte Platzhalter in _basis.md: {', '.join(sorted(unknown))}")
        parts = [
            render(self.load("_basis.md"), basis_values),
            render(self.load(f"{role.value}.md"), {}),
        ]
        if role is Role.CHAPTER_WRITER and kapitel_typ and kapitel_typ != "prosa":
            parts.append(render(self.load(f"zusaetze/{kapitel_typ}.md"), {}))
        return "\n\n".join(p.strip() for p in parts) + "\n"

    def auftrag(self, name: str, values: Mapping[str, object]) -> str:
        return render(self.load(f"auftraege/{name}.md"), values).strip()
