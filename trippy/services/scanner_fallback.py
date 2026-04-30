"""Shared Firecrawl/OpenClaw fallback for shortlist source research."""

from __future__ import annotations

import shutil
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from trippy import config
from trippy.models.shortlists import ResearchShortlistState
from trippy.services.source_research import (
    FirecrawlResearchAdapter,
    LinkResearchAdapter,
    OpenClawResearchAdapter,
    SourceResearchService,
)


def scanner_fallback_available() -> bool:
    """Return whether an API-failure scanner fallback can do useful live research."""
    firecrawl_ready = bool(config.FIRECRAWL_ENABLED and config.FIRECRAWL_API_KEY.strip())
    openclaw_ready = _openclaw_ready()
    return firecrawl_ready or openclaw_ready


def _openclaw_ready() -> bool:
    if not config.SOURCE_RESEARCH_OPENCLAW_ENABLED:
        return False
    if shutil.which(config.OPENCLAW_COMMAND) is None:
        return False
    try:
        request = Request(
            config.OPENCLAW_GATEWAY_URL.rstrip("/") + "/health",
            headers={"User-Agent": "Trippy/0.2 scanner fallback health"},
        )
        with urlopen(request, timeout=0.5) as response:  # noqa: S310 - localhost health probe
            return 200 <= int(getattr(response, "status", 200)) < 400
    except (HTTPError, URLError, OSError, TimeoutError, ValueError):
        return False


def run_scanner_fallback(
    state: ResearchShortlistState,
    *,
    adapter_mode: str = "auto",
    reason: str,
) -> ResearchShortlistState:
    """Run read-only scanner research without falling through to raw HTTP scraping.

    The normal deep-research path can still use every adapter. This fallback is specifically
    for provider/API failure, where Firecrawl and OpenClaw are the intended second line.
    """
    state.warnings.append(reason)
    state.artifacts["scanner_fallback"] = {
        "status": "attempted",
        "adapter_mode": adapter_mode,
        "reason": reason,
    }
    researched = SourceResearchService(
        adapters=[
            FirecrawlResearchAdapter(),
            OpenClawResearchAdapter(),
            LinkResearchAdapter(),
        ]
    ).research_state(state, adapter_mode=adapter_mode)
    researched.artifacts["scanner_fallback"]["status"] = researched.artifacts.get(
        "deep_research", {}
    ).get("status", "unknown")
    return researched
