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

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

# Load before dashboard imports so modules that read os.environ at import time see .env values.
_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env")
load_dotenv()

from dashboard.logging_config import configure_dashboard_logging

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from dashboard.hotkeys import (
    DEFAULT_CONFIG as HOTKEYS_DEFAULT_PATH,
    add_hotkey,
    check_hotkeys,
    list_configured_hotkeys,
    remove_hotkey,
)
from dashboard.taostats_client import (
    DEFAULT_MIN_DIVERGENCE_PCT,
    DEFAULT_SNAPSHOT_PATH,
    LOOKBACK_TOLERANCE_SEC,
    REQUEST_TIMEOUT,
    TARGET_LOOKBACK_SEC,
    divergence_from_snapshot_file,
    fetch_subnet_overview,
    run_taostats_cycle,
)

_SPA_DIST = _REPO_ROOT / "frontend" / "dist"
_SPA_ASSETS = _SPA_DIST / "assets"

log = logging.getLogger(__name__)


class HotkeyCheckBody(BaseModel):
    netuid: int | None = None
    ss58: str | None = Field(None, description="SS58 hotkey; with netuid, check only this key")


class HotkeyAddBody(BaseModel):
    name: str = ""
    netuid: int
    ss58: str


class HotkeyRemoveBody(BaseModel):
    netuid: int
    ss58: str


def _cors_origins() -> list[str]:
    raw = os.environ.get("DASHBOARD_CORS_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return ["http://127.0.0.1:5173", "http://localhost:5173"]


@asynccontextmanager
async def _lifespan(_: FastAPI):
    # After uvicorn configures logging (disables pre-import loggers), wire our handlers.
    configure_dashboard_logging()
    logging.getLogger(__name__).info(
        "logging ready (DASHBOARD_LOG_LEVEL=%s)",
        os.environ.get("DASHBOARD_LOG_LEVEL", "INFO").strip() or "INFO",
    )
    yield


app = FastAPI(
    title="Bittensor tools dashboard",
    version="0.1.0",
    lifespan=_lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _log_requests(request: Request, call_next):
    start = time.perf_counter()
    path = request.url.path
    noisy = path.startswith("/assets/") or path in ("/favicon.ico",)
    try:
        response = await call_next(request)
    except Exception:
        log.exception("request failed %s %s", request.method, path)
        raise
    elapsed_ms = (time.perf_counter() - start) * 1000
    line = "%s %s -> %s (%.1f ms)" % (request.method, path, response.status_code, elapsed_ms)
    if noisy:
        log.debug(line)
    else:
        log.info(line)
    return response


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
    log.debug("config requested")
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


@app.get("/api/taostats/overview")
def api_taostats_overview() -> dict:
    """All subnets: name, alpha price (pool), emission τ/day, reg cost τ, incentive_burn; no snapshot write."""
    key = os.environ.get("TAOSTATS_API_KEY", "").strip()
    if not key:
        log.warning("GET /api/taostats/overview rejected: TAOSTATS_API_KEY not set")
        raise HTTPException(
            status_code=400,
            detail="Set TAOSTATS_API_KEY in the environment or `.env` (Taostats API key).",
        )
    try:
        return fetch_subnet_overview(key)
    except Exception as e:  # noqa: BLE001
        log.exception("taostats overview failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.get("/api/taostats/divergence/snapshot")
def api_taostats_divergence_snapshot() -> dict:
    """
    Divergence table from the latest JSON snapshot on disk vs ~24h baseline.
    Does not call Taostats or require TAOSTATS_API_KEY (read-only file).
    """
    try:
        return divergence_from_snapshot_file(DEFAULT_SNAPSHOT_PATH, min_divergence_pct=None)
    except Exception as e:  # noqa: BLE001
        log.exception("divergence snapshot read failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/taostats/divergence")
def api_taostats_divergence() -> dict:
    key = os.environ.get("TAOSTATS_API_KEY", "").strip()
    if not key:
        log.warning("GET /api/taostats/divergence rejected: TAOSTATS_API_KEY not set")
        raise HTTPException(
            status_code=400,
            detail="Set TAOSTATS_API_KEY in the environment or `.env` (Taostats API key).",
        )
    try:
        return run_taostats_cycle(key, snapshot_path=DEFAULT_SNAPSHOT_PATH, min_divergence_pct=None)
    except Exception as e:  # noqa: BLE001
        log.exception("taostats divergence cycle failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.get("/api/hotkeys/config")
def api_hotkeys_config() -> dict:
    """Hotkeys from YAML (no chain query)."""
    log.debug("hotkeys config requested")
    return list_configured_hotkeys()


@app.post("/api/hotkeys/entry")
def api_hotkeys_add(body: HotkeyAddBody) -> dict:
    """Append a hotkey row to the YAML on disk (same shape as GET /api/hotkeys/config)."""
    try:
        add_hotkey(body.name, body.netuid, body.ss58)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OSError as e:
        log.exception("hotkeys write failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Could not write hotkeys file: {e}") from e
    log.info("hotkey added netuid=%s", body.netuid)
    return list_configured_hotkeys()


@app.post("/api/hotkeys/remove")
def api_hotkeys_remove(body: HotkeyRemoveBody) -> dict:
    """Remove a hotkey row matching netuid + SS58 from the YAML on disk."""
    try:
        ok = remove_hotkey(body.netuid, body.ss58)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OSError as e:
        log.exception("hotkeys write failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Could not write hotkeys file: {e}") from e
    if not ok:
        raise HTTPException(status_code=404, detail="Hotkey not found for that netuid.")
    log.info("hotkey removed netuid=%s", body.netuid)
    return list_configured_hotkeys()


@app.post("/api/hotkeys/check")
def api_hotkeys_check(
    body: HotkeyCheckBody = Body(default_factory=HotkeyCheckBody),
) -> dict:
    """Check all hotkeys, or one when both `netuid` and `ss58` are set."""
    try:
        if body.netuid is not None and body.ss58 and body.ss58.strip():
            results = check_hotkeys(only_netuid=body.netuid, only_ss58=body.ss58.strip())
        else:
            results = check_hotkeys()
        return {"results": results}
    except Exception as e:  # noqa: BLE001
        log.exception("hotkeys check failed: %s", e)
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
