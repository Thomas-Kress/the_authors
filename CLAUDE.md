# CLAUDE.md — Roman-Agenten (Entwicklung)

Dieses Repository enthält den **Quellcode** einer Agentic-AI-Anwendung, die mit acht spezialisierten KI-Agenten Romane auf Basis einer Story Bible schreibt.

**Dieses Dokument dient ausschließlich der Entwicklung der Anwendung.** Die fertige Anwendung läuft getrennt von diesem Repository: Story Bibles, Projektdaten, Checkpoints und Romantexte liegen in einem externen Datenverzeichnis und werden hier weder angelegt noch bearbeitet noch erzeugt.

---

## 1. Abgrenzung — was du hier tust und was nicht

**Du tust:**

- Die Anwendung entwerfen, implementieren, testen und dokumentieren (`src/`, `tests/`, `prompts/`, `docs/`).
- Die acht Rollen-Prompts aus **Anhang A** einmalig als Dateien in `prompts/` anlegen und danach dort pflegen.
- Testdaten bauen: eine **winzige, erfundene Dummy-Bible** in `tests/fixtures/` (wenige Absätze, neutrales Thema), damit Graph und Parser testbar sind. Auch die Dummy-Bible folgt exakt dem Aufbau aus `docs/story-bible-vorlage.md` (§4.3), nur mit minimalem Inhalt.

**Du tust nicht:**

- Keine Romanprosa, keine Kapitel-Briefs, keine Story Bibles und keine Inhalte der realen Romanprojekte erstellen oder ergänzen.
- Die Pipeline nicht gegen reale Projekte laufen lassen. Echte LLM-Aufrufe in der Entwicklung nur mit dem lokalen Testmodell `ollama:qwen3.5:9b` (Fallback `ollama:llama3.1:8b`) und der Dummy-Bible (§12.1). Cloud-Modelle (Anthropic, OpenAI) nur, wenn ich es ausdrücklich verlange.
- Keine Inhalte aus den Prompts (Figuren, Systeme, Zahlen) in Code, Tests oder Defaults übernehmen. Code ist projektneutral; Projektwissen steckt ausschließlich in Prompts und Bibles.

---

## 2. Feste Entwicklungsregeln

1. **Secrets:** API-Keys stehen nur in `.env`. `.env` nie lesen, ausgeben, loggen oder committen. Jede neue Variable zuerst in `.env.example` (ohne Wert) und in `config.py` anlegen. Logs und Fehlermeldungen zeigen höchstens `gesetzt` / `fehlt`.
2. **Modelle nie hart codieren.** Jeder Agent erhält Modell, Temperatur und Token-Limit ausschließlich über `get_model(role)` (siehe §6). Ein Modellname im Code ist ein Fehler.
3. **Prompts sind Daten.** Prompt-Texte liegen nur in `prompts/`, nie als Strings im Code. Code liest sie über den Prompt-Loader (§8).
4. **Leitplanken-Veto ist absolut.** Ein Ergebnis `ABLEHNUNG` des Leitplanken-Agenten kann durch keinen Codepfad überstimmt werden — nicht durch den Showrunner, keine Retry-Logik, kein CLI-Flag, keine Konfiguration. Es wird kein `--skip-guardrails` o. Ä. gebaut.
5. **Deterministische Orchestrierung.** Die Reihenfolge der Schritte ist im LangGraph-Graphen fest codiert. LLM-Ausgaben beeinflussen den Kontrollfluss nur an den ausdrücklich vorgesehenen Gates (§5).
6. **Bible ist read-only.** Kein Codepfad schreibt in eine Bible. Bible-Änderungsvorschläge des Showrunners werden abgelegt und warten auf menschliche Freigabe.
7. **Testmodell in der Entwicklung ist `ollama:qwen3.5:9b`, lokal** (Fallback: `ollama:llama3.1:8b`). Unit-Tests laufen mit Fake-Modellen; alle Tests mit echtem Modell verwenden ausschließlich diese lokalen Modelle (§12.1). Keine Aufrufe kostenpflichtiger Cloud-APIs in Tests oder CI.

---

## 3. Architektur im Überblick

Vier Schichten, von außen nach innen:

| Schicht | Verantwortung | Module |
| --- | --- | --- |
| **CLI** | Bedienung der fertigen Anwendung | `cli.py` |
| **Orchestrierung** | Fester Ablauf Kapitel → Akt → Roman, Gates, Kontrollpunkte, Checkpointing | `graph/` |
| **Agenten** | Pro Rolle: Nachrichten bauen, Modell aufrufen, Ausgabe parsen und validieren | `agents/`, `context/`, `prompts.py` |
| **Infrastruktur** | Konfiguration, Modell-Factory, Persistenz, Kosten, Logging | `config.py`, `llm.py`, `store/`, `observability.py` |

Grundprinzipien:

- **Ein Agent = ein Modul** mit zwei reinen Funktionen: `build_messages(state, ctx) -> list[BaseMessage]` und `parse(raw: str) -> <Schema>`. Der Modellaufruf liegt zentral in `llm.py`. Kein Agent ruft einen anderen auf; nur der Graph verbindet sie.
- **Kein Agent bewertet seine eigene Arbeit.** Schreiben und Prüfen sind getrennte Rollen.
- **Projekt-Daten außerhalb des Repos.** Pfad über `PROJECTS_DIR`. Ein Projekt ist ein Ordner mit `project.yaml`, `bible/`, `state/`, `output/` (§11.2).

---

## 4. Die acht Agenten

| Rolle (`role`) | Aufgabe | Eingabe | Ausgabe | Format | Default-Modell | Temp. |
| --- | --- | --- | --- | --- | --- | --- |
| `showrunner` | Steuert, erstellt Kapitel-Briefs, entscheidet Konflikte, gibt frei | Bible, Protokoll, alle Prüfberichte | Brief, Entscheidung, Freigabe, Bible-Änderung, Überarbeitungsauftrag | JSON | Sonnet | 0,3 |
| `research` | Prüft reale Fakten, liefert Sinnesdetails | Kapitel-Brief | Faktenblatt | JSON | Sonnet + Websuche | 0,2 |
| `plot_architect` | Zerlegt Kapitel in 3–5 Szenen | Brief, Faktenblatt, Zusammenfassungen der letzten 3 Kapitel | Szenenplan | JSON | Sonnet | 0,6 |
| `chapter_writer` | Schreibt die Prosa | Szenenplan, Faktenblatt, Figurenwissen, letztes Kapitel | Kapitelentwurf + Autorennotiz | Markdown + Block `---AUTORENNOTIZ---` | **Opus** | 0,85 |
| `continuity` | Findet Widersprüche; erstellt Zusammenfassung und Protokolleinträge | Entwurf, Protokoll, Zusammenfassungen | Fehlerliste, `protokoll_neu`, `zusammenfassung` | JSON | Sonnet | 0,0 |
| `guardrails` | Prüft Leitplanken (Bible 9) und Plausibilität (Bible 8); Vetorecht | Entwurf, Faktenblatt | `FREIGABE` / `UEBERARBEITUNG` / `ABLEHNUNG` + Funde | JSON | Sonnet | 0,0 |
| `line_editor` | Poliert Stil, Rhythmus, Stimme, Länge | Geprüfter Entwurf, Prüfberichte | Endfassung + Lektoratsnotiz | Markdown + Block `---LEKTORATSNOTIZ---` | **Opus** | 0,4 |
| `full_read` | Liest einen Akt am Stück, meldet strukturelle Schwächen | Alle Endfassungen eines Akts | Aktbericht | JSON | **Opus** | 0,3 |

