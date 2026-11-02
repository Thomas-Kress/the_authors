"""Pydantic-v2-Schemas aller Agentenausgaben (Anhang A)."""

from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, TypeAdapter, field_validator

KAPITEL_NR_REGEX = r"^(P|E|\d+|[A-Z]{1,3}\d+)$"
KAPITEL_NR_PATTERN = re.compile(KAPITEL_NR_REGEX)


def _str_coerce(v: Any) -> Any:
    """Kleine Modelle liefern Kapitelnummern und Werte gern als Zahl."""
    return str(v) if isinstance(v, int | float) and not isinstance(v, bool) else v


KapitelNr = Annotated[str, BeforeValidator(_str_coerce), Field(pattern=KAPITEL_NR_REGEX)]
Text = Annotated[str, BeforeValidator(_str_coerce)]


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


# --------------------------------------------------------------------- Showrunner


class KapitelBrief(BaseModel):
    """Kernfelder laut Vorlage 10.3 + genau ein projektspezifisches Feld (`brief_feld`)."""

    model_config = ConfigDict(extra="allow")

    titel: str
    kapitel_typ: str = "prosa"
    pov: str
    ort_zeit: str
    zielumfang_woerter: int = Field(gt=0)
    funktion: str
    ausgangszustand: str
    endzustand: str
    pflicht_ereignisse: list[str]
    figuren: list[str]
    verbotene_vorwegnahmen: list[str]
    schlussbild: str

    def pruefe_projekt(self, brief_feld: str, kapitel_typen: list[str]) -> list[str]:
        """Prüft die projektabhängigen Regeln; liefert Fehlermeldungen (leer = gültig)."""
        fehler: list[str] = []
        extra = self.model_extra or {}
        if brief_feld not in extra or extra[brief_feld] in (None, "", []):
            fehler.append(
                f"Pflichtfeld '{brief_feld}' (brief_feld aus project.yaml) fehlt im Brief"
            )
        if self.kapitel_typ not in kapitel_typen:
            fehler.append(
                f"kapitel_typ '{self.kapitel_typ}' ist nicht erlaubt (erlaubt: {kapitel_typen})"
            )
        return fehler


class Entscheidung(_Base):
    entscheidung: Literal["lektorat", "blockiert"]
    anweisungen: str = ""


class Freigabe(_Base):
    freigegeben: bool
    anmerkungen: str = ""


class BibleAenderung(_Base):
    abschnitt: str
    vorschlag: str
    begruendung: str = ""


class Auftrag(_Base):
    kapitel_nr: KapitelNr
    auftrag: str


class Ueberarbeitungsauftrag(_Base):
    auftraege: list[Auftrag]


class _ShowrunnerBase(_Base):
    kapitel_nr: KapitelNr
    begruendung: str = ""


class ShowrunnerBrief(_ShowrunnerBase):
    typ: Literal["kapitel_brief"]
    inhalt: KapitelBrief


class ShowrunnerEntscheidung(_ShowrunnerBase):
    typ: Literal["entscheidung"]
    inhalt: Entscheidung


class ShowrunnerFreigabe(_ShowrunnerBase):
    typ: Literal["freigabe"]
    inhalt: Freigabe


class ShowrunnerBibleAenderung(_ShowrunnerBase):
    typ: Literal["bible_aenderung"]
    inhalt: BibleAenderung


class ShowrunnerUeberarbeitung(_ShowrunnerBase):
    typ: Literal["ueberarbeitungsauftrag"]
    inhalt: Ueberarbeitungsauftrag


ShowrunnerOutput = Annotated[
    ShowrunnerBrief
    | ShowrunnerEntscheidung
    | ShowrunnerFreigabe
    | ShowrunnerBibleAenderung
    | ShowrunnerUeberarbeitung,
    Field(discriminator="typ"),
]
SHOWRUNNER_ADAPTER: TypeAdapter[ShowrunnerOutput] = TypeAdapter(ShowrunnerOutput)


# --------------------------------------------------------------------- Recherche


class Fakt(_Base):
    aussage: str
    status: Literal["REAL", "PLAUSIBEL", "FIKTIV", "UNGEPRUEFT"]
    quelle: str = ""
    nutzung: str = ""


