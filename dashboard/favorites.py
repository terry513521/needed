"""Favorite subnets + per-subnet alert thresholds and optional GitHub repo URLs (YAML on disk).

YAML shape::

    favorites:
      - netuid: 78
        alerts:
          burn_pct: 10
        github_url: https://github.com/owner/repo

Legacy ``favorites: [44, 78]`` (plain integers) is still read and migrated on save.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "favorites.yaml"

ALERT_METRIC_KEYS: tuple[str, ...] = (
    "alpha_price_pct",
    "alpha_emission_pct",
    "root_emission_pct",
    "burn_pct",
    "reg_pct",
    "actual_reward_pct",
)


@dataclass
class FavoriteEntry:
    netuid: int
    alerts: dict[str, float] = field(default_factory=dict)
    github_url: str | None = None


def favorites_yaml_path() -> Path:
    return Path(os.environ.get("BITTENSOR_TOOLS_FAVORITES", str(DEFAULT_CONFIG))).expanduser()


def _normalize_netuid_list(items: Any) -> list[int]:
    if not isinstance(items, list):
        return []
    seen: set[int] = set()
    out: list[int] = []
    for v in items:
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n < 0 or n in seen:
            continue
        seen.add(n)
        out.append(n)
    out.sort()
    return out


def _normalize_alerts(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for key in ALERT_METRIC_KEYS:
        if key not in raw:
            continue
        val = raw[key]
        if val is None or val == "":
            continue
        try:
            pct = float(val)
        except (TypeError, ValueError):
            continue
        if not (pct > 0 and pct == pct):
            continue
        out[key] = pct
    return out


def _normalize_github_url_field(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


def _parse_entry(item: Any) -> FavoriteEntry | None:
    if isinstance(item, int):
        return FavoriteEntry(netuid=item, alerts={})
    if not isinstance(item, dict):
        return None
    try:
        netuid = int(item.get("netuid", item.get("id", -1)))
    except (TypeError, ValueError):
        return None
    if netuid < 0:
        return None
    return FavoriteEntry(
        netuid=netuid,
        alerts=_normalize_alerts(item.get("alerts")),
        github_url=_normalize_github_url_field(item.get("github_url")),
    )


def _load_raw(path: Path | None = None) -> Any:
    p = path or favorites_yaml_path()
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:  # noqa: BLE001
        log.warning("favorites yaml unreadable at %s", p, exc_info=True)
        return {}


def load_favorites_config(path: Path | None = None) -> list[FavoriteEntry]:
    data = _load_raw(path)
    if isinstance(data, list):
        return [FavoriteEntry(netuid=n, alerts={}) for n in _normalize_netuid_list(data)]
    if not isinstance(data, dict):
        return []
    raw_fav = data.get("favorites")
    if isinstance(raw_fav, list) and raw_fav and isinstance(raw_fav[0], int):
        return [FavoriteEntry(netuid=n, alerts={}) for n in _normalize_netuid_list(raw_fav)]
    if not isinstance(raw_fav, list):
        return []
    by_netuid: dict[int, FavoriteEntry] = {}
    for item in raw_fav:
        ent = _parse_entry(item)
        if ent is None:
            continue
        if ent.netuid not in by_netuid:
            by_netuid[ent.netuid] = ent
    return sorted(by_netuid.values(), key=lambda e: e.netuid)


def load_favorites(path: Path | None = None) -> list[int]:
    return [e.netuid for e in load_favorites_config(path)]


def _entry_to_row(e: FavoriteEntry) -> dict[str, Any]:
    row: dict[str, Any] = {"netuid": e.netuid, "alerts": {}}
    if e.alerts:
        row["alerts"] = {k: e.alerts[k] for k in ALERT_METRIC_KEYS if k in e.alerts}
    if e.github_url:
        row["github_url"] = e.github_url
    return row


def _entries_to_yaml(entries: list[FavoriteEntry]) -> dict[str, Any]:
    return {"favorites": [_entry_to_row(e) for e in sorted(entries, key=lambda x: x.netuid)]}


def save_favorites_config(entries: list[FavoriteEntry], path: Path | None = None) -> list[FavoriteEntry]:
    p = path or favorites_yaml_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    by_netuid: dict[int, FavoriteEntry] = {}
    for e in entries:
        if e.netuid < 0:
            continue
        by_netuid[e.netuid] = FavoriteEntry(
            netuid=e.netuid,
            alerts=_normalize_alerts(e.alerts),
            github_url=_normalize_github_url_field(e.github_url),
        )
    norm = sorted(by_netuid.values(), key=lambda e: e.netuid)
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(_entries_to_yaml(norm), f, default_flow_style=False, sort_keys=False)
    return norm


def favorites_api_payload(path: Path | None = None) -> dict[str, Any]:
    entries = load_favorites_config(path)
    return {
        "favorites": [
            {
                "netuid": e.netuid,
                "alerts": dict(e.alerts),
                "github_url": e.github_url,
            }
            for e in entries
        ],
    }


def save_favorites(values: list[int], path: Path | None = None) -> list[int]:
    existing = {e.netuid: e for e in load_favorites_config(path)}
    entries = [
        FavoriteEntry(
            netuid=n,
            alerts=dict(existing[n].alerts) if n in existing else {},
            github_url=existing[n].github_url if n in existing else None,
        )
        for n in _normalize_netuid_list(values)
    ]
    save_favorites_config(entries, path)
    return [e.netuid for e in entries]


def add_favorite(netuid: int, path: Path | None = None) -> list[int]:
    if not isinstance(netuid, int) or netuid < 0:
        raise ValueError("netuid must be a non-negative integer.")
    entries = load_favorites_config(path)
    if any(e.netuid == netuid for e in entries):
        return [e.netuid for e in entries]
    entries.append(FavoriteEntry(netuid=netuid, alerts={}))
    save_favorites_config(entries, path)
    return [e.netuid for e in entries]


def remove_favorite(netuid: int, path: Path | None = None) -> list[int]:
    if not isinstance(netuid, int) or netuid < 0:
        raise ValueError("netuid must be a non-negative integer.")
    entries = [e for e in load_favorites_config(path) if e.netuid != netuid]
    save_favorites_config(entries, path)
    return [e.netuid for e in entries]


def set_favorites(values: list[int], path: Path | None = None) -> list[int]:
    return save_favorites(values, path)


def set_favorite_alerts(netuid: int, alerts: dict[str, Any], path: Path | None = None) -> FavoriteEntry:
    if not isinstance(netuid, int) or netuid < 0:
        raise ValueError("netuid must be a non-negative integer.")
    norm_alerts = _normalize_alerts(alerts)
    entries = load_favorites_config(path)
    found = False
    out: list[FavoriteEntry] = []
    for e in entries:
        if e.netuid == netuid:
            out.append(
                FavoriteEntry(netuid=netuid, alerts=norm_alerts, github_url=e.github_url)
            )
            found = True
        else:
            out.append(e)
    if not found:
        raise ValueError(f"netuid {netuid} is not in favorites.")
    save_favorites_config(out, path)
    gh = next((e.github_url for e in out if e.netuid == netuid), None)
    return FavoriteEntry(netuid=netuid, alerts=norm_alerts, github_url=gh)


def set_favorite_github(netuid: int, github_url: str | None, path: Path | None = None) -> FavoriteEntry:
    from dashboard.github_monitor import normalize_github_url

    if not isinstance(netuid, int) or netuid < 0:
        raise ValueError("netuid must be a non-negative integer.")
    norm_url: str | None = None
    if github_url is not None and str(github_url).strip():
        norm_url = normalize_github_url(github_url)
    entries = load_favorites_config(path)
    found = False
    out: list[FavoriteEntry] = []
    alerts: dict[str, float] = {}
    for e in entries:
        if e.netuid == netuid:
            alerts = e.alerts
            out.append(FavoriteEntry(netuid=netuid, alerts=e.alerts, github_url=norm_url))
            found = True
        else:
            out.append(e)
    if not found:
        raise ValueError(f"netuid {netuid} is not in favorites.")
    save_favorites_config(out, path)
    return FavoriteEntry(netuid=netuid, alerts=alerts, github_url=norm_url)


def get_favorite_entry(netuid: int, path: Path | None = None) -> FavoriteEntry | None:
    for e in load_favorites_config(path):
        if e.netuid == netuid:
            return e
    return None
