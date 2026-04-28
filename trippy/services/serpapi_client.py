"""SerpAPI live-data client.

One key (``SERPAPI_KEY``) gives Trippy live-signal data across flights,
hotels, and points-of-interest by wrapping Google Travel results. Each
function returns ``[]`` and a list of human-readable notes when the key
is missing or the request fails — callers fall back to source-link
handoff candidates.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from trippy import config

_BASE_URL = "https://serpapi.com/search.json"


def is_configured() -> bool:
    return bool(config.SERPAPI_KEY.strip())


def _get(params: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    if not is_configured():
        return None, "SERPAPI_KEY is not configured"
    query = {**params, "api_key": config.SERPAPI_KEY}
    url = f"{_BASE_URL}?{urlencode(query)}"
    request = Request(url, headers={"User-Agent": "Trippy/0.2 serpapi-client"})
    try:
        with urlopen(request, timeout=config.SERPAPI_TIMEOUT_SECONDS) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        return None, f"SerpAPI request failed: {exc}"
    error = payload.get("error") if isinstance(payload, dict) else None
    if error:
        return None, f"SerpAPI returned error: {error}"
    return payload, None


def search_flights(
    *,
    origin: str,
    destination: str,
    departure_date: date,
    return_date: date | None,
    adults: int = 1,
    children: int = 0,
    currency: str = "CAD",
    gl: str = "ca",
    hl: str = "en",
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (offers, notes) — offers are best_flights | other_flights merged."""
    params: dict[str, Any] = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": departure_date.isoformat(),
        "currency": currency,
        "hl": hl,
        "gl": gl,
        "adults": adults,
        "children": children,
        "type": "1" if return_date else "2",
    }
    if return_date:
        params["return_date"] = return_date.isoformat()
    payload, error = _get(params)
    if error or payload is None:
        return [], [error or "SerpAPI returned no payload"]
    best = payload.get("best_flights") or []
    other = payload.get("other_flights") or []
    merged = [item for item in (best + other) if isinstance(item, dict)]
    notes = []
    if not merged:
        notes.append("SerpAPI Google Flights returned no offers for this route/date.")
    else:
        notes.append(f"SerpAPI Google Flights returned {len(merged)} offer(s).")
    return merged, notes


def search_hotels(
    *,
    query: str,
    check_in: date,
    check_out: date,
    adults: int = 2,
    children_ages: list[int] | None = None,
    currency: str = "CAD",
    gl: str = "ca",
    hl: str = "en",
) -> tuple[list[dict[str, Any]], list[str]]:
    params: dict[str, Any] = {
        "engine": "google_hotels",
        "q": query,
        "check_in_date": check_in.isoformat(),
        "check_out_date": check_out.isoformat(),
        "adults": adults,
        "currency": currency,
        "gl": gl,
        "hl": hl,
    }
    if children_ages:
        params["children"] = len(children_ages)
        params["children_ages"] = ",".join(str(int(age)) for age in children_ages)
    payload, error = _get(params)
    if error or payload is None:
        return [], [error or "SerpAPI returned no payload"]
    properties = payload.get("properties") or []
    listings = [item for item in properties if isinstance(item, dict)]
    notes = []
    if not listings:
        notes.append("SerpAPI Google Hotels returned no properties for this query/date.")
    else:
        notes.append(f"SerpAPI Google Hotels returned {len(listings)} property listing(s).")
    return listings, notes


def search_things_to_do(
    *,
    query: str,
    near: str = "",
    gl: str = "ca",
    hl: str = "en",
) -> tuple[list[dict[str, Any]], list[str]]:
    """Use Google Maps engine to surface POIs / activities with ratings + price level."""
    full_query = f"{query} {near}".strip() if near else query
    params: dict[str, Any] = {
        "engine": "google_maps",
        "q": full_query,
        "type": "search",
        "gl": gl,
        "hl": hl,
    }
    payload, error = _get(params)
    if error or payload is None:
        return [], [error or "SerpAPI returned no payload"]
    local = payload.get("local_results") or []
    items = [item for item in local if isinstance(item, dict)]
    notes = []
    if not items:
        notes.append(f"SerpAPI Google Maps returned no results for '{full_query}'.")
    else:
        notes.append(f"SerpAPI Google Maps returned {len(items)} POI(s).")
    return items, notes


def search_car_rentals(
    *,
    location: str,
    pickup_date: date,
    return_date: date,
    gl: str = "ca",
    hl: str = "en",
) -> tuple[list[dict[str, Any]], list[str]]:
    """SerpAPI does not yet expose a Google Cars engine.

    We fall back to a Google search for car rentals at the location, which
    returns organic results + ad knowledge cards — enough to give a live
    price signal and link evidence even without a dedicated engine.
    """
    query = (
        f"car rental {location} pickup {pickup_date.isoformat()} "
        f"return {return_date.isoformat()}"
    )
    params: dict[str, Any] = {
        "engine": "google",
        "q": query,
        "gl": gl,
        "hl": hl,
    }
    payload, error = _get(params)
    if error or payload is None:
        return [], [error or "SerpAPI returned no payload"]
    organic = payload.get("organic_results") or []
    items = [item for item in organic if isinstance(item, dict)]
    knowledge = payload.get("knowledge_graph")
    if isinstance(knowledge, dict):
        items.insert(0, {"title": knowledge.get("title"), "link": knowledge.get("website"), "snippet": knowledge.get("description")})
    notes = []
    if not items:
        notes.append(f"SerpAPI returned no car-rental signal for {location}.")
    else:
        notes.append(f"SerpAPI returned {len(items)} car-rental search result(s); price signal only, not bookable.")
    return items, notes
