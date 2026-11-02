# Roman-Agenten

Eine Agentic-AI-Anwendung, die mit **acht spezialisierten KI-Agenten** einen Roman auf Basis einer **Story Bible** schreibt – Kapitel für Kapitel, Akt für Akt, mit festen Qualitätsschleifen und menschlichen Kontrollpunkten.

Dieses Repository enthält ausschließlich den **Quellcode** der Anwendung. Story Bibles, Projektdaten, Checkpoints und Romantexte liegen in einem **externen Datenverzeichnis** (`PROJECTS_DIR`) und werden hier weder angelegt noch bearbeitet.

## Die Idee

Ein einzelnes LLM verliert bei Romanlänge den Faden: Namen, Zahlen und Figurenwissen driften, Stil und Spannung ermüden, Sicherheitsgrenzen werden unscharf. Dieses Projekt löst das mit Arbeitsteilung nach Vorbild einer Autorenredaktion:

- **Eine Quelle der Wahrheit:** die Story Bible (Abschnitte 0–10). Jeder Agent bekommt nur die Abschnitte, die er für seine Rolle braucht.
- **Schreiben und Prüfen sind getrennt.** Kein Agent bewertet seine eigene Arbeit.
- **Deterministische Orchestrierung:** Die Schrittfolge ist im LangGraph-Graphen fest codiert. LLM-Ausgaben steuern den Ablauf nur an definierten Gates (Prüfergebnis, Wortzahl).
- **Leitplanken-Veto ist absolut:** Eine `ABLEHNUNG` des Leitplanken-Agenten kann durch keinen Codepfad überstimmt werden – weder durch den Showrunner noch durch Retries oder Flags.
- **Die Bible ist read-only.** Änderungsvorschläge werden abgelegt und warten auf menschliche Freigabe.
- **Prompts sind Daten** (`prompts/`), Modelle sind Konfiguration (`.env`). Der Code ist projektneutral.
- **Crash-sicher:** Nach jedem Knoten wird ein Checkpoint geschrieben; jede Überarbeitung wird als eigene Revision gespeichert.

## Ablauf

```
Showrunner (Brief) → Research → Plot-Architekt → Kapitel-Autor ◄────────┐
   → Kontinuität ∥ Leitplanken (parallel) → Gate                        │
        ABLEHNUNG / Fehler  → zurück zum Autor (max. MAX_REVISION_ROUNDS) ┘
        bestanden           → Lektor → Wortzahl-Gate
   → Kontinuität (Zusammenfassung + Protokoll) → Showrunner (Freigabe)
```

- **Kapitelgraph:** ein Kapitel von Brief bis Freigabe.
- **Aktgraph:** Kapitel nacheinander, danach Gesamtleser → Aktbericht → Kontrollpunkt → Überarbeitungsaufträge.
- **Romangraph:** alle Akte nacheinander, danach Export.
- Ist nach der maximalen Rundenzahl keine Einigung erreicht, entscheidet der Showrunner – außer bei `ABLEHNUNG`: dann wird das Kapitel `blockiert` und ein Mensch entscheidet.

## Die acht Agenten

| Rolle | Aufgabe | Ausgabe | Standard-Modell | Temp. |
| --- | --- | --- | --- | --- |
| **Showrunner** (`showrunner`) | Steuert das Ganze: erstellt Kapitel-Briefs, entscheidet Konflikte, gibt Kapitel frei, schlägt Bible-Änderungen vor, setzt Aktberichte in Überarbeitungsaufträge um. Schreibt selbst keine Prosa. | JSON | Sonnet | 0,3 |
| **Recherche** (`research`) | Prüft reale Fakten (optional mit Websuche), trennt REAL / PLAUSIBEL / FIKTIV, liefert Sinnesdetails pro Schauplatz. Beachtet den `stichtag_realitaet`. | Faktenblatt (JSON) | Sonnet | 0,2 |
| **Plot-Architekt** (`plot_architect`) | Zerlegt ein Kapitel in 3–5 Szenen (Ziel – Hindernis – Wendung) und verteilt die Wortzahl. | Szenenplan (JSON) | Sonnet | 0,6 |
| **Kapitel-Autor** (`chapter_writer`) | Schreibt die Prosa nach Szenenplan, Faktenblatt und Figurenwissen; kennt das vollständige vorherige Kapitel. | Markdown + `---AUTORENNOTIZ---` | Opus | 0,85 |
| **Kontinuität** (`continuity`) | Findet Widersprüche in Namen, Zahlen, Zeitlinie, Figurenwissen und -zustand. Erstellt nach der Freigabe die Zusammenfassung und neue Protokolleinträge. | Fehlerliste, Protokoll, Zusammenfassung (JSON) | Sonnet | 0,0 |
| **Leitplanken** (`guardrails`) | Prüft inhaltliche Leitplanken (Bible 9) und Plausibilität (Bible 8). Hat **Vetorecht**. | `FREIGABE` / `UEBERARBEITUNG` / `ABLEHNUNG` + Funde (JSON) | Sonnet | 0,0 |
| **Lektor** (`line_editor`) | Poliert Rhythmus, Stimme, Dichte und Länge des geprüften Entwurfs, ohne Handlung oder Fakten zu ändern. | Markdown + `---LEKTORATSNOTIZ---` | Opus | 0,4 |
| **Gesamtleser** (`full_read`) | Liest einen ganzen Akt am Stück und meldet strukturelle Schwächen (Spannung, Wiederholung, Figurenbögen, Wendepunkte). | Aktbericht (JSON) | Opus | 0,3 |

