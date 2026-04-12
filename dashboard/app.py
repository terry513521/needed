"""
Local dashboard: Taostats emission vs. registration-burn divergence (~24h) + hotkey checks.

  TAOSTATS_API_KEY — required for Taostats (can live in `.env`)

  Optional (all can be set in `.env`; see `.env.example`):
  TAOSTATS_API_URL, TAOSTATS_SNAPSHOT_PATH, TAOSTATS_MIN_DIVERGENCE_PCT,
  TAOSTATS_LOOKBACK_SEC, TAOSTATS_LOOKBACK_TOLERANCE_SEC, TAOSTATS_REQUEST_TIMEOUT,
  BITTENSOR_TOOLS_HOTKEYS, BITTENSOR_NETWORK, DASHBOARD_HOST, DASHBOARD_PORT,
  DASHBOARD_CORS_ORIGINS (comma-separated, for React dev server)

React UI: `npm run dev` in frontend/ (proxies /api → this server), or `npm run build`
and serve `frontend/dist` from this app (see static mounts below).

Run API + optional static UI: uvicorn dashboard.app:app --reload --host 127.0.0.1 --port 8765
Or:  python -m dashboard.app
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load before dashboard imports so modules that read os.environ at import time see .env values.
_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env")
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from dashboard.hotkeys import DEFAULT_CONFIG as HOTKEYS_DEFAULT_PATH, check_hotkeys
from dashboard.taostats_client import (
    DEFAULT_MIN_DIVERGENCE_PCT,
    DEFAULT_SNAPSHOT_PATH,
    LOOKBACK_TOLERANCE_SEC,
    REQUEST_TIMEOUT,
    TARGET_LOOKBACK_SEC,
    run_taostats_cycle,
)

_SPA_DIST = _REPO_ROOT / "frontend" / "dist"
_SPA_ASSETS = _SPA_DIST / "assets"


def _cors_origins() -> list[str]:
    raw = os.environ.get("DASHBOARD_CORS_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return ["http://127.0.0.1:5173", "http://localhost:5173"]


app = FastAPI(title="Bittensor tools dashboard", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.get("/api/config")
def api_config() -> dict:
    """Effective optional settings (from environment / `.env`). No secrets."""
    net = os.environ.get("BITTENSOR_NETWORK", "").strip()
    return {
        "min_divergence_pct": DEFAULT_MIN_DIVERGENCE_PCT,
        "lookback_sec": TARGET_LOOKBACK_SEC,
        "lookback_tolerance_sec": LOOKBACK_TOLERANCE_SEC,
        "snapshot_path": str(DEFAULT_SNAPSHOT_PATH),
        "taostats_api_url": os.environ.get("TAOSTATS_API_URL", "https://api.taostats.io").rstrip("/"),
        "request_timeout_sec": REQUEST_TIMEOUT,
        "hotkeys_config_path": os.environ.get("BITTENSOR_TOOLS_HOTKEYS", "").strip()
        or str(HOTKEYS_DEFAULT_PATH),
        "bittensor_network_override": net or None,
        "dashboard_host": os.environ.get("DASHBOARD_HOST", "127.0.0.1"),
        "dashboard_port": int(os.environ.get("DASHBOARD_PORT", "8765")),
    }


@app.get("/api/taostats/divergence")
def api_taostats_divergence() -> dict:
    key = os.environ.get("TAOSTATS_API_KEY", "").strip()
    if not key:
        raise HTTPException(
            status_code=400,
            detail="Set TAOSTATS_API_KEY in the environment or `.env` (Taostats API key).",
        )
    try:
        return run_taostats_cycle(key, snapshot_path=DEFAULT_SNAPSHOT_PATH, min_divergence_pct=None)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/api/hotkeys/check")
def api_hotkeys_check() -> dict:
    try:
        results = check_hotkeys()
        return {"results": results}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


if _SPA_ASSETS.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_SPA_ASSETS)), name="spa_assets")


def main() -> None:
    import uvicorn

    host = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
    port = int(os.environ.get("DASHBOARD_PORT", "8765"))
    uvicorn.run("dashboard.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
