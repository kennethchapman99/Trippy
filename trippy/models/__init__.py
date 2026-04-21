"""Canonical Pydantic models — source of truth for trip state."""

from trippy.models.dashboard import (
    DashboardIdeaTile,
    DashboardLink,
    DashboardTripTile,
    TravelDashboard,
)
from trippy.models.ideas import TripComparison, TripConcept, TripIdeaRequest
from trippy.models.intelligence import (
    EvidenceRef,
    EvidenceSourceType,
    IntelligenceCategory,
    PreferenceSignal,
    TravelIntelligenceReport,
)
from trippy.models.maps import MapPin, MapPinCategory, MapRoute, MapRouteMode, TripMapArtifact
from trippy.models.preferences import (
    DepartureTimePreference,
    FamilyTravelPreferences,
    LayoverPreference,
    TransferPreference,
)
from trippy.models.profile import FamilyProfile, TravelerProfile
from trippy.models.retrospective import TripRetrospectiveInput, TripRetrospectiveResult
from trippy.models.sources import (
    SourceAccessMode,
    SourceConfidence,
    SourcePlan,
    SourceRole,
    TravelSource,
    TravelSourceCategory,
)
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
    "DashboardIdeaTile",
    "DashboardLink",
    "DashboardTripTile",
    "DepartureTimePreference",
    "EvidenceRef",
    "EvidenceSourceType",
    "FamilyProfile",
    "FamilyTravelPreferences",
    "IntelligenceCategory",
    "LayoverPreference",
    "MapPin",
    "MapPinCategory",
    "MapRoute",
    "MapRouteMode",
    "PreferenceSignal",
    "RiskFlag",
    "RiskSeverity",
    "Segment",
    "SegmentType",
    "Stay",
    "StayType",
    "SyncMetadata",
    "SourceAccessMode",
    "SourceConfidence",
    "SourcePlan",
    "SourceRole",
    "TransferPreference",
    "Traveler",
    "TravelerProfile",
    "TravelDashboard",
    "TravelIntelligenceReport",
    "TravelSource",
    "TravelSourceCategory",
    "Trip",
    "TripComparison",
    "TripConcept",
    "TripIdeaRequest",
    "TripMapArtifact",
    "TripRetrospectiveInput",
    "TripRetrospectiveResult",
    "TripStatus",
]
