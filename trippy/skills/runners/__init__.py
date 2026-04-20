"""Skill runner protocol and registry."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SkillRunner(Protocol):
    """Protocol that all skill runners must implement."""

    skill_name: str

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Execute the skill with the given inputs, return structured outputs."""
        ...
