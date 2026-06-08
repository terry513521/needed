# Bittensor Tools Dashboard

A local dashboard for monitoring Bittensor subnet data, favorite subnets, miner rewards, TAO Daily news, and optional notification channels.

The project is split into a FastAPI backend and a React + Vite frontend. In development, Vite serves the UI and proxies `/api` requests to FastAPI. In production, the frontend can be built into `frontend/dist` and served by the backend.

## Features

- Taostats subnet overview, pool, emission, identity, and divergence data.
- Favorite subnet tracking with configurable alert thresholds.
- TaoMarketCap miner status, reward tables, and saved reward history.
- TAO Daily news modal for recent posts.
- Optional Telegram favorites digest.
- Optional Discord favorite-subnet and GitHub commit alerts.
- PM2 process config for keeping the dashboard online.

## Project Layout

```text
dashboard/                  FastAPI backend and API clients
frontend/                   React + TypeScript + Vite frontend
frontend/public/favicon.png Public avatar/favicon image
favorites.yaml              Favorite subnet configuration
notifications.yaml.example  Notification settings template
.env.example                Environment variable template
requirements.txt            Python dependencies
ecosystem.config.cjs        PM2 process config
```

Important backend modules:

- `dashboard/app.py`: FastAPI app, API routes, background tasks, and static frontend serving.
- `dashboard/taostats_client.py`: Taostats API integration, caching, snapshots, and divergence data.
- `dashboard/taomarketcap_client.py`: TaoMarketCap miner data, caching, and local reward history.
- `dashboard/taodaily_client.py`: TAO Daily WordPress API integration.
- `dashboard/favorites.py`: Favorite subnet and alert threshold config.
- `dashboard/*_notify.py`: Telegram and Discord notification helpers.
- `dashboard/github_monitor.py`: GitHub repository commit polling.

## Requirements

- Python 3.12+
- Node.js 20+ recommended
- Taostats API key for the Taostats dashboard panel
- Python packages from `requirements.txt`
- Frontend packages from `frontend/package.json`

## Setup

Create the environment file:

```bash
cp .env.example .env
```

Add your Taostats API key:

```env
TAOSTATS_API_KEY=your_key_here
```

Create or refresh the backend virtual environment:

```bash
python3 -m venv dashboard/venv
dashboard/venv/bin/pip install -r requirements.txt
```

Install frontend dependencies:

```bash
npm --prefix frontend install
```

Optional notification settings can be created from the example:

```bash
cp notifications.yaml.example notifications.yaml
```

## Run In Development

Start the backend from the repo root:

```bash
dashboard/venv/bin/python -m uvicorn dashboard.app:app --reload --host 127.0.0.1 --port 8765
```

Start the frontend from another terminal:

```bash
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```

Open:

```text
http://127.0.0.1:5173
```

The Vite dev server proxies `/api` to `http://127.0.0.1:8765`. You can override that target with `VITE_PROXY_TARGET`.

## Build And Serve From Backend

Build the React app:

```bash
npm --prefix frontend run build
```

Start the backend:

```bash
dashboard/venv/bin/python -m uvicorn dashboard.app:app --host 127.0.0.1 --port 8765
```

Open:

```text
http://127.0.0.1:8765
```

When `frontend/dist/index.html` exists, the backend serves the built UI at `/` and keeps the API under `/api`.

## PM2 Deployment

The included `ecosystem.config.cjs` runs:

```bash
dashboard/venv/bin/python -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8765
```

Build the frontend first:

```bash
npm --prefix frontend run build
```

Start and save the PM2 process:

```bash
pm2 start ecosystem.config.cjs
pm2 save
```

Enable startup after reboot:

```bash
pm2 startup
```

Run the command printed by PM2, then save again:

```bash
pm2 save
```

Useful PM2 commands:

```bash
pm2 status
pm2 logs bittensor-tools-dashboard
pm2 restart bittensor-tools-dashboard
pm2 stop bittensor-tools-dashboard
```

After production code changes:

```bash
npm --prefix frontend run build
pm2 restart bittensor-tools-dashboard
pm2 save
```

## Configuration

See `.env.example` for all supported settings.

Common settings:

```env
TAOSTATS_API_KEY=
TAOSTATS_API_URL=https://api.taostats.io
TAOSTATS_BLOCKS_PER_DAY=7200
TAOSTATS_OVERVIEW_CACHE_TTL_SEC=600

TAOMARKETCAP_API_URL=https://api.taomarketcap.com
TAOMARKETCAP_CACHE_TTL_SEC=86400
TAOMARKETCAP_DAILY_REFRESH_HOUR=0
TAOMARKETCAP_DAILY_REFRESH_MINUTE=0
TAOMARKETCAP_REWARD_HISTORY_DAYS=10
TAOMARKETCAP_PREWARM_NETUIDS=64,84

TAODAILY_API_URL=https://taodaily.io
TAODAILY_POST_LIMIT=30

DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8765
DASHBOARD_CORS_ORIGINS=http://127.0.0.1:5173,http://localhost:5173
```

Telegram:

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
FAVORITES_NOTIFY_INTERVAL_SEC=600
```

Discord and GitHub monitoring:

```env
DISCORD_WEBHOOK_FAVORITES=
DISCORD_WEBHOOK_GITHUB_COMMIT=
GITHUB_TOKEN=
GITHUB_COMMIT_POLL_INTERVAL_SEC=300
```

## Local Data

Favorites are stored in `favorites.yaml` by default.

Taostats divergence snapshots are stored at:

```text
~/.bittensor-tools/taostats_snapshots.json
```

TaoMarketCap miner reward history is stored at:

```text
~/.bittensor-tools/taomarketcap_miner_rewards/
```

Only the latest configured reward days are kept per subnet. The default is 10 days.

## Main API Routes

```text
GET  /api/config
GET  /api/taostats/overview
GET  /api/taostats/divergence/snapshot
GET  /api/taostats/divergence
GET  /api/taomarketcap/subnets/{netuid}/miners
GET  /api/alarms/news
GET  /api/favorites
POST /api/favorites/add
POST /api/favorites/remove
POST /api/favorites
POST /api/favorites/github
POST /api/favorites/alerts
GET  /api/favorites/alert-metrics
GET  /api/notifications/settings
POST /api/notifications/channel
GET  /api/notifications/telegram/status
POST /api/notifications/telegram/test
GET  /api/notifications/discord/status
POST /api/notifications/discord/test
GET  /api/notifications/github/status
```

## Validation

Backend syntax check:

```bash
python3 -m py_compile dashboard/app.py dashboard/taostats_client.py dashboard/taomarketcap_client.py dashboard/taodaily_client.py
```

Frontend lint:

```bash
npm --prefix frontend run lint
```

Frontend build:

```bash
npm --prefix frontend run build
```

## Troubleshooting

If the backend port is already in use:

```bash
ss -ltnp 'sport = :8765'
```

If the frontend cannot reach the API:

```bash
curl http://127.0.0.1:8765/api/config
curl http://127.0.0.1:5173/api/config
```

If Taostats returns rate-limit errors, avoid repeated manual refreshes, increase `TAOSTATS_OVERVIEW_CACHE_TTL_SEC`, and allow snapshots to build over time.

If the miner modal has no previous reward day, let the backend save more than one daily snapshot under `~/.bittensor-tools/taomarketcap_miner_rewards/`.

## Legacy Helper Scripts

The repo also contains older Bittensor helper scripts such as `check_balance.py` and `check_register.py`. They are separate from the dashboard and may require a normal Bittensor wallet under `~/.bittensor/wallets/`.
