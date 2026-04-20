"""Manage the family profile in memory and in JSON state."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from trippy.memory.store import MemoryStore
from trippy.models.profile import FamilyProfile, TravelerProfile
from trippy.models.trip import Traveler

logger = logging.getLogger(__name__)

_PROFILE_KEY = "profile:family"


class ProfileManager:
    """Load, update, and persist the family profile."""

    def __init__(self, memory: MemoryStore, profile_path: Path | None = None) -> None:
        self._memory = memory
        self._profile_path = profile_path

    def load(self) -> FamilyProfile:
        entry = self._memory.get(_PROFILE_KEY)
        if entry is not None:
            try:
                return FamilyProfile.model_validate(entry.value)
            except Exception as exc:
                logger.warning("Failed to parse profile from memory: %s", exc)
        if self._profile_path and self._profile_path.exists():
            raw = json.loads(self._profile_path.read_text(encoding="utf-8"))
            return FamilyProfile.model_validate(raw)
        return FamilyProfile()  # default Chapman profile

    def save(self, profile: FamilyProfile) -> None:
        self._memory.set(
            key=_PROFILE_KEY,
            value=profile.model_dump(mode="json"),
            category="profile",
            confidence=1.0,
            source="profile_manager",
        )
        if self._profile_path:
            self._profile_path.parent.mkdir(parents=True, exist_ok=True)
            self._profile_path.write_text(
                profile.model_dump_json(indent=2), encoding="utf-8"
            )

    def update_from_trip_travelers(
        self, trip_travelers: list[Traveler], profile: FamilyProfile | None = None
    ) -> FamilyProfile:
        """Merge traveler data from a canonical trip into the family profile."""
        if profile is None:
            profile = self.load()

        for tv in trip_travelers:
            existing = profile.get_traveler(tv.name)
            if existing is None:
                profile.travelers.append(
                    TravelerProfile(
                        name=tv.name,
                        passport_country=tv.passport_country,
                        passport_expiry=tv.passport_expiry,
                        date_of_birth=tv.date_of_birth,
                        is_minor=tv.is_minor,
                    )
                )
                logger.info("Added traveler %r to family profile", tv.name)
            else:
                # Update passport details if we have newer info
                if tv.passport_expiry and (
                    existing.passport_expiry is None
                    or tv.passport_expiry > existing.passport_expiry
                ):
                    existing.passport_expiry = tv.passport_expiry
                if tv.passport_country and not existing.passport_country:
                    existing.passport_country = tv.passport_country

        self.save(profile)
        return profile

    def check_passport_validity(
        self, profile: FamilyProfile, trip_end: date, buffer_months: int = 6
    ) -> list[str]:
        """Return names of travelers whose passports won't be valid for the trip."""
        issues: list[str] = []
        for t in profile.travelers:
            if not t.passport_valid_for_trip(trip_end, buffer_months):
                expiry_str = str(t.passport_expiry) if t.passport_expiry else "unknown"
                issues.append(
                    f"{t.name}: passport expires {expiry_str} "
                    f"(need valid until {buffer_months}mo after {trip_end})"
                )
        return issues
