"""Trippy domain MCP tools.

These tools expose narrow, safe Trippy product capabilities to Hermes.
Hermes should call these instead of reaching into app internals or using the
legacy custom agent router in ``trippy.agent``.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from trippy import config

logger = logging.getLogger(__name__)


def register_trippy_tools(mcp: FastMCP) -> None:
    """Register Trippy domain tools onto the given FastMCP instance."""

    @mcp.tool()
    def trippy_list_trips(status: str | None = None) -> dict[str, Any]:
        """List canonical Trippy trips.

        Args:
            status: Optional status filter such as planned, booked, completed, or idea.
        """
        from trippy.models.trip import TripStatus
        from trippy.services.trip_state import TripStateService

        svc = TripStateService()
        try:
            trips = svc.find_by_status(TripStatus(status)) if status else svc.load_all()
            return {"trips": [trip.summary() for trip in trips]}
        except Exception as exc:
            logger.exception("trippy_list_trips failed")
            return {"error": str(exc), "status": status}

    @mcp.tool()
    def trippy_get_trip(trip_id: str) -> dict[str, Any]:
        """Load canonical trip state by trip id."""
        from trippy.services.trip_state import TripStateService

        try:
            trip = TripStateService().load(trip_id)
            if trip is None:
                return {"error": "trip_not_found", "trip_id": trip_id}
            return trip.model_dump(mode="json")
        except Exception as exc:
            logger.exception("trippy_get_trip failed")
            return {"error": str(exc), "trip_id": trip_id}

    @mcp.tool()
    def trippy_create_intake(
        trip_name: str,
        destination: list[str],
        travel_window: str = "",
        duration_days: str | None = None,
        party_type: str = "whole_family",
        adults: int = 2,
        children: int = 3,
        goals: list[str] | None = None,
        avoidances: list[str] | None = None,
        trip_id: str = "",
    ) -> dict[str, Any]:
        """Create a Trippy trip intake through the deterministic intake service."""
        from trippy.models.trip_planning import (
            TravelWindow,
            TripIntake,
            TripIntakeMode,
            TripParty,
            TripPartyType,
        )
        from trippy.services.trip_intake import TripIntakeService

        try:
            normalized_party = party_type.strip().lower().replace("-", "_").replace(" ", "_")
            duration_payload: Any = duration_days
            intake = TripIntake(
                trip_id=trip_id,
                mode=TripIntakeMode.SELECTED_DESTINATION,
                trip_name=trip_name,
                destination_seeds=destination,
                travel_window=TravelWindow(label=travel_window or None),
                duration_days=duration_payload,
                travelers=adults + children,
                party=TripParty(
                    party_type=TripPartyType(normalized_party),
                    adults=adults,
                    children=children,
                    explicit=True,
                    defaulted_from_family_profile=False,
                ),
                goals=goals or [],
                avoidances=avoidances or [],
            )
            created = TripIntakeService().create(intake, overwrite=bool(trip_id))
            return created.model_dump(mode="json")
        except Exception as exc:
            logger.exception("trippy_create_intake failed")
            return {"error": str(exc), "trip_name": trip_name}

    @mcp.tool()
    def trippy_build_flight_shortlist(
        trip_id: str,
        validate_live: bool = False,
        deep_research: bool = False,
        adapter: str = "auto",
    ) -> dict[str, Any]:
        """Build source-linked flight recommendations for a trip."""
        from trippy.services.flight_shortlist import FlightShortlistService

        try:
            result = FlightShortlistService().build(
                trip_id,
                validate_live=validate_live,
                deep_research=deep_research,
                adapter_mode=adapter,
            )
            return result.model_dump(mode="json")
        except Exception as exc:
            logger.exception("trippy_build_flight_shortlist failed")
            return {"error": str(exc), "trip_id": trip_id}

    @mcp.tool()
    def trippy_build_lodging_shortlist(
        trip_id: str,
        validate_live: bool = False,
        deep_research: bool = False,
        adapter: str = "auto",
    ) -> dict[str, Any]:
        """Build family-fit lodging recommendations for a trip."""
        from trippy.services.lodging_shortlist import LodgingShortlistService

        try:
            result = LodgingShortlistService().build(
                trip_id,
                validate_live=validate_live,
                deep_research=deep_research,
                adapter_mode=adapter,
            )
            return result.model_dump(mode="json")
        except Exception as exc:
            logger.exception("trippy_build_lodging_shortlist failed")
            return {"error": str(exc), "trip_id": trip_id}

    @mcp.tool()
    def trippy_build_car_shortlist(
        trip_id: str,
        validate_live: bool = False,
        deep_research: bool = False,
        adapter: str = "auto",
    ) -> dict[str, Any]:
        """Build car rental recommendations for a trip."""
        from trippy.services.car_shortlist import CarShortlistService

        try:
            result = CarShortlistService().build(
                trip_id,
                validate_live=validate_live,
                deep_research=deep_research,
                adapter_mode=adapter,
            )
            return result.model_dump(mode="json")
        except Exception as exc:
            logger.exception("trippy_build_car_shortlist failed")
            return {"error": str(exc), "trip_id": trip_id}

    @mcp.tool()
    def trippy_build_activity_shortlist(
        trip_id: str,
        validate_live: bool = False,
        deep_research: bool = False,
        adapter: str = "auto",
    ) -> dict[str, Any]:
        """Build activity and tour recommendations for a trip."""
        from trippy.services.activity_shortlist import ActivityShortlistService

        try:
            result = ActivityShortlistService().build(
                trip_id,
                validate_live=validate_live,
                deep_research=deep_research,
                adapter_mode=adapter,
            )
            return result.model_dump(mode="json")
        except Exception as exc:
            logger.exception("trippy_build_activity_shortlist failed")
            return {"error": str(exc), "trip_id": trip_id}

    @mcp.tool()
    def trippy_run_friction_audit(trip_id: str) -> dict[str, Any]:
        """Run Trippy's deterministic friction audit for a trip."""
        from trippy.memory.store import MemoryStore
        from trippy.skills.runners.friction_audit import FrictionAuditRunner

        try:
            runner = FrictionAuditRunner(memory_store=MemoryStore(config.MEMORY_PATH))
            return runner.run({"trip_id": trip_id})
        except Exception as exc:
            logger.exception("trippy_run_friction_audit failed")
            return {"error": str(exc), "trip_id": trip_id}

    @mcp.tool()
    def trippy_sync_trip_sheet(trip_id: str) -> dict[str, Any]:
        """Push canonical trip state to its linked Google Sheet."""
        from trippy.services.sheet_sync import SheetSyncService
        from trippy.services.trip_state import TripStateService

        try:
            trip = TripStateService().load(trip_id)
            if trip is None:
                return {"error": "trip_not_found", "trip_id": trip_id}
            if not trip.sync.google_sheet_id:
                return {"error": "missing_google_sheet_id", "trip_id": trip_id}
            SheetSyncService().push_trip_to_sheet(trip, trip.sync.google_sheet_id)
            return {"ok": True, "trip_id": trip_id, "spreadsheet_id": trip.sync.google_sheet_id}
        except Exception as exc:
            logger.exception("trippy_sync_trip_sheet failed")
            return {"error": str(exc), "trip_id": trip_id}

    @mcp.tool()
    def trippy_record_learning_event(
        workflow_id: str,
        rating: str,
        notes: str = "",
        correction: str = "",
        future_learning: bool = False,
    ) -> dict[str, Any]:
        """Record reviewed workflow feedback for the Trippy learning loop."""
        from trippy.services.learning import FeedbackRating, LearningEventStore, UserFeedback

        try:
            store = LearningEventStore(config.LEARNING_PATH, memory_path=config.MEMORY_PATH)
            proposals = store.add_feedback(
                UserFeedback(
                    workflow_id=workflow_id,
                    rating=FeedbackRating(rating),
                    notes=notes,
                    correction=correction or None,
                    future_learning=future_learning,
                )
            )
            return {"ok": True, "proposal_ids": [proposal.id for proposal in proposals]}
        except Exception as exc:
            logger.exception("trippy_record_learning_event failed")
            return {"error": str(exc), "workflow_id": workflow_id}

    @mcp.tool()
    def trippy_propose_skill_update(
        skill_name: str,
        summary: str,
        before: str = "",
        after: str = "",
    ) -> dict[str, Any]:
        """Create a review-gated skill update proposal.

        This records the proposed change only. It does not mutate Hermes or Trippy
        skill files directly.
        """
        from trippy.services.learning import LearningEventStore, LearningProposal, ProposalType

        try:
            store = LearningEventStore(config.LEARNING_PATH, memory_path=config.MEMORY_PATH)
            proposals = store.add_proposals(
                [
                    LearningProposal(
                        proposal_type=ProposalType.SKILL_PATCH,
                        summary=summary,
                        before={"skill_name": skill_name, "content": before},
                        after={"skill_name": skill_name, "content": after},
                    )
                ]
            )
            return {"ok": True, "proposal_ids": [proposal.id for proposal in proposals]}
        except Exception as exc:
            logger.exception("trippy_propose_skill_update failed")
            return {"error": str(exc), "skill_name": skill_name}
