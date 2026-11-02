"""Strukturierte JSONL-Logs pro Projekt (§10). Kein Prompt-/Antworttext im Standard-Log;
Geheimwerte werden vor jedem Schreiben geschwärzt."""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from roman_agenten.config import Settings

log = logging.getLogger("roman_agenten")
REDACTED = "***"


def new_id() -> str:
    return uuid.uuid4().hex[:16]


class RedactingFilter(logging.Filter):
    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self.secrets = [s for s in secrets if s]

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for s in self.secrets:
            msg = msg.replace(s, REDACTED)
        record.msg, record.args = msg, None
        return True


class _StderrHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """Schreibt immer auf das aktuelle sys.stderr (robust gegen umgeleitete Streams)."""

    @property
    def stream(self) -> Any:
        return sys.stderr

    @stream.setter
    def stream(self, _value: Any) -> None:
        pass


def setup_logging(settings: Settings) -> None:
    root = logging.getLogger("roman_agenten")
    root.setLevel(settings.log_level.upper())
    if not root.handlers:
        handler = _StderrHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
    for h in root.handlers:
        h.filters = [f for f in h.filters if not isinstance(f, RedactingFilter)]
        h.addFilter(RedactingFilter(settings.secret_values()))


class RunLog:
    """Schreibt `state/run.log.jsonl` und `state/usage.jsonl` eines Projekts."""

    def __init__(
        self, state_dir: Path | None, settings: Settings, trace_id: str | None = None
    ) -> None:
        self.state_dir = state_dir
        self.settings = settings
        self.trace_id = trace_id or new_id()
        self._secrets = settings.secret_values()

    def _redact(self, text: str) -> str:
        for s in self._secrets:
            text = text.replace(s, REDACTED)
        return text

    def _append(self, name: str, record: dict[str, Any]) -> None:
        if self.state_dir is None:
            return
        self.state_dir.mkdir(parents=True, exist_ok=True)
        line = self._redact(json.dumps(record, ensure_ascii=False, default=str))
        with (self.state_dir / name).open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def event(self, ereignis: str, **fields: Any) -> None:
        self._append(
            "run.log.jsonl",
            {"ts": time.time(), "trace_id": self.trace_id, "ereignis": ereignis, **fields},
        )

    def usage(self, **fields: Any) -> None:
        self._append("usage.jsonl", {"ts": time.time(), "trace_id": self.trace_id, **fields})

    def payload(self, span_id: str, data: dict[str, Any]) -> None:
        if not self.settings.log_payloads or self.state_dir is None:
            return
        d = self.state_dir / "payloads"
        d.mkdir(parents=True, exist_ok=True)
        text = self._redact(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        (d / f"{self.trace_id}_{span_id}.json").write_text(text, encoding="utf-8")

    def total_cost(self) -> float:
        if self.state_dir is None or not (self.state_dir / "usage.jsonl").exists():
            return 0.0
        total = 0.0
        for line in (self.state_dir / "usage.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                total += float(json.loads(line).get("kosten_usd", 0.0))
        return total
