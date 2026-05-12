"""Small API-facing facade for canonical trip calendar operations.

This stays separate from the large local UI server so route wiring can remain thin:
GET /api/calendar should call calendar_payload(trip_id), while POST
/api/calendar/rebuild should call rebuild_calendar_payload(trip_id).
"""

from __future__ import annotations

from typing import Any

from trippy.services.trip_calendar import TripCalendarService
from trippy.services.trip_intake import TripIntakeService
from trippy.services.trip_planner import TripPlannerService


class TripCalendarFacade:
    """API-friendly wrapper around TripCalendarService."""

    def __init__(
        self,
        *,
        intake_service: TripIntakeService | None = None,
        planner_service: TripPlannerService | None = None,
        calendar_service: TripCalendarService | None = None,
    ) -> None:
        self._intakes = intake_service or TripIntakeService()
        self._planner = planner_service or TripPlannerService(self._intakes)
        self._calendar = calendar_service or TripCalendarService(
            intake_service=self._intakes,
            planner_service=self._planner,
        )

    def calendar_payload(self, trip_id: str) -> dict[str, Any]:
        """Return the current calendar, lazily creating it from intake if needed."""
        return self._calendar.ui_payload(trip_id)

    def rebuild_calendar_payload(self, trip_id: str) -> dict[str, Any]:
        """Rebuild the calendar from intake, selected flight state, and selected plan."""
        calendar = self._calendar.rebuild_from_current_state(trip_id)
        return {
            "trip_id": trip_id,
            "calendar": calendar.model_dump(mode="json"),
            "summary": {
                "status": calendar.status.value,
                "calendar_version": calendar.calendar_version,
                "date_dependency_hash": calendar.date_dependency_hash,
                "envelope_locked": calendar.envelope_locked,
                "trip_start_date": calendar.trip_envelope.trip_start_date,
                "trip_end_date": calendar.trip_envelope.trip_end_date,
                "trip_nights": calendar.trip_envelope.trip_nights,
                "stay_nights_total": calendar.stay_nights_total(),
                "booking_safe": calendar.integrity.booking_safe,
                "blocking_issues": calendar.integrity.blocking_issues,
                "warnings": calendar.integrity.warnings,
            },
        }
