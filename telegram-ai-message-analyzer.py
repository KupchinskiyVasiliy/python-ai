# Before running:
#
#
# You need Telegram API credentials from https://my.telegram.org/apps
#   - api_id and api_hash
#
# On first run, Telethon will ask for your phone number and a login code.
# A session file (telegram_session.session) is saved so you stay logged in.

import asyncio
import json
import os

from telethon import TelegramClient
from telethon.tl.types import (
    MessageMediaPoll,
    PeerChannel,
    PeerChat,
    PeerUser,
    MessageFwdHeader,
)

TELEGRAM_API_ID = int(os.environ['TELEGRAM_API_ID'])
TELEGRAM_API_HASH = os.environ['TELEGRAM_API_HASH']
TELEGRAM_SESSION = "telegram-ai-message-analyzer.py"

INITIAL_FETCH_LIMIT = 300

CHANNELS = [ch.strip() for ch in os.environ['TELEGRAM_CHANNELS'].split(',') if ch.strip()]

# ──────────────────────── Configuration ────────────────────────

# Telegram MTProto credentials (get from https://my.telegram.org/apps)

print(f'Working for channels: {", ".join(CHANNELS)}')

# ──────────────────────── Pointer helpers ────────────────────────

def pointer_file(channel: str) -> str:
    """Return the pointer file path for a given channel."""
    return f"telegram_pointer_{channel}.json"


def load_pointer(channel: str) -> int:
    """Load last_message_id for a channel."""
    path = pointer_file(channel)
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return 0


def save_pointer(channel: str, pointer: int):
    path = pointer_file(channel)
    with open(path, "w") as f:
        json.dump(pointer, f, indent=2)


# ──────────────────────── Telegram helpers ────────────────────────

def format_poll(media: MessageMediaPoll) -> str:
    """Format a poll into readable text."""
    poll = media.poll
    results = media.results
    lines = [f"📊 Poll: {poll.question.text if hasattr(poll.question, 'text') else poll.question}"]
    for i, answer in enumerate(poll.answers):
        answer_text = answer.text.text if hasattr(answer.text, 'text') else answer.text
        # Try to get vote count from results
        votes = ""
        if results and results.results and i < len(results.results):
            votes = f" — {results.results[i].voters} votes"
        lines.append(f"  • {answer_text}{votes}")
    if poll.close_date:
        lines.append(f"  Closes: {poll.close_date}")
    if poll.quiz:
        lines.append("  (Quiz mode)")
    return "\n".join(lines)


def format_forward(fwd: MessageFwdHeader) -> str:
    """Format forwarded-from info."""
    parts = []
    if fwd.from_name:
        parts.append(f"from '{fwd.from_name}'")
    if fwd.from_id:
        if isinstance(fwd.from_id, PeerUser):
            parts.append(f"user_id={fwd.from_id.user_id}")
        elif isinstance(fwd.from_id, PeerChannel):
            parts.append(f"channel_id={fwd.from_id.channel_id}")
        elif isinstance(fwd.from_id, PeerChat):
            parts.append(f"chat_id={fwd.from_id.chat_id}")
    if fwd.date:
        parts.append(f"date={fwd.date.isoformat()}")
    return "Forwarded " + ", ".join(parts) if parts else "Forwarded message"


def format_message(msg) -> str:
    """Convert a Telethon message to a text block for the AI."""
    parts = []

    # Header
    date_str = msg.date.isoformat() if msg.date else "unknown date"
    parts.append(f"[Message #{msg.id} | {date_str}]")

    # Forwarded info
    if msg.fwd_from:
        parts.append(f"  ↪ {format_forward(msg.fwd_from)}")

    # Reply info
    if msg.reply_to and hasattr(msg.reply_to, 'reply_to_msg_id') and msg.reply_to.reply_to_msg_id:
        parts.append(f"  ↩ Reply to message #{msg.reply_to.reply_to_msg_id}")

    # Text body
    if msg.text:
        parts.append(msg.text)

    # Poll
    if msg.media and isinstance(msg.media, MessageMediaPoll):
        parts.append(format_poll(msg.media))

    # Other media (photo, document, etc.) — mention it
    elif msg.media:
        media_type = type(msg.media).__name__
        parts.append(f"[Attachment: {media_type}]")

    return "\n".join(parts)


async def fetch_new_messages(client: TelegramClient, channel: str) -> list[str]:
    """Fetch new messages from the channel since last pointer."""
    min_id = load_pointer(channel)

    print(f"Fetching messages from '{channel}' (after message #{min_id})...")

    entity = await client.get_entity(channel)
    messages = []

    async for msg in client.iter_messages(
        entity,
        min_id=min_id,
        limit=INITIAL_FETCH_LIMIT if min_id == 0 else None,
    ):
        messages.append(msg)

    if not messages:
        print("No new messages.")
        return []

    # Messages come newest-first; reverse to chronological order
    messages.reverse()

    # Update pointer to the newest message ID
    new_max_id = messages[-1].id
    save_pointer(channel, new_max_id)
    print(f"Fetched {len(messages)} new messages. Pointer updated to #{new_max_id}.")

    # Format all messages
    formatted = [format_message(m) for m in messages]
    return formatted


# ──────────────────────── Main ────────────────────────

async def main():
    print("=" * 60)
    print("Telegram AI message Analyzer")
    print("=" * 60)

    # 1. Read Telegram messages from all channels
    all_formatted: list[str] = []
    async with TelegramClient(TELEGRAM_SESSION, TELEGRAM_API_ID, TELEGRAM_API_HASH) as client:
        for channel in CHANNELS:
            formatted_messages = await fetch_new_messages(client, channel)
            if formatted_messages:
                all_formatted.append(f"=== Channel: {channel} ===")
                all_formatted.extend(formatted_messages)

    if not all_formatted:
        print("Nothing to analyze.")
        return

    # 2. Combine messages into a single text block
    all_text = "\n\n---\n\n".join(all_formatted)
    print(f"\nTotal text length: {len(all_text)} chars")


if __name__ == "__main__":
    asyncio.run(main())

