"""Family and traveler profile models."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class TravelerProfile(BaseModel):
    name: str
    passport_country: str | None = None  # ISO alpha-3
    passport_expiry: date | None = None
    date_of_birth: date | None = None
    is_minor: bool = False
    dietary_notes: str | None = None
    accessibility_notes: str | None = None
    loyalty_numbers: dict[str, str] = Field(default_factory=dict)  # "AC" → "123456"
    known_tsa_precheck: bool = False
    known_nexus: bool = False
    known_global_entry: bool = False

    def passport_days_until_expiry(self, from_date: date | None = None) -> int | None:
        if not self.passport_expiry:
            return None
        ref = from_date or date.today()
        return (self.passport_expiry - ref).days

    def passport_valid_for_trip(self, trip_end: date, buffer_months: int = 6) -> bool:
        """Many countries require passport valid 6 months beyond trip end."""
        if not self.passport_expiry:
            return False
        from datetime import timedelta
        required_expiry = trip_end + timedelta(days=buffer_months * 30)
        return self.passport_expiry >= required_expiry


class FamilyProfile(BaseModel):
    family_name: str = "Chapman"
    home_city: str = "Oakville, Ontario, Canada"
    home_airport: str = "YYZ"
    alternate_airports: list[str] = Field(default_factory=lambda: ["YHM", "YTZ"])
    currency: str = "CAD"
    travelers: list[TravelerProfile] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def num_travelers(self) -> int:
        return len(self.travelers)

    @property
    def has_minors(self) -> bool:
        return any(t.is_minor for t in self.travelers)

    @property
    def minors(self) -> list[TravelerProfile]:
        return [t for t in self.travelers if t.is_minor]

    @property
    def adults(self) -> list[TravelerProfile]:
        return [t for t in self.travelers if not t.is_minor]

    def get_traveler(self, name: str) -> TravelerProfile | None:
        name_lower = name.lower()
        return next((t for t in self.travelers if t.name.lower() == name_lower), None)

    def passports_expiring_before(self, check_date: date) -> list[TravelerProfile]:
        return [
            t for t in self.travelers
            if t.passport_expiry and t.passport_expiry < check_date
        ]

    def to_context_string(self) -> str:
        lines = [
            f"## Family Profile: {self.family_name}",
            f"- Home: {self.home_city}",
            f"- Home airport: {self.home_airport}",
            f"- Party size: {self.num_travelers} ({len(self.adults)} adults, {len(self.minors)} minors)",
            "- Travelers:",
        ]
        for t in self.travelers:
            expiry = f" passport exp {t.passport_expiry}" if t.passport_expiry else ""
            minor_tag = " (minor)" if t.is_minor else ""
            lines.append(f"  · {t.name}{minor_tag}{expiry}")
        return "\n".join(lines)
