"""Generic connector-safe trip geography resolver."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Any

from trippy import config
from trippy.models.geography import ResolvedAirport, ResolvedPlace, TripGeography
from trippy.models.trip_planning import TripIntake
from trippy.services.llm_client import TrippyLLMClient

IATA_RE = re.compile(r"^[A-Z]{3}$")


class GeographyResolverService:
    """Resolve raw intake text into typed airport/place buckets."""

    def __init__(
        self,
        *,
        anthropic_client: Any | None = None,
        enabled: bool | None = None,
        model: str | None = None,
    ) -> None:
        self._enabled = config.TRIPPY_GEOGRAPHY_LLM_ENABLED if enabled is None else enabled
        self._model = model or config.TRIPPY_GEOGRAPHY_RESOLVER_MODEL
        self._llm = TrippyLLMClient(anthropic_client=anthropic_client)

    def resolve(self, intake: TripIntake) -> TripGeography:
        if self._enabled:
            geography = self._resolve_with_llm(intake)
            if geography is not None:
                return geography
            if self._llm.mode == "required":
                raise RuntimeError("Geography resolver LLM is required but unavailable")
        raw_destinations = _dedupe_strings(intake.destination_seeds)
        origins = self._resolve_origins(intake.departure_airports)
        destinations = self._resolve_destinations(raw_destinations)
        primary = _primary_destination(raw_destinations, intake.trip_name, destinations)
        places = self._resolve_places(raw_destinations, primary, destinations)
        map_locations = _dedupe_strings(place.search_label() for place in places)
        lodging_locations = _connector_locations(places, primary, {"city", "neighborhood", "district", "town", "beach", "region", "place"})
        car_locations = _car_locations(destinations, places, primary)
        activity_locations = _connector_locations(places, primary, {"city", "neighborhood", "district", "town", "beach", "region", "park", "place"})
        planning_regions = _planning_regions(places, primary)
        warnings: list[str] = []
        evidence: list[str] = []
        if destinations:
            evidence.append(f"Resolved destination airport {destinations[0].iata_code} from '{destinations[0].matched_text}'.")
        else:
            warnings.append("No destination airport resolved; live flight providers must fail closed until a valid IATA destination is selected.")
        return TripGeography(
            primary_destination_name=primary,
            origin_airports=origins,
            destination_airports=destinations,
            places=places,
            planning_regions=planning_regions,
            map_locations=map_locations,
            lodging_search_locations=lodging_locations,
            car_search_locations=car_locations,
            activity_search_locations=activity_locations,
            warnings=warnings,
            evidence=evidence,
        )

    def _resolve_with_llm(self, intake: TripIntake) -> TripGeography | None:
        prompt = _geography_prompt(intake)
        result = self._llm.complete_json(
            service="geography_resolver",
            model=self._model,
            prompt=prompt,
            system=(
                "Resolve travel geography into strict JSON. Only include valid IATA airport codes in airport arrays. "
                "Mark ambiguity and confirmation needs clearly."
            ),
            max_tokens=1800,
            trip_id=intake.trip_id,
            prompt_version="geography-resolver-v2",
        )
        if result.status != "success" or result.json is None:
            return None
        try:
            return _geography_from_payload(result.json)
        except Exception:
            return None

    def _resolve_origins(self, values: list[str]) -> list[ResolvedAirport]:
        airports = [
            airport
            for value in (values or ["YYZ"])
            if (airport := self._airport_from_explicit_code(value, role="origin"))
        ]
        return _dedupe_airports(airports) or [ResolvedAirport(iata_code="YYZ", role="origin", confidence=0.7, source="default_origin", matched_text="YYZ", requires_user_confirmation=True)]

    def _resolve_destinations(self, raw_destinations: list[str]) -> list[ResolvedAirport]:
        airports = [
            airport
            for value in _destination_pieces(raw_destinations)
            if (airport := self._airport_from_explicit_code(value, role="gateway"))
        ]
        if not airports:
            airports.extend(_fallback_gateway_hints(raw_destinations))
        return _dedupe_airports(airports)

    def _airport_from_explicit_code(self, value: str, *, role: str) -> ResolvedAirport | None:
        cleaned = value.strip().upper()
        if IATA_RE.fullmatch(cleaned):
            return ResolvedAirport(iata_code=cleaned, role=role, confidence=0.82, source="explicit_iata", matched_text=value)
        return None

    def _resolve_places(self, raw_destinations: list[str], primary: str, airports: list[ResolvedAirport]) -> list[ResolvedPlace]:
        pieces = _destination_pieces(raw_destinations or [primary])
        places: list[ResolvedPlace] = []
        for piece in pieces:
            if IATA_RE.fullmatch(piece.strip().upper()):
                continue
            kind = _infer_place_kind(piece)
            places.append(
                ResolvedPlace(
                    name=_title_place(piece),
                    kind=kind,
                    confidence=0.0,
                    source="text_parser",
                    use_for=_use_for_kind(kind),
                    raw_text=piece,
                )
            )
        return _dedupe_places(places) or [ResolvedPlace(name=primary, kind="place", confidence=0.5, source="fallback_text", use_for=["planning", "map", "lodging", "activity", "car"], raw_text=primary)]


def resolve_trip_geography(intake: TripIntake) -> TripGeography:
    return GeographyResolverService().resolve(intake)


def _destination_pieces(values: list[str]) -> list[str]:
    pieces: list[str] = []
    for value in values:
        text = re.sub(r"\s+-\s+", ",", value)
        pieces.extend(part.strip() for part in re.split(r"[,;/]", text) if part.strip())
    return _dedupe_strings(pieces)


def _primary_destination(raw_destinations: list[str], trip_name: str, airports: list[ResolvedAirport]) -> str:
    return _title_place(raw_destinations[0]) if raw_destinations else trip_name.strip() or "Destination"


def _planning_regions(places: list[ResolvedPlace], primary: str) -> list[str]:
    city_like = [place.search_label() for place in places if place.kind in {"city", "town", "place"}]
    return _dedupe_strings(city_like[:3] or [primary])


def _connector_locations(places: list[ResolvedPlace], primary: str, kinds: set[str]) -> list[str]:
    values = [place.search_label() for place in places if place.kind in kinds]
    values.append(primary)
    return _dedupe_strings(values)[:8]


def _car_locations(airports: list[ResolvedAirport], places: list[ResolvedPlace], primary: str) -> list[str]:
    values = [airport.iata_code for airport in airports]
    values.extend(place.search_label() for place in places if place.kind in {"city", "town", "region", "place"})
    values.append(primary)
    return _dedupe_strings(values)[:8]


def _infer_place_kind(value: str) -> str:
    normalized = _normalize(value)
    if any(term in normalized for term in ["valley", "wine", "region"]):
        return "region"
    if any(term in normalized for term in ["beach", "bay", "point", "cove"]):
        return "beach"
    if any(term in normalized for term in ["park", "gorge", "falls", "mount", "volcano"]):
        return "park"
    if any(term in normalized for term in ["barrio", "district", "quarter", "neighborhood", "neighbourhood"]):
        return "neighborhood"
    return "place"


def _use_for_kind(kind: str) -> list[str]:
    if kind == "neighborhood":
        return ["map", "lodging", "activity"]
    if kind in {"region", "park", "beach"}:
        return ["map", "activity", "car"]
    return ["planning", "map", "lodging", "activity", "car"]


def _title_place(value: str) -> str:
    cleaned = " ".join(value.strip().replace("_", " ").split())
    return " ".join(word if word.isupper() else word.capitalize() for word in cleaned.split()) or "Destination"


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(re.sub(r"[^a-zA-Z0-9]+", " ", ascii_value).lower().split())


def _dedupe_strings(values: Iterable[object]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = " ".join(str(value).strip().split())
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _dedupe_airports(values: list[ResolvedAirport]) -> list[ResolvedAirport]:
    result: list[ResolvedAirport] = []
    seen: set[str] = set()
    for airport in values:
        if airport.iata_code not in seen:
            seen.add(airport.iata_code)
            result.append(airport)
    return result


def _dedupe_places(values: list[ResolvedPlace]) -> list[ResolvedPlace]:
    result: list[ResolvedPlace] = []
    seen: set[str] = set()
    for place in values:
        key = place.search_label().casefold()
        if key not in seen:
            seen.add(key)
            result.append(place)
    return result


def _geography_prompt(intake: TripIntake) -> str:
    schema = {
        "primary_destination_name": "string",
        "country": "string",
        "destination_airports": [
            {
                "iata_code": "string",
                "role": "gateway|regional|unknown",
                "confidence": 0.0,
                "source": "llm",
                "matched_text": "string",
                "requires_user_confirmation": True,
            }
        ],
        "origin_airports": [],
        "places": [
            {
                "name": "string",
                "kind": "country|city|region|neighborhood|beach|park|place",
                "country": "string",
                "confidence": 0.0,
                "source": "llm",
                "use_for": ["planning", "map", "lodging", "activity", "car"],
                "raw_text": "string",
                "requires_user_confirmation": True,
            }
        ],
        "planning_regions": ["string"],
        "map_locations": ["string"],
        "lodging_search_locations": ["string"],
        "car_search_locations": ["string"],
        "activity_search_locations": ["string"],
        "warnings": ["string"],
        "evidence": ["string"],
    }
    return "\n".join(
        [
            "# Trippy Geography Resolver (geography-resolver-v2)",
            "Resolve raw destination input into connector-safe geography.",
            "Never put a freeform city, neighborhood, or itinerary string into airport arrays.",
            "If a gateway is only likely, include it with requires_user_confirmation=true.",
            "",
            "## Intake",
            str(intake.model_dump(mode="json")),
            "",
            "## Output JSON Schema",
            str(schema),
        ]
    )


def _geography_from_payload(payload: dict[str, Any]) -> TripGeography:
    airports = []
    for item in payload.get("destination_airports", []):
        if not isinstance(item, dict):
            continue
        code = str(item.get("iata_code") or "").strip().upper()
        if not IATA_RE.fullmatch(code):
            continue
        airports.append(
            ResolvedAirport(
                iata_code=code,
                role=str(item.get("role") or "gateway"),
                confidence=_float(item.get("confidence"), 0.5),
                source=str(item.get("source") or "llm"),
                matched_text=str(item.get("matched_text") or ""),
                requires_user_confirmation=bool(item.get("requires_user_confirmation", True)),
            )
        )
    origins = []
    for item in payload.get("origin_airports", []):
        if not isinstance(item, dict):
            continue
        code = str(item.get("iata_code") or "").strip().upper()
        if IATA_RE.fullmatch(code):
            origins.append(
                ResolvedAirport(
                    iata_code=code,
                    role="origin",
                    confidence=_float(item.get("confidence"), 0.8),
                    source=str(item.get("source") or "llm"),
                    matched_text=str(item.get("matched_text") or code),
                    requires_user_confirmation=bool(item.get("requires_user_confirmation", False)),
                )
            )
    places = []
    for item in payload.get("places", []):
        if isinstance(item, dict) and str(item.get("name") or "").strip():
            places.append(
                ResolvedPlace(
                    name=str(item.get("name")),
                    kind=str(item.get("kind") or "place"),
                    country=str(item.get("country") or payload.get("country") or ""),
                    confidence=_float(item.get("confidence"), 0.5),
                    source=str(item.get("source") or "llm"),
                    use_for=_string_list(item.get("use_for")),
                    raw_text=str(item.get("raw_text") or ""),
                )
            )
    warnings = _string_list(payload.get("warnings"))
    if not airports:
        warnings.append("No valid IATA destination airport resolved; flight providers must fail closed.")
    return TripGeography(
        primary_destination_name=str(payload.get("primary_destination_name") or ""),
        origin_airports=origins,
        destination_airports=airports,
        places=places,
        planning_regions=_string_list(payload.get("planning_regions")),
        map_locations=_string_list(payload.get("map_locations")),
        lodging_search_locations=_string_list(payload.get("lodging_search_locations")),
        car_search_locations=_string_list(payload.get("car_search_locations")),
        activity_search_locations=_string_list(payload.get("activity_search_locations")),
        warnings=warnings,
        evidence=_string_list(payload.get("evidence")),
    )


def _fallback_gateway_hints(raw_destinations: list[str]) -> list[ResolvedAirport]:
    text = " ".join(raw_destinations).casefold()
    hints = {
        "chile": ("SCL", "Chile likely international gateway candidate"),
        "santiago": ("SCL", "Santiago likely international gateway candidate"),
        "azores": ("PDL", "Azores likely gateway candidate"),
        "costa rica": ("SJO", "Costa Rica likely gateway candidate"),
    }
    airports = []
    for needle, (code, _evidence) in hints.items():
        if needle in text:
            airports.append(
                ResolvedAirport(
                    iata_code=code,
                    role="gateway",
                    confidence=0.55,
                    source="fallback",
                    matched_text=needle,
                    requires_user_confirmation=True,
                )
            )
            break
    return airports


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _float(value: Any, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default
