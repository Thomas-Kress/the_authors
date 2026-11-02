from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from roman_agenten.cli import app, bible_geruest
from roman_agenten.store.bible_loader import parse_bible
from roman_agenten.store.bible_validator import PFLICHT_UNTERABSCHNITTE

REPO = Path(__file__).resolve().parents[1]
runner = CliRunner()


@pytest.fixture
def env(projects_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ROMAN_ENV_FILE", str(REPO / ".env.example.test"))
    monkeypatch.setenv("PROJECTS_DIR", str(projects_dir))
    monkeypatch.setenv("PROMPTS_DIR", str(REPO / "prompts"))
    monkeypatch.setenv("LOG_PAYLOADS", "false")
    return projects_dir


def test_bible_check_ok(env: Path) -> None:
    r = runner.invoke(app, ["bible", "check", "dummy_projekt"])
    assert r.exit_code == 0, r.output
    assert "4 Kapitel" in r.output


def test_bible_check_listet_alle_fehler(env: Path) -> None:
    b = env / "dummy_projekt" / "bible" / "bible.md"
    b.write_text(
        b.read_text().replace("### 8.3 Wetter\n", "").replace("| 2 | Trockenheit", "| x | T")
    )
    r = runner.invoke(app, ["bible", "check", "dummy_projekt"])
    assert r.exit_code == 1
    assert "8.3" in r.output and "'x'" in r.output


def test_init_legt_geruest_an(env: Path) -> None:
    r = runner.invoke(app, ["init", "neu"])
    assert r.exit_code == 0, r.output
    assert (env / "neu" / "bible" / "bible.md").is_file()
    assert (env / "neu" / "project.yaml").is_file()


def test_geruest_hat_alle_pflichtueberschriften() -> None:
    b = parse_bible(bible_geruest())
    assert all(b.has(str(i)) for i in range(11))
    assert all(b.has(s) for s in PFLICHT_UNTERABSCHNITTE)


def test_prompt_dry_run(env: Path) -> None:
    r = runner.invoke(
        app,
        ["prompt", "chapter_writer", "--projekt", "dummy_projekt", "--kapitel", "1", "--dry-run"],
    )
    assert r.exit_code == 0, r.output
    assert (
        "===== SYSTEM =====" in r.output
        and "# Rolle: Kapitel-Autor" in r.output
        and "Tokens" in r.output
    )
    assert "{{" not in r.output


def test_schemas_export(tmp_path: Path) -> None:
    r = runner.invoke(app, ["schemas", "--export", "--out", str(tmp_path)])
    assert r.exit_code == 0
    assert (tmp_path / "KapitelBrief.json").is_file()


def test_status_ohne_lauf(env: Path) -> None:
    r = runner.invoke(app, ["status", "dummy_projekt"])
    assert r.exit_code == 0, r.output
    assert "Trockenheit" in r.output
