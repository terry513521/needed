"""Fetch Taostats subnet data and compute emission vs. registration-burn divergence over ~24h."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger(__name__)

TAOSTATS_BASE = os.environ.get("TAOSTATS_API_URL", "https://api.taostats.io").rstrip("/")
SUBNET_LATEST = f"{TAOSTATS_BASE}/api/subnet/latest/v1"
POOL_LATEST = f"{TAOSTATS_BASE}/api/dtao/pool/latest/v1"
SUBNET_EMISSION = f"{TAOSTATS_BASE}/api/dtao/subnet_emission/v1"

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
# Taostats subnet_emission: up to 200 rows/page API max; many tiers allow 50 per request — batch that way.
_raw_emission_lim = int(os.environ.get("TAOSTATS_SUBNET_EMISSION_LIMIT", "50"))
SUBNET_EMISSION_PAGE_LIMIT = max(1, min(200, _raw_emission_lim))
# Enough pages to cover all subnets at one block (e.g. 5 × 50 = 250 rows) without per-netuid calls.
SUBNET_EMISSION_MAX_REQUESTS = max(1, int(os.environ.get("TAOSTATS_SUBNET_EMISSION_MAX_REQUESTS", "5")))
_raw_subnet_latest_lim = int(os.environ.get("TAOSTATS_SUBNET_LATEST_LIMIT", "1024"))
SUBNET_LATEST_PAGE_LIMIT = max(1, min(1024, _raw_subnet_latest_lim))


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
    """Return raw subnet rows from Taostats latest snapshot (paginated, max rows per page)."""
    if timeout is None:
        timeout = REQUEST_TIMEOUT
    headers = _auth_headers(api_key)
    out: list[dict[str, Any]] = []
    page = 1
    for _ in range(50):
        r = requests.get(
            SUBNET_LATEST,
            headers=headers,
            params={"page": page, "limit": SUBNET_LATEST_PAGE_LIMIT, "order": "netuid_asc"},
            timeout=timeout,
        )
        r.raise_for_status()
        body = r.json()
        data = body.get("data") or []
        out.extend(data)
        log.debug(
            "subnet/latest page=%s rows=%s total_so_far=%s",
            page,
            len(data),
            len(out),
        )
        pag = body.get("pagination") or {}
        next_page = pag.get("next_page")
        if not next_page:
            break
        page = int(next_page)
    log.info("subnet/latest done: %s subnet rows", len(out))
    return out


def fetch_latest_pools(api_key: str, timeout: float | None = None) -> list[dict[str, Any]]:
    """dTAO pool snapshot: price (TAO per alpha), name, symbol, etc. (200 rows/page API max)."""
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
        log.debug("pool/latest page=%s rows=%s total_so_far=%s", page, len(data), len(out))
        pag = body.get("pagination") or {}
        next_page = pag.get("next_page")
        if not next_page:
            break
        page = int(next_page)
    log.info("pool/latest done: %s pool rows", len(out))
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
    Mainnet TAO flowing into the subnet pool each day (τ/day).

    From Taostats subnet/latest field `emission`: chain rate in rao/block (same units as
    snapshot `e`). τ/block = rao/block ÷ 1e9; multiply by blocks/day. This is the root
    emission share (TAO into the subnet), not alpha minted to participants.
    """
    tau_per_block = _parse_float_str(subnet_row.get("emission"))
    if tau_per_block is None:
        return None
    tau_per_day = tau_per_block * float(BLOCKS_PER_DAY) / 1e9
    return float(max(0.0, tau_per_day))


def _snapshot_block_number(subnet_rows: list[dict[str, Any]]) -> int | None:
    """Block height for the subnet/latest snapshot (rows should share one block; use max if mixed)."""
    blocks: list[int] = []
    for r in subnet_rows:
        bn = r.get("block_number")
        if bn is None:
            continue
        try:
            blocks.append(int(bn))
        except (TypeError, ValueError):
            continue
    if not blocks:
        return None
    return max(blocks)


def _price_tau_per_alpha_from_emission_row(em_row: dict[str, Any]) -> float | None:
    """
    τ/α from the same subnet_emission row: tao_in_pool / alpha_in_pool (both rao).

    Used when dTAO pool/latest has no row or no `price`, so alpha emission (τ/day) can still
    be shown from bulk subnet_emission data alone.
    """
    tao_rao = _parse_int(em_row.get("tao_in_pool"))
    alpha_rao = _parse_int(em_row.get("alpha_in_pool"))
    if alpha_rao <= 0 or tao_rao < 0:
        return None
    return float(tao_rao) / float(alpha_rao)


