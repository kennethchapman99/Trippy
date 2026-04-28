#!/usr/bin/env python3
"""Cloud-safe Firecrawl probe for travel web intelligence."""

from __future__ import annotations

import argparse
import json

from trippy.services.firecrawl import FirecrawlService
from trippy.services.web_intelligence import TravelWebIntelligenceService


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe Firecrawl travel extraction")
    parser.add_argument(
        "--domain", choices=["flights", "lodging", "cars", "activities"], required=True
    )
    parser.add_argument("--destination", default="")
    parser.add_argument("--dates", default="")
    parser.add_argument("--travelers", default="")
    parser.add_argument("--query", required=True)
    args = parser.parse_args()

    firecrawl = FirecrawlService()
    availability = firecrawl.availability()
    web = TravelWebIntelligenceService(firecrawl=firecrawl)

    print(
        json.dumps({"firecrawl_available": availability.available, "reason": availability.reason})
    )

    if args.domain == "lodging":
        rows = web.research_lodging_web(args.query)
    elif args.domain == "activities":
        rows = web.research_activities_web(args.query)
    elif args.domain == "cars":
        rows = web.enrich_car_rental_with_web_context(args.query)
    else:
        rows = [web.enrich_flight_with_web_context(args.query)]

    print(json.dumps([row.model_dump(mode="json") for row in rows], indent=2))


if __name__ == "__main__":
    main()
