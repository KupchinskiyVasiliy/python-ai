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
import re

from openai import OpenAI

from telethon import TelegramClient
from telethon.tl.types import (
    MessageMediaPoll,
    PeerChannel,
    PeerChat,
    PeerUser,
    MessageFwdHeader,
)

# ──────────────────────── Configuration ────────────────────────

TELEGRAM_API_ID = int(os.environ['TELEGRAM_API_ID'])
TELEGRAM_API_HASH = os.environ['TELEGRAM_API_HASH']
TELEGRAM_SESSION = os.environ['TELEGRAM_SESSION_PATH']

INITIAL_FETCH_LIMIT = int(os.environ['TELEGRAM_FETCH_LIMIT'])

CHANNELS = [ch.strip() for ch in os.environ['TELEGRAM_CHANNELS'].split(',') if ch.strip()]

AI_ENDPOINT = os.environ['AI_ENDPOINT']
AI_API_KEY = os.environ['AI_API_KEY']
AI_MODEL = os.environ.get('AI_MODEL', 'gpt-4o')
AI_PROMPT = os.environ.get('AI_PROMPT', '')

NOTIFY_USER = os.environ.get('NOTIFY_USER', '')  # Telegram username/phone/id to send notifications to

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


# ──────────────────────── AI Analysis ────────────────────────

SYSTEM_PROMPT = """\
Ты — ассистент, который анализирует сообщения из Telegram-канала и извлекает предстоящие события.
Тщательно просмотри ВСЕ предоставленные сообщения.
Для каждого найденного события верни JSON-массив объектов со следующими полями:
- event_name: краткое название события
- description: краткое описание
- when_description: когда происходит событие (как указано в сообщениях)
- source_message_id: числовой ID исходного сообщения (из заголовка [Message #ID | ...])
Верни ТОЛЬКО валидный JSON-массив, без markdown-обёрток, без пояснений.
Если события не найдены, верни [].
"""

def extract_json_array(text: str) -> list:
    """Extract a JSON array from AI response, stripping markdown fences if present."""
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`")
    # Find the outermost [ ... ]
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start != -1 and end != -1:
        return json.loads(cleaned[start : end + 1])
    return []


def build_ai_client() -> OpenAI:
    return OpenAI(
        base_url=AI_ENDPOINT,
        api_key=AI_API_KEY
    )


def analyze_channel_messages(ai_client: OpenAI, channel: str, formatted_messages: list[str]) -> list[dict]:
    """Send messages to Chat Completions API to extract events."""

    combined = "\n\n---\n\n".join(formatted_messages)

    instructions = SYSTEM_PROMPT
    if AI_PROMPT:
        instructions += f"\nAdditional instructions: {AI_PROMPT}"

    response = ai_client.chat.completions.create(
        model=AI_MODEL,
        messages=[
            {"role": "system", "content": instructions},
            {"role": "user", "content": (
                f"Analyze ALL messages from the Telegram channel '{channel}':\n\n"
                f"{combined}\n\n"
                "Extract every upcoming event and return them as a JSON array."
            )},
        ],
    )

    assistant_text = response.choices[0].message.content or ""
    print(f"  AI response length: {len(assistant_text)} chars")

    return extract_json_array(assistant_text)


# ──────────────────────── Notifications ────────────────────────

async def send_notifications(client: TelegramClient, results: dict[str, list[dict]]):
    """Send a Telegram message for each found event to NOTIFY_USER."""
    if not NOTIFY_USER:
        print("NOTIFY_USER not set — skipping notifications.")
        return

    entity = await client.get_entity(NOTIFY_USER)
    sent = 0

    for channel, events in results.items():
        for event in events:
            name = event.get("event_name", "—")
            desc = event.get("description", "—")
            when = event.get("when_description", "—")
            msg_id = event.get("source_message_id")
            channel_clean = channel.lstrip("@")
            source_link = f"https://t.me/{channel_clean}/{msg_id}" if msg_id else ""
            text = (
                f"📢 *{name}*\n"
                f"📝 {desc}\n"
                f"🕐 {when}\n"
                f"📌 Канал: @{channel_clean}"
            )
            if source_link:
                text += f"\n🔗 [Источник]({source_link})"
            await client.send_message(entity, text, parse_mode="md")
            sent += 1

    print(f"Sent {sent} notification(s) to '{NOTIFY_USER}'.")


# ──────────────────────── Main ────────────────────────

async def main():
    print("=" * 60)
    print("Telegram AI Message Analyzer")
    print("=" * 60)

    # 1. Fetch messages from all channels
    async with TelegramClient(TELEGRAM_SESSION, TELEGRAM_API_ID, TELEGRAM_API_HASH) as client:
        channel_messages: dict[str, list[str]] = {}
        for channel in CHANNELS:
            formatted = await fetch_new_messages(client, channel)
            if formatted:
                channel_messages[channel] = formatted

        if not channel_messages:
            print("Nothing to analyze.")
            return

        # 2. Analyze each channel with AI (separate request per channel)
        ai_client = build_ai_client()
        results: dict[str, list[dict]] = {}

        for channel, messages in channel_messages.items():
            print(f"\nAnalyzing channel '{channel}' ({len(messages)} messages)...")
            events = analyze_channel_messages(ai_client, channel, messages)
            results[channel] = events
            print(f"  Found {len(events)} event(s)")

        # 3. Output combined results
        print("\n" + "=" * 60)
        print("Results")
        print("=" * 60)
        print(json.dumps(results, indent=2, ensure_ascii=False))

        # 4. Send notifications
        await send_notifications(client, results)


if __name__ == "__main__":
    asyncio.run(main())
