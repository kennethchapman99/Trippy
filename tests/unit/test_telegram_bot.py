"""Unit tests for the Telegram text channel."""

from __future__ import annotations

from typing import Any

import pytest

from trippy.integrations.telegram_bot import (
    TelegramBotSettings,
    TelegramTrippyBot,
    chunk_reply,
    parse_allowed_chat_ids,
)


class FakeTelegramApi:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    def get_updates(self, *, offset: int | None, timeout_seconds: int) -> list[dict[str, Any]]:
        return []

    def send_message(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))


class FakeAgent:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def chat(self, user_message: str) -> str:
        self.messages.append(user_message)
        return f"reply: {user_message}"


def test_parse_allowed_chat_ids() -> None:
    assert parse_allowed_chat_ids("123, 456") == frozenset({123, 456})


def test_parse_allowed_chat_ids_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="Invalid Telegram chat ID"):
        parse_allowed_chat_ids("123, nope")


def test_chunk_reply_splits_on_readable_boundary() -> None:
    chunks = chunk_reply("first sentence\nsecond sentence", 16)

    assert chunks == ["first sentence", "second sentence"]


def test_handle_update_routes_allowed_text_to_trippy_agent() -> None:
    api = FakeTelegramApi()
    agent = FakeAgent()
    bot = TelegramTrippyBot(
        TelegramBotSettings(token="test", allowed_chat_ids=frozenset({123}), reply_chunk_size=100),
        api_client=api,
        agent_factory=lambda: agent,
    )

    bot.handle_update({"message": {"chat": {"id": 123}, "text": "Audit friction for Japan"}})

    assert agent.messages == ["Audit friction for Japan"]
    assert api.sent == [(123, "reply: Audit friction for Japan")]


def test_handle_update_rejects_unauthorized_chat() -> None:
    api = FakeTelegramApi()
    agent = FakeAgent()
    bot = TelegramTrippyBot(
        TelegramBotSettings(token="test", allowed_chat_ids=frozenset({123})),
        api_client=api,
        agent_factory=lambda: agent,
    )

    bot.handle_update({"message": {"chat": {"id": 999}, "text": "hello"}})

    assert agent.messages == []
    assert api.sent == [(999, "This Trippy bot is private.")]


def test_help_command_returns_usage_hint() -> None:
    api = FakeTelegramApi()
    bot = TelegramTrippyBot(
        TelegramBotSettings(token="test", allowed_chat_ids=frozenset({123})),
        api_client=api,
        agent_factory=FakeAgent,
    )

    bot.handle_update({"message": {"chat": {"id": 123}, "text": "/help"}})

    assert api.sent
    assert "Text Trippy questions" in api.sent[0][1]
    assert "/whoami" in api.sent[0][1]


def test_whoami_command_returns_chat_id() -> None:
    api = FakeTelegramApi()
    bot = TelegramTrippyBot(
        TelegramBotSettings(token="test", allowed_chat_ids=frozenset({123})),
        api_client=api,
        agent_factory=FakeAgent,
    )

    bot.handle_update({"message": {"chat": {"id": 123}, "text": "/whoami"}})

    assert api.sent == [(123, "Telegram chat ID: 123")]
