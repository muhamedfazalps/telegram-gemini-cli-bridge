# Telegram Gemini CLI Bridge

A small Python bot that lets you talk to a local Gemini CLI session through Telegram.

It was reconstructed from a previous local working script and cleaned for publication:
- no embedded bot tokens
- no local paths beyond configurable defaults
- no checked-in secrets

## What it does

- receives Telegram messages
- forwards them to a local `gemini` CLI process
- returns the CLI response back to Telegram
- supports `/start`, `/help`, `/status`, and `/reset`

## Requirements

- Python 3.9+
- A Telegram bot token from `@BotFather`
- Gemini CLI installed and available on your `PATH`

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and fill in your values:

```env
TELEGRAM_BOT_TOKEN=replace_with_your_bot_token
GEMINI_CLI_PATH=gemini
```

4. Run the bot:

```bash
python telegram_gemini_bridge.py
```

## Notes

- The bridge keeps a persistent Gemini CLI subprocess for faster follow-up replies.
- The response parsing is heuristic because CLI output formats vary by version.
- If your Gemini executable is not named `gemini`, set `GEMINI_CLI_PATH` explicitly.

## Security

- Do not commit `.env`.
- Regenerate any token that was previously pasted into local chats, config files, or transcripts.

## Origin

This project was inspired by a local prototype and the broader idea of remote Gemini CLI access over Telegram.
