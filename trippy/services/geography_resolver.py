"""Generic connector-safe trip geography resolver."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from trippy.models.geography import ResolvedAirport, ResolvedPlace, TripGeography
from trippy.models.trip_planning import TripIntake


@dataclass(frozen=True)
class AirportCatalogEntry:
    iata_code: str
    name: str
    city: str
    country: str
    aliases: tuple[str, ...]


AIRPORT_CATALOG: tuple[AirportCatalogEntry, ...] = (
    AirportCatalogEntry("YYZ", "Toronto Pearson International Airport", "Toronto", "Canada", ("yyz", "toronto", "pearson")),
    AirportCatalogEntry("SCL", "Arturo Merino Benitez International Airport", "Santiago", "Chile", ("scl", "santiago", "santiago chile")),
    AirportCatalogEntry("PDL", "Joao Paulo II Airport", "Ponta Delgada", "Portugal", ("pdl", "ponta delgada", "azores", "sao miguel")),
    AirportCatalogEntry("GCM", "Owen Roberts International Airport", "George Town", "Cayman Islands", ("gcm", "grand cayman", "cayman islands")),
    AirportCatalogEntry("LIS", "Lisbon Airport", "Lisbon", "Portugal", ("lis", "lisbon", "lisboa")),
    AirportCatalogEntry("HND", "Haneda Airport", "Tokyo", "Japan", ("hnd", "haneda", "tokyo")),
    AirportCatalogEntry("BKK", "Suvarnabhumi Airport", "Bangkok", "Thailand", ("bkk", "bangkok")),
    AirportCatalogEntry("SJO", "Juan Santamaria International Airport", "San Jose", "Costa Rica", ("sjo", "san jose costa rica", "costa rica")),
)

IATA_RE = re.compile(r"^[A-Z]{3}$")


class GeographyResolverService:
    """Resolve raw intake text into typed airport/place buckets."""

    def resolve(self, intake: TripIntake) -> TripGeography:
        raw_destinations = _dedupe_strings(intake.destination_seeds)
        raw_text = " ".join([intake.trip_name, *raw_destinations, intake.freeform_notes or ""])
        origins = self._resolve_origins(intake.departure_airports)
        destinations = self._resolve_destinations(raw_destinations, raw_text)
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

    def _resolve_origins(self, values: list[str]) -> list[ResolvedAirport]:
        airports = [airport for value in (values or ["YYZ"]) if (airport := self._airport_from_code_or_text(value, role="origin"))]
        return _dedupe_airports(airports) or [ResolvedAirport(iata_code="YYZ", role="origin", confidence=0.7, source="default_origin", matched_text="YYZ", requires_user_confirmation=True)]

    def _resolve_destinations(self, raw_destinations: list[str], raw_text: str) -> list[ResolvedAirport]:
        airports = [airport for value in raw_destinations if (airport := self._airport_from_code_or_text(value, role="gateway"))]
        if not airports:
            airport = self._airport_from_text(raw_text, role="gateway")
            if airport:
                airports.append(airport)
        return _dedupe_airports(airports[:1])

    def _airport_from_code_or_text(self, value: str, *, role: str) -> ResolvedAirport | None:
        cleaned = value.strip().upper()
        if IATA_RE.fullmatch(cleaned):
            entry = _entry_for_code(cleaned)
            if entry:
                return _airport_from_entry(entry, role=role, matched_text=value, confidence=0.98)
            return ResolvedAirport(iata_code=cleaned, role=role, confidence=0.82, source="explicit_iata", matched_text=value)
        return self._airport_from_text(value, role=role)

    def _airport_from_text(self, value: str, *, role: str) -> ResolvedAirport | None:
        normalized = _normalize(value)
        candidates: list[tuple[int, AirportCatalogEntry, str]] = []
        for entry in AIRPORT_CATALOG:
            for alias in entry.aliases:
                alias_norm = _normalize(alias)
                if alias_norm and re.search(rf"\b{re.escape(alias_norm)}\b", normalized):
                    candidates.append((len(alias_norm), entry, alias))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        _, entry, alias = candidates[0]
        return _airport_from_entry(entry, role=role, matched_text=alias, confidence=0.9)

    def _resolve_places(self, raw_destinations: list[str], primary: str, airports: list[ResolvedAirport]) -> list[ResolvedPlace]:
        airport_city = airports[0].city if airports else ""
        airport_country = airports[0].country if airports else ""
        pieces = _destination_pieces(raw_destinations or [primary])
        places: list[ResolvedPlace] = []
        for piece in pieces:
            if IATA_RE.fullmatch(piece.strip().upper()):
                continue
            kind = _infer_place_kind(piece, airport_city)
            places.append(
                ResolvedPlace(
                    name=_title_place(piece),
                    kind=kind,
                    city=airport_city if kind in {"neighborhood", "district"} else "",
                    country=airport_country,
                    confidence=0.72,
                    source="text_parser",
                    use_for=_use_for_kind(kind),
                    raw_text=piece,
                )
            )
        return _dedupe_places(places) or [ResolvedPlace(name=primary, kind="place", confidence=0.5, source="fallback_text", use_for=["planning", "map", "lodging", "activity", "car"], raw_text=primary)]


def resolve_trip_geography(intake: TripIntake) -> TripGeography:
    return GeographyResolverService().resolve(intake)


def _entry_for_code(code: str) -> AirportCatalogEntry | None:
    return next((entry for entry in AIRPORT_CATALOG if entry.iata_code == code), None)


def _airport_from_entry(entry: AirportCatalogEntry, *, role: str, matched_text: str, confidence: float) -> ResolvedAirport:
    return ResolvedAirport(iata_code=entry.iata_code, name=entry.name, city=entry.city, country=entry.country, role=role, confidence=confidence, source="airport_catalog", matched_text=matched_text)


def _destination_pieces(values: list[str]) -> list[str]:
    pieces: list[str] = []
    for value in values:
        text = value.replace("/", ",").replace(";", ",")
        comma_parts = [part.strip() for part in text.split(",") if part.strip()]
        if len(comma_parts) > 1:
            pieces.extend(comma_parts)
        else:
            pieces.extend(_split_repeated_city_path(text))
    return _dedupe_strings(pieces)


def _split_repeated_city_path(value: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"\s*-\s*", value) if part.strip()]
    if len(parts) <= 2:
        return [value.strip()]
    output: list[str] = []
    idx = 0
    while idx < len(parts):
        current = parts[idx]
        if idx + 1 < len(parts) and current.lower() in {"santiago", "toronto", "tokyo", "bangkok", "lisbon"}:
            output.append(parts[idx + 1])
            idx += 2
        else:
            output.append(current)
            idx += 1
    return output


def _primary_destination(raw_destinations: list[str], trip_name: str, airports: list[ResolvedAirport]) -> str:
    if airports and airports[0].city and airports[0].country:
        return f"{airports[0].city}, {airports[0].country}"
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


def _infer_place_kind(value: str, airport_city: str) -> str:
    normalized = _normalize(value)
    if airport_city and normalized == _normalize(airport_city):
        return "city"
    if any(term in normalized for term in ["valley", "wine", "region"]):
        return "region"
    if any(term in normalized for term in ["beach", "bay", "point", "cove"]):
        return "beach"
    if any(term in normalized for term in ["park", "gorge", "falls", "mount", "volcano"]):
        return "park"
    if any(term in normalized for term in ["barrio", "district", "quarter", "neighborhood", "neighbourhood"]):
        return "neighborhood"
    if airport_city and len(normalized.split()) <= 3:
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


def _dedupe_strings(values: object) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:  # type: ignore[operator]
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
