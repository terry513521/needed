# Bittensor Tools Dashboard

This repository contains a local Bittensor dashboard with a **FastAPI backend** and a **React + Vite frontend**.

The dashboard focuses on:

- Taostats subnet monitoring and divergence snapshots.
- Favorite subnets with alert thresholds and optional GitHub repo monitoring.
- TaoMarketCap miner status and daily reward charts.
- Local per-subnet miner reward history saved as JSON.
- TAO Daily news shown in a page-load modal.
- Optional Telegram and Discord notifications.

There are also older Python helper scripts for Bittensor wallet/subnet operations, but the main app in this repo is now the dashboard.

## Project Structure

```text
dashboard/                 FastAPI backend and external API clients
frontend/                  React + TypeScript + Vite frontend
favorites.yaml             Favorite subnet config
notifications.yaml.example Notification channel config template
.env.example               Environment variable template
requirements.txt           Python dependencies
```

Important backend modules:

- `dashboard/app.py`: FastAPI routes and background tasks.
- `dashboard/taostats_client.py`: Taostats overview, snapshots, divergence, and rate-limit cache fallback.
- `dashboard/taomarketcap_client.py`: TaoMarketCap miner rewards, daily cache, and local reward history files.
- `dashboard/taodaily_client.py`: TAO Daily WordPress news API integration.
- `dashboard/favorites.py`: Favorite subnet and alert threshold config.
- `dashboard/*_notify.py`: Telegram/Discord notification helpers.

## Requirements

- Python 3.12+
- Node.js 20+ recommended
- A Taostats API key for the Taostats dashboard panel
- Python packages from `requirements.txt`
- Frontend packages from `frontend/package.json`

## Setup

Create `.env` from the example and set your Taostats API key:

```bash
cp .env.example .env
```

Edit `.env`:

```env
TAOSTATS_API_KEY=your_key_here
```

Install Python dependencies into the existing dashboard virtualenv or create your own:

```bash
python3 -m venv dashboard/venv
dashboard/venv/bin/pip install -r requirements.txt
```

Install frontend dependencies:

```bash
npm --prefix frontend install
```

## Run In Development

Use two terminals from the repo root.

Backend:

```bash
dashboard/venv/bin/python -m uvicorn dashboard.app:app --reload --host 127.0.0.1 --port 8765
```

Frontend:

```bash
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```

Open:

```text
http://127.0.0.1:5173
```

The Vite frontend proxies `/api` to the backend at `http://127.0.0.1:8765`.

## Build Frontend And Serve From Backend

The FastAPI backend serves the built React app from `frontend/dist`. Build the frontend whenever UI code changes:

```bash
npm --prefix frontend run build
```

Then start the backend:

```bash
dashboard/venv/bin/python -m uvicorn dashboard.app:app --host 127.0.0.1 --port 8765
```

Open:

```text
http://127.0.0.1:8765
```

When `frontend/dist` exists, the FastAPI server serves both the built frontend and `/api`.

## Recommended PM2 Deployment

PM2 keeps the backend-served dashboard running and restarts it after reboot. The repo includes:

```text
ecosystem.config.cjs
```

That config runs:

```bash
dashboard/venv/bin/python -m uvicorn dashboard.app:app --host 127.0.0.1 --port 8765
```

Build the frontend first:

```bash
npm --prefix frontend run build
```

Start the dashboard with PM2:

```bash
pm2 start ecosystem.config.cjs
pm2 save
```

Enable PM2 startup on reboot:

```bash
pm2 startup
```

PM2 prints a command beginning with `sudo env ... pm2 startup ...`. Run that printed command, then run:

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

## Main Features

### Taostats Monitor

The Taostats panel loads subnet overview data from:

- `https://api.taostats.io/api/subnet/latest/v1`
- `https://api.taostats.io/api/dtao/pool/latest/v1`
- `https://api.taostats.io/api/dtao/subnet_emission/v1`
- `https://api.taostats.io/api/subnet/identity/v1`

It shows subnet metrics such as:

- Alpha price
- TAO emission per day
- Alpha emission per day
- Registration cost
- Incentive burn
- Estimated reward/day

