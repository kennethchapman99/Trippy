"""Canonical Pydantic models — source of truth for trip state."""

from trippy.models.preferences import (
    DepartureTimePreference,
    FamilyTravelPreferences,
    LayoverPreference,
    TransferPreference,
)
from trippy.models.profile import FamilyProfile, TravelerProfile
from trippy.models.trip import (
    Budget,
    ChecklistItem,
    Confirmation,
    RiskFlag,
    RiskSeverity,
    Segment,
    SegmentType,
    Stay,
    StayType,
    SyncMetadata,
    Traveler,
    Trip,
    TripStatus,
)

__all__ = [
    "Budget",
    "ChecklistItem",
    "Confirmation",
    "DepartureTimePreference",
    "FamilyProfile",
    "FamilyTravelPreferences",
    "LayoverPreference",
    "RiskFlag",
    "RiskSeverity",
    "Segment",
    "SegmentType",
    "Stay",
    "StayType",
    "SyncMetadata",
    "TransferPreference",
    "Traveler",
    "TravelerProfile",
    "Trip",
    "TripStatus",
]
