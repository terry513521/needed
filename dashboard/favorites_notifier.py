"""Background loop: periodically push a Telegram digest of favorite-subnet status.

Started from the FastAPI lifespan (``dashboard.app``). Runs every
``FAVORITES_NOTIFY_INTERVAL_SEC`` seconds (default 600 = 10 min). Each tick:

  * Loads the favorite netuids from ``favorites.yaml``.
  * Skips silently if there are no favorites or Telegram isn't configured.
  * Calls ``fetch_subnet_overview`` (sync, run in a worker thread).
  * Builds a compact HTML digest with per-row Δ% vs the previous tick (kept in
    process memory) and sends it via the Telegram Bot API.
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
from datetime import datetime, timezone
from typing import Any

from dashboard.favorites import load_favorites
from dashboard.taostats_client import fetch_subnet_overview
from dashboard.telegram_notify import is_telegram_configured, send_telegram_message

log = logging.getLogger(__name__)

DEFAULT_INTERVAL_SEC = 600
"""10 minutes — matches the user-facing 'every 10 mins' description."""

MIN_INTERVAL_SEC = 60
"""Floor to keep accidental misconfig from hammering the Taostats API."""

# Snapshot of last tick's per-favorite values, used to compute Δ% in the next message.
_PREV_STATE: dict[int, dict[str, float | None]] = {}


def notify_interval_sec() -> int:
    raw = os.environ.get("FAVORITES_NOTIFY_INTERVAL_SEC", "").strip()
    try:
        v = int(raw) if raw else DEFAULT_INTERVAL_SEC
    except ValueError:
        v = DEFAULT_INTERVAL_SEC
    return max(MIN_INTERVAL_SEC, v)


def _coerce_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # filter NaN


def _fmt_tao(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{max(0.0, v):.6f}"


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.2f}%"


def _fmt_alpha_price(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:.8f}"


def _fmt_delta(prev: float | None, now: float | None) -> str:
    if prev is None or now is None or prev == 0:
        return ""
    pct = (now - prev) / prev * 100
    sign = "+" if pct >= 0 else ""
    return f" ({sign}{pct:.2f}%)"


def _actual_reward(alpha_emission: float | None, burn: float | None) -> float | None:
    """Mirror the frontend formula: alpha emission × (1 − burn) × 0.41."""
    if alpha_emission is None or burn is None:
        return None
    return alpha_emission * (1.0 - burn) * 0.41


def _build_digest_text(favorites: list[int], overview: dict[str, Any]) -> str:
    rows_by_netuid: dict[int, dict[str, Any]] = {}
    for r in overview.get("subnets", []) or []:
        try:
            rows_by_netuid[int(r["netuid"])] = r
        except (KeyError, TypeError, ValueError):
            continue

    now_utc = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    parts: list[str] = [f"<b>Favorite subnets</b> — <i>{html.escape(now_utc)}</i>"]

    for nu in favorites:
        r = rows_by_netuid.get(nu)
        if not r:
            parts.append(f"\n<b>Subnet {nu}</b>: <i>not in latest overview</i>")
            continue
        alpha_price = _coerce_float(r.get("alpha_price_tao"))
        alpha_emission = _coerce_float(r.get("alpha_emission_tau_per_day"))
        burn = _coerce_float(r.get("incentive_burn_rate"))
        reg = _coerce_float(r.get("neuron_registration_cost_tao"))
        actual_reward = _actual_reward(alpha_emission, burn)

        prev = _PREV_STATE.get(nu, {})
        name = html.escape(str(r.get("name") or "?"))
        parts.append(
            f"\n<b>{nu} · {name}</b>"
            f"\n  α price: <code>{_fmt_alpha_price(alpha_price)}</code>"
            f"{_fmt_delta(prev.get('alpha_price'), alpha_price)}"
            f"\n  α emission: <code>{_fmt_tao(alpha_emission)}</code> τ/day"
            f"{_fmt_delta(prev.get('alpha_emission'), alpha_emission)}"
            f"\n  Actual reward: <code>{_fmt_tao(actual_reward)}</code> τ/day"
            f"{_fmt_delta(prev.get('actual_reward'), actual_reward)}"
            f"\n  Burn: <code>{_fmt_pct(burn)}</code>"
            f"{_fmt_delta(prev.get('burn'), burn)}"
            f"\n  Reg cost: <code>{_fmt_tao(reg)}</code> τ"
            f"{_fmt_delta(prev.get('reg'), reg)}"
        )
        _PREV_STATE[nu] = {
            "alpha_price": alpha_price,
            "alpha_emission": alpha_emission,
            "burn": burn,
            "reg": reg,
            "actual_reward": actual_reward,
        }

    # Drop state for previously-favorited netuids that are no longer favorites,
    # so re-favoriting later starts fresh instead of comparing against stale data.
    for nu in list(_PREV_STATE.keys()):
        if nu not in favorites:
            _PREV_STATE.pop(nu, None)

    return "\n".join(parts)


async def _tick() -> None:
    favorites = load_favorites()
    if not favorites:
        log.debug("favorites_notifier: no favorites; skipping tick")
        return
    if not is_telegram_configured():
        log.debug("favorites_notifier: telegram not configured; skipping tick")
        return
    api_key = os.environ.get("TAOSTATS_API_KEY", "").strip()
    if not api_key:
        log.warning("favorites_notifier: TAOSTATS_API_KEY missing; skipping tick")
        return
    try:
        overview = await asyncio.to_thread(fetch_subnet_overview, api_key)
    except Exception:  # noqa: BLE001
        log.exception("favorites_notifier: failed to fetch Taostats overview")
        return
    text = _build_digest_text(favorites, overview)
    if not text.strip():
        return
    try:
        await asyncio.to_thread(send_telegram_message, text)
        log.info("favorites_notifier: sent digest for %d favorite(s)", len(favorites))
    except Exception:  # noqa: BLE001
        log.exception("favorites_notifier: telegram send failed")


async def run_favorites_notifier(*, startup_delay_sec: float = 15.0) -> None:
    """Long-running asyncio task; cancel on shutdown."""
    interval = notify_interval_sec()
    log.info(
        "favorites_notifier: started (interval=%ds, telegram_configured=%s)",
        interval,
        is_telegram_configured(),
    )
    try:
        await asyncio.sleep(startup_delay_sec)
        while True:
            await _tick()
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        log.info("favorites_notifier: stopped")
        raise
