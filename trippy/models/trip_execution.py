"""Trip execution and confirmation packet models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ExecutionCategory(StrEnum):
    FLIGHT = "flight"
    LODGING = "lodging"
    CAR = "car"
    ACTIVITY = "activity"
    OTHER = "other"


class ExecutionStatus(StrEnum):
    SELECTED = "selected"
    BOOKED = "booked"
    CONFIRMED = "confirmed"


class TripPacketItem(BaseModel):
    """A human-facing travel execution item.

    Shortlists decide what to choose. Packet items track what the family has
    selected, booked, confirmed, and needs on trip day.
    """

    item_id: str
    category: ExecutionCategory
    option_id: str = ""
    title: str
    provider: str = ""
    status: ExecutionStatus = ExecutionStatus.SELECTED
    source_url: str = ""
    booking_link: str = ""
    confirmation_code: str = ""
    date: str = ""
    start_time: str = ""
    end_time: str = ""
    address: str = ""
    cost_cad: float | None = None
    notes: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("title")
    @classmethod
    def _title_required(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("packet item title is required")
        return cleaned

    @property
    def is_booked(self) -> bool:
        return self.status in {ExecutionStatus.BOOKED, ExecutionStatus.CONFIRMED}

    @property
    def is_confirmed(self) -> bool:
        return self.status == ExecutionStatus.CONFIRMED and bool(self.confirmation_code.strip())


class TripPacketState(BaseModel):
    trip_id: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    readiness_percent: int = 0
    status_label: str = "not ready"
    items: list[TripPacketItem] = Field(default_factory=list)
    missing_items: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    summary: str = ""

    def get_item(
        self,
        category: ExecutionCategory,
        option_id: str,
    ) -> TripPacketItem | None:
        return next(
            (
                item
                for item in self.items
                if item.category == category and item.option_id == option_id
            ),
            None,
        )
