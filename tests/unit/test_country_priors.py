"""Tests for historical country-level travel priors."""

from __future__ import annotations

from pathlib import Path

from trippy.memory.store import MemoryStore
from trippy.models.country_priors import CountryPriorBand
from trippy.services.country_priors import CountryPriorService


def test_country_priors_capture_high_and_caution_examples() -> None:
    service = CountryPriorService()

    greece = service.fit_for_country("Greece")
    usa = service.fit_for_country("United States")
    mexico = service.fit_for_country("Mexico")

    assert greece is not None
    assert greece.band == CountryPriorBand.STRONG_POSITIVE
    assert "food" in greece.positive_signals
    assert usa is not None
    assert usa.band == CountryPriorBand.CAUTION
    assert "safety/comfort concern" in usa.caution_signals
    assert mexico is not None
    assert mexico.band == CountryPriorBand.MIXED
    assert "safety varies by region" in mexico.caution_signals


def test_country_prior_text_matching_and_review_gated_proposals(tmp_path: Path) -> None:
    memory_path = tmp_path / "memory.json"
    service = CountryPriorService()

    matches = service.fit_for_text("Japan and Thailand food trip")
    proposals = service.propose_memory_updates(
        learning_dir=tmp_path / "learning",
        memory_path=memory_path,
        countries=["Japan"],
    )

    assert {match.country for match in matches} == {"Japan", "Thailand"}
    assert len(proposals) == 1
    assert proposals[0].after["key"] == "country_prior:japan"
    assert not MemoryStore(memory_path).all_entries()
