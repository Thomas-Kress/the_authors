"""Projektordner und `project.yaml` (§11.2)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from roman_agenten.config import Role

DEFAULT_KONTEXT: dict[str, list[str]] = {
    Role.SHOWRUNNER.value: ["alle"],
    Role.RESEARCH.value: ["2", "3", "8", "9"],
    Role.PLOT_ARCHITECT.value: ["1", "4", "5", "6"],
    Role.CHAPTER_WRITER.value: ["1", "3.3", "4.4", "5", "7", "9"],
    Role.CONTINUITY.value: ["3", "4", "5", "6", "10.4"],
    Role.GUARDRAILS.value: ["8", "9"],
    Role.LINE_EDITOR.value: ["5", "7"],
    Role.FULL_READ.value: ["1", "6"],
}


class ProjectError(RuntimeError):
    def __init__(self, fehler: list[str]) -> None:
        super().__init__("\n".join(fehler))
        self.fehler = fehler


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9_-]+$")
    titel: str
    sprache: str
    zielumfang_woerter: int = Field(gt=0)
    bible_version: int
    stichtag_realitaet: dt.date
    brief_feld: str = Field(pattern=r"^[a-z_][a-z0-9_]*$")
    kapitel_typen: list[str]
    kontrollpunkte: list[dict[str, Any]] = []
    kontext: dict[str, list[str]] | None = None

    @field_validator("kapitel_typen")
    @classmethod
    def _prosa(cls, v: list[str]) -> list[str]:
        if "prosa" not in v:
            raise ValueError("kapitel_typen muss 'prosa' enthalten")
        return v

    @field_validator("kontext")
    @classmethod
    def _rollen(cls, v: dict[str, list[str]] | None) -> dict[str, list[str]] | None:
        if v:
            unbekannt = set(v) - {r.value for r in Role}
            if unbekannt:
                raise ValueError(f"Unbekannte Rollen im kontext: {sorted(unbekannt)}")
        return v

    def abschnitte_fuer(self, role: Role) -> list[str]:
        mapping = {**DEFAULT_KONTEXT, **(self.kontext or {})}
        return list(mapping[role.value])

    def kontrollpunkt_nach_kapitel(self, nr: str) -> bool:
        return any(str(k.get("nach_kapitel")) == nr for k in self.kontrollpunkte)

    def kontrollpunkt_nach_akt(self) -> bool:
        return any(bool(k.get("nach_jedem_akt")) for k in self.kontrollpunkte)


@dataclass(frozen=True)
class Project:
    dir: Path
    config: ProjectConfig

    @property
    def id(self) -> str:
        return self.config.id

    @property
    def bible_dir(self) -> Path:
        return self.dir / "bible"

    @property
    def state_dir(self) -> Path:
        return self.dir / "state"

    @property
    def output_dir(self) -> Path:
        return self.dir / "output"

    def ensure_dirs(self) -> None:
        for d in (
            self.state_dir,
            self.output_dir / "kapitel",
            self.output_dir / "berichte",
            self.output_dir / "manuskript",
        ):
            d.mkdir(parents=True, exist_ok=True)


def load_project(projects_dir: Path, projekt_id: str) -> Project:
    pdir = projects_dir / projekt_id
    yml = pdir / "project.yaml"
    if not yml.is_file():
        raise ProjectError([f"{yml} nicht gefunden"])
    try:
        data = yaml.safe_load(yml.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ProjectError([f"project.yaml ist kein gültiges YAML: {e}"]) from e
    try:
        cfg = ProjectConfig.model_validate(data)
    except ValidationError as e:
        raise ProjectError(
            [
                f"project.yaml: {'.'.join(map(str, err['loc'])) or '<wurzel>'}: {err['msg']}"
                for err in e.errors()
            ]
        ) from e
    if cfg.id != projekt_id:
        raise ProjectError(
            [f"project.yaml: id '{cfg.id}' entspricht nicht dem Ordnernamen '{projekt_id}'"]
        )
    return Project(pdir, cfg)
