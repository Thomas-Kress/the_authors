"""Gemeinsame Bausteine der Agentenmodule.

Jedes Agentenmodul exportiert genau zwei reine Funktionen:
`build_messages(state, ctx) -> list[BaseMessage]` und `parse(raw) -> <Schema>`.
Der Modellaufruf liegt in `llm.py`, die Verdrahtung im Graphen.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from roman_agenten.config import Role
from roman_agenten.context.assembler import RollenKontext, assemble
from roman_agenten.prompts import PromptLoader
from roman_agenten.state import NovelState
from roman_agenten.store.bible_loader import Bible
from roman_agenten.store.project import ProjectConfig


@dataclass(frozen=True)
class AgentContext:
    project: ProjectConfig
    bible: Bible
    prompts: PromptLoader
    kapitel_nr: str
    modus: str | None = None
    max_rounds: int = 3

    def mit(self, **kw: object) -> AgentContext:
        return replace(self, **kw)  # type: ignore[arg-type]


def user_message(rk: RollenKontext, auftrag: str | None) -> str:
    teile = [f"<{tag}>\n{inhalt}\n</{tag}>" for tag, inhalt in rk.bloecke]
    if auftrag:
        teile.append(auftrag)
    return "\n\n".join(teile)


def messages_for(
    role: Role, state: NovelState, ctx: AgentContext, auftrag: str | None = None
) -> list[BaseMessage]:
    """System (statisch, cachebar) → User (getaggte Eingaben + Auftrag)."""
    rk = assemble(role, state, ctx.kapitel_nr, ctx.bible, ctx.project, ctx.modus)
    system = ctx.prompts.system_prompt(role, rk.basis, rk.kapitel_typ)
    return [SystemMessage(content=system), HumanMessage(content=user_message(rk, auftrag))]
