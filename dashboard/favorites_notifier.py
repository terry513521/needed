"""Background loop: Telegram alerts when favorite-subnet metrics cross per-subnet thresholds.

Poll interval: ``FAVORITES_NOTIFY_INTERVAL_SEC`` (default 600 s). Each tick fetches
Taostats overview, compares to the previous tick, and sends a message only when at
least one configured metric for a favorite exceeds its |Δ%| threshold (e.g. burn_pct: 10).
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
from datetime import datetime, timezone
from typing import Any

from dashboard.alert_dispatch import favorites_alerts_configured, send_favorites_alert
from dashboard.favorites import FavoriteEntry, load_favorites_config
from dashboard.taostats_client import fetch_subnet_overview

log = logging.getLogger(__name__)

DEFAULT_INTERVAL_SEC = 600
MIN_INTERVAL_SEC = 60

_PREV_STATE: dict[int, dict[str, float | None]] = {}

# (state_key, overview field getter label for message)
_METRIC_SPECS: tuple[tuple[str, str, str], ...] = (
    ("alpha_price", "alpha_price_pct", "Alpha price (τ/α)"),
    ("alpha_emission", "alpha_emission_pct", "Alpha emission (τ/day)"),
    ("root_emission", "root_emission_pct", "Root TAO in (τ/day)"),
    ("burn", "burn_pct", "Incentive burn"),
    ("reg", "reg_pct", "Reg cost (τ)"),
    ("actual_reward", "actual_reward_pct", "Actual reward (τ/day)"),
)


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
    return f if f == f else None


def _fmt_tao(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{max(0.0, v):.6f}"


def _fmt_pct_rate(v: float | None) -> str:
    """Incentive burn as 0–1 rate shown as percent."""
    if v is None:
        return "—"
    return f"{v * 100:.2f}%"


def _fmt_alpha_price(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:.8f}"


def _actual_reward(alpha_emission: float | None, burn: float | None) -> float | None:
    if alpha_emission is None or burn is None:
        return None
    return alpha_emission * (1.0 - burn) * 0.41


def _pct_change_abs(prev: float | None, now: float | None) -> float | None:
    """Absolute percent change; None if baseline missing or zero."""
    if prev is None or now is None:
        return None
    if prev == 0:
        return None if now == 0 else 100.0
    return abs((now - prev) / prev * 100.0)


def _extract_metrics(row: dict[str, Any]) -> dict[str, float | None]:
    alpha_emission = _coerce_float(row.get("alpha_emission_tau_per_day"))
    burn = _coerce_float(row.get("incentive_burn_rate"))
    return {
        "alpha_price": _coerce_float(row.get("alpha_price_tao")),
        "alpha_emission": alpha_emission,
        "root_emission": _coerce_float(row.get("emission_tau_per_day")),
        "burn": burn,
        "reg": _coerce_float(row.get("neuron_registration_cost_tao")),
        "actual_reward": _actual_reward(alpha_emission, burn),
    }


def _format_value(state_key: str, value: float | None) -> str:
    if value is None:
        return "—"
    if state_key == "burn":
        return _fmt_pct_rate(value)
    if state_key == "alpha_price":
        return _fmt_alpha_price(value)
    return _fmt_tao(value)


def _check_triggers(
    entry: FavoriteEntry,
    metrics: dict[str, float | None],
    prev: dict[str, float | None],
) -> list[tuple[str, str, str, float, float | None, float | None]]:
    """Returns (state_key, label, alert_key, |Δ%|, prev, now) for each fired metric."""
    fired: list[tuple[str, str, str, float, float | None, float | None]] = []
    if not entry.alerts:
        return fired
    for state_key, alert_key, label in _METRIC_SPECS:
        threshold = entry.alerts.get(alert_key)
        if threshold is None:
            continue
        now_v = metrics.get(state_key)
        prev_v = prev.get(state_key)
        delta = _pct_change_abs(prev_v, now_v)
        if delta is None:
            continue
        if delta >= threshold:
            fired.append((state_key, label, alert_key, delta, prev_v, now_v))
    return fired


def _build_alert_text(
    entries: list[FavoriteEntry],
    overview: dict[str, Any],
) -> str | None:
    rows_by_netuid: dict[int, dict[str, Any]] = {}
    for r in overview.get("subnets", []) or []:
        try:
            rows_by_netuid[int(r["netuid"])] = r
        except (KeyError, TypeError, ValueError):
            continue

    now_utc = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    parts: list[str] = [f"<b>Favorite subnet alerts</b> — <i>{html.escape(now_utc)}</i>"]
    any_alert = False

    for entry in entries:
        nu = entry.netuid
        if not entry.alerts:
            # Still update prev state for subnets without thresholds
            r = rows_by_netuid.get(nu)
            if r:
                _PREV_STATE[nu] = _extract_metrics(r)
            continue

        r = rows_by_netuid.get(nu)
        if not r:
            continue

        metrics = _extract_metrics(r)
        prev = _PREV_STATE.get(nu, {})
        fired = _check_triggers(entry, metrics, prev)
        _PREV_STATE[nu] = metrics

        if not fired:
            continue

        any_alert = True
        name = html.escape(str(r.get("name") or "?"))
        parts.append(f"\n<b>{nu} · {name}</b>")
        for state_key, label, alert_key, delta, prev_v, now_v in fired:
            thr = entry.alerts.get(alert_key, 0)
            parts.append(
                f"\n  ⚠ <b>{html.escape(label)}</b>: "
                f"<code>{_format_value(state_key, prev_v)}</code> → "
                f"<code>{_format_value(state_key, now_v)}</code> "
                f"(<b>{delta:.2f}%</b> Δ, threshold {thr:.2f}%)"
            )

    for nu in list(_PREV_STATE.keys()):
        if not any(e.netuid == nu for e in entries):
            _PREV_STATE.pop(nu, None)

    if not any_alert:
        return None
    return "\n".join(parts)


async def _tick() -> None:
    entries = load_favorites_config()
    if not entries:
        log.debug("favorites_notifier: no favorites; skipping tick")
        return
    if not any(e.alerts for e in entries):
        log.debug("favorites_notifier: no alert thresholds configured; skipping tick")
        return
    if not favorites_alerts_configured():
        log.debug("favorites_notifier: no alert channels configured; skipping tick")
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

    # Seed baseline on first poll (no Telegram spam on startup)
    if not _PREV_STATE:
        for entry in entries:
            r = next(
                (x for x in overview.get("subnets", []) or [] if int(x.get("netuid", -1)) == entry.netuid),
                None,
            )
            if r:
                _PREV_STATE[entry.netuid] = _extract_metrics(r)
        log.info("favorites_notifier: seeded baseline for %d subnet(s)", len(_PREV_STATE))
        return

    text = _build_alert_text(entries, overview)
    if not text:
        log.debug("favorites_notifier: no thresholds crossed this tick")
        return
    await send_favorites_alert(text)


async def run_favorites_notifier(*, startup_delay_sec: float = 15.0) -> None:
    interval = notify_interval_sec()
    log.info(
        "favorites_notifier: started (interval=%ds, alerts_configured=%s)",
        interval,
        favorites_alerts_configured(),
    )
    try:
        await asyncio.sleep(startup_delay_sec)
        while True:
            await _tick()
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        log.info("favorites_notifier: stopped")
        raise