Subnet identity data is used for:

- Subnet website link
- Logo/avatar
- GitHub repo link
- TaoMarketCap and Taostats links

The backend caches Taostats overview data to avoid repeated heavy requests and falls back to stale cached/snapshot data when Taostats rate-limits the app.

### Divergence Snapshots

Refreshing Taostats writes snapshot data used for divergence comparison.

Default snapshot location:

```text
~/.bittensor-tools/taostats_snapshots.json
```

The divergence table compares recent subnet metrics against an older baseline, usually around 24 hours ago.

### TaoMarketCap Miner Rewards

Clicking a subnet’s `Status` button opens a miner reward modal.

The backend fetches miner data from TaoMarketCap:

```text
https://api.taomarketcap.com/internal/v1/subnets/neurons/{netuid}/
```

The modal shows:

- Miner count
- Top miner reward
- Daily TAO reward bar chart
- Miner reward table
- Current and previous saved reward day navigation with arrow buttons

### Local Miner Reward History

Each subnet’s miner daily rewards are saved locally as a JSON file.

Default directory:

```text
~/.bittensor-tools/taomarketcap_miner_rewards/
```

Example:

```text
~/.bittensor-tools/taomarketcap_miner_rewards/subnet_1.json
```

Only the latest 10 saved reward days are kept per subnet by default.

The backend API keeps responses lightweight:

- Full current-day rows are returned in `current_reward_day.daily_rewards`.
- Full previous-day rows are returned in `previous_reward_day.daily_rewards` when available.
- `reward_history` returns lightweight day summaries.
- Duplicate top-level reward arrays are intentionally omitted.

### Favorites And Alerts

Favorites are stored in:

```text
favorites.yaml
```

For each favorite subnet, the UI can store alert thresholds for:

- Alpha price %
- Alpha emission %
- Root emission %
- Burn %
- Registration cost %
- Actual reward %

Favorites can also have a GitHub repo URL for commit monitoring.

### News Modal

On page load, the dashboard opens a news modal containing today and yesterday’s posts from:

```text
https://taodaily.io/
```

Featured images are loaded through the TAO Daily WordPress media API when available.

### Notifications

Optional notification channels:

- Telegram favorites digest
- Discord favorite-subnet alerts
- Discord GitHub commit alerts

Notification channel state is stored in `notifications.yaml` by default.

Copy the example if needed:

```bash
cp notifications.yaml.example notifications.yaml
```

## Environment Variables

See `.env.example` for the full list.

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

Discord:

```env
DISCORD_WEBHOOK_FAVORITES=
DISCORD_WEBHOOK_GITHUB_COMMIT=
```

GitHub monitor:

```env
GITHUB_TOKEN=
GITHUB_COMMIT_POLL_INTERVAL_SEC=300
```

## Useful API Routes

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
POST /api/favorites/alerts
POST /api/favorites/github
GET  /api/notifications/settings
POST /api/notifications/channel
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

### Backend Port Already In Use

Check what is using port `8765`:

```bash
ss -ltnp 'sport = :8765'
```

Stop the old process or use a different port.

### Frontend Cannot Reach API

Check the backend:

```bash
curl http://127.0.0.1:8765/api/config
```

Check the frontend proxy:

```bash
curl http://127.0.0.1:5173/api/config
```

### Taostats 429 Errors

The backend caches Taostats data and can serve stale cached/snapshot data. If you still hit rate limits:

- Avoid repeatedly pressing `Refresh Taostats`.
- Increase `TAOSTATS_OVERVIEW_CACHE_TTL_SEC`.
- Let snapshots build over time.

### No Previous Miner Reward Day

The miner modal can show previous-day rewards only after the backend has saved rewards for multiple days. Saved files are under:

```text
~/.bittensor-tools/taomarketcap_miner_rewards/
```

## Legacy Helper Scripts

The repo still includes older Bittensor helper scripts such as:

- `check_balance.py`
- `check_register.py`

They are separate from the dashboard and may require a normal Bittensor wallet under:

```text
~/.bittensor/wallets/
```