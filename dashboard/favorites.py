"""Persisted list of favorite subnet netuids (YAML on disk).

The list is shared between the React UI (Favorite subnets tab) and the
backend Telegram notifier loop, so it has to live somewhere both sides can
read. Same disk-config pattern as ``hotkeys.yaml``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "favorites.yaml"


def favorites_yaml_path() -> Path:
    """Resolved YAML path (env ``BITTENSOR_TOOLS_FAVORITES`` or repo ``favorites.yaml``)."""
    return Path(os.environ.get("BITTENSOR_TOOLS_FAVORITES", str(DEFAULT_CONFIG))).expanduser()


def _normalize(items: Any) -> list[int]:
    """Coerce arbitrary input to a deduped, sorted list of non-negative netuids."""
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


def load_favorites(path: Path | None = None) -> list[int]:
    """Read YAML; tolerate either ``[1, 2]`` or ``{favorites: [1, 2]}`` shapes."""
    p = path or favorites_yaml_path()
    if not p.exists():
        return []
    try:
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:  # noqa: BLE001 — corrupted yaml shouldn't crash the API
        log.warning("favorites yaml unreadable at %s", p, exc_info=True)
        return []
    if isinstance(data, list):
        return _normalize(data)
    if isinstance(data, dict):
        return _normalize(data.get("favorites"))
    return []


def save_favorites(values: list[int], path: Path | None = None) -> list[int]:
    """Write the (normalized) list and return what was persisted."""
    p = path or favorites_yaml_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    norm = _normalize(values)
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump({"favorites": norm}, f, default_flow_style=False, sort_keys=False)
    return norm


def add_favorite(netuid: int, path: Path | None = None) -> list[int]:
    if not isinstance(netuid, int) or netuid < 0:
        raise ValueError("netuid must be a non-negative integer.")
    cur = load_favorites(path)
    if netuid in cur:
        return cur
    cur.append(netuid)
    return save_favorites(cur, path)


def remove_favorite(netuid: int, path: Path | None = None) -> list[int]:
    if not isinstance(netuid, int) or netuid < 0:
        raise ValueError("netuid must be a non-negative integer.")
    cur = load_favorites(path)
    if netuid not in cur:
        return cur
    return save_favorites([n for n in cur if n != netuid], path)


def set_favorites(values: list[int], path: Path | None = None) -> list[int]:
    """Replace the full list (used by frontend localStorage migration)."""
    return save_favorites(values, path)
