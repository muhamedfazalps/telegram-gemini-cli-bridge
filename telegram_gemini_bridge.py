#!/usr/bin/env python3
"""
Telegram bridge for Gemini CLI.

This bot forwards Telegram messages to a local Gemini CLI process and returns
the CLI output back to Telegram.
"""

import asyncio
import logging
import os
import subprocess
import sys
from typing import Optional

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=getattr(logging, LOG_LEVEL, logging.INFO),
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_CLI_PATH = os.getenv("GEMINI_CLI_PATH", "gemini")
MAX_MESSAGE_LENGTH = 4096
RESPONSE_TIMEOUT = int(os.getenv("RESPONSE_TIMEOUT", "30"))
STARTUP_DELAY_SECONDS = float(os.getenv("STARTUP_DELAY_SECONDS", "2"))


class GeminiCLIBridge:
    def __init__(self) -> None:
        self.process: Optional[subprocess.Popen] = None
        self.output_queue: asyncio.Queue[str] = asyncio.Queue()
        self.read_task: Optional[asyncio.Task] = None

    async def start_gemini_cli(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return

        try:
            logger.info("Starting Gemini CLI: %s", GEMINI_CLI_PATH)
            self.process = subprocess.Popen(
                [GEMINI_CLI_PATH],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=False,
                bufsize=0,
            )
            self.read_task = asyncio.create_task(self._read_output())
            await asyncio.sleep(STARTUP_DELAY_SECONDS)
            await self._drain_queue()
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Gemini CLI not found at '{GEMINI_CLI_PATH}'. "
                "Install it or set GEMINI_CLI_PATH."
            ) from exc
        except Exception:
            self.cleanup()
            raise

    async def _read_output(self) -> None:
        try:
            while self.process and self.process.poll() is None:
                if self.process.stdout is None:
                    break

                line_bytes = self.process.stdout.readline()
                if not line_bytes:
                    break

                line = line_bytes.decode("utf-8", errors="replace").strip()
                if line:
                    await self.output_queue.put(line)
        except Exception as exc:
            logger.error("Error reading Gemini CLI output: %s", exc)
        finally:
            logger.info("Gemini CLI output reader stopped")

    async def _drain_queue(self) -> None:
        while not self.output_queue.empty():
            try:
                self.output_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def send_to_gemini(self, message: str) -> str:
        await self.start_gemini_cli()

        if not self.process or self.process.poll() is not None:
            return "Gemini CLI is not running."

        if self.process.stdin is None:
            return "Gemini CLI stdin is unavailable."

        try:
            await self._drain_queue()
            self.process.stdin.write((message + "\n").encode("utf-8"))
            self.process.stdin.flush()
            response = await self._wait_for_response()
            return response or "Gemini CLI did not produce any output."
        except Exception as exc:
            logger.error("Error communicating with Gemini CLI: %s", exc)
            self.cleanup()
            return f"Error communicating with Gemini CLI: {exc}"

    async def _wait_for_response(self) -> str:
        response_lines: list[str] = []
        deadline = asyncio.get_event_loop().time() + RESPONSE_TIMEOUT

        while asyncio.get_event_loop().time() < deadline:
            try:
                line = await asyncio.wait_for(self.output_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                if response_lines:
                    break
                continue

            if self._looks_like_prompt(line):
                if response_lines:
                    break
                continue

            response_lines.append(line)

        return "\n".join(response_lines).strip()

    @staticmethod
    def _looks_like_prompt(line: str) -> bool:
        stripped = line.strip()
        return stripped in {">", "$", "#"} or stripped.endswith((">", "$", ":"))

    def cleanup(self) -> None:
        if self.read_task and not self.read_task.done():
            self.read_task.cancel()

        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            except Exception as exc:
                logger.error("Error terminating Gemini CLI: %s", exc)

        self.process = None
        self.read_task = None


gemini_bridge = GeminiCLIBridge()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not update.message or not user:
        return

    await update.message.reply_html(
        rf"Hi {user.mention_html()}! I'm your Gemini CLI bridge bot."
        "\n\nSend me any message and I'll forward it to Gemini CLI."
        "\n\nCommands:"
        "\n/start - Show this help"
        "\n/reset - Reset the Gemini CLI session"
        "\n/status - Check bridge status"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    gemini_bridge.cleanup()
    if update.message:
        await update.message.reply_text("Gemini CLI session reset.")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if gemini_bridge.process and gemini_bridge.process.poll() is None:
        await update.message.reply_text("Gemini CLI is connected and running.")
    else:
        await update.message.reply_text("Gemini CLI is not connected.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    user_message = update.message.text
    logger.info("Received message: %s", user_message[:80])

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING,
    )

    response = await gemini_bridge.send_to_gemini(user_message)

    for start_index in range(0, len(response), MAX_MESSAGE_LENGTH):
        chunk = response[start_index : start_index + MAX_MESSAGE_LENGTH]
        await update.message.reply_text(chunk)


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. Add it to your environment or .env file."
        )

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    logger.info("Starting Telegram bot")
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        gemini_bridge.cleanup()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        gemini_bridge.cleanup()
    except Exception as exc:
        logger.error("Fatal error: %s", exc)
        gemini_bridge.cleanup()
        sys.exit(1)
