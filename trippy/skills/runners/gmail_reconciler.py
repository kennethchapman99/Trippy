"""trippy-gmail-reconciler skill runner."""

from __future__ import annotations

import logging
from datetime import datetime
from inspect import signature
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class GmailReconcilerRunner:
    skill_name = "trippy-gmail-reconciler"

    def __init__(
        self,
        trips_dir: Path | None = None,
        auth_manager: Any | None = None,
        anthropic_client: Any | None = None,
    ) -> None:
        self._trips_dir = trips_dir
        self._auth_manager = auth_manager
        self._anthropic_client = anthropic_client

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        from trippy import config
        from trippy.db import make_session_factory
        from trippy.db.models import Trip as DbTrip
        from trippy.ingest.gmail_watcher import GmailWatcher
        from trippy.ingest.google_auth import GoogleAuthManager
        from trippy.ingest.linker import TripLinker
        from trippy.ingest.parser import ConfirmationParser
        from trippy.services.sheet_sync import SheetSyncService
        from trippy.services.trip_state import TripStateService

        max_emails: int = inputs.get("max_emails", 50)
        label: str = inputs.get("label", "INBOX")
        query: str | None = inputs.get("query")
        target_trip_id: str | None = inputs.get("trip_id")
        dry_run: bool = bool(inputs.get("dry_run", False))

        auth = self._auth_manager or GoogleAuthManager()
        watcher = GmailWatcher(auth_manager=auth)
        watcher.authenticate()

        emails = _fetch_candidate_emails(
            watcher=watcher,
            label=label,
            query=query,
            max_emails=max_emails,
        )
        logger.info("GmailReconciler: fetched %d candidate emails", len(emails))

        parser = ConfirmationParser(anthropic_client=self._anthropic_client)
        factory = make_session_factory()

        linked_count = 0
        unlinked_count = 0
        failed_count = 0
        updates: list[dict[str, Any]] = []
        unlinked: list[dict[str, Any]] = []

        vault_path = config.VAULT_PATH
        trip_state = TripStateService(trips_dir=self._trips_dir)
        sheet_sync = SheetSyncService(auth_manager=auth)
        ambiguities: list[dict[str, Any]] = []

        for email_content in emails:
            eml_path = None if dry_run else watcher.save_to_vault(email_content, vault_path)
            atts = [(a.filename, a.content_type, a.data) for a in email_content.attachments]
            parse_result = parser.parse(
                body_text=email_content.body_text,
                body_html=email_content.body_html,
                attachments=atts,
                eml_path=eml_path,
            )

            if not parse_result.ok or parse_result.confirmation is None:
                failed_count += 1
                continue

            conf = parse_result.confirmation
            db_trip_name: str | None = None
            db_trip_slug: str | None = None
            canonical_from_db: Any | None = None
            matches_target = False
            with factory() as session:
                linker = TripLinker(session)
                link = linker.link(conf, raw_email_path=str(eml_path) if eml_path else None)
                db_trip = session.get(DbTrip, link.trip_id) if link.trip_id is not None else None
                matches_target = _db_trip_matches_filter(db_trip, target_trip_id)
                if db_trip is not None:
                    db_trip_name = db_trip.name
                    db_trip_slug = db_trip.name.lower().replace(" ", "-")
                    if matches_target:
                        canonical_from_db = trip_state.from_db_trip(db_trip)
                if dry_run or not matches_target:
                    session.rollback()
                else:
                    session.commit()

            if link.linked and not matches_target:
                unlinked_count += 1
                ambiguity = {
                    "type": "target_trip_mismatch",
                    "vendor": conf.vendor,
                    "code": conf.confirmation_code,
                    "confirmation_type": conf.confirmation_type,
                    "target_trip_id": target_trip_id,
                    "linked_trip_name": db_trip_name,
                    "reason": "Confirmation matched a different trip than the requested trip_id",
                    "email_subject": email_content.subject,
                }
                ambiguities.append(ambiguity)
                unlinked.append(ambiguity)
                continue

            if link.linked:
                linked_count += 1
                if db_trip is None:
                    ambiguities.append(
                        {
                            "type": "linked_trip_missing",
                            "confirmation_code": conf.confirmation_code,
                            "vendor": conf.vendor,
                            "trip_db_id": link.trip_id,
                            "reason": "Linked trip ID not found in SQL state",
                        }
                    )
                    continue

                trip = trip_state.load(db_trip_slug or "")
                if trip is None:
                    trip = canonical_from_db
                if trip is None:
                    ambiguities.append(
                        {
                            "type": "canonical_trip_missing",
                            "confirmation_code": conf.confirmation_code,
                            "vendor": conf.vendor,
                            "trip_db_id": link.trip_id,
                            "reason": "Linked trip could not be converted to canonical state",
                        }
                    )
                    continue

                canonical_confirmation = _to_canonical_confirmation(
                    confirmation=conf,
                    subject=email_content.subject,
                    eml_path=eml_path or Path("dry-run"),
                )
                match_info = _attach_confirmation_to_trip(trip, canonical_confirmation, conf)
                if not dry_run:
                    trip_state.save(trip)

                if trip.sync.google_sheet_id and not dry_run:
                    sheet_sync.push_trip_to_sheet(trip, trip.sync.google_sheet_id)

                updates.append(
                    {
                        "trip_id": link.trip_id,
                        "trip_canonical_id": trip.trip_id,
                        "confirmation_code": conf.confirmation_code,
                        "vendor": conf.vendor,
                        "method": link.method,
                        "linked_segment_id": match_info.get("linked_segment_id"),
                        "linked_stay_id": match_info.get("linked_stay_id"),
                        "dry_run": dry_run,
                    }
                )
                if match_info["ambiguity"] is not None:
                    ambiguities.append(match_info["ambiguity"])
            else:
                unlinked_count += 1
                ambiguity = {
                    "type": "unlinked_confirmation",
                    "vendor": conf.vendor,
                    "code": conf.confirmation_code,
                    "confirmation_type": conf.confirmation_type,
                    "reason": "No matching trip found",
                    "email_subject": email_content.subject,
                }
                ambiguities.append(ambiguity)
                unlinked.append(
                    {
                        "vendor": conf.vendor,
                        "code": conf.confirmation_code,
                        "type": conf.confirmation_type,
                        "reason": "No matching trip found",
                    }
                )

        return {
            "dry_run": dry_run,
            "target_trip_id": target_trip_id,
            "label": label,
            "query": query,
            "emails_scanned": len(emails),
            "confirmations_parsed": linked_count + unlinked_count,
            "confirmations_linked": linked_count,
            "confirmations_unlinked": unlinked_count,
            "parse_failures": failed_count,
            "updates": updates,
            "unlinked": unlinked,
            "ambiguities": ambiguities,
        }


