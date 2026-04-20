"""Tests for the JSON-backed MemoryStore."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trippy.memory.store import MemoryStore


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path / "memory.json")


class TestMemoryStoreCRUD:
    def test_set_and_get(self, store: MemoryStore) -> None:
        store.set("pref:departure", "07:00", category="preference")
        entry = store.get("pref:departure")
        assert entry is not None
        assert entry.value == "07:00"
        assert entry.category == "preference"

    def test_get_value_default(self, store: MemoryStore) -> None:
        assert store.get_value("nonexistent", default="fallback") == "fallback"

    def test_upsert_bumps_version(self, store: MemoryStore) -> None:
        store.set("pref:k", "v1", category="preference")
        store.set("pref:k", "v2", category="preference")
        entry = store.get("pref:k")
        assert entry is not None
        assert entry.value == "v2"
        assert entry.version == 2

    def test_upsert_updates_confidence(self, store: MemoryStore) -> None:
        store.set("pref:k", "v1", category="preference", confidence=0.5)
        store.set("pref:k", "v2", category="preference", confidence=0.9)
        assert store.get("pref:k").confidence == pytest.approx(0.9)  # type: ignore[union-attr]

    def test_delete(self, store: MemoryStore) -> None:
        store.set("pref:k", "v", category="preference")
        assert store.delete("pref:k") is True
        assert store.get("pref:k") is None
        assert store.delete("pref:k") is False  # idempotent

    def test_invalid_category_raises(self, store: MemoryStore) -> None:
        with pytest.raises(ValueError, match="Unknown category"):
            store.set("k", "v", category="invalid_cat")

    def test_list_by_category(self, store: MemoryStore) -> None:
        store.set("pref:a", "v1", category="preference")
        store.set("pref:b", "v2", category="preference")
        store.set("hint:x", "h1", category="skill_hint")
        prefs = store.list_by_category("preference")
        assert len(prefs) == 2
        hints = store.list_by_category("skill_hint")
        assert len(hints) == 1

    def test_complex_value(self, store: MemoryStore) -> None:
        val = {"time": "07:00", "evidence": "3 trips", "confidence": 0.8}
        store.set("pref:complex", val, category="preference")
        entry = store.get("pref:complex")
        assert entry is not None
        assert entry.value["time"] == "07:00"


class TestMemoryStorePersistence:
    def test_persists_to_disk(self, tmp_path: Path) -> None:
        path = tmp_path / "mem.json"
        s = MemoryStore(path)
        s.set("pref:key", "hello", category="preference")
        assert path.exists()

    def test_loads_from_disk(self, tmp_path: Path) -> None:
        path = tmp_path / "mem.json"
        s1 = MemoryStore(path)
        s1.set("pref:key", "hello", category="preference", confidence=0.8)

        s2 = MemoryStore(path)
        entry = s2.get("pref:key")
        assert entry is not None
        assert entry.value == "hello"
        assert entry.confidence == pytest.approx(0.8)

    def test_corrupt_file_starts_fresh(self, tmp_path: Path) -> None:
        path = tmp_path / "mem.json"
        path.write_text("not valid json", encoding="utf-8")
        store = MemoryStore(path)
        assert store.all_entries() == []

    def test_version_preserved_across_reload(self, tmp_path: Path) -> None:
        path = tmp_path / "mem.json"
        s1 = MemoryStore(path)
        s1.set("k", "v1", category="preference")
        s1.set("k", "v2", category="preference")

        s2 = MemoryStore(path)
        assert s2.get("k").version == 2  # type: ignore[union-attr]


class TestContextString:
    def test_empty_store(self, store: MemoryStore) -> None:
        assert store.to_context_string() == ""

    def test_renders_entries(self, store: MemoryStore) -> None:
        store.set("pref:departure", "07:00", category="preference")
        store.set("hint:japan", "JR Pass needed", category="skill_hint")
        ctx = store.to_context_string()
        assert "pref:departure" in ctx
        assert "07:00" in ctx
        assert "hint:japan" in ctx

    def test_category_filter(self, store: MemoryStore) -> None:
        store.set("pref:a", "v", category="preference")
        store.set("hint:b", "v", category="skill_hint")
        ctx = store.to_context_string(category="preference")
        assert "pref:a" in ctx
        assert "hint:b" not in ctx

    def test_low_confidence_annotated(self, store: MemoryStore) -> None:
        store.set("pref:uncertain", "maybe", category="preference", confidence=0.6)
        ctx = store.to_context_string()
        assert "conf=60%" in ctx
