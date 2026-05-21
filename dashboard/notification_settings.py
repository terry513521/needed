"""Persisted enable/disable flags per notification channel (YAML on disk).

Channels (``id`` in API)::

    telegram              — favorite-subnet threshold alerts via Telegram
    discord_favorites     — same alerts via DISCORD_WEBHOOK_FAVORITES
    discord_github_commit — GitHub commit monitor via DISCORD_WEBHOOK_GITHUB_COMMIT

Missing file or unknown keys default to **enabled** (``true``).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "notifications.yaml"

CHANNEL_TELEGRAM = "telegram"
CHANNEL_DISCORD_FAVORITES = "discord_favorites"
CHANNEL_DISCORD_GITHUB_COMMIT = "discord_github_commit"

ALL_CHANNEL_IDS: tuple[str, ...] = (
    CHANNEL_TELEGRAM,
    CHANNEL_DISCORD_FAVORITES,
    CHANNEL_DISCORD_GITHUB_COMMIT,
)

_CHANNEL_LABELS: dict[str, str] = {
    CHANNEL_TELEGRAM: "Telegram",
    CHANNEL_DISCORD_FAVORITES: "Discord · favorites",
    CHANNEL_DISCORD_GITHUB_COMMIT: "Discord · GitHub commits",
}


def notifications_yaml_path() -> Path:
    return Path(os.environ.get("BITTENSOR_TOOLS_NOTIFICATIONS", str(DEFAULT_CONFIG))).expanduser()


def _default_enabled() -> dict[str, bool]:
    return {ch: True for ch in ALL_CHANNEL_IDS}


def _normalize_enabled_map(raw: Any) -> dict[str, bool]:
    defaults = _default_enabled()
    if not isinstance(raw, dict):
        return defaults
    out = dict(defaults)
    for ch in ALL_CHANNEL_IDS:
        if ch not in raw:
            continue
        val = raw[ch]
        if isinstance(val, bool):
            out[ch] = val
        elif isinstance(val, str):
            out[ch] = val.strip().lower() in ("1", "true", "yes", "on")
    return out


def load_notification_settings(path: Path | None = None) -> dict[str, bool]:
    p = path or notifications_yaml_path()
    if not p.exists():
        return _default_enabled()
    try:
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:  # noqa: BLE001
        log.warning("notification settings unreadable at %s", p, exc_info=True)
        return _default_enabled()
    if not isinstance(data, dict):
        return _default_enabled()
    return _normalize_enabled_map(data.get("channels"))


def save_notification_settings(enabled: dict[str, bool], path: Path | None = None) -> None:
    p = path or notifications_yaml_path()
    norm = _normalize_enabled_map(enabled)
    payload = {"channels": {ch: norm[ch] for ch in ALL_CHANNEL_IDS}}
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, default_flow_style=False, sort_keys=False)
    log.info("notification settings saved to %s", p)


def is_channel_enabled(channel: str, path: Path | None = None) -> bool:
    ch = channel.strip().lower()
    if ch not in ALL_CHANNEL_IDS:
        return False
    return load_notification_settings(path).get(ch, True)


def set_channel_enabled(channel: str, enabled: bool, path: Path | None = None) -> dict[str, bool]:
    ch = channel.strip().lower()
    if ch not in ALL_CHANNEL_IDS:
        raise ValueError(f"Unknown channel {channel!r}. Use one of: {', '.join(ALL_CHANNEL_IDS)}")
    current = load_notification_settings(path)
    current[ch] = bool(enabled)
    save_notification_settings(current, path)
    return current


def channel_label(channel: str) -> str:
    return _CHANNEL_LABELS.get(channel.strip().lower(), channel)


def settings_api_payload(path: Path | None = None) -> dict[str, Any]:
    from dashboard.alert_dispatch import FAVORITES_DISCORD_CHANNEL
    from dashboard.discord_notify import is_discord_channel_configured
    from dashboard.telegram_notify import is_telegram_configured

    github_commit_discord = "github_commit"

    p = path or notifications_yaml_path()
    enabled = load_notification_settings(p)
    channels = [
        {
            "id": CHANNEL_TELEGRAM,
            "label": channel_label(CHANNEL_TELEGRAM),
            "configured": is_telegram_configured(),
            "enabled": enabled[CHANNEL_TELEGRAM],
            "active": is_telegram_configured() and enabled[CHANNEL_TELEGRAM],
        },
        {
            "id": CHANNEL_DISCORD_FAVORITES,
            "label": channel_label(CHANNEL_DISCORD_FAVORITES),
            "configured": is_discord_channel_configured(FAVORITES_DISCORD_CHANNEL),
            "enabled": enabled[CHANNEL_DISCORD_FAVORITES],
            "active": is_discord_channel_configured(FAVORITES_DISCORD_CHANNEL)
            and enabled[CHANNEL_DISCORD_FAVORITES],
        },
        {
            "id": CHANNEL_DISCORD_GITHUB_COMMIT,
            "label": channel_label(CHANNEL_DISCORD_GITHUB_COMMIT),
            "configured": is_discord_channel_configured(github_commit_discord),
            "enabled": enabled[CHANNEL_DISCORD_GITHUB_COMMIT],
            "active": is_discord_channel_configured(github_commit_discord)
            and enabled[CHANNEL_DISCORD_GITHUB_COMMIT],
        },
    ]
    return {
        "config_path": str(p),
        "channels": channels,
    }
