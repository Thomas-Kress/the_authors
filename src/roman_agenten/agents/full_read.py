"""Gesamtleser: liest alle Endfassungen eines Akts und liefert den Aktbericht."""

from __future__ import annotations

from langchain_core.messages import BaseMessage

from roman_agenten.agents.base import AgentContext, messages_for
from roman_agenten.agents.parsing import parse_json_as
from roman_agenten.config import Role
from roman_agenten.schemas import Aktbericht
from roman_agenten.state import NovelState

ROLE = Role.FULL_READ
JSON_MODE = True


def build_messages(state: NovelState, ctx: AgentContext) -> list[BaseMessage]:
    """`ctx.modus` ist der Akt (I/II/III)."""
    return messages_for(ROLE, state, ctx)


def parse(raw: str) -> Aktbericht:
    return parse_json_as(Aktbericht, raw)