class Faktenblatt(_Base):
    kapitel_nr: KapitelNr
    fakten: list[Fakt] = []
    sinnesdetails: dict[str, list[str]] = {}
    konflikte: list[str] = []
    warnungen: list[str] = []


# --------------------------------------------------------------------- Plot


class Szene(_Base):
    nr: int
    ort_zeit: str
    figuren: list[str] = []
    ziel: str
    hindernis: str
    wendung: str
    veraenderung: str
    fakten_ids: list[int] = []
    woerter: int = Field(gt=0)


class Szenenplan(_Base):
    kapitel_nr: KapitelNr
    pov: str
    einstieg: str
    szenen: list[Szene] = Field(min_length=1)
    schlussbild: str
    figurenwissen_ende: dict[str, str] = {}
    risiken: list[str] = []


# --------------------------------------------------------------------- Autor / Lektor


class Autorennotiz(_Base):
    woerter_gemeldet: int | None = None
    woerter_gezaehlt: int
    abweichungen_vom_plan: list[str] = []
    neue_details: list[str] = []
    annahmen: list[str] = []


class Kapitelentwurf(_Base):
    text: str
    notiz: Autorennotiz


class Lektoratsnotiz(_Base):
    woerter_vorher_gemeldet: int | None = None
    woerter_nachher_gemeldet: int | None = None
    woerter_nachher_gezaehlt: int
    wichtigste_aenderungen: list[str] = []


class Endfassung(_Base):
    text: str
    notiz: Lektoratsnotiz


# --------------------------------------------------------------------- Prüfer


class KontinuitaetsFund(_Base):
    schwere: Literal["KRITISCH", "MITTEL", "GERING"]
    kategorie: str = ""
    zitat: str = ""
    problem: str
    korrektur: str = ""


class ProtokollEintrag(_Base):
    fakt: str
    wert: Text
    erstmals_in: Text = ""


class KontinuitaetsPruefung(_Base):
    kapitel_nr: KapitelNr
    bestanden: bool
    funde: list[KontinuitaetsFund] = []
    protokoll_neu: list[ProtokollEintrag] = []
    zusammenfassung: str = ""

    @property
    def bestanden_effektiv(self) -> bool:
        """Besteht nur ohne KRITISCHE und MITTLERE Funde – unabhängig vom gemeldeten Flag."""
        return self.bestanden and not any(f.schwere in ("KRITISCH", "MITTEL") for f in self.funde)


class LeitplankenFund(_Base):
    regel: str = ""
    zitat: str = ""
    problem: str
    alternative: str = ""


class LeitplankenPruefung(_Base):
    kapitel_nr: KapitelNr
    ergebnis: Literal["FREIGABE", "UEBERARBEITUNG", "ABLEHNUNG"]
    funde: list[LeitplankenFund] = []


# --------------------------------------------------------------------- Gesamtleser


class AktProblem(_Base):
    prioritaet: int
    kapitel: list[str] = []
    problem: str
    vorschlag: str

    @field_validator("kapitel", mode="before")
    @classmethod
    def _kap(cls, v: Any) -> Any:
        return [str(x) for x in v] if isinstance(v, list) else v


class Aktbericht(_Base):
    akt: Literal["I", "II", "III"]
    gesamturteil: str
    staerken: list[str] = []
    probleme: list[AktProblem] = Field(default=[], max_length=10)


ALL_SCHEMAS: dict[str, type[BaseModel] | TypeAdapter[Any]] = {
    "ShowrunnerOutput": SHOWRUNNER_ADAPTER,
    "KapitelBrief": KapitelBrief,
    "Faktenblatt": Faktenblatt,
    "Szenenplan": Szenenplan,
    "Autorennotiz": Autorennotiz,
    "KontinuitaetsPruefung": KontinuitaetsPruefung,
    "LeitplankenPruefung": LeitplankenPruefung,
    "Lektoratsnotiz": Lektoratsnotiz,
    "Aktbericht": Aktbericht,
}


def export_json_schemas() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, sch in ALL_SCHEMAS.items():
        out[name] = sch.json_schema() if isinstance(sch, TypeAdapter) else sch.model_json_schema()
    return out


def dump(obj: BaseModel | dict[str, Any] | list[Any]) -> str:
    data = obj.model_dump(mode="json") if isinstance(obj, BaseModel) else obj
    return json.dumps(data, ensure_ascii=False, indent=2)
