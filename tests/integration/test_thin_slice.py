"""
Thin-slice acceptance test — exercises the full pipeline.
Phases 0-2: stubs only. Becomes live from Phase 3 onward.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Phase 1 not yet implemented")
def test_import_sheet_creates_trip() -> None:
    """Phase 1: Import fixture sheet → trip created in DB."""


@pytest.mark.skip(reason="Phase 2 not yet implemented")
def test_confirmation_email_links_to_leg() -> None:
    """Phase 2: Feed mock confirmation email → leg linked."""


@pytest.mark.skip(reason="Phase 3 not yet implemented")
def test_trip_hub_show_japan() -> None:
    """Phase 3: Query trip hub 'show Japan' → structured summary."""


@pytest.mark.skip(reason="Phase 4 not yet implemented")
def test_visa_check_returns_expected_flags() -> None:
    """Phase 4: Run visa check → expected flags returned."""


@pytest.mark.skip(reason="Phase 5 not yet implemented")
def test_retro_extracts_preference() -> None:
    """Phase 5: Submit mock retro → preference extracted."""


@pytest.mark.skip(reason="Phase 6 not yet implemented")
def test_flight_search_respects_preference() -> None:
    """Phase 6: Flight search → results respect preference."""


@pytest.mark.skip(reason="Phase 7 not yet implemented")
def test_timeline_export_contains_trip() -> None:
    """Phase 7: Export timeline → HTML contains the trip."""
