"""JSON-backed Hermes memory store.

Design principles:
- JSON file = inspectable, diffable, Git-friendly
- Structured by category, not free-form text
- Versioned entries track how preferences evolve
- to_context_string() renders memory for agent system prompt injection
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

VALID_CATEGORIES = frozenset({"preference", "profile", "skill_hint", "trip_insight"})


class MemoryEntry(BaseModel):
    key: str
    value: Any
    category: str
    confidence: float = 1.0  # 0.0–1.0; increases as evidence accumulates
    source: str = "agent"  # How this was learned
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    version: int = 1
    notes: str | None = None

    def bump(
        self,
        new_value: Any,
        source: str,
        confidence: float | None = None,
        notes: str | None = None,
    ) -> None:
        self.value = new_value
        self.source = source
        self.updated_at = datetime.utcnow()
        self.version += 1
        if confidence is not None:
            self.confidence = confidence
        if notes is not None:
            self.notes = notes


class _MemoryFile(BaseModel):
    version: str = "1.0"
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    entries: dict[str, MemoryEntry] = Field(default_factory=dict)


class MemoryStore:
    """Persistent, JSON-backed memory store for the Trippy Hermes agent.

    Thread-safety: not thread-safe; intended for single-agent, single-process use.
    """

    def __init__(self, store_path: Path) -> None:
        self.path = store_path
        self._data: _MemoryFile = _MemoryFile()
        if store_path.exists():
            self._load()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def set(
        self,
        key: str,
        value: Any,
        category: str,
        confidence: float = 1.0,
        source: str = "agent",
        notes: str | None = None,
    ) -> MemoryEntry:
        """Upsert a memory entry. Bumps version on update."""
        if category not in VALID_CATEGORIES:
            raise ValueError(f"Unknown category {category!r}. Use: {sorted(VALID_CATEGORIES)}")

        existing = self._data.entries.get(key)
        if existing is not None:
            existing.bump(value, source=source, confidence=confidence, notes=notes)
            entry = existing
        else:
            entry = MemoryEntry(
                key=key,
                value=value,
                category=category,
                confidence=confidence,
                source=source,
                notes=notes,
            )
            self._data.entries[key] = entry

        self._save()
        logger.debug("Memory set: %s (v%d, conf=%.2f)", key, entry.version, entry.confidence)
        return entry

    def get(self, key: str) -> MemoryEntry | None:
        return self._data.entries.get(key)

    def get_value(self, key: str, default: Any = None) -> Any:
        entry = self._data.entries.get(key)
        return entry.value if entry is not None else default

    def delete(self, key: str) -> bool:
        if key in self._data.entries:
            del self._data.entries[key]
            self._save()
            return True
        return False

    def list_by_category(self, category: str) -> list[MemoryEntry]:
        return [e for e in self._data.entries.values() if e.category == category]

    def all_entries(self) -> list[MemoryEntry]:
        return list(self._data.entries.values())

    # ------------------------------------------------------------------
    # Context rendering (for agent system prompt injection)
    # ------------------------------------------------------------------

    def to_context_string(self, category: str | None = None) -> str:
        """Render memory entries as readable text for agent context injection."""
        entries = self.list_by_category(category) if category else self.all_entries()
        if not entries:
            return ""

        # Sort by category then key
        entries_sorted = sorted(entries, key=lambda e: (e.category, e.key))

        sections: dict[str, list[str]] = {}
        for entry in entries_sorted:
            cat_label = entry.category.replace("_", " ").title()
            if cat_label not in sections:
                sections[cat_label] = []
            value_str = json.dumps(entry.value) if not isinstance(entry.value, str) else entry.value
            conf_str = f" (conf={entry.confidence:.0%})" if entry.confidence < 1.0 else ""
            sections[cat_label].append(f"  {entry.key}: {value_str}{conf_str}")

        lines = ["## Agent Memory"]
        for section, items in sections.items():
            lines.append(f"\n### {section}")
            lines.extend(items)

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._data = _MemoryFile.model_validate(raw)
            logger.debug("Loaded %d memory entries from %s", len(self._data.entries), self.path)
        except Exception as exc:
            logger.warning("Failed to load memory from %s: %s — starting fresh", self.path, exc)
            self._data = _MemoryFile()

    def _save(self) -> None:
        self._data.updated_at = datetime.utcnow()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            self._data.model_dump_json(indent=2),
            encoding="utf-8",
        )
