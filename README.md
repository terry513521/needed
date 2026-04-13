# bittensor-tools

Python helpers and a small CLI for **subnet registration** (PoW or burn), **watching registration**, **recycle cost**, and **publishing an axon** for mining.

## Install

```bash
pip install -e .
```

Requires a normal Bittensor wallet under `~/.bittensor/wallets/`.

The SDK loads chain defaults from the environment; this package sets `BT_NO_PARSE_CLI_ARGS=1` so `AsyncSubtensor` does not consume your process `argv`.

## CLI

Commands: `bttools` or `subnet-tools` (same entry point).

```bash
bttools status --wallet-name MY_COLDKEY --hotkey MY_HOTKEY --netuid 1
bttools watch --wallet-name MY_COLDKEY --hotkey MY_HOTKEY --netuid 1 --interval 15
bttools register --wallet-name MY_COLDKEY --hotkey MY_HOTKEY --netuid 1 --method burn
bttools register --method pow --cuda   # PoW path; needs torch / optional CUDA
bttools recycle-cost --netuid 1
bttools serve --wallet-name MY_COLDKEY --hotkey MY_HOTKEY --netuid 1 \
  --external-ip 203.0.113.10 --external-port 8091
```

`serve` only submits the on-chain axon advertisement; you still run your miner/Axon process that listens on the advertised host/port.

## Library

```python
import asyncio
from bittensor_tools.registration import fetch_registration_status, watch_registration
from bittensor_tools.wallet_util import load_wallet
import bittensor_tools.compat  # before AsyncSubtensor if you construct it yourself
from bittensor.core.async_subtensor import AsyncSubtensor

async def main():
    wallet = load_wallet("MY_COLDKEY", "MY_HOTKEY")
    async with AsyncSubtensor(network="finney") as s:
        print(await fetch_registration_status(s, 1, wallet.hotkey.ss58_address))

asyncio.run(main())
```

## Taostats + hotkey dashboard

The UI is a **React** app (`frontend/`, Vite + TypeScript) that talks to the **FastAPI** backend (`dashboard/app.py`) over HTTP (`/api/...`). That split keeps chain and Taostats logic on the server while the browser only renders state and issues actions—easy to extend, type-check, and test.

**Requirements**

- **Node.js** (for the frontend) and **Python** venv with this repo’s dependencies.
- Taostats API key: `TAOSTATS_API_KEY` (see [Taostats API docs](https://docs.taostats.io/reference)). Use `.env` at the repo root (see `.env.example`); `python-dotenv` loads it when the backend starts.
- For hotkeys: copy `hotkeys.example.yaml` to `hotkeys.yaml` and list `netuid`, `ss58`, and optional `name`.

**Optional environment variables** (backend / `.env`):

| Variable | Purpose |
|----------|---------|
| `TAOSTATS_API_URL` | Taostats API base URL (default `https://api.taostats.io`) |
| `TAOSTATS_SNAPSHOT_PATH` | Where subnet snapshots JSON is stored (default `~/.bittensor-tools/taostats_snapshots.json`) |
| `TAOSTATS_MIN_DIVERGENCE_PCT` | 24h divergence alert threshold in percentage points (default `2`) |
| `TAOSTATS_LOOKBACK_SEC` / `TAOSTATS_LOOKBACK_TOLERANCE_SEC` | Baseline age and match tolerance (defaults `86400` / `7200`) |
| `TAOSTATS_REQUEST_TIMEOUT` | HTTP timeout seconds for Taostats (default `60`) |
| `BITTENSOR_TOOLS_HOTKEYS` | Path to `hotkeys.yaml` if not at repo root |
| `BITTENSOR_NETWORK` | Overrides `network` in `hotkeys.yaml` (e.g. `finney`) |
| `DASHBOARD_HOST` / `DASHBOARD_PORT` | Bind address for the API (default `127.0.0.1` / `8765`) |
| `DASHBOARD_CORS_ORIGINS` | Comma-separated origins for browser access to the API (defaults include `http://127.0.0.1:5173` for Vite) |

`GET /api/config` returns the effective non-secret settings as JSON.

`GET /api/taostats/overview` lists all subnets using Taostats **`/api/subnet/latest/v1`** and **`/api/dtao/pool/latest/v1`**. **Emission/day (τ)** follows Taostats [Subnet Statistics](https://docs.taostats.io/docs/subnet-statistics) (TAO into the subnet): **`projected_emission`** from subnet/latest (τ per block) × **`TAOSTATS_BLOCKS_PER_DAY`** (default 7200). It is always ≥ 0 (unlike signed staking `net_flow_*` fields). **Incentive burn** is **`incentive_burn`** (0–1, shown as %). The response includes **`blocks_per_day`**. Blue % deltas in the UI are vs your previous refresh (in-memory only).

**Development** (two terminals: API + Vite):

```bash
cp .env.example .env   # set TAOSTATS_API_KEY
source venv/bin/activate
uvicorn dashboard.app:app --reload --host 127.0.0.1 --port 8765

# other terminal:
cd frontend && npm install && npm run dev
```

Open the URL Vite prints (usually http://127.0.0.1:5173). Vite **proxies** `/api` to `http://127.0.0.1:8765`. Override the proxy target with env `VITE_PROXY_TARGET` if your API runs elsewhere.

**Production-style** (single origin: API serves the built SPA):

```bash
cd frontend && npm run build
source venv/bin/activate
uvicorn dashboard.app:app --host 127.0.0.1 --port 8765
```

Then open http://127.0.0.1:8765 — the same server serves `frontend/dist` and `/api`. If `frontend/dist` is missing, `GET /` returns a small JSON hint instead of the UI.

Until a snapshot exists from about one lookback period ago, the UI explains that history is still building (refresh periodically or leave a scheduler running).

**Note:** The default rule compares **two day-over-day percentage changes** (chain `emission` vs. registration burn), not absolute TAO amounts.

node 
v23.3.0
python
v3.12.3

##Service:*
pm2 start uvicorn --name tool-backend \
  --interpreter python3 \
  -- dashboard.app:app --host 127.0.0.1 --port 8765

pm2 start npm --name "tool-frontend" -- run dev
pm2 start npm --name "tool-frontend" -- run dev -- --host 0.0.0.0 --port 5731
npm run dev -- --host 0.0.0.0 --port 5731