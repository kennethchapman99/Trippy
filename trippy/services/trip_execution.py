"""Trip packet and booking confirmation state."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from trippy import config
from trippy.models.shortlists import ResearchShortlistState, ShortlistCategory, ShortlistRowStatus
from trippy.models.trip_execution import (
    ExecutionCategory,
    ExecutionStatus,
    TripPacketItem,
    TripPacketState,
)
from trippy.services.shortlist_store import ShortlistStore


class TripExecutionService:
    """Build and persist the trip-ready execution packet.

    This service intentionally does not book anything. It tracks the human's
    selected, booked, and confirmed items so the rest of Trippy can produce a
    truthful timeline, sheet, map, and concierge packet.
    """

    def __init__(
        self,
        *,
        packet_dir: Path | None = None,
        shortlist_store: ShortlistStore | None = None,
    ) -> None:
        self._dir = packet_dir or config.WORKSPACES_PATH / "trip_packets"
        self._shortlists = shortlist_store or ShortlistStore()

    def path_for(self, trip_id: str) -> Path:
        return self._dir / f"{trip_id}.packet.json"

    def load(self, trip_id: str) -> TripPacketState | None:
        path = self.path_for(trip_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return TripPacketState.model_validate(data)

    def build(self, trip_id: str, *, save: bool = False) -> TripPacketState:
        packet = self.load(trip_id) or TripPacketState(trip_id=trip_id)
        packet = self._merge_selected_shortlist_items(packet)
        packet = self._recalculate(packet)
        if save:
            self.save(packet)
        return packet

    def save(self, packet: TripPacketState) -> TripPacketState:
        self._dir.mkdir(parents=True, exist_ok=True)
        packet.updated_at = datetime.utcnow()
        self.path_for(packet.trip_id).write_text(
            packet.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return packet

    def update_item(
        self,
        trip_id: str,
        *,
        category: str,
        option_id: str,
        status: str,
        provider: str = "",
        booking_link: str = "",
        confirmation_code: str = "",
        date: str = "",
        start_time: str = "",
        end_time: str = "",
        address: str = "",
        cost_cad: float | None = None,
        notes: str = "",
    ) -> TripPacketState:
        execution_category = ExecutionCategory(category)
        execution_status = ExecutionStatus(status)
        packet = self.build(trip_id, save=False)
        item = packet.get_item(execution_category, option_id)
        if item is None:
            item = TripPacketItem(
                item_id=f"{execution_category.value}:{option_id}",
                category=execution_category,
                option_id=option_id,
                title=option_id or execution_category.value.title(),
            )
            packet.items.append(item)
        item.status = execution_status
        if provider.strip():
            item.provider = provider.strip()
        if booking_link.strip():
            item.booking_link = booking_link.strip()
            item.source_url = item.source_url or item.booking_link
        if confirmation_code.strip():
            item.confirmation_code = confirmation_code.strip()
        if date.strip():
            item.date = date.strip()
        if start_time.strip():
            item.start_time = start_time.strip()
        if end_time.strip():
            item.end_time = end_time.strip()
        if address.strip():
            item.address = address.strip()
        if cost_cad is not None:
            item.cost_cad = cost_cad
        if notes.strip():
            item.notes = notes.strip()
        item.updated_at = datetime.utcnow()

        self._sync_shortlist_row_status(
            trip_id,
            execution_category,
            option_id,
            execution_status,
        )
        packet = self._recalculate(packet)
        return self.save(packet)

    def _merge_selected_shortlist_items(self, packet: TripPacketState) -> TripPacketState:
        existing_keys = {(item.category, item.option_id) for item in packet.items}
        for shortlist in self._shortlists.load_all(packet.trip_id):
            category = _execution_category_for_shortlist(shortlist.category)
            for option in _selected_options(shortlist):
                option_id = str(getattr(option, "option_id", ""))
                if not option_id or (category, option_id) in existing_keys:
                    continue
                packet.items.append(_packet_item_from_option(category, option))
                existing_keys.add((category, option_id))
        return packet

    def _sync_shortlist_row_status(
        self,
        trip_id: str,
        category: ExecutionCategory,
        option_id: str,
        status: ExecutionStatus,
    ) -> None:
        shortlist_category = _shortlist_category_for_execution(category)
        if shortlist_category is None:
            return
        state = self._shortlists.load(trip_id, shortlist_category)
        if state is None:
            return
        new_status = (
            ShortlistRowStatus.CONFIRMED
            if status == ExecutionStatus.CONFIRMED
            else ShortlistRowStatus.BOOKED
        )
        changed = False
        for option in _state_options(state):
            if getattr(option, "option_id", "") == option_id:
                option.row_status = new_status
                changed = True
        if changed:
            state.recommended_option_id = option_id or state.recommended_option_id
            self._shortlists.save(state)

    def _recalculate(self, packet: TripPacketState) -> TripPacketState:
        packet.items.sort(key=_packet_sort_key)
        required = _required_items(packet.items)
        score = 0
        max_score = max(len(required) * 100, 1)
        missing: list[str] = []
        for category in required:
            item = next((entry for entry in packet.items if entry.category == category), None)
            label = category.value
            if item is None:
                missing.append(f"Choose a {label} option.")
                continue
            if item.status == ExecutionStatus.SELECTED:
                score += 35
                missing.append(f"Book selected {label} or replace it.")
                continue
            if item.status == ExecutionStatus.BOOKED:
                score += 70
                if not item.confirmation_code:
                    missing.append(f"Add {label} confirmation code/details.")
                continue
            if item.is_confirmed:
                score += 100
            else:
                score += 80
                missing.append(f"Add {label} confirmation code/details.")

        packet.readiness_percent = int(round((score / max_score) * 100))
        if packet.readiness_percent >= 100:
            packet.status_label = "trip packet confirmed"
        elif any(item.status == ExecutionStatus.BOOKED for item in packet.items):
            packet.status_label = "bookings in progress"
        elif packet.items:
            packet.status_label = "recommendations selected"
        else:
            packet.status_label = "not ready"
        packet.missing_items = missing
        packet.next_actions = _next_actions(packet, required)
        packet.summary = _packet_summary(packet, required)
        packet.updated_at = datetime.utcnow()
        return packet


def _selected_options(state: ResearchShortlistState) -> list[Any]:
    selected_statuses = {
        ShortlistRowStatus.APPROVED,
        ShortlistRowStatus.BOOKED,
        ShortlistRowStatus.CONFIRMED,
    }
    options = [
        option
        for option in _state_options(state)
        if getattr(option, "row_status", "") in selected_statuses
    ]
    if options:
        return options
    recommended_id = state.recommended_option_id
    if recommended_id:
        return [
            option
            for option in _state_options(state)
            if getattr(option, "option_id", "") == recommended_id
        ]
    return []


def _state_options(state: ResearchShortlistState) -> list[Any]:
    if state.category == ShortlistCategory.FLIGHTS:
        return list(state.flight_options)
    if state.category == ShortlistCategory.LODGING:
        return list(state.lodging_options)
    if state.category == ShortlistCategory.CARS:
        return list(state.car_options)
    return list(state.activity_options)


def _packet_item_from_option(
    category: ExecutionCategory,
    option: Any,
) -> TripPacketItem:
    title = (
        getattr(option, "airline", "")
        or getattr(option, "name", "")
        or getattr(option, "vehicle_class", "")
        or getattr(option, "activity_name", "")
        or getattr(option, "option_id", "")
    )
    provider = (
        getattr(option, "booking_source", "")
        or getattr(option, "source", "")
        or getattr(option, "provider", "")
    )
    return TripPacketItem(
        item_id=f"{category.value}:{getattr(option, 'option_id', '')}",
        category=category,
        option_id=str(getattr(option, "option_id", "")),
        title=str(title),
        provider=str(provider),
        status=_execution_status_from_row(getattr(option, "row_status", "")),
        source_url=str(getattr(option, "deep_link", "") or ""),
        booking_link=str(getattr(option, "deep_link", "") or ""),
        date=str(
            getattr(option, "scheduled_date", "") or getattr(option, "suggested_date", "") or ""
        ),
        start_time=str(
            getattr(option, "scheduled_start_time", "")
            or getattr(option, "suggested_start_time", "")
            or getattr(option, "departure_time", "")
            or ""
        ),
        end_time=str(
            getattr(option, "scheduled_end_time", "")
            or getattr(option, "suggested_end_time", "")
            or getattr(option, "arrival_time", "")
            or ""
        ),
        evidence={
            "row_status": str(getattr(getattr(option, "row_status", ""), "value", "")),
            "verification": str(
                getattr(
                    getattr(getattr(option, "validation", None), "verification_status", ""),
                    "value",
                    "",
                )
            ),
            "confidence": getattr(getattr(option, "validation", None), "confidence", None),
        },
    )


def _execution_status_from_row(row_status: Any) -> ExecutionStatus:
    value = getattr(row_status, "value", row_status)
    if value == ShortlistRowStatus.CONFIRMED.value:
        return ExecutionStatus.CONFIRMED
    if value == ShortlistRowStatus.BOOKED.value:
        return ExecutionStatus.BOOKED
    return ExecutionStatus.SELECTED


def _execution_category_for_shortlist(category: ShortlistCategory) -> ExecutionCategory:
    return {
        ShortlistCategory.FLIGHTS: ExecutionCategory.FLIGHT,
        ShortlistCategory.LODGING: ExecutionCategory.LODGING,
        ShortlistCategory.CARS: ExecutionCategory.CAR,
        ShortlistCategory.ACTIVITIES: ExecutionCategory.ACTIVITY,
    }[category]


def _shortlist_category_for_execution(category: ExecutionCategory) -> ShortlistCategory | None:
    return {
        ExecutionCategory.FLIGHT: ShortlistCategory.FLIGHTS,
        ExecutionCategory.LODGING: ShortlistCategory.LODGING,
        ExecutionCategory.CAR: ShortlistCategory.CARS,
        ExecutionCategory.ACTIVITY: ShortlistCategory.ACTIVITIES,
    }.get(category)


def _required_items(items: list[TripPacketItem]) -> list[ExecutionCategory]:
    required = [ExecutionCategory.FLIGHT, ExecutionCategory.LODGING]
    if any(item.category == ExecutionCategory.CAR for item in items):
        required.append(ExecutionCategory.CAR)
    if any(item.category == ExecutionCategory.ACTIVITY for item in items):
        required.append(ExecutionCategory.ACTIVITY)
    return required


def _next_actions(
    packet: TripPacketState,
    required: list[ExecutionCategory],
) -> list[str]:
    actions = []
    for missing in packet.missing_items[:5]:
        actions.append(missing)
    if not actions and required:
        actions.append("Review the trip packet, map, and timeline before departure.")
    return actions


def _packet_summary(packet: TripPacketState, required: list[ExecutionCategory]) -> str:
    confirmed = sum(1 for item in packet.items if item.is_confirmed)
    booked = sum(1 for item in packet.items if item.is_booked)
    return (
        f"{booked} booked item(s), {confirmed} confirmed item(s), "
        f"{len(required)} required category/categories."
    )


def _packet_sort_key(item: TripPacketItem) -> tuple[int, str, str]:
    order = {
        ExecutionCategory.FLIGHT: 10,
        ExecutionCategory.LODGING: 20,
        ExecutionCategory.CAR: 30,
        ExecutionCategory.ACTIVITY: 40,
        ExecutionCategory.OTHER: 90,
    }
    return (order.get(item.category, 99), item.date or "", item.title)
