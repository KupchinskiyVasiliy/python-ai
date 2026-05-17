#!/bin/sh

# Example .env file:
# TELEGRAM_API_ID=
# TELEGRAM_API_HASH=
# TELEGRAM_CHANNELS= (comma separated)
# AI_ENDPOINT=       (Azure AI Foundry endpoint)
# AI_API_KEY=        (Azure AI API key)
# AI_MODEL=          (optional, defaults to gpt-4o)
# AI_PROMPT=         (optional, extra instructions for the AI)
# NOTIFY_USER=       (Telegram username/phone/id to send event notifications to)

set -e
curl --fail-with-body -L https://raw.githubusercontent.com/KupchinskiyVasiliy/python-ai/refs/heads/main/telegram-ai-message-analyzer.py

pip3 install telethon==1.43.2 openai==2.33.0

. .env
python3 telegram-ai-message-analyzer.py