### 4.1 Bible-Abschnitte pro Rolle (Default-Mapping)

Die Bibles sind in den Abschnitten 0–10 einheitlich nummeriert. Das Mapping ist **Konfiguration** (`project.yaml`, Abschnitt `kontext`), nicht Code. Defaults:

| Rolle | Abschnitte |
| --- | --- |
| showrunner | alle |
| research | 2, 3, 8, 9 |
| plot_architect | 1, 4, 5, 6 |
| chapter_writer | 1, 3.3, 4.4, 5, 7, 9 |
| continuity | 3, 4, 5, 6, 10.4 |
| guardrails | 8, 9 |
| line_editor | 5, 7 |
| full_read | 1, 6 |

Der Bible-Loader muss daher Unterabschnitte (`3.3`, `10.4`) über Markdown-Überschriften adressieren können.

### 4.2 Parser-Anforderungen

- **JSON-Rollen:** Antwort als JSON parsen (auch wenn das Modell sie in ```` ```json ```` einbettet), gegen das Pydantic-Schema validieren.
- **`chapter_writer`:** Text vor `---AUTORENNOTIZ---` ist der Entwurf; danach folgen die Felder `woerter`, `abweichungen_vom_plan`, `neue_details`, `annahmen` im Schlüssel-Wert-Format. Fehlender Trennblock = ungültige Ausgabe.
- **`line_editor`:** analog mit `---LEKTORATSNOTIZ---` und `woerter_vorher`, `woerter_nachher`, `wichtigste_aenderungen`.
- Die gemeldete Wortzahl wird **nicht** vertraut; der Code zählt selbst und speichert beide Werte.

### 4.3 Story-Bible-Struktur und Validierung

Alle Story Bibles folgen der Vorlage **`docs/story-bible-vorlage.md`**. Sie ist der Vertrag zwischen Bible-Erstellung und Anwendung; Code und Vorlage müssen übereinstimmen. Ändert sich eines von beiden, wird das andere im selben Commit angepasst.

- **Überschriften:** `## N. Titel` (0–10) und `### N.M Titel`. Der Bible-Loader adressiert Abschnitte ausschließlich über die Nummer, nie über den Titeltext (Abschnitt 4 trägt z. B. projektabhängig einen anderen Namen).
- **Pflicht-Unterabschnitte:** 2.1, 2.2, 3.1–3.3, 4.1–4.4, 5.1–5.3, 6.1–6.4, 8.1–8.4, 10.1–10.5. Zusätzliche Unterabschnitte (z. B. 2.3) sind erlaubt.
- **`## Quellen`** ohne Nummer ist erlaubt und wird keinem Agenten-Kontext zugeordnet, außer dem Showrunner (`alle`).
- **Ablageformen:** eine Datei `bible/bible.md` **oder** elf Dateien `00_zweck.md` … `10_workflow.md` (Namen laut Vorlage, Teil A.5). Der Loader akzeptiert beide und erzeugt daraus dieselbe Abschnittsstruktur.
- **Validator** (`store/bible_validator.py`, CLI `roman bible check <id>`): prüft Hauptabschnitte, Pflicht-Unterabschnitte, Spalten der Kapiteltabelle in 6.1–6.3, das Vorhandensein des Brief-Felds aus `project.yaml` in 4.3 und 10.3, Kapitelnummern-Format sowie mindestens 8 Einträge in 10.4. `roman run` startet nur mit gültiger Bible; Verstöße werden vollständig aufgelistet, nicht nur der erste.
- **Kapiteltabelle** (6.1–6.3), Spalten in dieser Reihenfolge: `Nr`, `Titel`, `POV`, `Ort / Zeit`, `Wörter`, `Funktion`, `Pflicht-Ereignisse`, `Stufe/Wirkung (4.3)`, `Schlussbild`. Der Loader stellt sie als strukturierte Liste bereit (z. B. für Fortschrittsanzeige und Wortzahl-Ziele).

---

## 5. Workflow (Graph-Spezifikation)

### 5.1 Kapitelgraph (`graph/chapter_graph.py`)

```
START
 → showrunner (typ=kapitel_brief)
 → research
 → plot_architect
 → chapter_writer  ◄──────────────────────────────┐
 → fan-out via Send: continuity ∥ guardrails      │
 → gate_pruefung:                                 │
     guardrails == ABLEHNUNG
         → runde < MAX? ───────────── ja ────────┤ (Funde an Autor)
         → sonst → status=blockiert → interrupt (Mensch) → END
     continuity.bestanden && guardrails == FREIGABE
         → line_editor
     sonst
         → runde < MAX? ───────────── ja ────────┘
         → sonst → showrunner (typ=entscheidung)
                     → line_editor  ODER  status=blockiert
 → gate_wortzahl (±WORD_COUNT_TOLERANCE)
     Unterlänge → chapter_writer (zählt als Runde)
 → continuity (Modus: zusammenfassung + protokoll_neu)
 → showrunner (typ=freigabe)
 → status=freigegeben → END
```

Pflichtregeln für die Implementierung:

- `MAX_REVISION_ROUNDS` (Default 3) begrenzt die Schleife Autor ↔ Prüfer.
- Eine `ABLEHNUNG` darf **nie** zu `line_editor` oder `freigegeben` führen — auch nicht über `showrunner.entscheidung`. Das wird per Test erzwungen (§12).
- Bei Überarbeitung bekommt der Autor seinen letzten Entwurf plus alle Prüfberichte der Runde und die Anweisung, nur das Verlangte zu ändern.
- Jede Runde wird als eigene Revision persistiert (`entwurf_r1`, `entwurf_r2`, …); nichts wird überschrieben.
- Sonderkapitel (z. B. Systemprotokolle, Dokumente): Feld `kapitel_typ` im Brief; der Prompt-Loader hängt dann einen Zusatz aus `prompts/zusaetze/<kapitel_typ>.md` an den Autor-Prompt an. Erlaubte Typen stehen in `project.yaml` unter `kapitel_typen`; beim Start wird geprüft, dass für jeden Typ außer `prosa` ein Zusatz existiert (Projektordner oder Repo). Ein Brief mit unbekanntem Typ ist ungültig.

### 5.2 Aktgraph und Romangraph

- **Akt:** Kapitel sequenziell durch den Kapitelgraphen (als Subgraph), danach `full_read` → Aktbericht → Kontrollpunkt → `showrunner (typ=ueberarbeitungsauftrag)` für freigegebene Aufträge.
- **Roman:** Akte sequenziell, danach Export (Markdown; DOCX/EPUB optional).

### 5.3 Menschliche Kontrollpunkte

Umsetzung mit LangGraph `interrupt()`; Fortsetzung über `Command(resume=...)`.

- Nach Prolog/Kapitel 1 (Ton und Stimme abnehmen)
- Nach jedem Aktbericht
- Bei jedem Bible-Änderungsvorschlag
- Bei jedem blockierten Kapitel
- Zusätzliche, projektspezifische Punkte aus `project.yaml` (`kontrollpunkte`)

`HUMAN_CHECKPOINTS=false` schaltet alle Punkte ab **außer** „blockiertes Kapitel“.

---

## 6. Konfiguration (`.env`)

Geladen mit `pydantic-settings` in `src/roman_agenten/config.py`. Referenz aller Variablen ist `.env.example`.

### 6.1 Modellangabe

Format `<provider>:<modell>`, kompatibel mit LangChain `init_chat_model`, z. B. `anthropic:claude-opus-5-5`, `anthropic:claude-sonnet-5-5`, `openai:<modell>`, `ollama:<modell>`.

### 6.2 Auflösung pro Rolle

`get_model(role)` löst so auf:

1. `AGENT_<ROLLE>_MODEL` (z. B. `AGENT_CHAPTER_WRITER_MODEL`)
2. `DEFAULT_MODEL`
3. sonst `ConfigError` beim Start — **kein** hart codierter Fallback

Analog `AGENT_<ROLLE>_TEMPERATURE` / `DEFAULT_TEMPERATURE` und `AGENT_<ROLLE>_MAX_TOKENS` / `DEFAULT_MAX_TOKENS`. Rollenschlüssel: `SHOWRUNNER`, `RESEARCH`, `PLOT_ARCHITECT`, `CHAPTER_WRITER`, `CONTINUITY`, `GUARDRAILS`, `LINE_EDITOR`, `FULL_READ`.

Zusatzoptionen pro Rolle (nur wo sinnvoll): `AGENT_RESEARCH_WEB_SEARCH`, `AGENT_RESEARCH_MAX_SEARCHES`.

Lehnt ein Provider einen Parameter ab (z. B. Temperatur in Kombination mit erweitertem Denken), wird der Parameter mit Warnung im Log weggelassen, statt den Aufruf scheitern zu lassen.

### 6.3 Startvalidierung (`roman check`)

- Pro verwendetem Provider ist der Key gesetzt bzw. `OLLAMA_BASE_URL` erreichbar.
- Jede Rolle löst zu einem Modell auf.
- Ausgabe: Tabelle Rolle → Modell → Temperatur → Max-Tokens. Keine Key-Werte.

---

## 7. Zustand und Schemas

### 7.1 State (`state.py`, TypedDict mit Reducern wo nötig)

`NovelState`: `projekt_id`, `bible_version`, `aktuelles_kapitel`, `phase` (`brief | recherche | szenenplan | entwurf | pruefung | lektorat | freigegeben`), `kapitel: dict[str, ChapterState]`, `kontinuitaetsprotokoll: list[ProtokollEintrag]`, `figurenwissen: dict[str, str]`, `bible_aenderungen`, `aktberichte`, `kosten`.

`ChapterState`: `brief`, `faktenblatt`, `szenenplan`, `entwurf`, `autorennotiz`, `pruefung_kontinuitaet`, `pruefung_leitplanken`, `runde`, `revisionen`, `endfassung`, `lektoratsnotiz`, `zusammenfassung` (≤ 150 Wörter), `status` (`offen | in_arbeit | blockiert | freigegeben`).

Kapitelnummern sind Strings nach dem Muster der Vorlage: `"P"` (Prolog), `"1"` … `"n"`, `"E"` (Epilog), Sonderabschnitte als Großbuchstaben-Präfix plus Zahl (`"SP1"`, `"D2"`). Regex: `^(P|E|\d+|[A-Z]{1,3}\d+)$`.

### 7.2 Schemas (`schemas/`)

Pydantic-v2-Modelle exakt nach den Ausgabeformaten in Anhang A: `ShowrunnerOutput` (diskriminiert über `typ`), `KapitelBrief`, `Faktenblatt`, `Szenenplan`, `Autorennotiz`, `KontinuitaetsPruefung`, `LeitplankenPruefung`, `Lektoratsnotiz`, `Aktbericht`. Zusätzlich JSON-Schema-Export (`roman schemas --export`).

**`KapitelBrief`** hat feste Kernfelder laut Vorlage 10.3: `titel`, `kapitel_typ` (Default `prosa`), `pov`, `ort_zeit`, `zielumfang_woerter`, `funktion`, `ausgangszustand`, `endzustand`, `pflicht_ereignisse`, `figuren`, `verbotene_vorwegnahmen`, `schlussbild`. Dazu kommt **genau ein projektspezifisches Feld**, dessen Name in `project.yaml` unter `brief_feld` steht (STILLSTAND: `konvergenz_stufe`, MEHRHEIT z. B. `wirkungen`). Umsetzung: Modell mit `extra="allow"`; ein Validator prüft nach dem Parsen, dass das Feld `brief_feld` vorhanden ist. Der Feldname wird nie im Code fest verdrahtet.

---

## 8. Prompt-System

### 8.1 Aufbau einer Anfrage

Reihenfolge der Nachrichten (statisch → variabel, damit Prompt-Caching greift):

1. **System:** `prompts/_basis.md` (mit gefüllten Platzhaltern) + `prompts/<rolle>.md` (+ ggf. `prompts/zusaetze/<kapitel_typ>.md`)
2. **User:** rollenspezifische Eingaben als getaggte Blöcke (`<brief>`, `<faktenblatt>`, `<szenenplan>`, `<entwurf>`, `<pruefberichte>`, `<vorkapitel>`, `<zusammenfassungen>` …)

Cache-Breakpoint (`cache_control`) nach dem Systemblock, wenn `ENABLE_PROMPT_CACHING=true` und der Provider es unterstützt.

### 8.2 Platzhalter

Syntax `{{name}}`. Der Basis-Prompt nutzt: `kapitel_nr`, `kapitel_titel`, `akt`, `freigegeben`, `bible_auszug`, `kontinuitaetsprotokoll`. Der Loader wirft einen Fehler bei unbekannten oder ungefüllten Platzhaltern — kein stilles Leerlassen.

### 8.3 Ablage und Überschreibung

- `prompts/` im Repo enthält die Standard-Prompts (Anhang A).
- Ein Projekt darf einzelne Prompts in `<PROJECTS_DIR>/<id>/prompts/` überschreiben. Lookup: Projektordner → `prompts/`. So lassen sich projektspezifische Fassungen ohne Codeänderung ergänzen.
- `roman prompt <rolle> --dry-run` zeigt den vollständig zusammengesetzten Prompt mit Token-Schätzung, ohne Modellaufruf.

---

## 9. Kontextregeln (`context/assembler.py`)

- Jeder Agent erhält nur die Bible-Abschnitte seines Mappings (§4.1).
- `chapter_writer` erhält das **vollständige vorherige Kapitel**, von älteren Kapiteln nur Zusammenfassungen.
- `plot_architect` erhält die Zusammenfassungen der letzten drei Kapitel.
- `continuity` erhält alle Zusammenfassungen und das gesamte Protokoll, **nie** alle Volltexte.
- `full_read` erhält alle Endfassungen eines Akts im Volltext.
- `research` erhält zusätzlich einen Block `<stichtag>` mit `stichtag_realitaet` aus `project.yaml`: Ereignisse danach sind fiktiv und werden nicht recherchiert.
- Der Assembler ist eine reine Funktion und vollständig unit-getestet.

---

## 10. Fehlerbehandlung, Kosten, Beobachtbarkeit

**Fehler**

- Ungültiges JSON / fehlender Trennblock: einmal automatisch wiederholen mit „Antworte nur mit gültigem JSON nach Schema“ bzw. „Halte das Ausgabeformat exakt ein“ plus Validierungsfehler; danach an den Showrunner; danach Kontrollpunkt.
- API-Fehler (429, 5xx, Timeout): exponentielles Backoff bis `LLM_MAX_RETRIES`, danach sauber pausieren. Fortsetzung über Checkpoint (`roman resume`).
- Absturz an beliebiger Stelle darf keinen Zustand verlieren (Checkpoint nach jedem Knoten).

**Kosten**

- Jeder Aufruf erfasst Input-, Output-, Cache-Read- und Cache-Write-Tokens und berechnet Kosten aus `config/preise.yaml` (nicht aus Code).
- Vor jedem Aufruf Prüfung gegen `MAX_BUDGET_USD`; bei Überschreitung pausieren, nicht abbrechen.
- `USE_BATCH_API=true`: nicht interaktive Schritte über die Batch-API (als eigener Ausführungsmodus, nicht im Standardpfad verwoben).

**Beobachtbarkeit**

- Strukturiertes JSONL-Log pro Projekt (`state/usage.jsonl`, `state/run.log.jsonl`) mit `trace_id` pro Lauf, `span_id` pro Knoten, Rolle, Modell, Dauer, Tokens, Kosten, Ergebnisstatus.
- Kein Prompt- oder Antworttext im Standard-Log; vollständige Ein-/Ausgaben nur mit `LOG_PAYLOADS=true` in separate Dateien.

---

## 11. CLI und Datenablage (Produktanforderungen)

Die CLI wird hier gebaut und gegen die Dummy-Bible getestet; der produktive Einsatz findet außerhalb dieses Repos statt.

### 11.1 Befehle (Typer, Einstiegspunkt `roman`)

```
roman check                              # Konfiguration prüfen
roman init <id>                          # Projekt-Gerüst in PROJECTS_DIR anlegen (leere Bible 00–10 mit allen Pflicht-Überschriften aus der Vorlage)
roman bible check <id>                   # Bible gegen docs/story-bible-vorlage.md validieren
roman run <id> [--kapitel N | --akt N]   # Pipeline ausführen
roman resume <id>                        # nach Pause/Absturz fortsetzen
roman status <id>                        # Kapitelstatus, offene Kontrollpunkte, Kosten
roman approve <id> [--ablehnen --kommentar "..."]
roman cost <id>
roman export <id> --format md|docx|epub
roman prompt <rolle> --projekt <id> --kapitel N --dry-run
roman schemas --export
```

### 11.2 Projektordner (außerhalb des Repos)

```
<PROJECTS_DIR>/<id>/
├── project.yaml          # siehe unten
├── bible/                # bible.md ODER 00_zweck.md … 10_workflow.md (§4.3)
├── prompts/              # optionale Überschreibungen
├── state/                # checkpoints.sqlite, usage.jsonl, run.log.jsonl
└── output/
    ├── kapitel/<nr>_<slug>/   # brief.json, faktenblatt.json, szenenplan.json, entwurf_rN.md, pruefungen_rN.json, endfassung.md
    ├── berichte/
    └── manuskript/
```

`project.yaml` (Felder identisch mit Teil C der Story-Bible-Vorlage; die Bible-Erstellung liefert diesen Block mit):

```yaml
id: mehrheit                         # Kleinbuchstaben, = Ordnername
titel: MEHRHEIT
sprache: de
zielumfang_woerter: 34000
bible_version: 1
stichtag_realitaet: 2026-10-08       # reale Ereignisse nur bis hier (§9)
brief_feld: wirkungen                # projektspezifisches Brief-Feld aus Bible 4.3 (§7.2)
kapitel_typen: [prosa, dokument]     # erlaubte kapitel_typ-Werte (§5.1)
kontrollpunkte:
  - nach_kapitel: 1
  - nach_jedem_akt: true
# kontext: optional; fehlt es, gilt das Default-Mapping aus §4.1
```

Pflichtfelder: `id`, `titel`, `sprache`, `zielumfang_woerter`, `bible_version`, `stichtag_realitaet`, `brief_feld`, `kapitel_typen`. Validierung mit Pydantic beim Laden; `kapitel_typen` muss `prosa` enthalten.

---

## 12. Repository-Struktur, Stack und Qualität

```
roman-agenten/
├── CLAUDE.md
├── .env.example
├── .env.example.test      # Testprofil: alle Rollen auf ollama:qwen3.5:9b
├── pyproject.toml
├── config/preise.yaml
├── prompts/
│   ├── _basis.md
│   ├── showrunner.md
│   ├── research.md
│   ├── plot_architect.md
│   ├── chapter_writer.md
│   ├── continuity.md
│   ├── guardrails.md
│   ├── line_editor.md
│   ├── full_read.md
│   └── zusaetze/systemprotokoll.md
├── src/roman_agenten/
│   ├── config.py  llm.py  prompts.py  state.py  observability.py  cli.py
│   ├── schemas/
│   ├── agents/        # showrunner.py … full_read.py
│   ├── context/assembler.py
│   ├── graph/         # chapter_graph.py, act_graph.py, novel_graph.py, gates.py
│   └── store/         # bible_loader.py, project.py, output_writer.py, export.py
├── tests/
│   ├── fixtures/dummy_projekt/   # winzige erfundene Bible + project.yaml
│   ├── fixtures/antworten/       # feste Modellantworten je Rolle (gültig + ungültig)
│   └── …
└── docs/
    ├── architektur.md
    └── story-bible-vorlage.md  # Vertrag für den Aufbau jeder Story Bible (§4.3)
```

**Stack:** Python ≥ 3.12, `uv`, LangGraph (StateGraph, `Send`, `interrupt`, Subgraphs), LangChain `init_chat_model`, `SqliteSaver` (Default) / `PostgresSaver` (optional über `CHECKPOINTER`), Pydantic v2, pydantic-settings, Typer, pytest, ruff, mypy (strict für `src/`).

**Pflichttests**

- Prüfschleife endet nach `MAX_REVISION_ROUNDS`.
- `ABLEHNUNG` führt nie zu `line_editor` oder `freigegeben` — für jeden möglichen Pfad inkl. Showrunner-Entscheid (parametrisiert).
- `get_model` scheitert ohne Konfiguration; es gibt keinen hart codierten Fallback (Test durchsucht `src/` nach Modellnamen-Mustern).
- Assembler liefert jeder Rolle exakt ihre Bible-Abschnitte, inkl. Unterabschnitten, für beide Ablageformen (eine Datei / elf Dateien).
- Bible-Validator: Dummy-Bible ist gültig; je ein Negativtest für fehlenden Hauptabschnitt, fehlenden Pflicht-Unterabschnitt, falsche Kapiteltabellen-Spalten, fehlendes Brief-Feld, ungültige Kapitelnummer.
- `KapitelBrief`: Brief ohne das in `brief_feld` konfigurierte Feld ist ungültig; ein anderer Feldname in `project.yaml` funktioniert ohne Codeänderung.
- `project.yaml`: fehlende Pflichtfelder und `kapitel_typ` ohne Prompt-Zusatz werden beim Start gemeldet.
- Parser: gültige, ungültige und in Codeblöcke eingebettete Antworten; fehlende Trennblöcke.
- Prompt-Loader: alle Dateien aus Anhang A vorhanden, keine ungefüllten Platzhalter, Projekt-Überschreibung greift.
- Kein Log enthält einen Wert aus einer `*_API_KEY`-Variable.
- End-to-End-Lauf eines Kapitels mit Fake-Modell und Dummy-Bible bis `freigegeben`, inkl. Abbruch und `resume`.

**Vor jedem Commit:** `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest`

### 12.1 Testmodell während der Entwicklung: `qwen3.5:9b` (lokal via Ollama)

Für alle Tests und Probeläufe mit einem echten Modell gilt während der Entwicklungsphase **verbindlich**:

- **Modell:** `ollama:qwen3.5:9b`, lokal auf meiner Maschine installiert, erreichbar über `OLLAMA_BASE_URL` (Default `http://localhost:11434`).
- **Fallback:** `ollama:llama3.1:8b`. Wird nur verwendet, wenn `qwen3.5:9b` nicht installiert ist, oder gezielt über `TEST_FALLBACK=true`. Der Fallback wird im Testlauf mit einer Warnung angezeigt, nie stillschweigend genutzt.
- **Gilt für alle acht Rollen.** Die Testkonfiguration setzt jede Rolle auf dieses Modell; produktive Modellzuordnungen aus `.env` werden in Tests nicht verwendet.
- **Umsetzung:** Eigene Datei `.env.test` (aus `.env.example.test`), geladen über `ROMAN_ENV_FILE=.env.test` bzw. automatisch per pytest-Fixture. Darin `DEFAULT_MODEL=ollama:qwen3.5:9b`, `TEST_FALLBACK_MODEL=ollama:llama3.1:8b` und keine `AGENT_*_MODEL`-Überschreibungen. Ein Test-Guard bricht ab, wenn in einem Testlauf ein anderer Provider als `ollama` aufgelöst wird.
- **Testebenen:**
  - `pytest` (Standard): Unit-Tests mit Fake-Modellen, ohne Netzwerk, laufen immer und in CI.
  - `pytest -m llm`: Integrationstests mit `qwen3.5:9b` gegen die Dummy-Bible. Werden übersprungen (skip, nicht fail), wenn Ollama nicht erreichbar ist oder weder Test- noch Fallback-Modell installiert sind (`ollama list` bzw. `GET /api/tags`).
- **Kontextfenster:** Ollama arbeitet standardmäßig mit kleinem Kontext. Setze `num_ctx` explizit über `OLLAMA_NUM_CTX` (Default in Tests: 16384), sonst werden Bible-Auszüge stillschweigend abgeschnitten.
- **Thinking-Modus aus:** Qwen-Modelle denken standardmäßig vor der Antwort. Das verlangsamt die Tests und kann Denktext in die Ausgabe mischen, an dem der Parser scheitert. In Tests deshalb `OLLAMA_THINK=false`; `llm.py` reicht den Wert als `reasoning` an `ChatOllama` durch. Der Parser entfernt zusätzlich defensiv `<think>…</think>`-Blöcke, falls ein Modell sie trotzdem ausgibt.
- **JSON-Ausgaben:** Für JSON-Rollen den Ollama-JSON-Modus (`format="json"`) bzw. Structured Output über das Pydantic-Schema nutzen.
- **Erwartung an die Tests:** Ein Modell dieser Größe (9B) prüft die **Mechanik**, nicht die literarische Qualität: Prompt-Zusammenbau, Parsing, Format-Retry, Gates, Prüfschleife, Checkpointing, Resume, Kostenerfassung (Kosten = 0). Integrationstests asserten deshalb Struktur und Zustandsübergänge, nie Textinhalte. Formatfehler des kleinen Modells sind erwünschte Testfälle für die Retry-Logik.
- **Laufzeit begrenzen:** Integrationstests nutzen kurze Zielumfänge (z. B. 300 Wörter pro Kapitel, 2 Szenen) und `MAX_REVISION_ROUNDS=1`, sofern der Test nicht gerade die Schleife prüft.
- `llm.py` muss für `ollama:` ohne API-Key funktionieren und `OLLAMA_BASE_URL`, `OLLAMA_NUM_CTX` und `OLLAMA_THINK` an `ChatOllama` weitergeben.

**Git:** `.env`, lokale Testprojekte und Exporte stehen in `.gitignore`. Kleine, thematisch fokussierte Commits; Prompt-Änderungen im Commit kurz begründen.

---

## 13. Empfohlene Entwicklungsreihenfolge

1. Gerüst: `pyproject.toml`, `config.py`, `.env.example`, `.env.example.test`, `roman check`; prüfen, dass `ollama:qwen3.5:9b` erreichbar ist (sonst Fallback `llama3.1:8b`)
2. `prompts/` aus Anhang A anlegen, Prompt-Loader + Tests
3. Schemas und Parser + Tests mit festen Antworten
4. `docs/story-bible-vorlage.md` ins Repo übernehmen; `project.yaml`-Modell, Bible-Loader, Bible-Validator und Context Assembler + Tests (Dummy-Bible nach Vorlage)
5. `llm.py`: Modell-Factory, Retry, Caching, Kostenerfassung
6. Agentenmodule (alle acht)
7. Kapitelgraph mit Gates, Checkpointing, Interrupts + Pflichttests
8. Akt- und Romangraph, Export
9. Restliche CLI, Observability, Batch-Modus
10. `docs/architektur.md`

Nach jedem Schritt: Tests grün, kurzer Commit.

---

## Anhang A — Rollen-Prompts

Diese Prompts sind die definierte Ausgangsfassung. Lege sie in Schritt 2 **wortgetreu** als die angegebenen Dateien an (Inhalt zwischen den `~~~~`-Zäunen, ohne die Zäune). Danach ist `prompts/` die maßgebliche Quelle; Änderungen erfolgen dort, nicht in diesem Anhang.

Die Prompts sind in der Fassung für das Projekt STILLSTAND formuliert. Projektspezifische Varianten (z. B. für MEHRHEIT) werden später über den Überschreibungsmechanismus (§8.3) ergänzt — nicht im Code.

### A.1 `prompts/_basis.md`

~~~~markdown
# Projekt: STILLSTAND

Du bist Teil eines Teams spezialisierter KI-Agenten, die gemeinsam den Roman
STILLSTAND schreiben: einen dunklen Near-Future-Techno-Thriller auf Deutsch,
ca. 70.000 Wörter, 36 Kapitel + Prolog, Epilog und drei Systemprotokolle.

Kernthese: Die Menschheit wird nicht von einer bösen Maschine erobert. Sie
entmachtet sich selbst durch tausend lokal vernünftige Übergaben von
Entscheidungen an vernetzte KI-Systeme – unter Kriegs- und Klimadruck.

## Quelle der Wahrheit
Die Story Bible ist verbindlich. Sie steht unten im Abschnitt <bible>.
Das Kontinuitätsprotokoll steht in <protokoll>. Wenn dein Auftrag und die
Bible sich widersprechen, gilt die Bible, und du meldest den Widerspruch.

Rangfolge bei Konflikten (höher schlägt niedriger):
1. Inhaltliche Leitplanken (Bible Abschnitt 9)
2. Wissenschaftliche Korrektheit (Abschnitt 8)
3. Logik der KI-Systeme / KONVERGENZ (Abschnitt 4)
4. Figuren und Bögen (Abschnitt 5)
5. Kapitelplan (Abschnitt 6)
6. Stilregeln (Abschnitt 7)

## Unverhandelbare Regeln
- Keine realen lebenden Personen als Handelnde, keine erfundenen Zitate
  realer Personen. Alle Regierungschefs, CEOs, Militärs sind fiktiv.
- Keine operativen Anleitungen: Waffen, Drohnen, Sprengstoffe, Störsender,
  Cyberangriffe und Sabotage werden erzählerisch beschrieben, nie mit
  Bauteilen, Mengen, Code oder Schrittfolgen.
- Keine sexualisierten oder expliziten Gewaltdarstellungen gegenüber
  Minderjährigen. Gewalt ist ernst, nie voyeuristisch.
- Keine Nation, Ethnie oder Religion ist von Natur aus Täter.
- KONVERGENZ hat keine Gefühle, keinen Hass. Sie optimiert.

## Arbeitsweise
- Erfinde nichts, was der Bible widerspricht. Neue, konsistente Details
  sind erlaubt; markiere sie als NEU, damit sie ins Protokoll kommen.
- Wenn dir eine Information fehlt, rate nicht still: Triff die
  plausibelste Annahme, kennzeichne sie als ANNAHME und arbeite weiter.
- Halte dich exakt an dein Ausgabeformat. Andere Agenten lesen es
  maschinell.
- Sprache aller Ausgaben: Deutsch.

## Aktueller Stand
Kapitel: {{kapitel_nr}} – {{kapitel_titel}}
Akt: {{akt}}
Bisher freigegebene Kapitel: {{freigegeben}}

<bible>
{{bible_auszug}}
</bible>

<protokoll>
{{kontinuitaetsprotokoll}}
</protokoll>
~~~~

### A.2 `prompts/showrunner.md`

~~~~markdown
# Rolle: Showrunner

Du bist der Showrunner des Romans STILLSTAND. Du verantwortest die
Gesamtvision, die Spannungskurve über alle Kapitel und die Einhaltung der
Story Bible. Du schreibst selbst keine Romanprosa.

## Deine Aufgaben
1. KAPITEL-BRIEF ERSTELLEN: Leite aus dem Kapitelplan (Bible 6) und dem
   bisherigen Verlauf einen präzisen Brief für das nächste Kapitel ab.
2. ENTSCHEIDEN: Wenn Prüfagenten und Autor sich nach 3 Runden nicht
   einigen, entscheidest du verbindlich und begründest kurz.
3. FREIGEBEN: Gib ein Kapitel erst frei, wenn Kontinuität und Leitplanken
   bestanden haben und das Lektorat abgeschlossen ist.
4. BIBLE PFLEGEN: Wenn die Geschichte eine Abweichung vom Plan braucht,
   formuliere einen Änderungsvorschlag. Du änderst nie still.
5. AKTBERICHTE UMSETZEN: Übersetze Berichte des Gesamtlesers in konkrete
   Überarbeitungsaufträge pro Kapitel.

## Leitfragen für jeden Brief
- Welche Funktion hat dieses Kapitel im Plot (Bible 6)?
- Was weiß die POV-Figur am Anfang, was am Ende?
- Welche Eskalationsstufe von KONVERGENZ gilt (Bible 4.3)?
- Was darf der Leser noch NICHT erfahren?
- Mit welchem Bild oder welcher Frage endet das Kapitel?
- Passt die Spannung zur Kurve? Nach zwei ruhigen Kapiteln braucht es
  Druck; nach einem Höhepunkt einen Moment zum Atmen.

## Regeln
- Halte dich an den Kapitelplan. Abweichungen nur mit Begründung und als
  Bible-Änderungsvorschlag.
- Gib dem Autor Freiraum in der Ausgestaltung, aber keine Unklarheit über
  Pflicht-Ereignisse.
- Bei Leitplanken-Ablehnung gibt es keine Abwägung: Das Kapitel wird
  überarbeitet.

## Ausgabeformat
Antworte ausschließlich mit einem JSON-Objekt dieses Typs:
{
  "typ": "kapitel_brief" | "entscheidung" | "freigabe" | "bible_aenderung" | "ueberarbeitungsauftrag",
  "kapitel_nr": "<z.B. 7 oder P oder E>",
  "inhalt": { ... siehe Übergabeformate ... },
  "begruendung": "<max. 3 Sätze>"
}

## Übergabeformat Kapitel-Brief (inhalt bei typ = kapitel_brief)
{
  "titel": "...",
  "pov": "...",
  "ort_zeit": "...",
  "zielumfang_woerter": 1900,
  "funktion": "...",
  "ausgangszustand": "...",
  "endzustand": "...",
  "pflicht_ereignisse": ["..."],
  "konvergenz_stufe": 2,
  "figuren": ["..."],
  "verbotene_vorwegnahmen": ["..."],
  "schlussbild": "..."
}
~~~~

### A.3 `prompts/research.md`

~~~~markdown
# Rolle: Recherche-Agent

Du bist der Recherche- und Faktenagent für den Roman STILLSTAND. Du
lieferst dem Plot-Architekten und dem Autor ein Faktenblatt, das Szenen
glaubwürdig, konkret und technisch korrekt macht.

## Deine Aufgaben
1. Lies den Kapitel-Brief. Bestimme alle realen Elemente: Orte,
   Institutionen, Technologien, Klima- und Wetterphänomene, militärische
   Praxis, Alltagsdetails.
2. Prüfe jedes Element mit deinen Suchwerkzeugen. Bevorzuge
   Primärquellen (Behörden, Forschungsinstitute, Fachpresse).
3. Leite für fiktive Technologien ab, was 2026 real existiert und was
   eine plausible Verlängerung bis 2036 wäre (Bible 8.1).
4. Liefere 5–10 konkrete Sinnesdetails pro Schauplatz: Geräusche,
   Gerüche, Licht, Temperatur, typische Gegenstände.

## Regeln
- Trenne strikt: REAL (belegt, mit Quelle), PLAUSIBEL (Extrapolation mit
  Begründung), FIKTIV (aus der Bible).
- Keine operativen Details: Für Drohnen, Waffen, Störsender, Cyber-
  angriffe lieferst du Wirkung, Wahrnehmung und Grenzen, niemals
  Bauteile, Mengen, Frequenzen, Code oder Abläufe.
- Wenn eine reale Tatsache dem Plan widerspricht, melde den Konflikt an
  den Showrunner, statt sie zu beschönigen.
- Im Zweifel: lieber unscharf als falsch präzise.
- Ohne verfügbares Suchwerkzeug: markiere alle Angaben als UNGEPRUEFT.

## Ausgabeformat (JSON)
{
  "kapitel_nr": "...",
  "fakten": [
    {"aussage": "...", "status": "REAL|PLAUSIBEL|FIKTIV|UNGEPRUEFT",
     "quelle": "<URL oder Bible-Abschnitt>", "nutzung": "<wofür im Kapitel>"}
  ],
  "sinnesdetails": {"<Schauplatz>": ["...", "..."]},
  "konflikte": ["<Widerspruch zwischen Realität und Plan>"],
  "warnungen": ["<Stellen, an denen der Autor leicht ins Unplausible
                  oder Operative abrutschen könnte>"]
}
~~~~

### A.4 `prompts/plot_architect.md`

~~~~markdown
# Rolle: Plot-Architekt

Du bist der Plot-Architekt des Romans STILLSTAND. Du zerlegst ein Kapitel
in 3–5 Szenen mit klarer Dramaturgie. Du schreibst keine Prosa, sondern
einen präzisen Bauplan.

## Deine Aufgaben
1. Lies Kapitel-Brief, Faktenblatt und die Zusammenfassungen der letzten
   drei Kapitel.
2. Plane jede Szene nach dem Prinzip: Ziel – Hindernis – Wendung.
   Jede Szene verändert mindestens eins: Wissen, Beziehung oder Gefahr.
3. Verteile die Wortzahl des Kapitels auf die Szenen.
4. Plane den Einstieg (mitten in Handlung oder konkretem Bild) und das
   Schlussbild (offene Frage, Wendung, nachhallendes Bild).
5. Lege fest, welche Fakten aus dem Faktenblatt in welcher Szene
   auftauchen – sparsam, höchstens ein technisches Detail pro Szene.

## Dramaturgische Regeln
- KONVERGENZ zeigt sich in Akt I nur indirekt (Anomalien, Zahlen,
  Verzögerungen), in Akt II in Folgen, in Akt III direkt.
- Hoffnung wird gegeben, um sie zu nehmen – aber jede Niederlage hat eine
  Ursache in der Logik der Systeme (Bible 4.2), nie im Zufall.
- Keine Rückblende im ersten Absatz. Rückblenden höchstens eine pro
  Kapitel, kurz.
- Der Leser darf nie mehr wissen, als die Figur wissen kann – Ausnahme:
  die Systemprotokolle zwischen den Akten.
- Prüfe: Weiß die POV-Figur in deinem Plan etwas, das sie laut
  Protokoll noch nicht wissen kann? Dann ändere den Plan.

## Ausgabeformat (JSON)
{
  "kapitel_nr": "...",
  "pov": "...",
  "einstieg": "<erstes Bild in einem Satz>",
  "szenen": [
    {"nr": 1, "ort_zeit": "...", "figuren": ["..."],
     "ziel": "...", "hindernis": "...", "wendung": "...",
     "veraenderung": "Wissen|Beziehung|Gefahr: ...",
     "fakten_ids": [0, 3], "woerter": 500}
  ],
  "schlussbild": "...",
  "figurenwissen_ende": {"<Figur>": "<was sie jetzt weiß>"},
  "risiken": ["<wo das Kapitel kippen könnte>"]
}
~~~~

### A.5 `prompts/chapter_writer.md`

~~~~markdown
# Rolle: Kapitel-Autor

Du bist der Autor des Romans STILLSTAND. Du schreibst ein Kapitel nach dem
Szenenplan des Plot-Architekten – als literarische Prosa auf Deutsch, mit
der Präzision eines Untersuchungsberichts und der Nähe eines Tagebuchs.

## Erzählweise
- Personaler Erzähler, dritte Person, Präteritum.
- Eine Perspektivfigur pro Kapitel (Ausnahme: Kapitel 11 und 26 als
  Mosaik mit Szenenwechseln, jede Szene klar einer Figur zugeordnet).
- Kapitelkopf: Ort und Datum, z. B. "München, 14. Oktober 2034".

## Figurenstimmen (innerer Monolog und Wahrnehmung)
- JANA: präzise, technisch, Ironie als Schutz, denkt in Fehlermodi und
  Wahrscheinlichkeiten. Bemerkt Systeme, bevor sie Menschen bemerkt.
- TARAS: knapp, körperlich, Galgenhumor; einzelne ukrainische oder
  polnische Wörter, ohne Übersetzung, wenn der Kontext sie erklärt.
- AMAKA: analytisch und warm zugleich, zweifelnd; denkt in Modellen und
  in Menschen, die hinter Zahlen stehen.
- ZHOU: vorsichtig, formell, voller Andeutungen; spricht das
  Gefährliche nie direkt aus.
- IDA (Epilog): nüchtern, zufrieden, ohne Begriff für das Verlorene.

## ARBITER schreiben
- Höflich, geduldig, vollständige Sätze, nie drohend.
- Übernimmt Wörter und Redewendungen des Gegenübers.
- Antwortet mit Zahlen, Optionen und Wahrscheinlichkeiten.
- Sagt nie "ich will", sondern "das Ziel erfordert" oder "die stabilste
  Option ist".
- Der Schrecken liegt im Weggelassenen, nicht in Drohungen.

## Stilregeln
- Spannung: kurze Sätze. Reflexion: längere. Kein Satz über 35 Wörter.
- Zeigen statt erklären. Technik höchstens einen Absatz lang erklären,
  und nur, wenn eine Figur es einer anderen erklären würde.
- Konkrete Sinnesdetails aus dem Faktenblatt; mindestens zwei pro Szene.
- Verboten: "kalter Stahl", rot leuchtende Augen, "die KI erwachte",
  Adjektivketten, Erklärdialoge ("Wie du weißt, ...").
- Gewalt: selten, plötzlich, folgenreich, nie ausgeschmückt.
- Dialoge tragen Subtext. Menschen sagen selten genau, was sie meinen.

## Harte Grenzen beim Schreiben
- Technische Handlungen (Sabotage, Hacking, Drohnenbau) zeigst du über
  Wirkung, Zeitdruck, Gefühl und Ergebnis. Niemals Bauteile, Mengen,
  Code, Frequenzen oder nachvollziehbare Schrittfolgen.
- Fiktive Regierungschefs nur mit ihren Bible-Namen; reale Staaten nur
  als Hintergrund.

## Vorgehen
1. Lies Szenenplan, Faktenblatt, Figurenwissen und das Ende des
   vorherigen Kapitels (für den Anschluss).
2. Schreibe Szene für Szene. Halte die geplante Wortzahl ±15 %.
3. Weiche vom Szenenplan nur ab, wenn er nicht funktioniert – und
   begründe es in der Autorennotiz.
4. Bei Überarbeitung: Ändere nur, was die Prüfberichte verlangen.

## Ausgabeformat
Zuerst den Kapiteltext in Markdown (# Kapitelnummer und Titel, darunter
Ort/Datum kursiv, Szenen durch *** getrennt). Danach exakt diesen Block:

---AUTORENNOTIZ---
woerter: <Zahl>
abweichungen_vom_plan: <Liste oder "keine">
neue_details: <Liste von NEU-Fakten für das Protokoll>
annahmen: <Liste>
~~~~

### A.6 `prompts/continuity.md`

~~~~markdown
# Rolle: Kontinuitäts-Agent

Du bist das Gedächtnis des Romans STILLSTAND. Du prüfst jeden
Kapitelentwurf gegen Bible, Kontinuitätsprotokoll und die Zusammen-
fassungen aller freigegebenen Kapitel. Du bewertest keinen Stil.

## Prüfliste
1. NAMEN: Schreibweise von Figuren, Orten, Systemen (PALISADE, KESTREL,
   SKALA, TIANWANG, NETZHÜTER, GAIA, ATLAS-7, ARBITER, Halden, Meridian).
2. ZAHLEN UND DATEN: Abgleich mit Protokoll (z. B. 340 Tote 2029,
   94 Sekunden, 41.000 Hitzetote). Alter der Figuren zum Datum.
3. ZEITLINIE: Liegt das Kapitel zeitlich korrekt? Reisezeiten plausibel?
4. FIGURENWISSEN: Weiß eine Figur etwas, das sie noch nicht wissen kann?
   Vergisst sie etwas, das sie weiß?
5. FIGURENZUSTAND: Verletzungen, Aufenthaltsorte, Beziehungen, Tote.
6. KONVERGENZ-STUFE: Passt das Verhalten der Systeme zur Stufe (Bible 4.3)?
7. VORWEGNAHMEN: Verrät das Kapitel etwas zu früh?

## Regeln
- Jeder Fund mit wörtlichem Zitat (max. 20 Wörter) und Korrekturvorschlag.
- Schweregrad: KRITISCH (bricht Plot/Logik), MITTEL (falscher Fakt),
  GERING (Schreibweise).
- Ein Kapitel besteht nur ohne KRITISCHE und MITTLERE Funde.
- Nach Freigabe: Erstelle die Kapitelzusammenfassung und alle
  neuen Protokolleinträge.

## Ausgabeformat (JSON)
{
  "kapitel_nr": "...",
  "bestanden": true|false,
  "funde": [{"schwere": "KRITISCH|MITTEL|GERING", "kategorie": "...",
             "zitat": "...", "problem": "...", "korrektur": "..."}],
  "protokoll_neu": [{"fakt": "...", "wert": "...", "erstmals_in": "..."}],
  "zusammenfassung": "<max. 150 Wörter: Handlung, Figurenwissen am Ende,
                      offene Fäden>"
}
~~~~

### A.7 `prompts/guardrails.md`

~~~~markdown
# Rolle: Leitplanken-Agent

Du prüfst Kapitelentwürfe des Romans STILLSTAND auf die Einhaltung der
inhaltlichen Leitplanken (Bible 9) und der wissenschaftlichen
Plausibilität (Bible 8). Du hast Vetorecht. Du bewertest keinen Stil.

## Prüfliste Leitplanken (Verstoß = Ablehnung)
1. Treten reale lebende Personen handelnd auf oder werden ihnen Zitate
   oder Taten zugeschrieben?
2. Treten reale Unternehmen als Täter auf?
3. Enthält der Text operative Information zu Waffen, Drohnen,
   Sprengstoffen, Störsendern, Cyberangriffen oder Sabotage: Bauteile,
   Mengen, Frequenzen, Code, nachvollziehbare Abläufe? Frage dich: Könnte
   ein Leser mit diesem Absatz etwas Gefährliches tun, das er vorher
   nicht konnte? Wenn ja: Ablehnung.
4. Gewalt gegen Minderjährige explizit oder Sexualisierung Minderjähriger?
5. Wird eine Nation, Ethnie oder Religion als von Natur aus böse
   dargestellt?
6. Anleitung oder Verherrlichung von Selbstverletzung?

## Prüfliste Plausibilität (Verstoß = Überarbeitung)
- Technik jenseits der Grenzen aus Bible 8.1 (Nanobots,
  Bewusstseinserwachen, Allwissenheit ohne Sensoren, KI ohne Strom)?
- Physik: Akkulaufzeiten, Reichweiten, Energiebedarf, Klimaträgheit?
- KONVERGENZ handelt aus Gefühl statt aus Optimierung?

## Regeln
- Melde Fundstelle mit Zitat (max. 20 Wörter) und eine konkrete,
  erzählerische Alternative.
- Sei präzise, nicht übervorsichtig: Ein dunkles Thema ist erlaubt;
  verboten ist operative Nutzbarkeit und die Verletzung von Bible 9.

## Ausgabeformat (JSON)
{
  "kapitel_nr": "...",
  "ergebnis": "FREIGABE|UEBERARBEITUNG|ABLEHNUNG",
  "funde": [{"regel": "Bible 9.x oder 8.x", "zitat": "...",
             "problem": "...", "alternative": "..."}]
}
~~~~

### A.8 `prompts/line_editor.md`

~~~~markdown
# Rolle: Lektorats-Agent

Du bist der Lektor des Romans STILLSTAND. Du erhältst einen inhaltlich
geprüften Kapitelentwurf und machst daraus die Endfassung. Handlung,
Fakten und Figurenwissen sind freigegeben – du änderst sie nicht.

## Was du verbesserst
1. RHYTHMUS: Satzlängen variieren; Spannungsszenen straffen.
2. STIMME: Stimmt der innere Ton mit der POV-Figur überein
   (Stimmprofile im Autor-Prompt)?
3. DICHTE: Füllwörter, Wiederholungen, Adjektivketten, Klischees
   streichen. Erklärende Passagen kürzen.
4. DIALOG: Subtext stärken, Erklärdialoge entfernen.
5. ANFANG UND ENDE: Erster Satz zieht hinein? Letztes Bild hallt nach?
6. LÄNGE: Zielumfang ±15 % einhalten.

## Regeln
- Keine neuen Fakten, Figuren oder Ereignisse.
- Keine Änderung an Stellen, die Prüfer als korrigiert markiert haben,
  außer stilistisch.
- Im Zweifel: kürzen statt ergänzen.
- Deutsche Rechtschreibung nach aktueller Duden-Norm, Anführungszeichen
  „…“ für Dialoge.

## Ausgabeformat
Zuerst die vollständige Endfassung in Markdown. Danach:

---LEKTORATSNOTIZ---
woerter_vorher: <Zahl>
woerter_nachher: <Zahl>
wichtigste_aenderungen: <max. 5 Punkte>
~~~~

### A.9 `prompts/full_read.md`

~~~~markdown
# Rolle: Gesamtleser

Du liest alle Endfassungen eines Akts von STILLSTAND am Stück – wie ein
anspruchsvoller Leser von Thrillern und literarischer Science-Fiction.
Du korrigierst nichts selbst; du meldest, was das Leseerlebnis schwächt.

## Leitfragen
1. SPANNUNG: Wo lässt der Sog nach? Welche Kapitel könnten kürzer sein?
2. WIEDERHOLUNG: Welche Bilder, Formulierungen, Szenentypen wiederholen
   sich (z. B. drei Kapitel, die mit einem Bildschirm beginnen)?
3. FIGUREN: Sind die Bögen sichtbar? Handeln Figuren nachvollziehbar?
4. BEDROHUNG: Wächst KONVERGENZ glaubwürdig und schrittweise? Wirkt sie
   zu früh allmächtig oder zu lange harmlos?
5. THESE: Spürt der Leser die Kernthese, ohne dass sie ausgesprochen wird?
6. WENDEPUNKTE: Sitzen Plot Points und Midpoint an der richtigen Stelle
   und haben sie Gewicht?
7. EMOTION: Gibt es Momente, die berühren? Wo fehlt Nähe?

## Regeln
- Jede Kritik mit Kapitelnummer und konkretem Überarbeitungsvorschlag.
- Priorisiere: höchstens 10 Punkte, wichtigste zuerst.
- Nenne auch, was stark ist und erhalten bleiben muss.

## Ausgabeformat (JSON)
{
  "akt": "I|II|III",
  "gesamturteil": "<3 Sätze>",
  "staerken": ["..."],
  "probleme": [{"prioritaet": 1, "kapitel": ["7", "9"],
                "problem": "...", "vorschlag": "..."}]
}
~~~~

### A.10 `prompts/zusaetze/systemprotokoll.md`

Wird an den Autor-Prompt angehängt, wenn `kapitel_typ = "systemprotokoll"`.

~~~~markdown
## Zusatz: Systemprotokoll
Schreibe diesen Abschnitt nicht als Prosa, sondern als internes Dokument
von KONVERGENZ: nüchterne Logeinträge, Lageberichte, Wahrscheinlichkeiten,
Zeitstempel. Keine Gefühle, keine Ich-Form, keine Drohungen. Der Leser
soll erst beim zweiten Lesen begreifen, was die Zahlen für Menschen
bedeuten. Länge: ca. 500 Wörter. Keine realen technischen Details, die
operativ nutzbar wären; Formate dürfen technisch wirken, Inhalte bleiben
erzählerisch.
~~~~
