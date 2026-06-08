"""TaoMarketCap API helpers for subnet holder/reward views."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

TAOMARKETCAP_API_URL = os.environ.get("TAOMARKETCAP_API_URL", "https://api.taomarketcap.com").rstrip("/")
TAOMARKETCAP_REQUEST_TIMEOUT = float(os.environ.get("TAOMARKETCAP_REQUEST_TIMEOUT", "30"))
TAOMARKETCAP_MAX_MINERS = int(os.environ.get("TAOMARKETCAP_MAX_MINERS", "500"))
TAOMARKETCAP_CACHE_TTL_SEC = int(os.environ.get("TAOMARKETCAP_CACHE_TTL_SEC", "86400"))
TAOMARKETCAP_DAILY_REFRESH_HOUR = int(os.environ.get("TAOMARKETCAP_DAILY_REFRESH_HOUR", "0"))
TAOMARKETCAP_DAILY_REFRESH_MINUTE = int(os.environ.get("TAOMARKETCAP_DAILY_REFRESH_MINUTE", "0"))
TAOMARKETCAP_REWARD_HISTORY_LEGACY_PATH = Path(
    os.environ.get(
        "TAOMARKETCAP_REWARD_HISTORY_PATH",
        str(Path.home() / ".bittensor-tools" / "taomarketcap_miner_rewards_history.json"),
    )
).expanduser()
TAOMARKETCAP_REWARD_HISTORY_DIR = Path(
    os.environ.get(
        "TAOMARKETCAP_REWARD_HISTORY_DIR",
        str(Path.home() / ".bittensor-tools" / "taomarketcap_miner_rewards"),
    )
).expanduser()
TAOMARKETCAP_REWARD_HISTORY_DAYS = max(1, int(os.environ.get("TAOMARKETCAP_REWARD_HISTORY_DAYS", "10")))

log = logging.getLogger(__name__)

_CACHE_LOCK = threading.RLock()
_SUBNET_CACHE: dict[int, dict[str, Any]] = {}


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def _auth_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    key = os.environ.get("TAOMARKETCAP_API_KEY", "").strip()
    if key:
        headers["Authorization"] = key if key.lower().startswith("bearer ") else f"Bearer {key}"
    return headers


def _with_cache_meta(payload: dict[str, Any], *, cache_hit: bool) -> dict[str, Any]:
    out = copy.deepcopy(payload)
    cached_at = int(out.get("cached_at") or out.get("fetched_at") or time.time())
    out["cached_at"] = cached_at
    out["cache_hit"] = cache_hit
    out["cache_ttl_sec"] = TAOMARKETCAP_CACHE_TTL_SEC
    out["cache_expires_at"] = _cache_expires_at(cached_at)
    return out


def _next_daily_refresh_at(reference: datetime) -> datetime:
    target = reference.replace(
        hour=max(0, min(23, TAOMARKETCAP_DAILY_REFRESH_HOUR)),
        minute=max(0, min(59, TAOMARKETCAP_DAILY_REFRESH_MINUTE)),
        second=0,
        microsecond=0,
    )
    if target <= reference:
        target += timedelta(days=1)
    return target


def _cache_expires_at(cached_at: int | float) -> int:
    daily_expiry = int(_next_daily_refresh_at(datetime.fromtimestamp(cached_at)).timestamp())
    if TAOMARKETCAP_CACHE_TTL_SEC <= 0:
        return daily_expiry
    ttl_expiry = int(cached_at + TAOMARKETCAP_CACHE_TTL_SEC)
    return min(daily_expiry, ttl_expiry)


def _cache_is_fresh(payload: dict[str, Any], now: float) -> bool:
    cached_at = float(payload.get("cached_at") or payload.get("fetched_at") or 0)
    return cached_at > 0 and now < _cache_expires_at(cached_at)


def _reward_day(timestamp: int | float | None = None) -> str:
    return datetime.fromtimestamp(timestamp or time.time()).date().isoformat()


def _reward_history_path(netuid: int) -> Path:
    return TAOMARKETCAP_REWARD_HISTORY_DIR / f"subnet_{netuid}.json"


def _load_legacy_reward_history_unlocked(netuid: int) -> dict[str, Any]:
    if not TAOMARKETCAP_REWARD_HISTORY_LEGACY_PATH.exists():
        return {}
    try:
        data = json.loads(TAOMARKETCAP_REWARD_HISTORY_LEGACY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("could not read legacy miner reward history: %s", TAOMARKETCAP_REWARD_HISTORY_LEGACY_PATH)
        return {}
    by_day = ((data.get("subnets") or {}).get(str(netuid)) or {}) if isinstance(data, dict) else {}
    return by_day if isinstance(by_day, dict) else {}


def _load_reward_history_unlocked(netuid: int) -> dict[str, Any]:
    legacy_by_day = _load_legacy_reward_history_unlocked(netuid)
    path = _reward_history_path(netuid)
    if not path.exists():
        return legacy_by_day
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("could not read miner reward history: %s", path)
        return legacy_by_day
    by_day = data.get("days") if isinstance(data, dict) else None
    if not isinstance(by_day, dict):
        return legacy_by_day
    return {**legacy_by_day, **by_day}


def _save_reward_history_unlocked(netuid: int, by_day: dict[str, Any]) -> None:
    path = _reward_history_path(netuid)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "netuid": netuid,
        "updated_at": int(time.time()),
        "days": by_day,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _reward_history_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    fetched_at = int(payload.get("cached_at") or payload.get("fetched_at") or time.time())
    return {
        "date": _reward_day(fetched_at),
        "fetched_at": fetched_at,
        "daily_reward_count": payload.get("daily_reward_count"),
        "total_alpha_per_day": payload.get("total_alpha_per_day"),
        "total_tao_per_day": payload.get("total_tao_per_day"),
        "daily_rewards": copy.deepcopy(payload.get("daily_rewards") or []),
    }


def _compact_reward_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": row.get("rank"),
        "uid": row.get("uid"),
        "netuid": row.get("netuid"),
        "hotkey": row.get("hotkey") or "",
        "coldkey": row.get("coldkey") or "",
        "alpha_per_day": row.get("alpha_per_day"),
        "tao_per_day": row.get("tao_per_day"),
        "incentive": row.get("incentive"),
    }


def _compact_reward_day(day: dict[str, Any], *, include_rows: bool) -> dict[str, Any]:
    out = {
        "date": day.get("date"),
        "fetched_at": day.get("fetched_at"),
        "daily_reward_count": day.get("daily_reward_count"),
        "total_alpha_per_day": day.get("total_alpha_per_day"),
        "total_tao_per_day": day.get("total_tao_per_day"),
    }
    if include_rows:
        out["daily_rewards"] = [
            _compact_reward_row(row)
            for row in (day.get("daily_rewards") or [])
            if isinstance(row, dict)
        ]
    return out


def _record_reward_history_unlocked(netuid: int, payload: dict[str, Any]) -> None:
    snapshot = _reward_history_snapshot(payload)
    day = str(snapshot["date"])
    by_day = _load_reward_history_unlocked(netuid)
    by_day[day] = snapshot
    for old_day in sorted(by_day.keys())[:-TAOMARKETCAP_REWARD_HISTORY_DAYS]:
        by_day.pop(old_day, None)
    _save_reward_history_unlocked(netuid, by_day)


def _reward_history_for_netuid_unlocked(netuid: int) -> list[dict[str, Any]]:
    by_day = _load_reward_history_unlocked(netuid)
    return [
        copy.deepcopy(value)
        for _day, value in sorted(by_day.items(), reverse=True)
        if isinstance(value, dict)
    ]


def _with_reward_history(payload: dict[str, Any]) -> dict[str, Any]:
    netuid = int(payload.get("netuid") or 0)
    with _CACHE_LOCK:
        _record_reward_history_unlocked(netuid, payload)
        history = _reward_history_for_netuid_unlocked(netuid)
    out = copy.deepcopy(payload)
    out["miners"] = []
    out["daily_rewards"] = []
    out["reward_history"] = [_compact_reward_day(day, include_rows=False) for day in history]
    out["available_reward_days"] = [str(item.get("date")) for item in history if item.get("date")]
    out["current_reward_day"] = _compact_reward_day(history[0], include_rows=True) if history else None
    out["previous_reward_day"] = _compact_reward_day(history[1], include_rows=True) if len(history) > 1 else None
    return out


def _prewarm_netuid_list() -> list[int]:
    raw = os.environ.get("TAOMARKETCAP_PREWARM_NETUIDS", "").strip()
    if not raw:
        return []
    out: list[int] = []
    seen: set[int] = set()
    for part in raw.split(","):
        try:
            netuid = int(part.strip())
        except ValueError:
            continue
        if netuid < 0 or netuid in seen:
            continue
        seen.add(netuid)
        out.append(netuid)
    return out


def cached_or_prewarm_netuid_list() -> list[int]:
    with _CACHE_LOCK:
        ids = set(_SUBNET_CACHE.keys())
    ids.update(_prewarm_netuid_list())
    return sorted(ids)


def _seconds_until_next_daily_refresh() -> float:
    now = datetime.now()
    target = _next_daily_refresh_at(now)
    return max(1.0, (target - now).total_seconds())


def _fetch_subnet_miner_rewards_live(netuid: int) -> dict[str, Any]:
    """
    Fetch subnet miner reward data from TaoMarketCap.

    TaoMarketCap endpoint:
      /internal/v1/subnets/neurons/{netuid}/

    Observed row shape:
      {uid, subnet, hotkey, owner, alpha_per_day, alpha_stake, alpha_stake_in_tao, incentive, ...}
    """
    url = f"{TAOMARKETCAP_API_URL}/internal/v1/subnets/neurons/{netuid}/"
    r = requests.get(
        url,
        headers=_auth_headers(),
        timeout=TAOMARKETCAP_REQUEST_TIMEOUT,
    )
    r.raise_for_status()
    body = r.json()
    if not isinstance(body, list):
        raise ValueError("Unexpected TaoMarketCap subnet neurons response; expected a list.")

    price_samples: list[float] = []
    for item in body:
        if not isinstance(item, dict):
            continue
        alpha_stake = _coerce_float(item.get("alpha_stake"))
        alpha_stake_in_tao = _coerce_float(item.get("alpha_stake_in_tao"))
        if alpha_stake and alpha_stake > 0 and alpha_stake_in_tao and alpha_stake_in_tao > 0:
            price_samples.append(alpha_stake_in_tao / alpha_stake)
    price_tao_per_alpha = sorted(price_samples)[len(price_samples) // 2] if price_samples else None

    rows: list[dict[str, Any]] = []
    for item in body:
        if not isinstance(item, dict):
            continue
        if not item.get("is_miner"):
            continue
        alpha_per_day = _coerce_float(item.get("alpha_per_day"))
        tao_per_day = (
            alpha_per_day * price_tao_per_alpha
            if alpha_per_day is not None and price_tao_per_alpha is not None
            else None
        )
        alpha_stake_rao = _coerce_float(item.get("alpha_stake"))
        tao_stake_rao = _coerce_float(item.get("tao_stake"))
        rows.append(
            {
                "rank": int(item.get("uid") or len(rows)),
                "uid": int(item.get("uid") or len(rows)),
                "netuid": netuid,
                "hotkey": str(item.get("hotkey") or ""),
                "coldkey": str(item.get("owner") or ""),
                "percentage": _coerce_float(item.get("staked_percentage")),
                "total_alpha": (alpha_stake_rao / 1e9) if alpha_stake_rao is not None else None,
                "total_alpha_rao": alpha_stake_rao,
                "tao_stake": (tao_stake_rao / 1e9) if tao_stake_rao is not None else None,
                "realized_pnl_tao": None,
                "unrealized_pnl_tao": None,
                "alpha_per_day": alpha_per_day,
                "tao_per_day": tao_per_day,
                "incentive": _coerce_float(item.get("incentive")),
                "miner_performance": _coerce_float(item.get("miner_performance")),
                "flagged": False,
            }
        )

    rows.sort(key=lambda x: int(x["uid"]))
    daily_reward_rows = [
        {**row, "rank": idx}
        for idx, row in enumerate(
            sorted(
                rows,
                key=lambda x: (x["tao_per_day"] is None, -(x["tao_per_day"] or 0.0)),
            )[: max(1, TAOMARKETCAP_MAX_MINERS)],
            start=1,
        )
    ]

    now = int(time.time())
    total_alpha = sum(float(row["total_alpha"] or 0.0) for row in rows)
    total_alpha_per_day = sum(float(row["alpha_per_day"] or 0.0) for row in daily_reward_rows)
    total_tao_per_day = sum(float(row["tao_per_day"] or 0.0) for row in daily_reward_rows)
    return {
        "netuid": netuid,
        "fetched_at": now,
        "cached_at": now,
        "source": url,
        "price_tao_per_alpha": price_tao_per_alpha,
        "total_count": len(rows),
        "miner_count": len(rows),
        "daily_reward_count": len(daily_reward_rows),
        "total_alpha": total_alpha,
        "total_alpha_per_day": total_alpha_per_day,
        "total_tao_per_day": total_tao_per_day,
        "total_realized_pnl_tao": None,
        "total_unrealized_pnl_tao": None,
        "miners": rows,
        "daily_rewards": daily_reward_rows,
    }


def fetch_subnet_miner_rewards(netuid: int, *, refresh: bool = False) -> dict[str, Any]:
    """Return cached subnet holder data, refreshing from TaoMarketCap at most once per day."""
    now = time.time()
    with _CACHE_LOCK:
        cached = _SUBNET_CACHE.get(netuid)
        if cached is not None and not refresh and _cache_is_fresh(cached, now):
            return _with_reward_history(_with_cache_meta(cached, cache_hit=True))

    try:
        live = _fetch_subnet_miner_rewards_live(netuid)
    except Exception as e:  # noqa: BLE001
        with _CACHE_LOCK:
            cached = _SUBNET_CACHE.get(netuid)
            if cached is not None:
                log.warning("taomarketcap live fetch failed netuid=%s; serving stale cache: %s", netuid, e)
                out = _with_cache_meta(cached, cache_hit=True)
                out["cache_stale"] = True
                out["cache_warning"] = f"Live TaoMarketCap fetch failed; served cached miner data instead: {e}"
                return _with_reward_history(out)
        raise
    with _CACHE_LOCK:
        _SUBNET_CACHE[netuid] = copy.deepcopy(live)
    return _with_reward_history(_with_cache_meta(live, cache_hit=False))


def refresh_subnet_miner_cache(netuids: list[int] | None = None) -> dict[str, Any]:
    """Refresh cached subnet holder data for known/preconfigured netuids."""
    targets = netuids if netuids is not None else cached_or_prewarm_netuid_list()
    refreshed: list[int] = []
    failed: dict[int, str] = {}
    for netuid in targets:
        try:
            fetch_subnet_miner_rewards(netuid, refresh=True)
            refreshed.append(netuid)
        except Exception as e:  # noqa: BLE001
            failed[netuid] = str(e)
            log.warning("taomarketcap cache refresh failed netuid=%s: %s", netuid, e)
    return {
        "refreshed": refreshed,
        "failed": failed,
        "target_count": len(targets),
        "refreshed_at": int(time.time()),
    }


async def run_taomarketcap_cache_refresher() -> None:
    """Background loop that refreshes known/prewarmed subnet status cache every morning."""
    prewarm = _prewarm_netuid_list()
    if prewarm:
        log.info("taomarketcap cache prewarm starting for netuids=%s", prewarm)
        await asyncio.to_thread(refresh_subnet_miner_cache, prewarm)
    while True:
        sleep_sec = _seconds_until_next_daily_refresh()
        log.info(
            "taomarketcap cache next daily refresh in %.0fs at %02d:%02d local time",
            sleep_sec,
            TAOMARKETCAP_DAILY_REFRESH_HOUR,
            TAOMARKETCAP_DAILY_REFRESH_MINUTE,
        )
        await asyncio.sleep(sleep_sec)
        targets = cached_or_prewarm_netuid_list()
        if not targets:
            log.info("taomarketcap cache daily refresh skipped: no cached/prewarmed netuids")
            continue
        result = await asyncio.to_thread(refresh_subnet_miner_cache, targets)
        log.info(
            "taomarketcap cache daily refresh done: refreshed=%s failed=%s",
            len(result["refreshed"]),
            len(result["failed"]),
        )