def compute_alpha_emission_tau_per_day(alpha_rewards_rao: int, price_tao: float | None) -> float | None:
    """
    Daily value in TAO of subnet alpha emission to participants (α/block × τ/α × blocks/day).

    `alpha_rewards` from Taostats /api/dtao/subnet_emission/v1 is α emitted per block in rao
    (typically 1e9 = 1 α/block for alpha_out). `price_tao` is τ/α from pool/latest or from
    emission row reserves (see _price_tau_per_alpha_from_emission_row).
    """
    if price_tao is None or not isinstance(price_tao, (int, float)) or price_tao <= 0:
        return None
    alpha_per_block = float(alpha_rewards_rao) / 1e9
    return float(max(0.0, alpha_per_block * float(price_tao) * float(BLOCKS_PER_DAY)))


def fetch_subnet_emission_bulk(
    api_key: str,
    *,
    subnet_rows: list[dict[str, Any]] | None = None,
    timeout: float | None = None,
) -> dict[int, dict[str, Any]]:
    """
    Fetch subnet_emission in bulk — never one HTTP call per netuid.

    Each request asks for up to SUBNET_EMISSION_PAGE_LIMIT subnet rows at once (default 50).
    Primary path: `block_number` from subnet/latest + `order=netuid_asc`, then follow `next_page`
    until exhausted or SUBNET_EMISSION_MAX_REQUESTS (default 5) — e.g. 5 × 50 rows for one block.

    Fallback without snapshot block: `block_number_desc` pages, same page size; keep first row
    per netuid when merging across pages.
    """
    return {}
    if timeout is None:
        timeout = REQUEST_TIMEOUT
    headers = _auth_headers(api_key)
    out: dict[int, dict[str, Any]] = {}

    def _merge_rows_overwrite(data: list[dict[str, Any]]) -> None:
        for row in data:
            uid = row.get("netuid")
            if uid is None:
                continue
            out[int(uid)] = row

    def _fetch_pages(params_base: dict[str, Any], *, first_row_only_per_uid: bool) -> None:
        page: int | None = 1
        requests_made = 0
        while page is not None and requests_made < SUBNET_EMISSION_MAX_REQUESTS:
            params = {**params_base, "page": page, "limit": SUBNET_EMISSION_PAGE_LIMIT}
            r = requests.get(SUBNET_EMISSION, headers=headers, params=params, timeout=timeout)
            r.raise_for_status()
            requests_made += 1
            body = r.json()
            data = body.get("data") or []
            log.debug(
                "subnet_emission HTTP #%s page=%s params=%s body_rows=%s",
                requests_made,
                page,
                params_base,
                len(data),
            )
            if first_row_only_per_uid:
                for row in data:
                    uid = row.get("netuid")
                    if uid is None:
                        continue
                    n = int(uid)
                    if n not in out:
                        out[n] = row
            else:
                _merge_rows_overwrite(data)
            next_page = (body.get("pagination") or {}).get("next_page")
            page = int(next_page) if next_page else None

    snap_block = _snapshot_block_number(subnet_rows or [])

    if snap_block is not None:
        log.info("subnet_emission: snapshot block=%s limit=%s max_requests=%s", snap_block, SUBNET_EMISSION_PAGE_LIMIT, SUBNET_EMISSION_MAX_REQUESTS)
        _fetch_pages(
            {"block_number": snap_block, "order": "netuid_asc"},
            first_row_only_per_uid=False,
        )
        log.info("subnet_emission done: %s netuids (block-scoped)", len(out))
        return out

    log.warning("subnet_emission: no block_number on subnet/latest rows; using block_number_desc fallback")
    _fetch_pages({"order": "block_number_desc"}, first_row_only_per_uid=True)
    log.info("subnet_emission done: %s netuids (fallback)", len(out))
    return out


