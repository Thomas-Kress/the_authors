"""Leitplanken-Agent: FREIGABE / UEBERARBEITUNG / ABLEHNUNG. Sein Veto ist absolut (§2.4)."""

from __future__ import annotations

from langchain_core.messages import BaseMessage

from roman_agenten.agents.base import AgentContext, messages_for
from roman_agenten.agents.parsing import parse_json_as
from roman_agenten.config import Role
from roman_agenten.schemas import LeitplankenPruefung
from roman_agenten.state import NovelState

ROLE = Role.GUARDRAILS
JSON_MODE = True


def build_messages(state: NovelState, ctx: AgentContext) -> list[BaseMessage]:
    return messages_for(ROLE, state, ctx)


def parse(raw: str) -> LeitplankenPruefung:
    return parse_json_as(LeitplankenPruefung, raw)
