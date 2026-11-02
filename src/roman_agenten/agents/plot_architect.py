"""Plot-Architekt: zerlegt das Kapitel in 3–5 Szenen (Ziel – Hindernis – Wendung)."""

from __future__ import annotations

from langchain_core.messages import BaseMessage

from roman_agenten.agents.base import AgentContext, messages_for
from roman_agenten.agents.parsing import parse_json_as
from roman_agenten.config import Role
from roman_agenten.schemas import Szenenplan
from roman_agenten.state import NovelState

ROLE = Role.PLOT_ARCHITECT
JSON_MODE = True


def build_messages(state: NovelState, ctx: AgentContext) -> list[BaseMessage]:
    return messages_for(ROLE, state, ctx)


def parse(raw: str) -> Szenenplan:
    return parse_json_as(Szenenplan, raw)
