#!/bin/sh

# Example .env file:
# TELEGRAM_API_ID=
# TELEGRAM_API_HASH=
# TELEGRAM_CHANNELS= (comma separated)
# AI_PROMPT=

set -e
curl --fail-with-body -L https://raw.githubusercontent.com/KupchinskiyVasiliy/python-ai/refs/heads/main/telegram-ai-message-analyzer.py

pip3 install telethon==1.43.2 azure-ai-projects==2.1.0 openai==2.33.0

. .env
python3 telegram-ai-message-analyzer.py
