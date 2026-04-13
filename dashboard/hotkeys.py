"""Check hotkey registration on-chain (Finney/local) via Bittensor metagraph."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import bittensor as bt
import yaml

log = logging.getLogger(__name__)

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "hotkeys.yaml"


def hotkeys_yaml_path() -> Path:
    """Resolved path to the hotkeys YAML (env ``BITTENSOR_TOOLS_HOTKEYS`` or repo ``hotkeys.yaml``)."""
    return Path(os.environ.get("BITTENSOR_TOOLS_HOTKEYS", str(DEFAULT_CONFIG))).expanduser()


def _entries_from_cfg(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalized rows: name, netuid, hotkey (ss58)."""
    out: list[dict[str, Any]] = []
    for item in cfg.get("hotkeys", []):
        hk = (item.get("ss58") or item.get("hotkey") or "").strip()
        netuid = int(item.get("netuid", 0))
        name = item.get("name") or (hk[:16] + "…" if hk else "?")
        out.append({"name": name, "netuid": netuid, "hotkey": hk})
    return out


def load_hotkey_config_disk(path: Path | None = None) -> dict[str, Any]:
    """YAML as on disk (no ``BITTENSOR_NETWORK`` override)."""
    p = path or hotkeys_yaml_path()
    if not p.exists():
        return {"network": "finney", "hotkeys": []}
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data.get("hotkeys"), list):
        data["hotkeys"] = []
    data.setdefault("network", "finney")
    return data


def load_hotkey_config(path: Path | None = None) -> dict[str, Any]:
    """Effective config: disk YAML plus optional ``BITTENSOR_NETWORK`` override for reads."""
    data = dict(load_hotkey_config_disk(path))
    net_override = os.environ.get("BITTENSOR_NETWORK", "").strip()
    if net_override:
        data["network"] = net_override
    return data


def save_hotkey_config_disk(data: dict[str, Any], path: Path | None = None) -> None:
    """Write full config dict to YAML (preserves extra top-level keys if present)."""
    p = path or hotkeys_yaml_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(
            data,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )


def add_hotkey(name: str, netuid: int, ss58: str, path: Path | None = None) -> None:
    """Append one hotkey entry; raises ValueError if duplicate or invalid."""
    ss58 = (ss58 or "").strip()
    if not ss58:
        raise ValueError("Hotkey (SS58) is required.")
    data = load_hotkey_config_disk(path)
    netuid = int(netuid)
    for item in data["hotkeys"]:
        nu = int(item.get("netuid", 0))
        hk = (item.get("ss58") or item.get("hotkey") or "").strip()
        if nu == netuid and hk == ss58:
            raise ValueError("This hotkey is already listed for that netuid.")
    label = (name or "").strip() or (ss58[:16] + "…" if len(ss58) > 16 else ss58)
    data["hotkeys"].append({"name": label, "netuid": netuid, "ss58": ss58})
    save_hotkey_config_disk(data, path)


def remove_hotkey(netuid: int, ss58: str, path: Path | None = None) -> bool:
    """Remove matching entry from disk. Returns False if not found."""
    ss58 = (ss58 or "").strip()
    if not ss58:
        raise ValueError("Hotkey (SS58) is required.")
    data = load_hotkey_config_disk(path)
    netuid = int(netuid)
    new_hotkeys: list[dict[str, Any]] = []
    removed = False
    for item in data["hotkeys"]:
        hk = (item.get("ss58") or item.get("hotkey") or "").strip()
        if int(item.get("netuid", 0)) == netuid and hk == ss58:
            removed = True
            continue
        new_hotkeys.append(item)
    if not removed:
        return False
    data["hotkeys"] = new_hotkeys
    save_hotkey_config_disk(data, path)
    return True


def list_configured_hotkeys(path: Path | None = None) -> dict[str, Any]:
    """Config only (no chain): network + hotkeys for the UI."""
    cfg = load_hotkey_config(path)
    return {
        "network": cfg.get("network", "finney"),
        "hotkeys": _entries_from_cfg(cfg),
    }


def check_hotkeys(
    config_path: Path | None = None,
    *,
    only_netuid: int | None = None,
    only_ss58: str | None = None,
) -> list[dict[str, Any]]:
    cfg = load_hotkey_config(config_path)
    network = cfg.get("network", "finney")
    entries = _entries_from_cfg(cfg)
    log.info(
        "check_hotkeys network=%s entries=%s filter_netuid=%s",
        network,
        len(entries),
        only_netuid,
    )
    if only_netuid is not None and only_ss58 is not None:
        only_ss58 = only_ss58.strip()
        entries = [e for e in entries if e["netuid"] == only_netuid and e["hotkey"] == only_ss58]
        if not entries:
            return [
                {
                    "name": "?",
                    "netuid": only_netuid,
                    "hotkey": only_ss58,
                    "registered": False,
                    "uid": None,
                    "error": "hotkey not in config",
                }
            ]
    sub = bt.Subtensor(network=network)
    results: list[dict[str, Any]] = []
    for entry in entries:
        hk = entry["hotkey"]
        netuid = entry["netuid"]
        name = entry["name"]
        if not hk:
            results.append(
                {
                    "name": name,
                    "netuid": netuid,
                    "hotkey": hk,
                    "registered": False,
                    "error": "missing ss58/hotkey",
                }
            )
            continue
        try:
            mg = sub.metagraph(netuid)
            registered = hk in mg.hotkeys
            uid = None
            if registered:
                idx = mg.hotkeys.index(hk)
                uid = int(mg.uids[idx])
            results.append(
                {
                    "name": name,
                    "netuid": netuid,
                    "hotkey": hk,
                    "registered": registered,
                    "uid": uid,
                    "error": None,
                }
            )
        except Exception as e:  # noqa: BLE001 — surface chain errors to UI
            log.warning("metagraph check failed name=%s netuid=%s: %s", name, netuid, e)
            results.append(
                {
                    "name": name,
                    "netuid": netuid,
                    "hotkey": hk,
                    "registered": False,
                    "error": str(e),
                }
            )
    ok = sum(1 for r in results if r.get("registered"))
    log.info("check_hotkeys done: %s registered / %s rows", ok, len(results))
    return results
