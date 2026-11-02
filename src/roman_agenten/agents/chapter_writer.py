"""Kapitel-Autor: Prosa in Markdown + Block `---AUTORENNOTIZ---`."""

from __future__ import annotations

from langchain_core.messages import BaseMessage

from roman_agenten.agents.base import AgentContext, messages_for
from roman_agenten.agents.parsing import as_int, as_list, count_words, parse_kv_block, split_marker
from roman_agenten.config import Role
from roman_agenten.schemas import Autorennotiz, Kapitelentwurf
from roman_agenten.state import NovelState, chapter

ROLE = Role.CHAPTER_WRITER
JSON_MODE = False
MARKER = "---AUTORENNOTIZ---"
KEYS = ["woerter", "abweichungen_vom_plan", "neue_details", "annahmen"]


def build_messages(state: NovelState, ctx: AgentContext) -> list[BaseMessage]:
    ch = chapter(state, ctx.kapitel_nr)
    grund = ch.get("ueberarbeitungsgrund") or ""
    ziel = ch.get("brief", {}).get("zielumfang_woerter", "?")
    runde = ch.get("runde", 0) + 1
    if grund == "pruefung":
        auftrag = ctx.prompts.auftrag(
            "chapter_writer_ueberarbeitung", {"runde": runde, "zielumfang": ziel}
        )
    elif grund == "unterlaenge":
        woerter = ch.get("lektoratsnotiz", {}).get("woerter_nachher_gezaehlt", "?")
        auftrag = ctx.prompts.auftrag(
            "chapter_writer_unterlaenge", {"runde": runde, "zielumfang": ziel, "woerter": woerter}
        )
    else:
        auftrag = ctx.prompts.auftrag(
            "chapter_writer_entwurf", {"kapitel_nr": ctx.kapitel_nr, "zielumfang": ziel}
        )
    return messages_for(ROLE, state, ctx, auftrag)


def parse(raw: str) -> Kapitelentwurf:
    text, block = split_marker(raw, MARKER)
    kv = parse_kv_block(block, KEYS)
    notiz = Autorennotiz(
        woerter_gemeldet=as_int(kv.get("woerter")),
        woerter_gezaehlt=count_words(text),
        abweichungen_vom_plan=as_list(kv.get("abweichungen_vom_plan")),
        neue_details=as_list(kv.get("neue_details")),
        annahmen=as_list(kv.get("annahmen")),
    )
    return Kapitelentwurf(text=text, notiz=notiz)
