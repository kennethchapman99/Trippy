# Telegram channel for Trippy

This thin slice lets Ken text Trippy from Telegram and receive replies from the existing `TrIppyAgent` runtime.

## What this adds

- Long-polling Telegram Bot API bridge; no webhook or public server required.
- Private allowlist via Telegram chat IDs.
- One `TrIppyAgent` session per chat ID so short conversations keep local agent context.
- Reply chunking so longer agent answers fit Telegram message limits.
- Foundation for later proactive reminders using the same `send_message` path.

## Setup

1. In Telegram, open `@BotFather`.
2. Send `/newbot` and follow the prompts.
3. Copy the bot API token into `.env`:

```bash
TRIPPY_TELEGRAM_BOT_TOKEN=<paste-token-here>
```

4. Start the bot locally in open/dev mode:

```bash
uv run trippy-telegram
```

5. Send `/whoami` to the bot from your phone.
6. Copy the returned chat ID into `.env` and restart the bot:

```bash
TRIPPY_TELEGRAM_ALLOWED_CHAT_IDS=123456789
```

You can allow multiple chats with a comma-separated list:

```bash
TRIPPY_TELEGRAM_ALLOWED_CHAT_IDS=123456789,987654321
```

## Local run

```bash
uv sync
uv run trippy doctor
uv run trippy-telegram
```

Example messages:

```text
/start
/whoami
What trips do we have coming up?
Audit friction for our next trip
What confirmations are missing for Japan 2026?
What should I do today in Rome?
```

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `TRIPPY_TELEGRAM_BOT_TOKEN` | Telegram BotFather token | Required |
| `TRIPPY_TELEGRAM_ALLOWED_CHAT_IDS` | Comma-separated private chat allowlist | Empty = open/dev mode |
| `TRIPPY_TELEGRAM_POLL_TIMEOUT_SECONDS` | Long-poll timeout | `25` |
| `TRIPPY_TELEGRAM_REPLY_CHUNK_SIZE` | Max reply chunk size | `3500` |

## Notes

- This bridge only handles inbound text messages today.
- It does not expose OpenClaw controls directly. It routes text into Trippy, and Trippy can continue to use its existing OpenClaw-backed source research when enabled.
- For proactive reminders, add a scheduler/job that calls `TelegramApiClient.send_message(chat_id, text)` after detecting due reminders from trip state, Gmail, sheets, or friction audits.
