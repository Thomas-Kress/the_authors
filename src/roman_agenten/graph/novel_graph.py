"""Gesamtgraph und Pipeline-Treiber.

Ein Graph pro Projekt, ein Checkpointer-Thread pro Projekt (`thread_id = projekt_id`), damit
Protokoll, Zusammenfassungen und Figurenwissen über Kapitel hinweg erhalten bleiben.
`lauf.art` wählt den Einstieg: Kapitelgraph oder Akt-Abschluss.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import START, StateGraph
from langgraph.types import Command

from roman_agenten.config import ConfigError, Settings
from roman_agenten.context.assembler import kapitel_der_akte
from roman_agenten.graph.act_graph import add_act_nodes
from roman_agenten.graph.chapter_graph import add_chapter_nodes
from roman_agenten.graph.runtime import Runtime
from roman_agenten.llm import LLMClient, ModelGateway, Preise
from roman_agenten.observability import RunLog
from roman_agenten.prompts import PromptLoader
from roman_agenten.state import NovelState
from roman_agenten.store.bible_loader import load_bible
from roman_agenten.store.bible_validator import validate_bible
from roman_agenten.store.output_writer import OutputWriter
from roman_agenten.store.project import ProjectError, load_project


class PipelineBusy(RuntimeError):
    """Es gibt einen offenen Lauf oder Kontrollpunkt."""


def build_graph(rt: Runtime) -> StateGraph:  # type: ignore[type-arg]
    g: StateGraph = StateGraph(NovelState)  # type: ignore[type-arg]
    add_chapter_nodes(g, rt)
    add_act_nodes(g, rt)

    def einstieg(state: NovelState) -> str:
        return "full_read" if (state.get("lauf") or {}).get("art") == "akt" else "showrunner_brief"

    g.add_conditional_edges(START, einstieg, ["showrunner_brief", "full_read"])
    return g


def open_checkpointer(settings: Settings, rt: Runtime) -> BaseCheckpointSaver:  # type: ignore[type-arg]
    if settings.checkpointer == "postgres":
        if settings.postgres_url is None:
            raise ConfigError("CHECKPOINTER=postgres verlangt POSTGRES_URL")
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
        except ImportError as e:
            raise ConfigError("Postgres-Checkpointer: `uv sync --extra postgres` ausführen") from e
        saver = PostgresSaver.from_conn_string(settings.postgres_url.get_secret_value()).__enter__()
        saver.setup()
        return saver  # type: ignore[no-any-return]
    from langgraph.checkpoint.sqlite import SqliteSaver

    rt.project.state_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(rt.project.state_dir / "checkpoints.sqlite", check_same_thread=False)
    return SqliteSaver(conn)


def open_runtime(
    settings: Settings, projekt_id: str, llm: LLMClient | None = None, trace_id: str | None = None
) -> Runtime:
    """Lädt Projekt + Bible und prüft alles, was vor `roman run` gültig sein muss."""
    project = load_project(settings.projects_dir, projekt_id)
    bible = load_bible(project.bible_dir)
    fehler = validate_bible(bible, project.config)
    prompts = PromptLoader(settings.prompts_dir, project.dir)
    fehlend = prompts.missing_zusaetze(project.config.kapitel_typen)
    fehler += [f"kapitel_typ '{t}' hat keinen Prompt-Zusatz zusaetze/{t}.md" for t in fehlend]
    if fehler:
        raise ProjectError(fehler)
    project.ensure_dirs()
    runlog = RunLog(project.state_dir, settings, trace_id)
    client = llm or ModelGateway(settings, runlog, Preise.load(settings.preise_file))
    return Runtime(settings, project, bible, prompts, client, runlog, OutputWriter(project))


@dataclass
class Outcome:
    interrupts: list[dict[str, Any]] = field(default_factory=list)
    state: NovelState = field(default_factory=lambda: NovelState())
    offen: tuple[str, ...] = ()

    @property
    def pausiert(self) -> bool:
        return bool(self.interrupts or self.offen)


class Pipeline:
    def __init__(self, rt: Runtime, checkpointer: BaseCheckpointSaver) -> None:  # type: ignore[type-arg]
        self.rt = rt
        self.graph = build_graph(rt).compile(checkpointer=checkpointer)
        self.config: RunnableConfig = {
            "configurable": {"thread_id": rt.project.id},
            "recursion_limit": 200,
        }

    # ------------------------------------------------------------ Zustand
    def snapshot(self) -> Any:
        return self.graph.get_state(self.config)

    def state(self) -> NovelState:
        return NovelState(**(self.snapshot().values or {}))  # type: ignore[typeddict-item]

    def interrupts(self) -> list[dict[str, Any]]:
        snap = self.snapshot()
        out: list[dict[str, Any]] = []
        for task in snap.tasks or ():
            for itr in getattr(task, "interrupts", ()) or ():
                out.append(dict(itr.value) if isinstance(itr.value, dict) else {"wert": itr.value})
        return out

    def _outcome(self) -> Outcome:
        snap = self.snapshot()
        return Outcome(self.interrupts(), self.state(), tuple(snap.next or ()))

    def _invoke(self, inp: Any) -> Outcome:
        self.rt.runlog.event("lauf_start", projekt=self.rt.project.id)
        self.graph.invoke(inp, self.config, durability="sync")
        out = self._outcome()
        self.rt.runlog.event(
            "lauf_ende",
            projekt=self.rt.project.id,
            pausiert=out.pausiert,
            kosten_usd=out.state.get("kosten", {}).get("usd", 0.0),
        )
        return out

    def _ensure_idle(self) -> None:
        if self.snapshot().next:
            raise PipelineBusy(
                "Es gibt einen offenen Lauf oder Kontrollpunkt – erst `roman status`, "
                "dann `roman approve` bzw. `roman resume`."
            )

    # ------------------------------------------------------------ Befehle
    def run_kapitel(self, nr: str) -> Outcome:
        self._ensure_idle()
        if self.rt.bible.kapitel(nr) is None:
            raise ValueError(f"Kapitel '{nr}' steht nicht in der Kapiteltabelle (Bible 6.1–6.3)")
        cfg = self.rt.project.config
        return self._invoke(
            {
                "projekt_id": cfg.id,
                "bible_version": cfg.bible_version,
                "aktuelles_kapitel": nr,
                "lauf": {"art": "kapitel"},
            }
        )

    def run_akt(self, akt: str) -> Outcome:
        kapitel = kapitel_der_akte(self.rt.bible, akt)
        if not kapitel:
            raise ValueError(f"Akt '{akt}' hat keine Kapitel")
        out = self._outcome()
        for nr in kapitel:
            if out.state.get("kapitel", {}).get(nr, {}).get("status") == "freigegeben":
                continue
            out = self.run_kapitel(nr)
            if (
                out.pausiert
                or out.state.get("kapitel", {}).get(nr, {}).get("status") != "freigegeben"
            ):
                return out
        self._ensure_idle()
        cfg = self.rt.project.config
        return self._invoke(
            {
                "projekt_id": cfg.id,
                "bible_version": cfg.bible_version,
                "aktuelles_kapitel": kapitel[-1],
                "lauf": {"art": "akt", "akt": akt},
            }
        )

    def run_alle(self) -> Outcome:
        out = self._outcome()
        for akt in ("I", "II", "III"):
            if kapitel_der_akte(self.rt.bible, akt):
                out = self.run_akt(akt)
                if out.pausiert:
                    return out
        return out

    def resume(self) -> Outcome:
        if self.interrupts():
            raise PipelineBusy("Offener Kontrollpunkt – mit `roman approve` beantworten.")
        if not self.snapshot().next:
            return self._outcome()
        return self._invoke(None)

    def approve(self, genehmigt: bool = True, kommentar: str = "") -> Outcome:
        if not self.interrupts():
            raise PipelineBusy("Kein offener Kontrollpunkt.")
        return self._invoke(Command(resume={"genehmigt": genehmigt, "kommentar": kommentar}))
