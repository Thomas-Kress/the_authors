"""Kontinuitäts-Agent: Modus `pruefung` (Fehlerliste) und `abschluss` (Zusammenfassung + Protokoll)."""

from __future__ import annotations

from langchain_core.messages import BaseMessage

from roman_agenten.agents.base import AgentContext, messages_for
from roman_agenten.agents.parsing import count_words, parse_json_as
from roman_agenten.config import Role
from roman_agenten.schemas import KontinuitaetsPruefung
from roman_agenten.state import NovelState

ROLE = Role.CONTINUITY
JSON_MODE = True
MODI = ("pruefung", "abschluss")
MAX_ZUSAMMENFASSUNG_WOERTER = 150


def build_messages(state: NovelState, ctx: AgentContext) -> list[BaseMessage]:
    modus = ctx.modus or "pruefung"
    if modus not in MODI:
        raise ValueError(f"Unbekannter Kontinuitäts-Modus '{modus}'")
    return messages_for(
        ROLE, state, ctx.mit(modus=modus), ctx.prompts.auftrag(f"continuity_{modus}", {})
    )


def parse(raw: str) -> KontinuitaetsPruefung:
    return parse_json_as(KontinuitaetsPruefung, raw)


def kuerze_zusammenfassung(text: str, limit: int = MAX_ZUSAMMENFASSUNG_WOERTER) -> str:
    if count_words(text) <= limit:
        return text
    return " ".join(text.split()[:limit]) + " …"
