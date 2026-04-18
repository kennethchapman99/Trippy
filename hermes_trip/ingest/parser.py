"""Confirmation email parser — extracts structured booking data via Claude."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic output schema
# ---------------------------------------------------------------------------


class ParsedConfirmation(BaseModel):
    confirmation_type: str  # flight | hotel | rental | tour | transfer | other
    confirmation_code: str
    vendor: str
    # Flight-specific
    origin: str | None = None
    destination: str | None = None
    depart_at: str | None = None  # ISO datetime string
    arrive_at: str | None = None
    flight_number: str | None = None
    cabin_class: str | None = None
    # Stay-specific
    property_name: str | None = None
    city: str | None = None
    country: str | None = None
    check_in: str | None = None  # ISO date string
    check_out: str | None = None
    # Common
    cost_cad: float | None = None
    traveler_names: list[str] = []
    notes: str | None = None
    confidence: float = 1.0


_EXTRACT_CONFIRMATION_TOOL: dict[str, Any] = {
    "name": "extract_confirmation",
    "description": (
        "Extract structured booking data from a travel confirmation email or attachment."
    ),
    "input_schema": {
        "type": "object",
        "required": ["confirmation_type", "confirmation_code", "vendor"],
        "properties": {
            "confirmation_type": {
                "type": "string",
                "enum": ["flight", "hotel", "rental", "tour", "transfer", "other"],
            },
            "confirmation_code": {"type": "string"},
            "vendor": {"type": "string"},
            "origin": {"type": ["string", "null"]},
            "destination": {"type": ["string", "null"]},
            "depart_at": {"type": ["string", "null"], "description": "ISO 8601 datetime"},
            "arrive_at": {"type": ["string", "null"], "description": "ISO 8601 datetime"},
            "flight_number": {"type": ["string", "null"]},
            "cabin_class": {"type": ["string", "null"]},
            "property_name": {"type": ["string", "null"]},
            "city": {"type": ["string", "null"]},
            "country": {"type": ["string", "null"]},
            "check_in": {"type": ["string", "null"], "description": "ISO 8601 date"},
            "check_out": {"type": ["string", "null"], "description": "ISO 8601 date"},
            "cost_cad": {"type": ["number", "null"]},
            "traveler_names": {"type": "array", "items": {"type": "string"}},
            "notes": {"type": ["string", "null"]},
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Overall extraction confidence",
            },
        },
    },
}

_SYSTEM_PROMPT = """\
You are a travel-booking data extractor for the Chapman family (Ken, Melissa, and three kids).
Extract structured fields from the provided email text and/or attachment text.

Rules:
- Use IATA codes for airports where possible (e.g. YYZ, NRT).
- Dates and times in ISO 8601 (2026-03-15 or 2026-03-15T13:30:00).
- Convert costs to CAD if possible; if currency unknown set cost_cad to null.
- confirmation_code: booking reference / PNR / reservation number.
- confidence: your overall certainty (0–1) that you extracted correct data.
- If a field is not present in the text, use null.
"""


# ---------------------------------------------------------------------------
# PDF / attachment text extraction
# ---------------------------------------------------------------------------


def _extract_pdf_text(data: bytes) -> str:
    """Return text from a PDF byte string; falls back to empty string on error."""
    try:
        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        parts: list[str] = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                parts.append(text)
        return "\n".join(parts)
    except Exception as exc:
        logger.warning("pypdf extraction failed: %s", exc)
        return ""


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass
class ParserResult:
    ok: bool
    confirmation: ParsedConfirmation | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# ConfirmationParser
# ---------------------------------------------------------------------------


class ConfirmationParser:
    """Parses booking confirmation emails into structured data using Claude.

    Pass ``anthropic_client`` to inject a mock in tests; omit for production.
    """

    def __init__(self, anthropic_client: Any | None = None) -> None:
        if anthropic_client is not None:
            self._client = anthropic_client
        else:
            import anthropic

            self._client = anthropic.Anthropic()

    # ------------------------------------------------------------------

    def parse(
        self,
        body_text: str,
        body_html: str = "",
        attachments: list[tuple[str, str, bytes]] | None = None,
        eml_path: Path | None = None,
    ) -> ParserResult:
        """Parse an email body (+ optional attachments) into a ParsedConfirmation.

        ``attachments`` is a list of ``(filename, content_type, data)`` tuples.
        ``eml_path`` is used only for logging/tracing.
        """
        content_parts: list[str] = []

        if body_text:
            content_parts.append(f"=== EMAIL BODY (TEXT) ===\n{body_text}")
        if body_html:
            # Strip tags crudely for context; not perfect but helps Claude
            import re

            clean = re.sub(r"<[^>]+>", " ", body_html)
            clean = re.sub(r"\s{2,}", " ", clean).strip()
            content_parts.append(f"=== EMAIL BODY (HTML, tags stripped) ===\n{clean}")

        for fname, ctype, data in (attachments or []):
            if ctype == "application/pdf" or fname.lower().endswith(".pdf"):
                pdf_text = _extract_pdf_text(data)
                if pdf_text:
                    content_parts.append(f"=== ATTACHMENT: {fname} ===\n{pdf_text}")

        if not content_parts:
            return ParserResult(ok=False, error="No parseable content in email")

        full_text = "\n\n".join(content_parts)[:12_000]  # stay within context

        try:
            result = self._call_claude(full_text)
            return ParserResult(ok=True, confirmation=result)
        except Exception as exc:
            logger.warning("ConfirmationParser failed for %s: %s", eml_path, exc)
            return ParserResult(ok=False, error=str(exc))

    def _call_claude(self, text: str) -> ParsedConfirmation:
        from anthropic.types import ToolChoiceToolParam, ToolParam

        tool: ToolParam = {
            "name": _EXTRACT_CONFIRMATION_TOOL["name"],
            "description": _EXTRACT_CONFIRMATION_TOOL["description"],
            "input_schema": _EXTRACT_CONFIRMATION_TOOL["input_schema"],
        }
        tool_choice: ToolChoiceToolParam = {"type": "tool", "name": "extract_confirmation"}

        message = self._client.messages.create(
            model="claude-opus-4-7",
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            tools=[tool],
            tool_choice=tool_choice,
            messages=[{"role": "user", "content": text}],
        )

        from anthropic.types import ToolUseBlock

        for block in message.content:
            if isinstance(block, ToolUseBlock) and block.name == "extract_confirmation":
                return ParsedConfirmation.model_validate(block.input)
            # MagicMock fallback for tests
            b_type = getattr(block, "type", None)
            b_name = getattr(block, "name", None)
            b_input = getattr(block, "input", None)
            if b_type == "tool_use" and b_name == "extract_confirmation" and b_input is not None:
                return ParsedConfirmation.model_validate(b_input)

        raise RuntimeError("Claude did not return an extract_confirmation tool call")
