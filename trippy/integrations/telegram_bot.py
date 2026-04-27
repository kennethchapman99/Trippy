"""Telegram Bot API channel for texting with Trippy.

This is intentionally dependency-light: it uses Telegram's HTTPS Bot API directly
so the feature works with the existing project dependencies.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from trippy.agent import TrIppyAgent

logger = logging.getLogger(__name__)

TRIPPY_TELEGRAM_BOT_TOKEN_ENV = "TRIPPY_TELEGRAM_BOT_TOKEN"
TRIPPY_TELEGRAM_ALLOWED_CHAT_IDS_ENV = "TRIPPY_TELEGRAM_ALLOWED_CHAT_IDS"
TRIPPY_TELEGRAM_POLL_TIMEOUT_ENV = "TRIPPY_TELEGRAM_POLL_TIMEOUT_SECONDS"
TRIPPY_TELEGRAM_REPLY_CHUNK_SIZE_ENV = "TRIPPY_TELEGRAM_REPLY_CHUNK_SIZE"

TelegramAgentFactory = Callable[[], TrIppyAgent]


@dataclass(frozen=True)
class TelegramBotSettings:
    """Runtime settings for the Telegram polling bridge."""

    token: str
    allowed_chat_ids: frozenset[int]
    poll_timeout_seconds: int = 25
    reply_chunk_size: int = 3500

    @classmethod
    def from_env(cls) -> "TelegramBotSettings":
        token = os.environ.get(TRIPPY_TELEGRAM_BOT_TOKEN_ENV, "").strip()
        if not token:
            raise ValueError(f"{TRIPPY_TELEGRAM_BOT_TOKEN_ENV} is required")
        return cls(
            token=token,
            allowed_chat_ids=parse_allowed_chat_ids(
                os.environ.get(TRIPPY_TELEGRAM_ALLOWED_CHAT_IDS_ENV, "")
            ),
            poll_timeout_seconds=_positive_int_env(TRIPPY_TELEGRAM_POLL_TIMEOUT_ENV, 25),
            reply_chunk_size=_positive_int_env(TRIPPY_TELEGRAM_REPLY_CHUNK_SIZE_ENV, 3500),
        )


def parse_allowed_chat_ids(raw: str) -> frozenset[int]:
    """Parse comma-separated Telegram chat IDs.

    Empty means local/dev open mode. Production should always set an allowlist.
    """
    values: set[int] = set()
    for part in raw.split(","):
        item = part.strip()
        if not item:
            continue
        try:
            values.add(int(item))
        except ValueError as exc:
            raise ValueError(f"Invalid Telegram chat ID: {item!r}") from exc
    return frozenset(values)


def _positive_int_env(key: str, default: int) -> int:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{key} must be positive")
    return value


class TelegramApiClient:
    """Minimal Telegram Bot API client."""

    def __init__(self, token: str, *, timeout_seconds: int = 30) -> None:
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._timeout_seconds = timeout_seconds

    def get_updates(self, *, offset: int | None, timeout_seconds: int) -> list[dict[str, Any]]:
        params: dict[str, object] = {
            "timeout": timeout_seconds,
            "allowed_updates": json.dumps(["message"]),
        }
        if offset is not None:
            params["offset"] = offset
        payload = self._call("getUpdates", params)
        result = payload.get("result", [])
        if not isinstance(result, list):
            return []
        return [cast(dict[str, Any], item) for item in result if isinstance(item, dict)]

    def send_message(self, chat_id: int, text: str) -> None:
        self._call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
        )

    def _call(self, method: str, params: dict[str, object]) -> dict[str, Any]:
        encoded = urlencode(params).encode("utf-8")
        request = Request(
            f"{self._base_url}/{method}",
            data=encoded,
            headers={"User-Agent": "Trippy Telegram Bot", "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:  # noqa: S310 - Telegram Bot API endpoint
                raw = response.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"Telegram API call failed for {method}: {exc}") from exc
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise RuntimeError(f"Telegram API returned an error for {method}: {payload}")
        return cast(dict[str, Any], payload)


class TelegramTrippyBot:
    """Poll Telegram, route text messages into TrippyAgent, and reply."""

    def __init__(
        self,
        settings: TelegramBotSettings,
        *,
        api_client: TelegramApiClient | None = None,
        agent_factory: TelegramAgentFactory | None = None,
    ) -> None:
        self._settings = settings
        self._api = api_client or TelegramApiClient(settings.token)
        self._agent_factory = agent_factory or TrIppyAgent
        self._agents_by_chat_id: dict[int, TrIppyAgent] = {}

    def run_forever(self) -> None:
        """Run long polling until interrupted by the process manager/user."""
        offset: int | None = None
        logger.info("Starting Trippy Telegram polling")
        while True:
            try:
                updates = self._api.get_updates(
                    offset=offset,
                    timeout_seconds=self._settings.poll_timeout_seconds,
                )
                for update in updates:
                    offset = int(update.get("update_id", 0)) + 1
                    self.handle_update(update)
            except KeyboardInterrupt:
                raise
            except Exception:
                logger.exception("Telegram polling loop failed; retrying after short backoff")
                time.sleep(3)

    def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat")
        if not isinstance(chat, dict):
            return
        chat_id_raw = chat.get("id")
        if not isinstance(chat_id_raw, int):
            return
        chat_id = chat_id_raw
        text_raw = message.get("text")
        if not isinstance(text_raw, str) or not text_raw.strip():
            return
        text = text_raw.strip()

        if self._settings.allowed_chat_ids and chat_id not in self._settings.allowed_chat_ids:
            logger.warning("Rejected Telegram message from unauthorized chat_id=%s", chat_id)
            self._api.send_message(chat_id, "This Trippy bot is private.")
            return

        if text in {"/start", "/help"}:
            self._api.send_message(
                chat_id,
                "Text Trippy questions like: 'What confirmations are missing for Japan?' or 'Audit friction for our next trip.'",
            )
            return

        agent = self._agents_by_chat_id.get(chat_id)
        if agent is None:
            agent = self._agent_factory()
            self._agents_by_chat_id[chat_id] = agent
        try:
            reply = agent.chat(text)
        except Exception:
            logger.exception("Trippy agent failed while handling Telegram message")
            reply = "Trippy hit an internal error handling that message. Check the local logs."

        for chunk in chunk_reply(reply, self._settings.reply_chunk_size):
            self._api.send_message(chat_id, chunk)


def chunk_reply(text: str, chunk_size: int) -> list[str]:
    """Split replies into Telegram-safe chunks while preserving readability."""
    normalized = text.strip() or "Done."
    if len(normalized) <= chunk_size:
        return [normalized]
    chunks: list[str] = []
    remaining = normalized
    while len(remaining) > chunk_size:
        split_at = remaining.rfind("\n", 0, chunk_size)
        if split_at < chunk_size // 2:
            split_at = remaining.rfind(" ", 0, chunk_size)
        if split_at < chunk_size // 2:
            split_at = chunk_size
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def run_telegram_bot() -> None:
    """Entrypoint used by the CLI."""
    logging.basicConfig(level=logging.INFO)
    TelegramTrippyBot(TelegramBotSettings.from_env()).run_forever()
