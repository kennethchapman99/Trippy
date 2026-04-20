"""Trippy Hermes skills — reusable travel planning workflows."""

from __future__ import annotations

from pathlib import Path

SKILLS_DIR = Path(__file__).parent / "definitions"
RUNNERS_DIR = Path(__file__).parent / "runners"

SKILL_NAMES = [
    "trippy-past-trip-miner",
    "trippy-preference-extractor",
    "trippy-trip-sheet-creator",
    "trippy-gmail-reconciler",
    "trippy-flight-friction-audit",
    "trippy-family-itinerary-builder",
]


def get_skill_definition(name: str) -> str:
    """Load a skill's markdown definition for agent context injection."""
    path = SKILLS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Skill definition not found: {path}")
    return path.read_text(encoding="utf-8")


def get_all_skill_summaries() -> str:
    """Return a concise summary of all skills for agent context."""
    lines = ["## Available Trippy Skills\n"]
    for name in SKILL_NAMES:
        path = SKILLS_DIR / f"{name}.md"
        if path.exists():
            content = path.read_text(encoding="utf-8")
            # Extract first two lines after the title
            skill_lines = [line for line in content.splitlines() if line.strip()]
            desc = skill_lines[2] if len(skill_lines) > 2 else ""
            lines.append(f"- **{name}**: {desc}")
    return "\n".join(lines)
