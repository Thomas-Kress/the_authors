"""Recherche-Agent: Faktenblatt (REAL / PLAUSIBEL / FIKTIV / UNGEPRUEFT) + Sinnesdetails."""

from __future__ import annotations

from langchain_core.messages import BaseMessage

from roman_agenten.agents.base import AgentContext, messages_for
from roman_agenten.agents.parsing import parse_json_as
from roman_agenten.config import Role
from roman_agenten.schemas import Faktenblatt
from roman_agenten.state import NovelState

ROLE = Role.RESEARCH
JSON_MODE = True


def build_messages(state: NovelState, ctx: AgentContext) -> list[BaseMessage]:
    return messages_for(ROLE, state, ctx)


def parse(raw: str) -> Faktenblatt:
    return parse_json_as(Faktenblatt, raw)


def ohne_suche(fb: Faktenblatt) -> Faktenblatt:
    """Ohne Suchwerkzeug kann nichts als REAL belegt sein → UNGEPRUEFT."""
    fakten = [
        f.model_copy(update={"status": "UNGEPRUEFT"}) if f.status == "REAL" else f
        for f in fb.fakten
    ]
    return fb.model_copy(update={"fakten": fakten})
