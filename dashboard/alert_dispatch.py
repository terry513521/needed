"""Dispatch favorite-subnet alerts to all configured notification channels."""

from __future__ import annotations

import asyncio
import logging

from dashboard.discord_notify import (
    is_discord_channel_configured,
    send_discord_message,
)
from dashboard.telegram_notify import is_telegram_configured, send_telegram_message

log = logging.getLogger(__name__)

FAVORITES_DISCORD_CHANNEL = "favorites"


def favorites_alerts_configured() -> bool:
    return is_telegram_configured() or is_discord_channel_configured(FAVORITES_DISCORD_CHANNEL)


async def send_favorites_alert(html_text: str) -> dict[str, bool]:
    """Send the same alert payload to Telegram and/or Discord favorites channel."""
    results: dict[str, bool] = {}

    if is_telegram_configured():
        try:
            await asyncio.to_thread(send_telegram_message, html_text)
            results["telegram"] = True
            log.info("favorites alert sent via Telegram")
        except Exception:  # noqa: BLE001
            log.exception("favorites alert: Telegram send failed")
            results["telegram"] = False
    else:
        results["telegram"] = False

    if is_discord_channel_configured(FAVORITES_DISCORD_CHANNEL):
        try:
            await asyncio.to_thread(
                send_discord_message,
                FAVORITES_DISCORD_CHANNEL,
                html_text,
                username="Bittensor tools",
            )
            results["discord_favorites"] = True
            log.info("favorites alert sent via Discord (%s)", FAVORITES_DISCORD_CHANNEL)
        except Exception:  # noqa: BLE001
            log.exception("favorites alert: Discord send failed")
            results["discord_favorites"] = False
    else:
        results["discord_favorites"] = False

    return results
