"""
Local dashboard: Taostats emission vs. registration-burn divergence (~24h) + TAO Daily alarms.

  TAOSTATS_API_KEY — required for Taostats (can live in `.env`)

  Optional (all can be set in `.env`; see `.env.example`):
  TAOSTATS_API_URL, TAOSTATS_SNAPSHOT_PATH, TAOSTATS_MIN_DIVERGENCE_PCT,
  TAOSTATS_LOOKBACK_SEC, TAOSTATS_LOOKBACK_TOLERANCE_SEC, TAOSTATS_REQUEST_TIMEOUT,
  BITTENSOR_NETWORK, DASHBOARD_HOST, DASHBOARD_PORT,
  DASHBOARD_CORS_ORIGINS (comma-separated, for React dev server)

React UI: `npm run dev` in frontend/ (proxies /api → this server), or `npm run build`
and serve `frontend/dist` from this app (see static mounts below).

Run API + optional static UI: uvicorn dashboard.app:app --reload --host 127.0.0.1 --port 8765
Or:  python -m dashboard.app
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager, suppress

from dashboard.env import REPO_ROOT, env_file_path, load_env, notification_env_summary

# Ensure .env is loaded before other dashboard modules (also runs via dashboard/__init__.py).
load_env()

_REPO_ROOT = REPO_ROOT

from dashboard.logging_config import configure_dashboard_logging

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from dashboard.favorites import (
    ALERT_METRIC_KEYS,
    DEFAULT_CONFIG as FAVORITES_DEFAULT_PATH,
    add_favorite,
    favorites_api_payload,
    favorites_yaml_path,
    load_favorites_config,
    remove_favorite,
    set_favorite_alerts,
    set_favorite_github,
    set_favorites,
)
from dashboard.favorites_notifier import (
    notify_interval_sec as favorites_notify_interval_sec,
    run_favorites_notifier,
)
from dashboard.taostats_client import (
    DEFAULT_MIN_DIVERGENCE_PCT,
    DEFAULT_SNAPSHOT_PATH,
    LOOKBACK_TOLERANCE_SEC,
    REQUEST_TIMEOUT,
    TARGET_LOOKBACK_SEC,
    divergence_from_snapshot_file,
    fetch_subnet_overview,
    run_taostats_cycle,
)
from dashboard.taodaily_client import fetch_taodaily_recent_news
from dashboard.taomarketcap_client import (
    TAOMARKETCAP_API_URL,
    TAOMARKETCAP_CACHE_TTL_SEC,
    TAOMARKETCAP_DAILY_REFRESH_HOUR,
    TAOMARKETCAP_DAILY_REFRESH_MINUTE,
    TAOMARKETCAP_REQUEST_TIMEOUT,
    fetch_subnet_miner_rewards,
    run_taomarketcap_cache_refresher,
)
from dashboard.alert_dispatch import FAVORITES_DISCORD_CHANNEL, favorites_alerts_configured
from dashboard.github_monitor import (
    GITHUB_COMMIT_DISCORD_CHANNEL,
    github_monitor_configured,
    poll_interval_sec as github_poll_interval_sec,
    run_github_monitor,
)
from dashboard.discord_notify import (
    is_discord_channel_configured,
    list_discord_channels,
    send_discord_message,
)
from dashboard.notification_settings import (
    CHANNEL_DISCORD_FAVORITES,
    CHANNEL_DISCORD_GITHUB_COMMIT,
    CHANNEL_TELEGRAM,
    is_channel_enabled,
    notifications_yaml_path,
    set_channel_enabled,
    settings_api_payload,
)
from dashboard.telegram_notify import (
    is_telegram_configured,
    send_telegram_message,
    telegram_settings,
)

_SPA_DIST = _REPO_ROOT / "frontend" / "dist"
_SPA_ASSETS = _SPA_DIST / "assets"

log = logging.getLogger(__name__)


class FavoriteBody(BaseModel):
    netuid: int


class FavoritesSetBody(BaseModel):
    favorites: list[int] = Field(default_factory=list)


class FavoriteAlertsBody(BaseModel):
    """Per-metric |Δ%| thresholds; omit or null = disabled for that metric."""

    alpha_price_pct: float | None = Field(None, ge=0, le=10000)
    alpha_emission_pct: float | None = Field(None, ge=0, le=10000)
    root_emission_pct: float | None = Field(None, ge=0, le=10000)
    burn_pct: float | None = Field(None, ge=0, le=10000)
    reg_pct: float | None = Field(None, ge=0, le=10000)
    actual_reward_pct: float | None = Field(None, ge=0, le=10000)


class FavoriteAlertsUpdateBody(BaseModel):
    netuid: int
    alerts: FavoriteAlertsBody


class FavoriteGithubUpdateBody(BaseModel):
    netuid: int
    github_url: str | None = Field(
        default=None,
        description="https://github.com/owner/repo or empty to clear",
    )


class TelegramTestBody(BaseModel):
    text: str | None = Field(
        default=None,
        description="Optional override; defaults to a short hello message.",
    )


class DiscordTestBody(BaseModel):
    channel: str = Field(
        default=FAVORITES_DISCORD_CHANNEL,
        description="Discord channel key (env DISCORD_WEBHOOK_<KEY>).",
    )
    text: str | None = Field(default=None, description="Optional message override.")


class NotificationChannelBody(BaseModel):
    channel: str = Field(
        description="telegram | discord_favorites | discord_github_commit",
    )
    enabled: bool


def _cors_origins() -> list[str]:
    raw = os.environ.get("DASHBOARD_CORS_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return ["http://127.0.0.1:5173", "http://localhost:5173"]


@asynccontextmanager
async def _lifespan(_: FastAPI):
    # Reload .env on each process start (pm2 restart, uvicorn reload worker).
    load_env(force=True)
    # After uvicorn configures logging (disables pre-import loggers), wire our handlers.
    configure_dashboard_logging()
    log = logging.getLogger(__name__)
    log.info(
        "logging ready (DASHBOARD_LOG_LEVEL=%s, env_file=%s)",
        os.environ.get("DASHBOARD_LOG_LEVEL", "INFO").strip() or "INFO",
        env_file_path(),
    )
    log.info("notification env: %s", notification_env_summary())
    notifier_task = asyncio.create_task(
        run_favorites_notifier(),
        name="favorites_notifier",
    )
    github_task = asyncio.create_task(
        run_github_monitor(),
        name="github_monitor",
    )
    taomarketcap_cache_task = asyncio.create_task(
        run_taomarketcap_cache_refresher(),
        name="taomarketcap_cache_refresher",
    )
    try:
        yield
    finally:
        for task in (notifier_task, github_task, taomarketcap_cache_task):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(
    title="Bittensor tools dashboard",
    version="0.1.0",
    lifespan=_lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _log_requests(request: Request, call_next):
    start = time.perf_counter()
    path = request.url.path
    noisy = path.startswith("/assets/") or path in ("/favicon.ico",)
    try:
        response = await call_next(request)
    except Exception:
        log.exception("request failed %s %s", request.method, path)
        raise
    elapsed_ms = (time.perf_counter() - start) * 1000
    line = "%s %s -> %s (%.1f ms)" % (request.method, path, response.status_code, elapsed_ms)
    if noisy:
        log.debug(line)
    else:
        log.info(line)
    return response


@app.get("/")
def root():
    index = _SPA_DIST / "index.html"
    if index.is_file():
        return FileResponse(index)
    return {
        "service": "bittensor-tools dashboard API",
        "frontend_dev": "cd frontend && npm run dev  (Vite proxies /api to this server on port 8765)",
        "frontend_build": "cd frontend && npm run build  then restart uvicorn to serve the UI from /",
        "docs": "/docs",
    }


def _frontend_file_response(*names: str) -> FileResponse | None:
    for name in names:
        path = _SPA_DIST / name
        if path.is_file():
            return FileResponse(path)
    return None


@app.get("/favicon.png")
def favicon_svg():
    response = _frontend_file_response("favicon.png")
    if response is None:
        raise HTTPException(status_code=404, detail="favicon.png not found")
    return response

@app.get("/src/assets/{asset_name}")
def legacy_src_asset(asset_name: str):
    response = _frontend_file_response(asset_name, "team.png", "favicon.svg")
    if response is None:
        raise HTTPException(status_code=404, detail=f"{asset_name} not found")
    return response


@app.get("/api/config")
def api_config() -> dict:
    """Effective optional settings (from environment / `.env`). No secrets."""
    log.debug("config requested")
    net = os.environ.get("BITTENSOR_NETWORK", "").strip()
    return {
        "min_divergence_pct": DEFAULT_MIN_DIVERGENCE_PCT,
        "lookback_sec": TARGET_LOOKBACK_SEC,
        "lookback_tolerance_sec": LOOKBACK_TOLERANCE_SEC,
        "snapshot_path": str(DEFAULT_SNAPSHOT_PATH),
        "taostats_api_url": os.environ.get("TAOSTATS_API_URL", "https://api.taostats.io").rstrip("/"),
        "taomarketcap_api_url": TAOMARKETCAP_API_URL,
        "taomarketcap_request_timeout_sec": TAOMARKETCAP_REQUEST_TIMEOUT,
        "taomarketcap_cache_ttl_sec": TAOMARKETCAP_CACHE_TTL_SEC,
        "taomarketcap_daily_refresh_hour": TAOMARKETCAP_DAILY_REFRESH_HOUR,
        "taomarketcap_daily_refresh_minute": TAOMARKETCAP_DAILY_REFRESH_MINUTE,
        "request_timeout_sec": REQUEST_TIMEOUT,
        "favorites_config_path": str(favorites_yaml_path()),
        "favorites_default_path": str(FAVORITES_DEFAULT_PATH),
        "notifications_config_path": str(notifications_yaml_path()),
        "env_file_path": env_file_path(),
        "favorites_notify_interval_sec": favorites_notify_interval_sec(),
        "telegram_configured": is_telegram_configured(),
        "discord_favorites_configured": is_discord_channel_configured(FAVORITES_DISCORD_CHANNEL),
        "discord_github_commit_configured": is_discord_channel_configured(GITHUB_COMMIT_DISCORD_CHANNEL),
        "github_commit_poll_interval_sec": github_poll_interval_sec(),
        "github_monitor_configured": github_monitor_configured(),
        "favorites_alerts_configured": favorites_alerts_configured(),
        "bittensor_network_override": net or None,
        "dashboard_host": os.environ.get("DASHBOARD_HOST", "127.0.0.1"),
        "dashboard_port": int(os.environ.get("DASHBOARD_PORT", "8765")),
    }


@app.get("/api/taostats/overview")
def api_taostats_overview(refresh: bool = False) -> dict:
    """All subnets: name, alpha price (pool), emission τ/day, reg cost τ, incentive_burn; no snapshot write."""
    key = os.environ.get("TAOSTATS_API_KEY", "").strip()
    if not key:
        log.warning("GET /api/taostats/overview rejected: TAOSTATS_API_KEY not set")
        raise HTTPException(
            status_code=400,
            detail="Set TAOSTATS_API_KEY in the environment or `.env` (Taostats API key).",
        )
    try:
        return fetch_subnet_overview(key, refresh=refresh)
    except Exception as e:  # noqa: BLE001
        log.exception("taostats overview failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.get("/api/taomarketcap/subnets/{netuid}/miners")
def api_taomarketcap_subnet_miners(netuid: int, refresh: bool = False) -> dict:
    """Subnet miner reward status from TaoMarketCap, cached daily by default."""
    if netuid < 0:
        raise HTTPException(status_code=400, detail="netuid must be a non-negative integer.")
    try:
        return fetch_subnet_miner_rewards(netuid, refresh=refresh)
    except Exception as e:  # noqa: BLE001
        log.exception("taomarketcap subnet miners failed netuid=%s: %s", netuid, e)
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.get("/api/taostats/divergence/snapshot")
def api_taostats_divergence_snapshot() -> dict:
    """
    Divergence table from the latest JSON snapshot on disk vs ~24h baseline.
    Does not call Taostats or require TAOSTATS_API_KEY (read-only file).
    """
    try:
        return divergence_from_snapshot_file(DEFAULT_SNAPSHOT_PATH, min_divergence_pct=None)
    except Exception as e:  # noqa: BLE001
        log.exception("divergence snapshot read failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/taostats/divergence")
def api_taostats_divergence() -> dict:
    key = os.environ.get("TAOSTATS_API_KEY", "").strip()
    if not key:
        log.warning("GET /api/taostats/divergence rejected: TAOSTATS_API_KEY not set")
        raise HTTPException(
            status_code=400,
            detail="Set TAOSTATS_API_KEY in the environment or `.env` (Taostats API key).",
        )
    try:
        return run_taostats_cycle(key, snapshot_path=DEFAULT_SNAPSHOT_PATH, min_divergence_pct=None)
    except Exception as e:  # noqa: BLE001
        log.exception("taostats divergence cycle failed; falling back to latest snapshot: %s", e)
        try:
            fallback = divergence_from_snapshot_file(DEFAULT_SNAPSHOT_PATH, min_divergence_pct=None)
            fallback["warning"] = f"Live Taostats refresh failed; showing latest saved snapshot instead: {e}"
            fallback["from_snapshot_file"] = True
            return fallback
        except Exception as fallback_error:  # noqa: BLE001
            log.exception("divergence snapshot fallback failed: %s", fallback_error)
            raise HTTPException(status_code=502, detail=str(e)) from e


@app.get("/api/alarms/news")
def api_alarms_news() -> dict:
    """TAO Daily posts from today and yesterday for the dashboard alarms panel."""
    try:
        return fetch_taodaily_recent_news()
    except Exception as e:  # noqa: BLE001
        log.exception("taodaily news fetch failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.get("/api/favorites")
def api_favorites_list() -> dict:
    """Favorites with per-subnet Telegram alert thresholds."""
    return favorites_api_payload()


@app.post("/api/favorites/add")
def api_favorites_add(body: FavoriteBody) -> dict:
    try:
        add_favorite(body.netuid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OSError as e:
        log.exception("favorites write failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Could not write favorites file: {e}") from e
    log.info("favorite added netuid=%s", body.netuid)
    return favorites_api_payload()


@app.post("/api/favorites/remove")
def api_favorites_remove(body: FavoriteBody) -> dict:
    try:
        remove_favorite(body.netuid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OSError as e:
        log.exception("favorites write failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Could not write favorites file: {e}") from e
    log.info("favorite removed netuid=%s", body.netuid)
    return favorites_api_payload()


@app.post("/api/favorites")
def api_favorites_set(body: FavoritesSetBody) -> dict:
    """Replace the entire favorites list (used for one-shot localStorage migration)."""
    try:
        set_favorites(list(body.favorites))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OSError as e:
        log.exception("favorites write failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Could not write favorites file: {e}") from e
    log.info("favorites set count=%s", len(body.favorites))
    return favorites_api_payload()


@app.post("/api/favorites/github")
def api_favorites_github(body: FavoriteGithubUpdateBody) -> dict:
    """Set or clear GitHub repo URL for a favorite subnet (commit monitoring)."""
    try:
        set_favorite_github(body.netuid, body.github_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OSError as e:
        log.exception("favorites write failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Could not write favorites file: {e}") from e
    log.info("favorite github_url updated netuid=%s", body.netuid)
    return favorites_api_payload()


@app.post("/api/favorites/alerts")
def api_favorites_alerts(body: FavoriteAlertsUpdateBody) -> dict:
    """Set per-metric notification thresholds for one favorite subnet."""
    try:
        alerts_dict = body.alerts.model_dump(exclude_none=False)
        set_favorite_alerts(body.netuid, alerts_dict)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OSError as e:
        log.exception("favorites write failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Could not write favorites file: {e}") from e
    log.info("favorite alerts updated netuid=%s", body.netuid)
    return favorites_api_payload()


@app.get("/api/favorites/alert-metrics")
def api_favorites_alert_metrics() -> dict:
    """Metric keys and labels for the dashboard alert form."""
    labels = {
        "alpha_price_pct": "Alpha price (τ/α)",
        "alpha_emission_pct": "Alpha emission (τ/day)",
        "root_emission_pct": "Root TAO in (τ/day)",
        "burn_pct": "Incentive burn",
        "reg_pct": "Reg cost (τ)",
        "actual_reward_pct": "Actual reward (τ/day)",
    }
    return {
        "metrics": [
            {"key": k, "label": labels.get(k, k)} for k in ALERT_METRIC_KEYS
        ],
    }


@app.get("/api/notifications/settings")
def api_notification_settings() -> dict:
    """Per-channel configured / enabled / active flags (persisted in notifications.yaml)."""
    return settings_api_payload()


@app.post("/api/notifications/channel")
def api_notification_channel(body: NotificationChannelBody) -> dict:
    """Enable or disable a notification channel without removing .env credentials."""
    try:
        set_channel_enabled(body.channel, body.enabled)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OSError as e:
        log.exception("notification settings write failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Could not write settings: {e}") from e
    log.info("notification channel %s enabled=%s", body.channel, body.enabled)
    return settings_api_payload()


@app.get("/api/notifications/telegram/status")
def api_telegram_status() -> dict:
    """Whether Telegram credentials are present and the digest cadence."""
    token, chat_id = telegram_settings()
    configured = bool(token and chat_id)
    enabled = is_channel_enabled(CHANNEL_TELEGRAM)
    return {
        "configured": configured,
        "enabled": enabled,
        "active": configured and enabled,
        "has_token": bool(token),
        "has_chat_id": bool(chat_id),
        "interval_sec": favorites_notify_interval_sec(),
    }


@app.post("/api/notifications/telegram/test")
def api_telegram_test(
    body: TelegramTestBody = Body(default_factory=TelegramTestBody),
) -> dict:
    """Send a one-off test message to confirm the bot is wired up correctly."""
    text = (body.text or "").strip() or (
        "<b>bittensor-tools</b>: Telegram is wired up. "
        "You'll get favorite-subnet status digests from now on."
    )
    try:
        send_telegram_message(text)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001 — surface network errors verbatim
        log.exception("telegram test send failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"ok": True}


@app.get("/api/notifications/discord/status")
def api_discord_status() -> dict:
    """Configured Discord webhook channels (from DISCORD_WEBHOOK_* env vars)."""
    channels = list_discord_channels()
    return {
        "channels": [
            {
                "key": key,
                "configured": bool(url),
                "env_var": f"DISCORD_WEBHOOK_{key.upper()}",
            }
            for key, url in channels.items()
        ],
        "favorites_channel": FAVORITES_DISCORD_CHANNEL,
        "favorites_configured": is_discord_channel_configured(FAVORITES_DISCORD_CHANNEL),
        "favorites_enabled": is_channel_enabled(CHANNEL_DISCORD_FAVORITES),
        "favorites_active": is_discord_channel_configured(FAVORITES_DISCORD_CHANNEL)
        and is_channel_enabled(CHANNEL_DISCORD_FAVORITES),
        "github_commit_configured": is_discord_channel_configured(GITHUB_COMMIT_DISCORD_CHANNEL),
        "github_commit_enabled": is_channel_enabled(CHANNEL_DISCORD_GITHUB_COMMIT),
        "github_commit_active": is_discord_channel_configured(GITHUB_COMMIT_DISCORD_CHANNEL)
        and is_channel_enabled(CHANNEL_DISCORD_GITHUB_COMMIT),
        "github_commit_channel": GITHUB_COMMIT_DISCORD_CHANNEL,
        "interval_sec": favorites_notify_interval_sec(),
    }


@app.get("/api/notifications/github/status")
def api_github_monitor_status() -> dict:
    entries = load_favorites_config()
    with_github = [e for e in entries if e.github_url]
    webhook_ok = is_discord_channel_configured(GITHUB_COMMIT_DISCORD_CHANNEL)
    gh_enabled = is_channel_enabled(CHANNEL_DISCORD_GITHUB_COMMIT)
    return {
        "configured": webhook_ok,
        "enabled": gh_enabled,
        "active": github_monitor_configured(),
        "poll_interval_sec": github_poll_interval_sec(),
        "discord_channel": GITHUB_COMMIT_DISCORD_CHANNEL,
        "env_var": f"DISCORD_WEBHOOK_{GITHUB_COMMIT_DISCORD_CHANNEL.upper()}",
        "monitored_count": len(with_github),
        "monitored": [
            {"netuid": e.netuid, "github_url": e.github_url} for e in with_github
        ],
    }


@app.post("/api/notifications/discord/test")
def api_discord_test(
    body: DiscordTestBody = Body(default_factory=DiscordTestBody),
) -> dict:
    """Send a test message to a named Discord webhook channel."""
    channel = (body.channel or FAVORITES_DISCORD_CHANNEL).strip().lower()
    text = (body.text or "").strip() or (
        "**bittensor-tools**: Discord webhook is wired up. "
        "Favorite-subnet alerts will post here when thresholds are crossed."
    )
    try:
        send_discord_message(channel, text, username="Bittensor tools")
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        log.exception("discord test send failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"ok": True, "channel": channel}


if _SPA_ASSETS.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_SPA_ASSETS)), name="spa_assets")


# def main() -> None:
#     import uvicorn
#     host = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
#     port = int(os.environ.get("DASHBOARD_PORT", "8765"))
#     uvicorn.run("dashboard.app:app", host=host, port=port, reload=True)
