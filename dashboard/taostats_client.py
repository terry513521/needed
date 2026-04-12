"""Fetch Taostats subnet data and compute emission vs. registration-burn divergence over ~24h."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

TAOSTATS_BASE = os.environ.get("TAOSTATS_API_URL", "https://api.taostats.io").rstrip("/")
SUBNET_LATEST = f"{TAOSTATS_BASE}/api/subnet/latest/v1"
POOL_LATEST = f"{TAOSTATS_BASE}/api/dtao/pool/latest/v1"

# ~12s blocks → 7200 blocks/day on Finney (override if your network differs)
BLOCKS_PER_DAY = int(os.environ.get("TAOSTATS_BLOCKS_PER_DAY", "7200"))

_snap = os.environ.get("TAOSTATS_SNAPSHOT_PATH", "").strip()
DEFAULT_SNAPSHOT_PATH = (
    Path(_snap).expanduser()
    if _snap
    else Path.home() / ".bittensor-tools" / "taostats_snapshots.json"
)

TARGET_LOOKBACK_SEC = int(os.environ.get("TAOSTATS_LOOKBACK_SEC", "86400"))
LOOKBACK_TOLERANCE_SEC = int(os.environ.get("TAOSTATS_LOOKBACK_TOLERANCE_SEC", "7200"))
REQUEST_TIMEOUT = float(os.environ.get("TAOSTATS_REQUEST_TIMEOUT", "60"))
DEFAULT_MIN_DIVERGENCE_PCT = float(os.environ.get("TAOSTATS_MIN_DIVERGENCE_PCT", "2.0"))


@dataclass
class SubnetPoint:
    netuid: int
    emission: int  # rao (integer string from API)
    neuron_registration_cost: int  # rao — registration burn


@dataclass
class DivergenceRow:
    netuid: int
    emission_pct_per_day: float | None
    burn_pct_per_day: float | None
    divergence_pct_points: float
    emission_now: str
    burn_now: str
    emission_then: str | None
    burn_then: str | None


def _parse_int(s: str | int | None) -> int:
    if s is None:
        return 0
    if isinstance(s, int):
        return s
    s = str(s).strip()
    if not s:
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def _auth_headers(api_key: str) -> dict[str, str]:
    key = api_key.strip()
    if key.lower().startswith("bearer "):
        return {"Authorization": key}
    return {"Authorization": key}


def fetch_latest_subnets(api_key: str, timeout: float | None = None) -> list[dict[str, Any]]:
    """Return raw subnet rows from Taostats latest snapshot (paginated)."""
    if timeout is None:
        timeout = REQUEST_TIMEOUT
    headers = _auth_headers(api_key)
    out: list[dict[str, Any]] = []
    page = 1
    for _ in range(50):
        r = requests.get(
            SUBNET_LATEST,
            headers=headers,
            params={"page": page, "limit": 1024, "order": "netuid_asc"},
            timeout=timeout,
        )
        r.raise_for_status()
        body = r.json()
        data = body.get("data") or []
        out.extend(data)
        pag = body.get("pagination") or {}
        next_page = pag.get("next_page")
        if not next_page:
            break
        page = int(next_page)
    return out


def fetch_latest_pools(api_key: str, timeout: float | None = None) -> list[dict[str, Any]]:
    """dTAO pool snapshot: price (TAO per alpha), name, symbol, etc."""
    if timeout is None:
        timeout = REQUEST_TIMEOUT
    headers = _auth_headers(api_key)
    out: list[dict[str, Any]] = []
    page = 1
    for _ in range(50):
        r = requests.get(
            POOL_LATEST,
            headers=headers,
            params={"page": page, "limit": 200, "order": "netuid_asc"},
            timeout=timeout,
        )
        r.raise_for_status()
        body = r.json()
        data = body.get("data") or []
        out.extend(data)
        pag = body.get("pagination") or {}
        next_page = pag.get("next_page")
        if not next_page:
            break
        page = int(next_page)
    return out


def _parse_float_str(s: Any) -> float | None:
    if s is None:
        return None
    try:
        return float(str(s).strip())
    except ValueError:
        return None


def emission_tau_per_day_from_subnet_row(subnet_row: dict[str, Any]) -> float | None:
    """
    TAO/day into the subnet from Taostats subnet/latest `projected_emission`.

    Per Taostats docs (Subnet Statistics), subnet emission is the share of TAO flowing into
    the subnet each block. `projected_emission` is that rate in τ/block (string or number).
    Daily τ ≈ τ/block × blocks/day. Result is ≥ 0.
    """
    tau_per_block = _parse_float_str(subnet_row.get("projected_emission"))
    if tau_per_block is None or tau_per_block <= 0:
        return None
    tau_per_day = tau_per_block * float(BLOCKS_PER_DAY)
    return float(max(0.0, tau_per_day))


def build_subnet_overview(
    subnet_rows: list[dict[str, Any]],
    pool_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str | None]:
    """Merge subnet/latest + pool/latest by netuid."""
    pools_by_uid: dict[int, dict[str, Any]] = {}
    for row in pool_rows:
        uid = row.get("netuid")
        if uid is not None:
            pools_by_uid[int(uid)] = row

    merged: list[dict[str, Any]] = []
    for row in subnet_rows:
        uid = row.get("netuid")
        if uid is None:
            continue
        netuid = int(uid)
        pool = pools_by_uid.get(netuid)
        name = None
        symbol = None
        price_tao: float | None = None
        if pool:
            name = pool.get("name")
            symbol = pool.get("symbol")
            price_tao = _parse_float_str(pool.get("price"))
        emission_tau_per_day = emission_tau_per_day_from_subnet_row(row)
        # Fraction of miner incentive burned to owner (0–1), per chain hyperparams
        incentive_burn = _parse_float_str(row.get("incentive_burn"))
        raw_reg = row.get("neuron_registration_cost")
        if raw_reg is None:
            neuron_registration_cost_tao: float | None = None
        else:
            neuron_registration_cost_tao = _parse_int(raw_reg) / 1e9
        if name and symbol and str(symbol) != str(name):
            label = f"{name} ({symbol})"
        elif name:
            label = str(name)
        elif symbol:
            label = str(symbol)
        else:
            label = f"Subnet {netuid}"

        merged.append(
            {
                "netuid": netuid,
                "name": label,
                "alpha_price_tao": price_tao,
                "emission_tau_per_day": emission_tau_per_day,
                "neuron_registration_cost_tao": neuron_registration_cost_tao,
                "incentive_burn_rate": incentive_burn,
            }
        )
    merged.sort(key=lambda x: x["netuid"])
    warn: str | None = None
    if not pool_rows:
        warn = "No pool data returned (alpha price may be missing)."
    return merged, warn


def fetch_subnet_overview(api_key: str) -> dict[str, Any]:
    """Latest subnets + pool prices; does not write snapshot files."""
    subnets = fetch_latest_subnets(api_key)
    pool_warning: str | None = None
    try:
        pools = fetch_latest_pools(api_key)
    except Exception as e:  # noqa: BLE001
        pools = []
        pool_warning = f"Pool API error (alpha price unavailable): {e}"
    rows, merge_warn = build_subnet_overview(subnets, pools)
    warnings = [w for w in (pool_warning, merge_warn) if w]
    return {
        "fetched_at": int(time.time()),
        "subnets": rows,
        "pool_warning": " ".join(warnings) if warnings else None,
        "blocks_per_day": BLOCKS_PER_DAY,
    }


def rows_to_points(rows: list[dict[str, Any]]) -> dict[int, SubnetPoint]:
    m: dict[int, SubnetPoint] = {}
    for row in rows:
        uid = row.get("netuid")
        if uid is None:
            continue
        m[int(uid)] = SubnetPoint(
            netuid=int(uid),
            emission=_parse_int(row.get("emission")),
            neuron_registration_cost=_parse_int(row.get("neuron_registration_cost")),
        )
    return m


def pct_change(prev: int, now: int) -> float | None:
    if prev <= 0 and now <= 0:
        return 0.0
    if prev <= 0:
        return None  # undefined relative change from zero baseline
    return (now - prev) / prev * 100.0


def load_snapshots(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def save_snapshots(path: Path, snapshots: list[dict[str, Any]], max_keep: int = 200) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    trimmed = snapshots[-max_keep:]
    path.write_text(json.dumps(trimmed, indent=0), encoding="utf-8")


def append_snapshot(path: Path, points: dict[int, SubnetPoint]) -> list[dict[str, Any]]:
    snapshots = load_snapshots(path)
    entry = {
        "t": int(time.time()),
        "subnets": {
            str(uid): {"e": p.emission, "b": p.neuron_registration_cost}
            for uid, p in points.items()
        },
    }
    snapshots.append(entry)
    save_snapshots(path, snapshots)
    return snapshots


def pick_baseline(snapshots: list[dict[str, Any]], now_t: int | None = None) -> dict[str, Any] | None:
    """Pick snapshot closest to 24h before now (within tolerance)."""
    if not snapshots:
        return None
    now_t = now_t or int(time.time())
    target = now_t - TARGET_LOOKBACK_SEC
    best: dict[str, Any] | None = None
    best_dist = 1e18
    for s in snapshots:
        t = int(s.get("t", 0))
        if not t:
            continue
        dist = abs(t - target)
        if dist < best_dist and dist <= LOOKBACK_TOLERANCE_SEC:
            best_dist = dist
            best = s
    return best


def compute_divergences(
    current: dict[int, SubnetPoint],
    baseline: dict[str, Any] | None,
    min_divergence_pct: float | None = None,
) -> tuple[list[DivergenceRow], str | None]:
    """
    Compare day-over-day % change in chain-reported subnet `emission` vs
    `neuron_registration_cost` (registration burn). Rows where the absolute
    gap between those two % changes exceeds min_divergence_pct are returned.
    """
    if min_divergence_pct is None:
        min_divergence_pct = DEFAULT_MIN_DIVERGENCE_PCT
    if not baseline:
        return [], "Need at least one snapshot from ~24h ago. Keep the dashboard running or wait after the first save."

    then_map = baseline.get("subnets") or {}
    rows: list[DivergenceRow] = []

    for uid, p in sorted(current.items()):
        key = str(uid)
        if key not in then_map:
            continue
        prev_e = int(then_map[key].get("e", 0))
        prev_b = int(then_map[key].get("b", 0))
        pe = pct_change(prev_e, p.emission)
        pb = pct_change(prev_b, p.neuron_registration_cost)
        if pe is None or pb is None:
            div = abs((pe or 0) - (pb or 0)) if (pe is not None or pb is not None) else 0.0
        else:
            div = abs(pe - pb)
        if div >= min_divergence_pct:
            rows.append(
                DivergenceRow(
                    netuid=uid,
                    emission_pct_per_day=pe,
                    burn_pct_per_day=pb,
                    divergence_pct_points=div,
                    emission_now=str(p.emission),
                    burn_now=str(p.neuron_registration_cost),
                    emission_then=str(prev_e),
                    burn_then=str(prev_b),
                )
            )

    rows.sort(key=lambda r: r.divergence_pct_points, reverse=True)
    return rows, None


def run_taostats_cycle(
    api_key: str,
    snapshot_path: Path | None = None,
    min_divergence_pct: float | None = None,
) -> dict[str, Any]:
    """Fetch latest, append snapshot, compute divergences vs ~24h baseline."""
    if min_divergence_pct is None:
        min_divergence_pct = DEFAULT_MIN_DIVERGENCE_PCT
    path = snapshot_path or DEFAULT_SNAPSHOT_PATH
    raw = fetch_latest_subnets(api_key)
    points = rows_to_points(raw)
    snapshots = append_snapshot(path, points)
    baseline = pick_baseline(snapshots[:-1])  # exclude just-appended
    div_rows, warn = compute_divergences(points, baseline, min_divergence_pct=min_divergence_pct)
    return {
        "warning": warn,
        "subnet_count": len(points),
        "snapshot_time": snapshots[-1]["t"] if snapshots else None,
        "baseline_time": baseline["t"] if baseline else None,
        "divergences": [r.__dict__ for r in div_rows],
        "min_divergence_pct": min_divergence_pct,
        "lookback_sec": TARGET_LOOKBACK_SEC,
        "lookback_tolerance_sec": LOOKBACK_TOLERANCE_SEC,
        "snapshot_path": str(path),
    }
