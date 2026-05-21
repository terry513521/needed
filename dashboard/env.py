"""Load ``.env`` from the repo root for every dashboard entry point.

Call ``load_env()`` from ``dashboard/__init__.py`` so imports work regardless of
process cwd (pm2, uvicorn, ``python -m dashboard``). Uses ``override=True`` for
the repo ``.env`` so empty shell placeholders do not block real values.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"

_loaded = False


def load_env(*, force: bool = False) -> Path:
    """Load repo ``.env`` (idempotent unless ``force=True``)."""
    global _loaded
    if _loaded and not force:
        return ENV_FILE

    if ENV_FILE.is_file():
        load_dotenv(ENV_FILE, override=True)
        log.debug("loaded environment from %s", ENV_FILE)
    else:
        log.debug("no .env at %s", ENV_FILE)

    # Optional extra file from cwd (does not override already-set keys).
    load_dotenv(override=False)

    _loaded = True
    return ENV_FILE


def env_file_path() -> str:
    return str(ENV_FILE)


def notification_env_summary() -> dict[str, bool]:
    """Non-secret booleans for logs / debug endpoints."""
    from dashboard.alert_dispatch import FAVORITES_DISCORD_CHANNEL
    from dashboard.discord_notify import is_discord_channel_configured
    from dashboard.telegram_notify import is_telegram_configured

    return {
        "telegram": is_telegram_configured(),
        "discord_favorites": is_discord_channel_configured(FAVORITES_DISCORD_CHANNEL),
        "discord_github_commit": is_discord_channel_configured("github_commit"),
        "taostats_api_key": bool(os.environ.get("TAOSTATS_API_KEY", "").strip()),
    }
