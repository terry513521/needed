"""Send messages to a Telegram chat via the Bot API.

Configuration (in ``.env`` or environment):
  TELEGRAM_BOT_TOKEN — bot token from @BotFather (e.g. ``123:abc…``)
  TELEGRAM_CHAT_ID — target chat id (positive for private DMs, negative for groups)

Optional:
  TELEGRAM_API_BASE — default https://api.telegram.org
  TELEGRAM_REQUEST_TIMEOUT — float seconds, default 15

Synchronous on purpose: callers from asyncio code wrap with ``asyncio.to_thread``.
"""

from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://api.telegram.org"
# Telegram rejects single ``sendMessage`` payloads above 4096 chars; keep margin for HTML markup.
MAX_MESSAGE_CHARS = 3800


def _api_base() -> str:
    return os.environ.get("TELEGRAM_API_BASE", DEFAULT_API_BASE).rstrip("/")


def _request_timeout() -> float:
    raw = os.environ.get("TELEGRAM_REQUEST_TIMEOUT", "").strip()
    try:
        return float(raw) if raw else 15.0
    except ValueError:
        return 15.0


def telegram_settings() -> tuple[str, str]:
    """``(bot_token, chat_id)`` — both empty strings when unconfigured."""
    return (
        os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
        os.environ.get("TELEGRAM_CHAT_ID", "").strip(),
    )


def is_telegram_configured() -> bool:
    token, chat_id = telegram_settings()
    return bool(token and chat_id)


def _split_for_telegram(text: str, limit: int = MAX_MESSAGE_CHARS) -> list[str]:
    """Greedy split on newline boundaries so HTML tags stay intact across chunks."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    buf: list[str] = []
    cur = 0
    for line in text.split("\n"):
        ln = len(line) + 1
        if cur + ln > limit and buf:
            chunks.append("\n".join(buf))
            buf = [line]
            cur = ln
        else:
            buf.append(line)
            cur += ln
    if buf:
        chunks.append("\n".join(buf))
    return chunks


def send_telegram_message(text: str, *, parse_mode: str = "HTML") -> list[dict]:
    """Send ``text`` to the configured chat. Auto-chunks long messages.

    Returns the list of Telegram API responses (one per chunk).
    Raises ``RuntimeError`` if Telegram isn't configured or the API rejects the call.
    """
    token, chat_id = telegram_settings()
    if not token or not chat_id:
        raise RuntimeError(
            "Telegram is not configured: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env."
        )
    timeout = _request_timeout()
    base = _api_base()
    url = f"{base}/bot{token}/sendMessage"
    responses: list[dict] = []
    for chunk in _split_for_telegram(text):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        r = requests.post(url, json=payload, timeout=timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"Telegram API error {r.status_code}: {r.text[:300]}")
        try:
            responses.append(r.json())
        except ValueError:
            responses.append({"raw": r.text})
    return responses
