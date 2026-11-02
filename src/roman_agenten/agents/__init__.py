"""Die acht Agentenmodule. Jedes hat `ROLE`, `JSON_MODE`, `build_messages`, `parse`."""

from __future__ import annotations

from types import ModuleType

from roman_agenten.agents import (
    chapter_writer,
    continuity,
    full_read,
    guardrails,
    line_editor,
    plot_architect,
    research,
    showrunner,
)
from roman_agenten.config import Role

AGENTS: dict[Role, ModuleType] = {
    m.ROLE: m
    for m in (
        showrunner,
        research,
        plot_architect,
        chapter_writer,
        continuity,
        guardrails,
        line_editor,
        full_read,
    )
}
