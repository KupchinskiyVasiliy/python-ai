#!/bin/sh

# Example .env file:
# TELEGRAM_API_ID=
# TELEGRAM_API_HASH=
# TELEGRAM_CHANNELS= (comma separated)
# AI_ENDPOINT=       (OpenAI API endpoint)
# AI_API_KEY=        (OpenAI API key)
# AI_MODEL=          (optional, defaults to gpt-4o)
# AI_PROMPT=         (optional, extra instructions for the AI)
# NOTIFY_USER=       (Telegram username/phone/id to send event notifications to)
# SESSION_INITIAL_S3_URL=

set -e

export SESSION_PATH=/tmp/telegram-ai-message-analyzer.py.session

if [ ! -f "$SESSION_PATH" ]; then
    aws s3 cp "$SESSION_INITIAL_S3_URL" "$SESSION_PATH"
fi

python3 telegram-ai-message-analyzer.py
