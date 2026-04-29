"""Convert SerpAPI payloads into Trippy shortlist options.

Each ``*_from_serpapi`` returns a list of pre-ranked options stamped with
``LiveDataStatus.LIVE_VERIFIED`` (or ``LIVE_SIGNAL`` semantics where
SerpAPI gives prices but not bookable inventory) and a populated
``SourceValidation`` block so the UI can show "Live verified · SerpAPI"
pills.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import quote_plus

from trippy.models.shortlists import (
    ActivityOption,
    AvailabilityStatus,
    CarOption,
    FlightOption,
    FreshnessStatus,
    LiveDataStatus,
    LodgingOption,
    PriceStatus,
    RecommendationGrade,
    ShortlistRowStatus,
    SourceType,
    SourceValidation,
    VerificationStatus,
)


def _validation(
    *,
    source_name: str = "SerpAPI",
    confidence: float = 0.78,
    evidence_url: str,
    adapter: str,
    extracted: dict[str, Any],
    notes: list[str],
    price_status: PriceStatus = PriceStatus.LIVE_SIGNAL,
) -> SourceValidation:
    return SourceValidation(
        source_name=source_name,
        source_type=SourceType.LIVE_SEARCH,
        verified_at=datetime.utcnow(),
        freshness_status=FreshnessStatus.CURRENT,
        verification_status=VerificationStatus.LIVE_VERIFIED,
        availability_status=AvailabilityStatus.AVAILABILITY_SIGNAL,
        price_status=price_status,
        confidence=confidence,
        evidence_url=evidence_url,
        adapter_used=adapter,
        extracted_fields=extracted,
        notes=notes,
    )


# ── Flights ──────────────────────────────────────────────────────


def flight_options_from_serpapi(
    offers: list[dict[str, Any]],
    *,
    origin: str,
    destination: str,
    deep_link: str,
    rank_offset: int = 0,
) -> list[FlightOption]:
    options: list[FlightOption] = []
    for index, offer in enumerate(offers[:8], start=1):
        legs = [item for item in (offer.get("flights") or []) if isinstance(item, dict)]
        if not legs:
            continue
        first, last = legs[0], legs[-1]
        dep_airport = (first.get("departure_airport") or {})
        arr_airport = (last.get("arrival_airport") or {})
        dep_iso = str(dep_airport.get("time") or "")
        arr_iso = str(arr_airport.get("time") or "")
        dep_date, dep_time = _split_serpapi_timestamp(dep_iso)
        arr_date, arr_time = _split_serpapi_timestamp(arr_iso)
        flight_numbers = [str(leg.get("flight_number") or "").replace(" ", "") for leg in legs if leg.get("flight_number")]
        carriers = []
        airline_logo_url = ""
        for leg in legs:
            name = str(leg.get("airline") or "")
            if name and name not in carriers:
                carriers.append(name)
            if not airline_logo_url:
                airline_logo_url = str(leg.get("airline_logo") or "")
        airline = " / ".join(carriers) or "Live offer"
        layovers = [item for item in (offer.get("layovers") or []) if isinstance(item, dict)]
        layover_codes = [str(lay.get("id") or "") for lay in layovers if lay.get("id")]
        stops = max(0, len(legs) - 1)
        total_minutes = int(offer.get("total_duration") or 0)
        duration = _format_minutes(total_minutes) if total_minutes else "duration unknown"
        layover_duration = (
            ", ".join(
                f"{lay.get('id') or ''} {_format_minutes(int(lay.get('duration') or 0))}".strip()
                for lay in layovers
                if lay.get("duration")
            )
            or None
        )
        price_amount = offer.get("price")
        price_str = f"CAD {price_amount} per person" if price_amount else "live signal; price unavailable"
        rank = rank_offset + index
        friction = min(90, 8 + stops * 16)
        comfort = max(35, 94 - stops * 12)
        options.append(
            FlightOption(
                option_id=f"serpapi-flight-{rank}",
                rank=rank,
                airline=airline,
                airline_logo_url=airline_logo_url,
                flight_numbers=flight_numbers,
                departure_date=dep_date,
                arrival_date=arr_date,
                departure_airport=str(dep_airport.get("id") or origin),
                arrival_airport=str(arr_airport.get("id") or destination),
                departure_time=dep_time,
                arrival_time=arr_time,
                stops=stops,
                layover_airports=layover_codes,
                layover_duration=layover_duration,
                total_travel_duration=duration,
                timing_fit="Live Google Flights signal — verify exact fare, bags, and seats before booking.",
                fare_estimate_cad=price_str,
                price_band=price_str,
                baggage_cabin_notes="SerpAPI does not return baggage detail; verify on the carrier site before booking.",
                booking_source="Google Flights (SerpAPI)",
                deep_link=deep_link,
                friction_score=friction,
                family_comfort_score=comfort,
                recommendation_grade=RecommendationGrade.STRONG if stops == 0 else RecommendationGrade.GOOD,
                tradeoffs=[
                    "Live Google Flights price + schedule signal.",
                    "SerpAPI offers are not directly bookable; use the deep link to book.",
                ],
                friction_flags=[],
                confidence_notes=[
                    "Itinerary and price came from SerpAPI Google Flights live search.",
                ],
                live_data_status=LiveDataStatus.LIVE_VERIFIED,
                row_status=ShortlistRowStatus.VERIFIED_LIVE,
                validation=_validation(
                    evidence_url=deep_link,
                    adapter="serpapi/google_flights",
                    extracted={
                        "airline": airline,
                        "airline_logo_url": airline_logo_url,
                        "flight_numbers": flight_numbers,
                        "stops": stops,
                        "total_duration": duration,
                        "price": price_str,
                    },
                    notes=[
                        "Live signal from Google Flights via SerpAPI; fares and inventory can change.",
                    ],
                ),
            )
        )
    return options


# ── Lodging ──────────────────────────────────────────────────────


def lodging_options_from_serpapi(
    properties: list[dict[str, Any]],
    *,
    region: str,
    deep_link: str,
    rank_offset: int = 0,
    requires_three_beds: bool = False,
) -> list[LodgingOption]:
    options: list[LodgingOption] = []
    for index, prop in enumerate(properties[:8], start=1):
        name = str(prop.get("name") or "Live property listing")
        prop_type = str(prop.get("type") or "hotel/listing")
        rate = prop.get("rate_per_night") or {}
        total = prop.get("total_rate") or {}
        nightly_str = (
            f"{rate.get('currency') or 'CAD'} {rate.get('extracted_lowest') or rate.get('lowest') or '?'}/night"
            if rate
            else "live rate"
        )
        total_str = (
            f"{total.get('currency') or 'CAD'} {total.get('extracted_lowest') or total.get('lowest') or '?'} total"
            if total
            else nightly_str
        )
        location = str(prop.get("nearby_places", [{}])[0].get("name") if prop.get("nearby_places") else region)
        amenities = prop.get("amenities") or []
        amenity_str = ", ".join(str(a) for a in amenities[:5])
        rating = prop.get("overall_rating") or prop.get("rating")
        reviews = prop.get("reviews")
        review_signal = (
            f"{rating}★ ({reviews} reviews)" if rating and reviews else (f"{rating}★" if rating else "")
        )
        link = str(prop.get("link") or prop.get("serpapi_property_details_link") or deep_link)
        photo_urls = _lodging_photo_urls(prop)
        rank = rank_offset + index
        comfort = 75 + (5 if (rating or 0) >= 4.3 else 0)
        friction = 18 + (8 if not amenities else 0)
        flags: list[str] = []
        if not amenities:
            flags.append("amenity list missing — verify before booking")
        if not rate:
            flags.append("nightly rate not returned; verify live")
        bed_satisfied = None
        if requires_three_beds:
            flags.append("3+ bed signal must be verified live (SerpAPI does not return bed counts)")
        options.append(
            LodgingOption(
                option_id=f"serpapi-lodging-{rank}",
                rank=rank,
                source="Google Hotels (SerpAPI)",
                name=name,
                location_area=location,
                island_or_region=region,
                lodging_type=prop_type,
                bed_layout="Bed layout pending OpenClaw/FireCrawl verification",
                min_three_beds_satisfied=bed_satisfied,
                king_bed_preference_satisfied=None,
                family_of_five_fit=None,
                parking_practicality="verify on listing",
                driving_practicality="verify on listing",
                walkability="verify on map",
                cancellation_notes="cancellation terms not returned; check listing",
                price_band=total_str,
                current_price_signal=nightly_str,
                deep_link=link,
                photo_urls=photo_urls,
                validation_links={"Google Hotels": link},
                friction_score=friction,
                family_comfort_score=comfort,
                recommendation_grade=RecommendationGrade.GOOD if (rating or 0) >= 4 else RecommendationGrade.CONDITIONAL,
                tradeoffs=[
                    f"Live Google Hotels signal: {review_signal}" if review_signal else "Live Google Hotels rate signal.",
                    f"Amenities: {amenity_str}" if amenity_str else "Amenities not returned by SerpAPI.",
                ],
                friction_flags=flags,
                confidence_notes=[
                    "Property and rate came from SerpAPI Google Hotels live search.",
                ],
                live_data_status=LiveDataStatus.LIVE_VERIFIED,
                row_status=ShortlistRowStatus.VERIFIED_LIVE,
                validation=_validation(
                    evidence_url=link,
                    adapter="serpapi/google_hotels",
                    extracted={
                        "name": name,
                        "type": prop_type,
                        "rate_per_night": nightly_str,
                        "total_rate": total_str,
                        "rating": rating,
                        "reviews": reviews,
                        "photo_count": len(photo_urls),
                    },
                    notes=[
                        "Live signal from Google Hotels via SerpAPI; rates can change.",
                        "Bed layout should be verified with OpenClaw/FireCrawl source research.",
                    ],
                ),
            )
        )
    return options


def _lodging_photo_urls(prop: dict[str, Any]) -> list[str]:
    """Collect stable image URLs from known Google Hotels/SerpAPI payload shapes."""
    urls: list[str] = []
    for key in ("images", "photos"):
        values = prop.get(key)
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, str):
                candidate = item
            elif isinstance(item, dict):
                candidate = str(
                    item.get("thumbnail")
                    or item.get("original_image")
                    or item.get("link")
                    or item.get("url")
                    or ""
                )
            else:
                candidate = ""
            if candidate.startswith("http") and candidate not in urls:
                urls.append(candidate)
    thumbnail = str(prop.get("thumbnail") or "")
    if thumbnail.startswith("http") and thumbnail not in urls:
        urls.insert(0, thumbnail)
    return urls[:12]


# ── Cars ─────────────────────────────────────────────────────────


def car_options_from_serpapi(
    results: list[dict[str, Any]],
    *,
    location: str,
    deep_link: str,
    rank_offset: int = 0,
) -> list[CarOption]:
    options: list[CarOption] = []
    for index, item in enumerate(results[:6], start=1):
        title = str(item.get("title") or "Live car-rental signal")
        link = str(item.get("link") or deep_link)
        snippet = str(item.get("snippet") or "")
        rank = rank_offset + index
        options.append(
            CarOption(
                option_id=f"serpapi-car-{rank}",
                rank=rank,
                booking_source=_host(link) or "Google search",
                pickup_location=location,
                dropoff_location=location,
                vehicle_class="verify class on listing",
                price_band="live signal — open listing for fare",
                current_price_signal=snippet[:160] or "open listing",
                seating_capacity=None,
                passenger_fit="verify seating on listing",
                luggage_fit="verify luggage on listing",
                cancellation_notes="verify cancellation on listing",
                fees_caution="verify deposit and one-way fees on listing",
                deep_link=link,
                photo_urls=_car_photo_urls(item),
                comparison_links={"Google search": deep_link},
                family_comfort_score=70,
                luggage_practicality_score=65,
                pickup_dropoff_simplicity_score=70,
                driving_parking_suitability_score=68,
                total_friction_score=30,
                recommendation_grade=RecommendationGrade.CONDITIONAL,
                tradeoffs=[
                    f"Live signal: {title[:120]}",
                    "SerpAPI returns search-result evidence, not direct car inventory.",
                ],
                friction_flags=[
                    "vehicle class, fees, and cancellation must be verified on listing",
                ],
                confidence_notes=[
                    "Result came from SerpAPI Google search; treat as a price/availability signal only.",
                ],
                live_data_status=LiveDataStatus.PARTIAL,
                row_status=ShortlistRowStatus.RESEARCHED,
                validation=_validation(
                    confidence=0.55,
                    evidence_url=link,
                    adapter="serpapi/google",
                    extracted={"title": title, "snippet": snippet},
                    notes=["Live search signal via SerpAPI; not bookable inventory."],
                    price_status=PriceStatus.ESTIMATED_BAND,
                ),
            )
        )
    return options


def _car_photo_urls(item: dict[str, Any]) -> list[str]:
    """Collect source-provided car thumbnails from common SerpAPI result shapes."""
    urls: list[str] = []
    for key in ("thumbnail", "image", "image_url"):
        value = str(item.get(key) or "")
        if value.startswith("http") and value not in urls:
            urls.append(value)
    for key in ("images", "photos"):
        values = item.get(key)
        if not isinstance(values, list):
            continue
        for entry in values:
            if isinstance(entry, str):
                candidate = entry
            elif isinstance(entry, dict):
                candidate = str(
                    entry.get("thumbnail")
                    or entry.get("original_image")
                    or entry.get("link")
                    or entry.get("url")
                    or ""
                )
            else:
                candidate = ""
            if candidate.startswith("http") and candidate not in urls:
                urls.append(candidate)
    return urls[:6]


# ── Activities ───────────────────────────────────────────────────


def activity_options_from_serpapi(
    results: list[dict[str, Any]],
    *,
    region: str,
    deep_link: str,
    rank_offset: int = 0,
) -> list[ActivityOption]:
    options: list[ActivityOption] = []
    for index, item in enumerate(results[:8], start=1):
        title = str(item.get("title") or "Live POI")
        rating = item.get("rating")
        reviews = item.get("reviews")
        types = item.get("types") or []
        type_str = ", ".join(str(t) for t in types[:3])
        address = str(item.get("address") or region)
        maps_link = _google_maps_link(item, title=title, address=address, fallback=deep_link)
        website = str(item.get("website") or "")
        link = website if website.startswith("http") else maps_link
        photo_urls = _activity_photo_urls(item)
        review_signal = (
            f"{rating}★ ({reviews} reviews)" if rating and reviews else (f"{rating}★" if rating else "rating unknown")
        )
        price = str(
            item.get("price")
            or item.get("price_level")
            or item.get("price_description")
            or "open listing for price"
        )
        rank = rank_offset + index
        comfort_pace = 75 if (rating or 0) >= 4.4 else 65
        friction = 22 if (rating or 0) >= 4 else 35
        options.append(
            ActivityOption(
                option_id=f"serpapi-activity-{rank}",
                rank=rank,
                activity_name=title,
                source="Google Maps (SerpAPI)",
                island_location=address,
                group_size_signal="verify on operator site",
                review_safety_signal=review_signal,
                age_family_fit="verify on listing",
                price_band=price,
                duration="verify on listing",
                deep_link=link,
                photo_urls=photo_urls,
                validation_links={
                    **({"Operator website": website} if website.startswith("http") else {}),
                    "Google Maps": maps_link,
                },
                family_pace_fit_score=comfort_pace,
                safety_confidence_score=70 if (rating or 0) >= 4 else 55,
                crowd_fit_score=70,
                total_friction_score=friction,
                recommendation_grade=RecommendationGrade.GOOD if (rating or 0) >= 4 else RecommendationGrade.CONDITIONAL,
                tradeoffs=[
                    f"Live Google Maps signal: {review_signal}",
                    f"Type: {type_str}" if type_str else "Type not categorized.",
                ],
                friction_flags=[
                    "exact duration, group size, and cancellation must be verified on operator site",
                ],
                confidence_notes=[
                    "POI came from SerpAPI Google Maps live search.",
                ],
                live_data_status=LiveDataStatus.LIVE_VERIFIED,
                row_status=ShortlistRowStatus.VERIFIED_LIVE,
                validation=_validation(
                    evidence_url=link,
                    adapter="serpapi/google_maps",
                    extracted={
                        "title": title,
                        "rating": rating,
                        "reviews": reviews,
                        "types": types,
                        "address": address,
                        "website": website,
                        "google_maps_url": maps_link,
                        "photo_count": len(photo_urls),
                    },
                    notes=["Live POI signal from Google Maps via SerpAPI."],
                    price_status=PriceStatus.ESTIMATED_BAND,
                ),
            )
        )
    return options


# ── helpers ──────────────────────────────────────────────────────


def _split_serpapi_timestamp(value: str) -> tuple[str, str]:
    """SerpAPI returns 'YYYY-MM-DD HH:MM' in local airport time."""
    if not value:
        return "", ""
    parts = value.split(" ", 1)
    if len(parts) == 2:
        date_part, time_part = parts
        return date_part, _format_clock(time_part)
    return parts[0], ""


def _format_clock(value: str) -> str:
    m = re.match(r"^(\d{1,2}):(\d{2})", value)
    if not m:
        return value
    hour = int(m.group(1))
    minute = m.group(2)
    suffix = "AM" if hour < 12 else "PM"
    display_hour = hour % 12 or 12
    return f"{display_hour}:{minute} {suffix}"


def _format_minutes(total_minutes: int) -> str:
    if total_minutes <= 0:
        return "duration unavailable"
    h, m = divmod(total_minutes, 60)
    if h and m:
        return f"{h}h {m}m"
    if h:
        return f"{h}h"
    return f"{m}m"


def _host(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "")
    return m.group(1).replace("www.", "") if m else ""


def _activity_photo_urls(item: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for key in ("thumbnail", "image", "image_url"):
        value = str(item.get(key) or "")
        if value.startswith("http") and value not in urls:
            urls.append(value)
    for key in ("photos", "images"):
        values = item.get(key)
        if not isinstance(values, list):
            continue
        for photo in values:
            if isinstance(photo, str):
                candidate = photo
            elif isinstance(photo, dict):
                candidate = str(
                    photo.get("thumbnail")
                    or photo.get("image")
                    or photo.get("url")
                    or photo.get("link")
                    or ""
                )
            else:
                candidate = ""
            if candidate.startswith("http") and candidate not in urls:
                urls.append(candidate)
    return urls[:8]


def _google_maps_link(
    item: dict[str, Any],
    *,
    title: str,
    address: str,
    fallback: str,
) -> str:
    link = str(item.get("link") or item.get("place_link") or "")
    if link.startswith("http"):
        return link
    place_id = str(item.get("place_id") or "")
    if place_id:
        return f"https://www.google.com/maps/place/?q=place_id:{quote_plus(place_id)}"
    query = " ".join(part for part in (title, address) if part).strip()
    if query:
        return f"https://www.google.com/maps/search/?api=1&query={quote_plus(query)}"
    return fallback
