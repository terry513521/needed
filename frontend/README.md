# Bittensor Tools Frontend

React + TypeScript + Vite frontend for the Bittensor Tools Dashboard.

The frontend displays subnet overview data, favorite subnet alerts, miner rewards, TAO Daily news, and notification settings. During development it proxies API requests to the FastAPI backend.

## Requirements

- Node.js 20+ recommended
- Backend running on `http://127.0.0.1:8765`

## Install

```bash
npm install
```

## Run Locally

From the `frontend` directory:

```bash
npm run dev -- --host 127.0.0.1 --port 5173
```

Open:

```text
http://127.0.0.1:5173
```

The dev server proxies `/api` requests to `http://127.0.0.1:8765`. To use a different backend:

```bash
VITE_PROXY_TARGET=http://127.0.0.1:8765 npm run dev
```

## Build

```bash
npm run build
```

The production build is written to `dist/`. The FastAPI backend can serve this directory from the repo root.

## Preview Build

```bash
npm run preview
```

## Lint

```bash
npm run lint
```

## Public Assets

Files in `public/` are served from the site root by Vite.

The dashboard avatar and browser icon use:

```text
public/favicon.png -> /favicon.png
```

Use root-relative paths such as `/favicon.png` for public files. Do not reference them as `/public/favicon.png`.
