"""Gemeinsame Parser-Bausteine: JSON aus Modellantworten, Trennblöcke, Wortzählung."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError

THINK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)
FENCE_RE = re.compile(r"```(?:json|JSON)?\s*\n(.*?)\n?```", re.S)
WORD_RE = re.compile(r"[0-9A-Za-zÄÖÜäöüßÀ-ÿ]+(?:[-'’][0-9A-Za-zÄÖÜäöüßÀ-ÿ]+)*")


class OutputFormatError(ValueError):
    """Modellantwort entspricht nicht dem Ausgabeformat. `kind` = json | format."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def strip_think(raw: str) -> str:
    """Entfernt defensiv <think>…</think>-Blöcke (Denkmodus lokaler Modelle)."""
    text = THINK_RE.sub("", raw)
    # unvollständiger Denkblock am Anfang
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    return text.strip()


def count_words(text: str) -> int:
    """Zählt Wörter selbst – die vom Modell gemeldete Zahl wird nicht vertraut."""
    return len(WORD_RE.findall(text))


def _balanced_object(text: str) -> str | None:
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        start = text.find("{", start + 1)
    return None


def extract_json(raw: str) -> Any:
    text = strip_think(raw)
    candidates: list[str] = [text]
    candidates += [m.group(1) for m in FENCE_RE.finditer(text)]
    obj = _balanced_object(text)
    if obj:
        candidates.append(obj)
    last_err = "keine JSON-Struktur gefunden"
    for cand in candidates:
        try:
            return json.loads(cand)
        except json.JSONDecodeError as e:
            last_err = f"{e.msg} (Zeile {e.lineno}, Spalte {e.colno})"
    raise OutputFormatError("json", f"Ungültiges JSON: {last_err}")


def _validation_message(e: ValidationError) -> str:
    parts = []
    for err in e.errors()[:10]:
        loc = ".".join(str(x) for x in err["loc"]) or "<wurzel>"
        parts.append(f"- {loc}: {err['msg']}")
    return "\n".join(parts)


def parse_json_as[T: BaseModel](model: type[T], raw: str) -> T:
    data = extract_json(raw)
    try:
        return model.model_validate(data)
    except ValidationError as e:
        raise OutputFormatError("json", "Schemaverletzung:\n" + _validation_message(e)) from e


def parse_json_adapter(adapter: TypeAdapter[Any], raw: str) -> Any:
    data = extract_json(raw)
    try:
        return adapter.validate_python(data)
    except ValidationError as e:
        raise OutputFormatError("json", "Schemaverletzung:\n" + _validation_message(e)) from e


def split_marker(raw: str, marker: str) -> tuple[str, str]:
    """Trennt Text und Notizblock. Fehlender Trennblock = ungültige Ausgabe."""
    text = strip_think(raw)
    if marker not in text:
        raise OutputFormatError("format", f"Trennblock '{marker}' fehlt")
    body, _, notiz = text.rpartition(marker)
    body = (
        FENCE_RE.sub(lambda m: m.group(1), body).strip()
        if body.lstrip().startswith("```")
        else body.strip()
    )
    if not body:
        raise OutputFormatError("format", f"Kein Text vor '{marker}'")
    return body, notiz.strip()


def parse_kv_block(block: str, keys: list[str]) -> dict[str, str]:
    """Schlüssel-Wert-Format; Folgezeilen (z. B. '- Punkt') gehören zum letzten Schlüssel."""
    out: dict[str, str] = {}
    current: str | None = None
    key_re = re.compile(
        r"^\s*[-*]?\s*\**(" + "|".join(map(re.escape, keys)) + r")\**\s*:\s*(.*)$", re.I
    )
    for line in block.splitlines():
        m = key_re.match(line)
        if m:
            current = m.group(1).lower()
            out[current] = m.group(2).strip()
        elif current and line.strip():
            out[current] = (out[current] + "\n" + line.strip()).strip()
    return out


def as_list(value: str | None) -> list[str]:
    if value is None:
        return []
    v = value.strip()
    if not v or v.lower() in ("keine", "keine.", "-", "—", "[]", "none"):
        return []
    if v.startswith("["):
        try:
            data = json.loads(v)
            if isinstance(data, list):
                return [str(x) for x in data]
        except json.JSONDecodeError:
            pass
    items = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip() for line in v.splitlines()]
    items = [i for i in items if i]
    if len(items) == 1 and ";" in items[0]:
        items = [i.strip() for i in items[0].split(";") if i.strip()]
    return items


def as_int(value: str | None) -> int | None:
    if not value:
        return None
    m = re.search(r"\d[\d.]*", value)
    return int(m.group(0).replace(".", "")) if m else None
