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
import tempfile

from azure.ai.projects import AIProjectClient
from azure.core.credentials import AzureKeyCredential
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
TELEGRAM_SESSION = "telegram-ai-message-analyzer.py"

INITIAL_FETCH_LIMIT = 300

CHANNELS = [ch.strip() for ch in os.environ['TELEGRAM_CHANNELS'].split(',') if ch.strip()]

AI_ENDPOINT = os.environ['AI_ENDPOINT']
AI_API_KEY = os.environ['AI_API_KEY']
AI_MODEL = os.environ.get('AI_MODEL', 'gpt-4o')
AI_PROMPT = os.environ.get('AI_PROMPT', '')

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
You are an assistant that analyzes Telegram channel messages and extracts upcoming events.
Search through ALL the attached files thoroughly.
For each event found, return a JSON array of objects with exactly these fields:
- event_name: short name of the event
- description: brief description
- when_description: when the event happens (as described in the messages)
Return ONLY a valid JSON array, no markdown fences, no explanation.
If no events found, return [].
"""


def build_ai_client() -> AIProjectClient:
    return AIProjectClient(
        endpoint=AI_ENDPOINT,
        credential=AzureKeyCredential(AI_API_KEY),
    )


def extract_json_array(text: str) -> list:
    """Extract a JSON array from AI response, stripping markdown fences if present."""
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`")
    # Find the outermost [ ... ]
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start != -1 and end != -1:
        return json.loads(cleaned[start : end + 1])
    return []


def analyze_channel_messages(ai_client: AIProjectClient, channel: str, formatted_messages: list[str]) -> list[dict]:
    """Upload messages as a file, create a vector store, and use an agent with
    file_search to extract events — saves tokens by letting the model retrieve
    only relevant chunks instead of reading the full message history."""

    # Write messages to a temporary file
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, prefix=f"ch_{channel}_"
    )
    try:
        tmp.write("\n\n---\n\n".join(formatted_messages))
        tmp.close()

        # Upload file & build vector store
        uploaded_file = ai_client.agents.upload_file(file_path=tmp.name, purpose="assistants")
        print(f"  Uploaded file {uploaded_file.id} ({os.path.getsize(tmp.name)} bytes)")

        vector_store = ai_client.agents.create_vector_store_and_poll(
            file_ids=[uploaded_file.id],
            name=f"channel-{channel}",
        )
        print(f"  Vector store {vector_store.id} ready")

        # Create agent with file_search tool
        instructions = SYSTEM_PROMPT
        if AI_PROMPT:
            instructions += f"\nAdditional instructions: {AI_PROMPT}"

        agent = ai_client.agents.create_agent(
            model=AI_MODEL,
            name=f"analyzer-{channel}",
            instructions=instructions,
            tools=[{"type": "file_search"}],
            tool_resources={"file_search": {"vector_store_ids": [vector_store.id]}},
        )

        # Run conversation
        thread = ai_client.agents.create_thread()
        ai_client.agents.create_message(
            thread_id=thread.id,
            role="user",
            content=(
                f"Analyze ALL messages from the Telegram channel '{channel}' "
                "in the attached file. Extract every upcoming event and return "
                "them as a JSON array."
            ),
        )
        run = ai_client.agents.create_and_process_run(
            thread_id=thread.id, agent_id=agent.id
        )

        if run.status == "failed":
            print(f"  ✗ AI run failed: {run.last_error}")
            return []

        # Read assistant reply
        msgs = ai_client.agents.list_messages(thread_id=thread.id)
        assistant_text = ""
        for content_block in msgs.data[0].content:
            if hasattr(content_block, "text"):
                assistant_text += content_block.text.value
        print(f"  AI response length: {len(assistant_text)} chars")

        # Cleanup remote resources
        ai_client.agents.delete_agent(agent.id)
        ai_client.agents.delete_vector_store(vector_store.id)
        ai_client.agents.delete_file(uploaded_file.id)

        return extract_json_array(assistant_text)
    finally:
        os.unlink(tmp.name)


# ──────────────────────── Main ────────────────────────

async def main():
    print("=" * 60)
    print("Telegram AI Message Analyzer")
    print("=" * 60)

    # 1. Fetch messages from all channels
    channel_messages: dict[str, list[str]] = {}
    async with TelegramClient(TELEGRAM_SESSION, TELEGRAM_API_ID, TELEGRAM_API_HASH) as client:
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


if __name__ == "__main__":
    asyncio.run(main())