Pro Agent gibt es ein Modul in `src/roman_agenten/agents/` mit `build_messages(...)` und `parse(...)`; der Modellaufruf liegt zentral in `llm.py`. Kein Agent ruft einen anderen auf – nur der Graph verbindet sie. Die Modelle in der Tabelle sind nur Vorschläge aus `.env.example`; im Code ist kein Modellname fest verdrahtet.

## Menschliche Kontrollpunkte

Die Pipeline pausiert (LangGraph `interrupt`) und wartet auf `roman approve`:

- nach Prolog/Kapitel 1 (Ton und Stimme abnehmen)
- nach jedem Aktbericht
- bei jedem Bible-Änderungsvorschlag
- bei jedem blockierten Kapitel
- zusätzliche Punkte aus `project.yaml` (`kontrollpunkte`)

`HUMAN_CHECKPOINTS=false` schaltet alle Punkte ab – **außer** „blockiertes Kapitel“.

## Installation

Voraussetzungen: Python ≥ 3.12 und [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env     # dann .env bearbeiten
uv run roman check
```

## Konfiguration (`.env`)

Alle Variablen sind in `.env.example` dokumentiert. Die `.env` wird nie committet.

- **Modelle:** Format `<provider>:<modell>` (`anthropic`, `openai`, `ollama`). Pro Rolle gilt `AGENT_<ROLLE>_MODEL`, sonst `DEFAULT_MODEL`, sonst Fehler beim Start. Analog `…_TEMPERATURE` und `…_MAX_TOKENS`. Rollenschlüssel: `SHOWRUNNER`, `RESEARCH`, `PLOT_ARCHITECT`, `CHAPTER_WRITER`, `CONTINUITY`, `GUARDRAILS`, `LINE_EDITOR`, `FULL_READ`.
- **Keys:** `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`; für Ollama `OLLAMA_BASE_URL`, `OLLAMA_NUM_CTX`, `OLLAMA_THINK`.
- **Pipeline:** `MAX_REVISION_ROUNDS` (Default 3), `WORD_COUNT_TOLERANCE` (Default 0,15), `HUMAN_CHECKPOINTS`.
- **Kosten:** `MAX_BUDGET_USD` (bei Überschreitung wird pausiert, nicht abgebrochen), `ENABLE_PROMPT_CACHING`, `USE_BATCH_API`. Preise stehen in `config/preise.yaml`.
- **Pfade:** `PROJECTS_DIR` (außerhalb des Repos), `PROMPTS_DIR`, `PREISE_FILE`.
- **Betrieb:** `LLM_MAX_RETRIES`, `LLM_TIMEOUT_SECONDS`, `CHECKPOINTER` (`sqlite` | `postgres`), `LOG_LEVEL`, `LOG_PAYLOADS`.

## Ein Projekt anlegen

Ein Projekt ist ein Ordner unter `PROJECTS_DIR`:

```
<PROJECTS_DIR>/<id>/
├── project.yaml          # Metadaten und Einstellungen
├── bible/                # bible.md ODER 00_zweck.md … 10_workflow.md
├── prompts/              # optionale Überschreibungen einzelner Prompts
├── state/                # checkpoints.sqlite, usage.jsonl, run.log.jsonl
└── output/
    ├── kapitel/<nr>_<slug>/   # brief.json, faktenblatt.json, szenenplan.json,
    │                          # entwurf_rN.md, pruefungen_rN.json, endfassung.md
    ├── berichte/
    └── manuskript/
```

Beispiel `project.yaml`:

```yaml
id: meinroman                  # Kleinbuchstaben, = Ordnername
titel: MEIN ROMAN
sprache: de
zielumfang_woerter: 34000
bible_version: 1
stichtag_realitaet: 2026-10-08 # reale Ereignisse nur bis hierhin
brief_feld: wirkungen          # projektspezifisches Brief-Feld aus Bible 4.3
kapitel_typen: [prosa, dokument]
kontrollpunkte:
  - nach_kapitel: 1
  - nach_jedem_akt: true
```

Pflichtfelder: `id`, `titel`, `sprache`, `zielumfang_woerter`, `bible_version`, `stichtag_realitaet`, `brief_feld`, `kapitel_typen` (muss `prosa` enthalten). Für jeden Kapiteltyp außer `prosa` muss ein Prompt-Zusatz in `prompts/zusaetze/<typ>.md` existieren.

Die **Story Bible** ist in Abschnitte `## 0.` bis `## 10.` mit festen Pflicht-Unterabschnitten gegliedert (`### N.M`); die Kapitelplan-Tabellen (6.1–6.3) haben feste Spalten. `roman bible check` listet alle Verstöße gegen diese Struktur auf.

## Benutzung

```bash
roman check                         # Konfiguration prüfen (Rolle → Modell → Temp. → Tokens)
roman init <id>                     # Projekt-Gerüst mit leerer Bible anlegen
roman bible check <id>              # Bible validieren
roman run <id>                      # gesamten Roman schreiben
roman run <id> --akt II             # nur einen Akt
roman run <id> --kapitel 1          # nur ein Kapitel (auch P, E, SP1 …)
roman status <id>                   # Kapitelstatus, offene Kontrollpunkte, Kosten
roman approve <id>                  # offenen Kontrollpunkt freigeben
roman approve <id> --ablehnen --kommentar "Ton zu kühl, bitte wärmer"
roman resume <id>                   # nach Pause (Budget, API-Fehler) oder Absturz fortsetzen
roman cost <id>                     # Kosten und Tokens pro Rolle
roman export <id> --format md       # Manuskript exportieren
roman prompt chapter_writer --projekt <id> --kapitel 1 --dry-run
                                    # zusammengesetzten Prompt ohne Modellaufruf ansehen
roman schemas --export              # JSON-Schemas aller Agentenausgaben
```

Typischer Ablauf:

1. `roman init <id>` – Gerüst anlegen, Bible und `project.yaml` einfügen.
2. `roman bible check <id>` – Struktur prüfen; `roman run` startet nur mit gültiger Bible.
3. `roman run <id> --kapitel 1` – erstes Kapitel schreiben, mit `roman status <id>` den Stand ansehen.
4. `roman approve <id>` – Ton und Stimme abnehmen; danach `roman run <id>` bzw. `--akt N`.
5. Bei Pause oder Absturz: `roman resume <id>`.
6. `roman export <id> --format md` – Manuskript erzeugen (Ablage in `output/manuskript/`).

## Prompts anpassen

Die Standard-Prompts liegen in `prompts/` (`_basis.md`, ein Prompt je Rolle, `auftraege/` für Aufgabenvarianten, `zusaetze/` für Sonderkapitel). Ein Projekt kann einzelne Dateien in `<PROJECTS_DIR>/<id>/prompts/` überschreiben, ohne Codeänderung. Platzhalter haben die Form `{{name}}`; unbekannte oder ungefüllte Platzhalter führen zu einem Fehler.

## Entwicklung

```bash
uv run pytest                       # Unit-Tests mit Fake-Modellen, ohne Netzwerk
uv run pytest -m llm                # Integrationstests mit lokalem Ollama-Modell
uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest
```

Für Probeläufe mit echtem Modell wird ausschließlich das lokale Modell `ollama:qwen3.5:9b` (Fallback `ollama:llama3.1:8b`) mit einer winzigen Dummy-Bible verwendet; das Testprofil liefert `.env.example.test`. Cloud-Modelle werden in Tests nicht aufgerufen. Details zu Architektur und Regeln stehen in `CLAUDE.md`.