def _fetch_candidate_emails(
    *,
    watcher: Any,
    label: str,
    query: str | None,
    max_emails: int,
) -> list[Any]:
    """Call GmailWatcher while staying compatible with older injected test fakes."""
    params = signature(watcher.fetch_new_messages).parameters
    kwargs: dict[str, Any] = {"max_results": max_emails}
    if "label" in params:
        kwargs["label"] = label
    if "query" in params:
        kwargs["query"] = query
    return watcher.fetch_new_messages(**kwargs)  # type: ignore[no-any-return]


def _db_trip_matches_filter(db_trip: Any | None, target_trip_id: str | None) -> bool:
    if target_trip_id is None:
        return True
    if db_trip is None:
        return False
    slug = str(db_trip.name).lower().replace(" ", "-")
    return target_trip_id in {str(db_trip.id), slug}


def _to_canonical_confirmation(confirmation: Any, subject: str, eml_path: Path) -> Any:
    from trippy.models.trip import Confirmation, ConfirmationType

    return Confirmation(
        confirmation_id=f"{confirmation.vendor}-{confirmation.confirmation_code}-{int(datetime.utcnow().timestamp())}",
        confirmation_type=ConfirmationType(confirmation.confirmation_type),
        confirmation_code=confirmation.confirmation_code,
        vendor=confirmation.vendor,
        raw_email_subject=subject,
        raw_email_path=str(eml_path),
        received_at=datetime.utcnow(),
        parsed_at=datetime.utcnow(),
        extracted_data=confirmation.model_dump(),
    )


def _attach_confirmation_to_trip(
    trip: Any, canonical_confirmation: Any, parsed: Any
) -> dict[str, Any]:
    """Attach confirmation to canonical trip and enrich a matching segment/stay."""
    trip.confirmations.append(canonical_confirmation)

    ambiguity: dict[str, Any] | None = None
    linked_segment_id: str | None = None
    linked_stay_id: str | None = None

    if parsed.confirmation_type == "flight":
        for segment in trip.segments:
            if segment.segment_type.value != "flight":
                continue
            if (
                parsed.origin
                and parsed.destination
                and segment.origin.upper() == parsed.origin.upper()
                and segment.destination.upper() == parsed.destination.upper()
            ) or (
                parsed.flight_number
                and segment.flight_number
                and segment.flight_number.upper() == parsed.flight_number.upper()
            ):
                segment.confirmation_code = parsed.confirmation_code
                segment.carrier = parsed.vendor or segment.carrier
                if parsed.depart_at:
                    segment.depart_at = datetime.fromisoformat(parsed.depart_at)
                if parsed.arrive_at:
                    segment.arrive_at = datetime.fromisoformat(parsed.arrive_at)
                linked_segment_id = segment.segment_id
                canonical_confirmation.linked_segment_id = segment.segment_id
                break

        if linked_segment_id is None:
            ambiguity = {
                "type": "segment_unresolved",
                "trip_id": trip.trip_id,
                "confirmation_code": parsed.confirmation_code,
                "vendor": parsed.vendor,
                "reason": "Trip linked but no matching segment found",
            }

    elif parsed.confirmation_type in {"hotel", "rental"}:
        for stay in trip.stays:
            city_match = bool(parsed.city and stay.city.lower() == parsed.city.lower())
            property_match = bool(
                parsed.property_name and stay.property_name.lower() == parsed.property_name.lower()
            )
            date_match = bool(
                parsed.check_in
                and stay.check_in
                and stay.check_in.isoformat() == parsed.check_in[:10]
            )
            if city_match or property_match or date_match:
                stay.confirmation_code = parsed.confirmation_code
                stay.property_name = parsed.property_name or stay.property_name
                if parsed.city:
                    stay.city = parsed.city
                if parsed.country:
                    stay.country = parsed.country
                linked_stay_id = stay.stay_id
                canonical_confirmation.linked_stay_id = stay.stay_id
                break

        if linked_stay_id is None:
            ambiguity = {
                "type": "stay_unresolved",
                "trip_id": trip.trip_id,
                "confirmation_code": parsed.confirmation_code,
                "vendor": parsed.vendor,
                "reason": "Trip linked but no matching stay found",
            }

    return {
        "linked_segment_id": linked_segment_id,
        "linked_stay_id": linked_stay_id,
        "ambiguity": ambiguity,
    }
