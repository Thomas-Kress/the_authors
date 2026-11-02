"""Showrunner: Kapitel-Brief, Entscheidung, Freigabe, Bible-Änderung, Überarbeitungsauftrag."""

from __future__ import annotations

from langchain_core.messages import BaseMessage

from roman_agenten.agents.base import AgentContext, messages_for
from roman_agenten.agents.parsing import OutputFormatError, parse_json_adapter
from roman_agenten.config import Role
from roman_agenten.schemas import SHOWRUNNER_ADAPTER, ShowrunnerBrief, ShowrunnerOutput
from roman_agenten.state import NovelState, chapter

ROLE = Role.SHOWRUNNER
JSON_MODE = True
MODI = ("kapitel_brief", "entscheidung", "freigabe", "ueberarbeitungsauftrag")
# Beim Brief darf der Showrunner stattdessen eine Bible-Änderung vorschlagen.
ERLAUBTE_TYPEN = {
    "kapitel_brief": {"kapitel_brief", "bible_aenderung"},
    "entscheidung": {"entscheidung"},
    "freigabe": {"freigabe"},
    "ueberarbeitungsauftrag": {"ueberarbeitungsauftrag"},
}


def build_messages(state: NovelState, ctx: AgentContext) -> list[BaseMessage]:
    modus = ctx.modus or "kapitel_brief"
    if modus not in MODI:
        raise ValueError(f"Unbekannter Showrunner-Modus '{modus}'")
    werte: dict[str, object] = {"kapitel_nr": ctx.kapitel_nr}
    if modus == "kapitel_brief":
        werte |= {
            "kapitel_typen": ", ".join(ctx.project.kapitel_typen),
            "brief_feld": ctx.project.brief_feld,
        }
    elif modus == "entscheidung":
        werte = {"runden": chapter(state, ctx.kapitel_nr).get("runde", 0)}
    return messages_for(
        ROLE, state, ctx.mit(modus=modus), ctx.prompts.auftrag(f"showrunner_{modus}", werte)
    )


def parse(
    raw: str,
    *,
    modus: str | None = None,
    brief_feld: str | None = None,
    kapitel_typen: list[str] | None = None,
) -> ShowrunnerOutput:
    out: ShowrunnerOutput = parse_json_adapter(SHOWRUNNER_ADAPTER, raw)
    if modus and out.typ not in ERLAUBTE_TYPEN[modus]:
        raise OutputFormatError(
            "json",
            f"typ '{out.typ}' ist hier nicht erlaubt; erwartet: {sorted(ERLAUBTE_TYPEN[modus])}",
        )
    if isinstance(out, ShowrunnerBrief) and brief_feld is not None:
        fehler = out.inhalt.pruefe_projekt(brief_feld, kapitel_typen or ["prosa"])
        if fehler:
            raise OutputFormatError(
                "json", "Brief ungültig:\n" + "\n".join(f"- {f}" for f in fehler)
            )
    return out
