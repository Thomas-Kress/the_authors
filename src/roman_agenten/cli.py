"""CLI `roman` (§11.1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from roman_agenten.agents import AGENTS
from roman_agenten.agents.base import AgentContext
from roman_agenten.config import ConfigError, Role, Settings, all_models, load_settings
from roman_agenten.context.assembler import reihenfolge
from roman_agenten.graph.novel_graph import (
    Outcome,
    Pipeline,
    PipelineBusy,
    open_checkpointer,
    open_runtime,
)
from roman_agenten.llm import BudgetExceeded, LLMUnavailable, ollama_installed, resolve_ollama_model
from roman_agenten.observability import setup_logging
from roman_agenten.prompts import PromptError, PromptLoader
from roman_agenten.schemas import export_json_schemas
from roman_agenten.state import NovelState
from roman_agenten.store.bible_loader import KAPITELTABELLE_SPALTEN, BibleError, load_bible
from roman_agenten.store.bible_validator import (
    HAUPTABSCHNITTE,
    PFLICHT_UNTERABSCHNITTE,
    validate_bible,
)
from roman_agenten.store.export import ExportError, export
from roman_agenten.store.project import ProjectError, load_project

app = typer.Typer(
    help="Roman-Agenten: acht KI-Agenten schreiben Romane nach einer Story Bible.",
    no_args_is_help=True,
)
bible_app = typer.Typer(help="Story Bible prüfen", no_args_is_help=True)
app.add_typer(bible_app, name="bible")


def _settings() -> Settings:
    s = load_settings()
    setup_logging(s)
    return s


def _fail(msg: str, code: int = 1) -> None:
    typer.secho(msg, fg=typer.colors.RED, err=True)
    raise typer.Exit(code)


def _pipeline(s: Settings, projekt_id: str) -> Pipeline:
    try:
        rt = open_runtime(s, projekt_id)
    except ProjectError as e:
        _fail("Projekt ungültig:\n" + "\n".join(f"  - {f}" for f in e.fehler))
    except (BibleError, ConfigError, PromptError) as e:
        _fail(str(e))
    return Pipeline(rt, open_checkpointer(s, rt))


def _report(out: Outcome, nr: str | None = None) -> None:
    kap = out.state.get("kapitel", {})
    if nr and nr in kap:
        ch = kap[nr]
        typer.echo(f"Kapitel {nr}: Status {ch.get('status')}, Runde {ch.get('runde', 0)}")
        if ch.get("blockiert_grund"):
            typer.echo(f"  Grund: {ch['blockiert_grund']}")
    for itr in out.interrupts:
        typer.secho(
            f"Kontrollpunkt offen: {itr.get('art')} {itr.get('kapitel') or itr.get('akt') or ''}",
            fg=typer.colors.YELLOW,
        )
        if itr.get("grund"):
            typer.echo(f"  Grund: {itr['grund']}")
        typer.echo('  → roman approve <id> [--ablehnen --kommentar "…"]')
    if out.offen and not out.interrupts:
        typer.secho(
            f"Lauf pausiert vor: {', '.join(out.offen)} → roman resume <id>", fg=typer.colors.YELLOW
        )
    typer.echo(f"Kosten bisher: {out.state.get('kosten', {}).get('usd', 0.0):.4f} USD")


def _run_guarded(fn: Any, *args: Any) -> Outcome:
    try:
        return fn(*args)  # type: ignore[no-any-return]
    except (BudgetExceeded, LLMUnavailable) as e:
        _fail(f"Pausiert: {e}\nFortsetzen mit `roman resume <id>`.", 2)
    except PipelineBusy as e:
        _fail(str(e), 3)
    except ValueError as e:
        _fail(str(e))
    raise AssertionError("unreachable")


# ------------------------------------------------------------------ check


@app.command()
def check() -> None:
    """Konfiguration prüfen: Modelle pro Rolle, Keys (nur gesetzt/fehlt), Ollama."""
    s = _settings()
    try:
        models = all_models(s)
    except ConfigError as e:
        _fail(str(e))
    ok = True
    typer.echo(f"{'Rolle':<16}{'Modell':<40}{'Temp.':>6}{'Max-Tokens':>12}")
    providers = {m.provider for m in models.values()}
    installed = ollama_installed(s.ollama_base_url) if "ollama" in providers else None
    for role, m in models.items():
        model = resolve_ollama_model(m.model, s, installed) if m.provider == "ollama" else m.model
        typer.echo(
            f"{role.value:<16}{m.provider + ':' + model:<40}{m.temperature:>6.2f}{m.max_tokens:>12}"
        )
    typer.echo("")
    for p in sorted(providers):
        if p == "ollama":
            if installed is None:
                ok = False
                typer.secho(f"ollama: {s.ollama_base_url} nicht erreichbar", fg=typer.colors.RED)
                continue
            typer.echo(
                f"ollama: erreichbar ({s.ollama_base_url}), num_ctx={s.ollama_num_ctx}, think={s.ollama_think}"
            )
            for name in {
                resolve_ollama_model(x.model, s, installed)
                for x in models.values()
                if x.provider == "ollama"
            }:
                da = name in installed
                ok &= da
                typer.secho(
                    f"  Modell {name}: {'installiert' if da else 'fehlt (ollama pull ' + name + ')'}",
                    fg=None if da else typer.colors.RED,
                )
        else:
            status = s.key_status(p)
            ok &= status == "gesetzt"
            typer.echo(f"{p.upper()}_API_KEY: {status}")
    if not ok:
        raise typer.Exit(1)
    typer.secho("Konfiguration in Ordnung.", fg=typer.colors.GREEN)


# ------------------------------------------------------------------ init / bible


TITEL = {
    "0": "Zweck",
    "1": "Prämisse",
    "2": "Welt",
    "3": "Schauplätze und Zeit",
    "4": "Projektspezifisches System",
    "5": "Figuren",
    "6": "Kapitelplan",
    "7": "Stil",
    "8": "Wissenschaftliche Plausibilität",
    "9": "Inhaltliche Leitplanken",
    "10": "Workflow",
}


def bible_geruest() -> str:
    zeilen = [
        "# Story Bible",
        "",
        "<!-- Gerüst nach docs/story-bible-vorlage.md – Titel und Inhalte dort -->",
        "",
    ]
    for nr in HAUPTABSCHNITTE:
        zeilen += [f"## {nr}. {TITEL[nr]}", ""]
        for sub in [x for x in PFLICHT_UNTERABSCHNITTE if x.split(".")[0] == nr]:
            zeilen += [f"### {sub} …", ""]
            if sub in ("6.1", "6.2", "6.3"):
                zeilen += [
                    "| " + " | ".join(KAPITELTABELLE_SPALTEN) + " |",
                    "|" + "---|" * len(KAPITELTABELLE_SPALTEN),
                    "",
                ]
    return "\n".join(zeilen)


@app.command()
def init(projekt_id: str) -> None:
    """Projekt-Gerüst in PROJECTS_DIR anlegen (leere Bible mit allen Pflicht-Überschriften)."""
    s = _settings()
    pdir = s.projects_dir / projekt_id
    if pdir.exists():
        _fail(f"{pdir} existiert bereits")
    for d in (
        "bible",
        "prompts",
        "state",
        "output/kapitel",
        "output/berichte",
        "output/manuskript",
    ):
        (pdir / d).mkdir(parents=True)
    (pdir / "bible" / "bible.md").write_text(bible_geruest(), encoding="utf-8")
    (pdir / "project.yaml").write_text(
        f"id: {projekt_id}\ntitel: {projekt_id.upper()}\nsprache: de\nzielumfang_woerter: 0\nbible_version: 1\n"
        "stichtag_realitaet: 2000-01-01\nbrief_feld: <feldname>\nkapitel_typen: [prosa]\n"
        "kontrollpunkte:\n  - nach_kapitel: 1\n  - nach_jedem_akt: true\n",
        encoding="utf-8",
    )
    typer.echo(
        f"Projekt angelegt: {pdir}\nNächster Schritt: Bible und project.yaml füllen, dann "
        f"`roman bible check {projekt_id}`."
    )


@bible_app.command("check")
def bible_check(projekt_id: str) -> None:
    """Bible gegen die Vorlage validieren (alle Verstöße werden gelistet)."""
    s = _settings()
    try:
        project = load_project(s.projects_dir, projekt_id)
        bible = load_bible(project.bible_dir)
    except ProjectError as e:
        _fail("\n".join(e.fehler))
    except BibleError as e:
        _fail(str(e))
    fehler = validate_bible(bible, project.config)
    fehler += [
        f"kapitel_typ '{t}' ohne Prompt-Zusatz"
        for t in PromptLoader(s.prompts_dir, project.dir).missing_zusaetze(
            project.config.kapitel_typen
        )
    ]
    if fehler:
        _fail(f"{len(fehler)} Verstoß/Verstöße:\n" + "\n".join(f"  - {f}" for f in fehler))
    typer.secho(
        f"Bible gültig: {len(bible.kapiteltabelle())} Kapitel in der Kapiteltabelle.",
        fg=typer.colors.GREEN,
    )


# ------------------------------------------------------------------ run / resume / approve


@app.command()
def run(
    projekt_id: str,
    kapitel: Annotated[
        str | None, typer.Option("--kapitel", help="Ein Kapitel, z. B. 1, P, E, SP1")
    ] = None,
    akt: Annotated[
        str | None, typer.Option("--akt", help="Einen Akt: I, II, III (oder 1–3)")
    ] = None,
) -> None:
    """Pipeline ausführen (ein Kapitel, ein Akt oder alles)."""
    if kapitel and akt:
        _fail("--kapitel und --akt schließen sich aus")
    s = _settings()
    p = _pipeline(s, projekt_id)
    if kapitel:
        _report(_run_guarded(p.run_kapitel, kapitel), kapitel)
    elif akt:
        _report(_run_guarded(p.run_akt, {"1": "I", "2": "II", "3": "III"}.get(akt, akt)))
    else:
        _report(_run_guarded(p.run_alle))


@app.command()
def resume(projekt_id: str) -> None:
    """Nach Pause (Budget, API-Fehler) oder Absturz fortsetzen."""
    p = _pipeline(_settings(), projekt_id)
    out = _run_guarded(p.resume)
    _report(out, out.state.get("aktuelles_kapitel"))


@app.command()
def approve(
    projekt_id: str,
    ablehnen: Annotated[bool, typer.Option("--ablehnen")] = False,
    kommentar: Annotated[str, typer.Option("--kommentar")] = "",
) -> None:
    """Offenen Kontrollpunkt beantworten."""
    p = _pipeline(_settings(), projekt_id)
    out = _run_guarded(p.approve, not ablehnen, kommentar)
    _report(out, out.state.get("aktuelles_kapitel"))


# ------------------------------------------------------------------ status / cost / export


@app.command()
def status(projekt_id: str) -> None:
    """Kapitelstatus, offene Kontrollpunkte, Kosten."""
    p = _pipeline(_settings(), projekt_id)
    st = p.state()
    kap = st.get("kapitel", {})
    typer.echo(f"{'Nr':<5}{'Akt':<5}{'Status':<13}{'Runde':>6}{'Wörter':>8}{'Ziel':>7}  Titel")
    for z in p.rt.bible.kapiteltabelle():
        ch = kap.get(z.nr, {})
        w = (
            (ch.get("lektoratsnotiz") or {}).get("woerter_nachher_gezaehlt")
            or (ch.get("autorennotiz") or {}).get("woerter_gezaehlt")
            or ""
        )
        typer.echo(
            f"{z.nr:<5}{z.akt:<5}{ch.get('status', 'offen'):<13}{ch.get('runde', 0):>6}{w!s:>8}"
            f"{z.woerter or '':>7}  {z.titel}"
        )
    _report(Outcome(p.interrupts(), st, tuple(p.snapshot().next or ())))


@app.command()
def cost(projekt_id: str) -> None:
    """Kosten und Tokens pro Rolle aus state/usage.jsonl."""
    s = _settings()
    try:
        project = load_project(s.projects_dir, projekt_id)
    except ProjectError as e:
        _fail("\n".join(e.fehler))
    f = project.state_dir / "usage.jsonl"
    rollen: dict[str, dict[str, float]] = {}
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            agg = rollen.setdefault(
                r.get("rolle", "?"), {"aufrufe": 0, "input": 0, "output": 0, "usd": 0.0}
            )
            agg["aufrufe"] += 1
            agg["input"] += r.get("input_tokens", 0)
            agg["output"] += r.get("output_tokens", 0)
            agg["usd"] += r.get("kosten_usd", 0.0)
    typer.echo(f"{'Rolle':<16}{'Aufrufe':>8}{'Input':>10}{'Output':>10}{'USD':>10}")
    for rolle, a in sorted(rollen.items()):
        typer.echo(
            f"{rolle:<16}{int(a['aufrufe']):>8}{int(a['input']):>10}{int(a['output']):>10}{a['usd']:>10.4f}"
        )
    typer.echo(f"{'Summe':<16}{'':>28}{sum(a['usd'] for a in rollen.values()):>10.4f}")


@app.command("export")
def export_cmd(projekt_id: str, format: Annotated[str, typer.Option("--format")] = "md") -> None:
    """Freigegebene Kapitel als Manuskript exportieren."""
    p = _pipeline(_settings(), projekt_id)
    try:
        path = export(p.rt.project, p.rt.bible, p.state(), format)
    except ExportError as e:
        _fail(str(e))
    typer.echo(f"Exportiert: {path}")


# ------------------------------------------------------------------ prompt / schemas


@app.command()
def prompt(
    rolle: Role,
    projekt: Annotated[str, typer.Option("--projekt")],
    kapitel: Annotated[str, typer.Option("--kapitel")],
    modus: Annotated[
        str | None, typer.Option("--modus", help="z. B. entscheidung, freigabe, abschluss")
    ] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = True,
) -> None:
    """Vollständig zusammengesetzten Prompt anzeigen (ohne Modellaufruf)."""
    if not dry_run:
        _fail("Nur --dry-run wird unterstützt")
    p = _pipeline(_settings(), projekt)
    st: NovelState = p.state()
    if kapitel not in reihenfolge(p.rt.bible, st):
        _fail(f"Kapitel '{kapitel}' unbekannt")
    st = NovelState(**{**st, "aktuelles_kapitel": kapitel})
    ctx: AgentContext = p.rt.ctx(kapitel, modus)
    msgs = AGENTS[rolle].build_messages(st, ctx)
    gesamt = 0
    for m in msgs:
        text = (
            m.content if isinstance(m.content, str) else json.dumps(m.content, ensure_ascii=False)
        )
        gesamt += len(text)
        typer.secho(f"===== {m.type.upper()} =====", fg=typer.colors.CYAN)
        typer.echo(text)
    typer.secho(f"\n≈ {gesamt // 4} Tokens (Schätzung: Zeichen/4)", fg=typer.colors.CYAN)


@app.command()
def schemas(
    export_: Annotated[bool, typer.Option("--export")] = False,
    out: Annotated[Path, typer.Option("--out")] = Path("schemas_export"),
) -> None:
    """JSON-Schemas aller Agentenausgaben exportieren."""
    data = export_json_schemas()
    if not export_:
        typer.echo("\n".join(data))
        return
    out.mkdir(parents=True, exist_ok=True)
    for name, sch in data.items():
        (out / f"{name}.json").write_text(
            json.dumps(sch, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    typer.echo(f"{len(data)} Schemas nach {out}/ exportiert")


if __name__ == "__main__":
    app()
