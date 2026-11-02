"""Lektorats-Agent: Endfassung in Markdown + Block `---LEKTORATSNOTIZ---`."""

from __future__ import annotations

from langchain_core.messages import BaseMessage

from roman_agenten.agents.base import AgentContext, messages_for
from roman_agenten.agents.parsing import as_int, as_list, count_words, parse_kv_block, split_marker
from roman_agenten.config import Role
from roman_agenten.schemas import Endfassung, Lektoratsnotiz
from roman_agenten.state import NovelState

ROLE = Role.LINE_EDITOR
JSON_MODE = False
MARKER = "---LEKTORATSNOTIZ---"
KEYS = ["woerter_vorher", "woerter_nachher", "wichtigste_aenderungen"]


def build_messages(state: NovelState, ctx: AgentContext) -> list[BaseMessage]:
    return messages_for(ROLE, state, ctx)


def parse(raw: str) -> Endfassung:
    text, block = split_marker(raw, MARKER)
    kv = parse_kv_block(block, KEYS)
    notiz = Lektoratsnotiz(
        woerter_vorher_gemeldet=as_int(kv.get("woerter_vorher")),
        woerter_nachher_gemeldet=as_int(kv.get("woerter_nachher")),
        woerter_nachher_gezaehlt=count_words(text),
        wichtigste_aenderungen=as_list(kv.get("wichtigste_aenderungen"))[:5],
    )
    return Endfassung(text=text, notiz=notiz)
