"""Send messages to Discord channels via incoming webhooks.

Add a channel by setting an environment variable::

    DISCORD_WEBHOOK_FAVORITES=https://discord.com/api/webhooks/...

The suffix after ``DISCORD_WEBHOOK_`` is the channel key (lowercase in API).
Future examples: ``DISCORD_WEBHOOK_DIVERGENCE``, ``DISCORD_WEBHOOK_BALANCE``.

Optional:
  DISCORD_REQUEST_TIMEOUT — HTTP timeout seconds (default 15)
"""

from __future__ import annotations

import logging
import os
import re

import requests

log = logging.getLogger(__name__)

ENV_PREFIX = "DISCORD_WEBHOOK_"
# Discord message content limit
MAX_CONTENT_CHARS = 1900


def _request_timeout() -> float:
    raw = os.environ.get("DISCORD_REQUEST_TIMEOUT", "").strip()
    try:
        return float(raw) if raw else 15.0
    except ValueError:
        return 15.0


def _channel_key_from_env(name: str) -> str | None:
    """``DISCORD_WEBHOOK_FAVORITES`` → ``favorites``."""
    if not name.startswith(ENV_PREFIX):
        return None
    key = name[len(ENV_PREFIX) :].strip().lower()
    return key or None


def list_discord_channels() -> dict[str, str | None]:
    """Discover configured channels: ``{ channel_key: webhook_url_or_none }``."""
    found: dict[str, str | None] = {}
    for env_name, value in os.environ.items():
        key = _channel_key_from_env(env_name)
        if key is None:
            continue
        url = (value or "").strip()
        found[key] = url if url else None
    return dict(sorted(found.items()))


def get_webhook_url(channel: str) -> str | None:
    """Return webhook URL for ``channel`` (e.g. ``favorites``), or None if unset."""
    key = channel.strip().lower()
    if not key:
        return None
    env_name = f"{ENV_PREFIX}{key.upper()}"
    url = os.environ.get(env_name, "").strip()
    return url or None


def is_discord_channel_configured(channel: str) -> bool:
    return bool(get_webhook_url(channel))


def html_to_discord_markdown(text: str) -> str:
    """Best-effort HTML (Telegram-style) → Discord markdown."""
    s = text
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = s.replace("<b>", "**").replace("</b>", "**")
    s = s.replace("<i>", "*").replace("</i>", "*")
    s = s.replace("<code>", "`").replace("</code>", "`")
    return s


def _split_content(text: str, limit: int = MAX_CONTENT_CHARS) -> list[str]:
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


def send_discord_message(
    channel: str,
    content: str,
    *,
    username: str | None = None,
) -> list[dict]:
    """Post ``content`` to the named Discord webhook channel.

    Raises ``RuntimeError`` if the channel is not configured or Discord rejects the call.
    """
    url = get_webhook_url(channel)
    if not url:
        raise RuntimeError(
            f"Discord channel {channel!r} is not configured: set {ENV_PREFIX}{channel.upper()} in .env."
        )
    timeout = _request_timeout()
    body_content = html_to_discord_markdown(content)
    responses: list[dict] = []
    for chunk in _split_content(body_content):
        payload: dict[str, str] = {"content": chunk}
        if username:
            payload["username"] = username
        r = requests.post(url, json=payload, timeout=timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"Discord webhook error {r.status_code}: {r.text[:300]}")
        try:
            responses.append(r.json() if r.text else {"status": r.status_code})
        except ValueError:
            responses.append({"raw": r.text, "status": r.status_code})
    return responses
