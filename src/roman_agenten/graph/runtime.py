"""Laufzeitobjekte, die die Graph-Knoten brauchen, aber nicht im State liegen."""

from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from roman_agenten.agents.base import AgentContext
from roman_agenten.agents.parsing import OutputFormatError
from roman_agenten.config import Role, Settings, get_model
from roman_agenten.llm import LLMClient
from roman_agenten.observability import RunLog, new_id
from roman_agenten.prompts import PromptLoader
from roman_agenten.state import NovelState
from roman_agenten.store.bible_loader import Bible
from roman_agenten.store.output_writer import OutputWriter
from roman_agenten.store.project import Project


class AgentFormatError(RuntimeError):
    """Ausgabe auch nach automatischer Wiederholung ungültig."""

    def __init__(self, role: Role, message: str) -> None:
        super().__init__(f"{role.value}: {message}")
        self.role = role


@dataclass
class Runtime:
    settings: Settings
    project: Project
    bible: Bible
    prompts: PromptLoader
    llm: LLMClient
    runlog: RunLog
    writer: OutputWriter

    def ctx(self, nr: str, modus: str | None = None) -> AgentContext:
        return AgentContext(
            self.project.config,
            self.bible,
            self.prompts,
            nr,
            modus,
            self.settings.max_revision_rounds,
        )

    def web_search_aktiv(self) -> bool:
        return (
            self.settings.agent_research_web_search
            and get_model(Role.RESEARCH, self.settings).provider == "anthropic"
        )

    def call(
        self, agent: ModuleType, state: NovelState, ctx: AgentContext, **parse_kw: Any
    ) -> tuple[Any, dict[str, float]]:
        """Baut Nachrichten, ruft das Modell, parst. Bei Formatfehler genau eine Wiederholung
        mit Fehlerhinweis (§10); danach `AgentFormatError`."""
        role: Role = agent.ROLE
        messages: list[BaseMessage] = agent.build_messages(state, ctx)
        kosten: dict[str, float] = {}
        span = new_id()
        start_event = {
            "span_id": span,
            "rolle": role.value,
            "kapitel": ctx.kapitel_nr,
            "modus": ctx.modus,
        }
        self.runlog.event("knoten_start", **start_event)

        def _invoke(msgs: list[BaseMessage]) -> str:
            res = self.llm.invoke(
                role, msgs, json_mode=agent.JSON_MODE, span_id=span, kapitel_nr=ctx.kapitel_nr
            )
            kosten["usd"] = kosten.get("usd", 0.0) + res.kosten_usd
            for k, v in res.usage.items():
                kosten[k] = kosten.get(k, 0.0) + v
            return res.text

        raw = _invoke(messages)
        try:
            parsed = agent.parse(raw, **parse_kw)
        except OutputFormatError as e:
            self.runlog.event("formatfehler", **start_event, versuch=1, art=e.kind)
            retry = "format_retry_json" if agent.JSON_MODE else "format_retry_text"
            hinweis = self.prompts.auftrag(retry, {"fehler": str(e)})
            raw2 = _invoke([*messages, AIMessage(content=raw), HumanMessage(content=hinweis)])
            try:
                parsed = agent.parse(raw2, **parse_kw)
            except OutputFormatError as e2:
                self.runlog.event("formatfehler", **start_event, versuch=2, art=e2.kind)
                raise AgentFormatError(role, str(e2)) from e2
        self.runlog.event("knoten_ende", **start_event, status="ok")
        return parsed, kosten