def build_subnet_overview(
    subnet_rows: list[dict[str, Any]],
    pool_rows: list[dict[str, Any]],
    subnet_emission_by_uid: dict[int, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Merge subnet/latest + pool/latest (+ optional subnet_emission) by netuid."""
    pools_by_uid: dict[int, dict[str, Any]] = {}
    for row in pool_rows:
        uid = row.get("netuid")
        if uid is not None:
            pools_by_uid[int(uid)] = row
    emission_by_uid = subnet_emission_by_uid or {}

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
        em_row = emission_by_uid.get(netuid)
        alpha_emission_tau_per_day: float | None = None
        # print("----- debug price tao -----", price_tao)
        if em_row is not None and em_row.get("alpha_rewards") is not None:
            eff_price = price_tao
            if eff_price is None or not isinstance(eff_price, (int, float)) or eff_price <= 0:
                eff_price = _price_tau_per_alpha_from_emission_row(em_row)
        alpha_emission_tau_per_day = price_tao * 7200
            # alpha_emission_tau_per_day = compute_alpha_emission_tau_per_day(
            #     _parse_int(em_row.get("alpha_rewards")), eff_price
            # )
        # Fraction of miner incentive burned to owner (0–1), per chain hyperparams
        # print("----- debug emission tau -----", alpha_emission_tau_per_day)
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
                "alpha_emission_tau_per_day": alpha_emission_tau_per_day,
                "neuron_registration_cost_tao": neuron_registration_cost_tao,
                "incentive_burn_rate": incentive_burn,
            }
        )
    merged.sort(key=lambda x: x["netuid"])
    warn: str | None = None
    if not pool_rows:
        warn = "No pool data returned (alpha price may be missing)."
    return merged, warn


def _fetch_and_build_overview(api_key: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    """
    Shared Taostats pull: raw subnet/latest rows + merged overview rows (same as dashboard table).
    """
    log.info("taostats overview: fetching subnet/latest + pool + subnet_emission")
    subnets = fetch_latest_subnets(api_key)
    pool_warning: str | None = None
    emission_warning: str | None = None
    try:
        pools = fetch_latest_pools(api_key)
    except Exception as e:  # noqa: BLE001
        pools = []
        pool_warning = f"Pool API error (alpha price unavailable): {e}"
        log.warning("%s", pool_warning)
    subnet_emission_by_uid: dict[int, dict[str, Any]] = {}
    try:
        subnet_emission_by_uid = fetch_subnet_emission_bulk(api_key, subnet_rows=subnets)
    except Exception as e:  # noqa: BLE001
        emission_warning = f"Subnet emission API error (alpha emission τ/day unavailable): {e}"
        log.warning("%s", emission_warning)
    rows, merge_warn = build_subnet_overview(subnets, pools, subnet_emission_by_uid)
    warnings = [w for w in (pool_warning, emission_warning, merge_warn) if w]
    if merge_warn:
        log.warning("%s", merge_warn)
    log.info(
        "taostats overview: merged %s subnets (emission rows=%s)",
        len(rows),
        len(subnet_emission_by_uid),
    )
    return subnets, rows, " ".join(warnings) if warnings else None


def fetch_subnet_overview(api_key: str) -> dict[str, Any]:
    """
    Latest subnets + pool prices + subnet alpha emission; does not write snapshot files.

    Uses large page sizes (subnet/latest up to 1024, pool/emission 200) to minimize HTTP calls
    for Taostats rate limits (~5 responses/minute typical).
    """
    _subnets, rows, warn = _fetch_and_build_overview(api_key)
    return {
        "fetched_at": int(time.time()),
        "subnets": rows,
        "pool_warning": warn,
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


def _overview_row_for_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    """Copy merged overview fields for JSON (same keys as /api/taostats/overview subnets[])."""
    return {
        "netuid": int(row["netuid"]),
        "name": row.get("name"),
        "alpha_price_tao": row.get("alpha_price_tao"),
        "emission_tau_per_day": row.get("emission_tau_per_day"),
        "alpha_emission_tau_per_day": row.get("alpha_emission_tau_per_day"),
        "neuron_registration_cost_tao": row.get("neuron_registration_cost_tao"),
        "incentive_burn_rate": row.get("incentive_burn_rate"),
    }


def append_snapshot(
    path: Path,
    points: dict[int, SubnetPoint],
    *,
    overview_by_netuid: dict[int, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Append one time-stamped entry. Each subnet keeps chain fields ``e``/``b`` (rao) for
    divergence math, plus optional ``overview`` (merged dashboard row) when provided.
    """
    snapshots = load_snapshots(path)
    subnets_out: dict[str, Any] = {}
    for uid, p in points.items():
        rec: dict[str, Any] = {"e": p.emission, "b": p.neuron_registration_cost}
        if overview_by_netuid and uid in overview_by_netuid:
            rec["overview"] = _overview_row_for_snapshot(overview_by_netuid[uid])
        subnets_out[str(uid)] = rec
    entry = {
        "t": int(time.time()),
        "subnets": subnets_out,
        "blocks_per_day": BLOCKS_PER_DAY,
    }
    snapshots.append(entry)
    save_snapshots(path, snapshots)
    log.debug("snapshot appended %s subnets -> %s", len(points), path)
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
        prev_entry = then_map[key]
        if not isinstance(prev_entry, dict):
            continue
        prev_e = int(prev_entry.get("e", 0))
        prev_b = int(prev_entry.get("b", 0))
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


def subnet_points_from_snapshot_entry(subnets_obj: dict[str, Any]) -> dict[int, SubnetPoint]:
    """Build SubnetPoint map from one snapshot's ``subnets`` object (keys = netuid str)."""
    points: dict[int, SubnetPoint] = {}
    for key, entry in subnets_obj.items():
        if not isinstance(entry, dict):
            continue
        try:
            uid = int(key)
        except ValueError:
            continue
        points[uid] = SubnetPoint(
            netuid=uid,
            emission=int(entry.get("e", 0)),
            neuron_registration_cost=int(entry.get("b", 0)),
        )
    return points


def divergence_from_snapshot_file(
    snapshot_path: Path | None = None,
    min_divergence_pct: float | None = None,
) -> dict[str, Any]:
    """
    Divergence table from the latest on-disk snapshot vs ~24h baseline — no Taostats API call.

    Baseline is chosen with ``pick_baseline`` relative to the **last** snapshot's timestamp so
    the numbers match what they were when that snapshot was written.
    """
    if min_divergence_pct is None:
        min_divergence_pct = DEFAULT_MIN_DIVERGENCE_PCT
    path = snapshot_path or DEFAULT_SNAPSHOT_PATH
    snapshots = load_snapshots(path)
    base: dict[str, Any] = {
        "warning": None,
        "subnet_count": 0,
        "snapshot_time": None,
        "baseline_time": None,
        "divergences": [],
        "min_divergence_pct": min_divergence_pct,
        "lookback_sec": TARGET_LOOKBACK_SEC,
        "lookback_tolerance_sec": LOOKBACK_TOLERANCE_SEC,
        "snapshot_path": str(path),
        "from_snapshot_file": True,
    }
    if not snapshots:
        base["warning"] = "No snapshots on disk yet. Press Refresh Taostats once to create history."
        return base

    last = snapshots[-1]
    last_t = int(last.get("t", 0))
    subnet_map = last.get("subnets") or {}
    points = subnet_points_from_snapshot_entry(subnet_map)
    base["subnet_count"] = len(points)
    base["snapshot_time"] = last_t if last_t else None

    if len(snapshots) < 2:
        base["warning"] = (
            "Only one snapshot on disk; need an older snapshot (~24h lookback) to compute divergence. "
            "Keep refreshing or wait — then open the page again."
        )
        return base

    prior = snapshots[:-1]
    baseline = pick_baseline(prior, now_t=last_t)
    div_rows, warn = compute_divergences(points, baseline, min_divergence_pct=min_divergence_pct)
    base["warning"] = warn
    base["baseline_time"] = baseline["t"] if baseline else None
    base["divergences"] = [r.__dict__ for r in div_rows]
    log.info(
        "divergence from file: subnets=%s div_rows=%s snapshot_t=%s baseline_t=%s",
        len(points),
        len(div_rows),
        last_t,
        base["baseline_time"],
    )
    return base


def run_taostats_cycle(
    api_key: str,
    snapshot_path: Path | None = None,
    min_divergence_pct: float | None = None,
) -> dict[str, Any]:
    """Fetch latest, append snapshot, compute divergences vs ~24h baseline."""
    if min_divergence_pct is None:
        min_divergence_pct = DEFAULT_MIN_DIVERGENCE_PCT
    path = snapshot_path or DEFAULT_SNAPSHOT_PATH
    log.info("taostats divergence cycle: snapshot_path=%s min_div_pct=%s", path, min_divergence_pct)
    raw, merged_rows, _warn = _fetch_and_build_overview(api_key)
    points = rows_to_points(raw)
    overview_by_netuid = {int(r["netuid"]): r for r in merged_rows}
    snapshots = append_snapshot(path, points, overview_by_netuid=overview_by_netuid)
    baseline = pick_baseline(snapshots[:-1])  # exclude just-appended
    div_rows, warn = compute_divergences(points, baseline, min_divergence_pct=min_divergence_pct)
    if warn:
        log.info("taostats divergence: %s", warn)
    log.info(
        "taostats divergence cycle done: subnet_count=%s divergences=%s baseline_t=%s",
        len(points),
        len(div_rows),
        baseline.get("t") if baseline else None,
    )
    out = {
        "warning": warn,
        "subnet_count": len(points),
        "snapshot_time": snapshots[-1]["t"] if snapshots else None,
        "baseline_time": baseline["t"] if baseline else None,
        "divergences": [r.__dict__ for r in div_rows],
        "min_divergence_pct": min_divergence_pct,
        "lookback_sec": TARGET_LOOKBACK_SEC,
        "lookback_tolerance_sec": LOOKBACK_TOLERANCE_SEC,
        "snapshot_path": str(path),
        "from_snapshot_file": False,
    }
    return out
