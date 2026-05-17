#!/bin/sh

# Environment variables:
# TELEGRAM_API_ID=
# TELEGRAM_API_HASH=
# TELEGRAM_FETCH_LIMIT=
# TELEGRAM_CHANNELS= (comma separated)
# TELEGRAM_SESSION_INITIAL_S3_URL=
# AI_ENDPOINT=       (OpenAI API endpoint)
# AI_API_KEY=        (OpenAI API key)
# AI_MODEL=          (optional, defaults to gpt-4o)
# AI_PROMPT=         (optional, extra instructions for the AI)
# NOTIFY_USER=       (Telegram username/phone/id to send event notifications to)

set -e

export SESSION_PATH=/tmp/telegram-ai-message-analyzer.py.session

if [ ! -f "$SESSION_PATH" ]; then
    aws s3 cp "$TELEGRAM_SESSION_INITIAL_S3_URL" "$SESSION_PATH"
fi

python3 telegram-ai-message-analyzer.py
