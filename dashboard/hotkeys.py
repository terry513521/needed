"""Check hotkey registration on-chain (Finney/local) via Bittensor metagraph."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import bittensor as bt
import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "hotkeys.yaml"


def load_hotkey_config(path: Path | None = None) -> dict[str, Any]:
    p = path or Path(os.environ.get("BITTENSOR_TOOLS_HOTKEYS", str(DEFAULT_CONFIG)))
    if not p.exists():
        return {"network": "finney", "hotkeys": []}
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if "hotkeys" not in data:
        data["hotkeys"] = []
    data.setdefault("network", "finney")
    net_override = os.environ.get("BITTENSOR_NETWORK", "").strip()
    if net_override:
        data["network"] = net_override
    return data


def check_hotkeys(config_path: Path | None = None) -> list[dict[str, Any]]:
    cfg = load_hotkey_config(config_path)
    network = cfg.get("network", "finney")
    sub = bt.Subtensor(network=network)
    results: list[dict[str, Any]] = []
    for item in cfg.get("hotkeys", []):
        hk = (item.get("ss58") or item.get("hotkey") or "").strip()
        netuid = int(item.get("netuid", 0))
        name = item.get("name") or hk[:16] + "…"
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
            results.append(
                {
                    "name": name,
                    "netuid": netuid,
                    "hotkey": hk,
                    "registered": False,
                    "error": str(e),
                }
            )
    return results
