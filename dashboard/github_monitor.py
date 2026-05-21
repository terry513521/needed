"""Poll GitHub repos linked to favorite subnets; alert on new commits via Discord.

Per favorite entry with ``github_url`` set in ``favorites.yaml``, polls the latest
commit on the default branch. First sighting seeds state (no alert); new SHAs post to
``DISCORD_WEBHOOK_GITHUB_COMMIT`` (channel key ``github_commit``).

Optional:
  GITHUB_TOKEN — raises API rate limits
  GITHUB_COMMIT_POLL_INTERVAL_SEC — default 300
  GITHUB_COMMIT_STATE_PATH — JSON file for last-seen SHAs
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from dashboard.discord_notify import is_discord_channel_configured, send_discord_message
from dashboard.favorites import FavoriteEntry, load_favorites_config
from dashboard.notification_settings import CHANNEL_DISCORD_GITHUB_COMMIT, is_channel_enabled

log = logging.getLogger(__name__)

GITHUB_COMMIT_DISCORD_CHANNEL = "github_commit"
GITHUB_API = "https://api.github.com"
DEFAULT_POLL_INTERVAL_SEC = 300
MIN_POLL_INTERVAL_SEC = 60

_REPO_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?(?:/.*)?$",
    re.I,
)


def _state_path() -> Path:
    raw = os.environ.get("GITHUB_COMMIT_STATE_PATH", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".bittensor-tools" / "github_commit_state.json"


def poll_interval_sec() -> int:
    raw = os.environ.get("GITHUB_COMMIT_POLL_INTERVAL_SEC", "").strip()
    try:
        v = int(raw) if raw else DEFAULT_POLL_INTERVAL_SEC
    except ValueError:
        v = DEFAULT_POLL_INTERVAL_SEC
    return max(MIN_POLL_INTERVAL_SEC, v)


def _request_timeout() -> float:
    raw = os.environ.get("GITHUB_REQUEST_TIMEOUT", "").strip()
    try:
        return float(raw) if raw else 20.0
    except ValueError:
        return 20.0


def parse_github_repo_url(url: str) -> tuple[str, str] | None:
    """Return ``(owner, repo)`` or None if not a valid GitHub repo URL."""
    u = (url or "").strip()
    if not u:
        return None
    if not u.startswith(("http://", "https://")):
        u = f"https://{u}"
    m = _REPO_RE.match(u.split("?")[0].rstrip("/"))
    if not m:
        return None
    owner = m.group("owner").strip()
    repo = m.group("repo").strip()
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        return None
    return owner, repo


def normalize_github_url(url: str | None) -> str | None:
    if url is None:
        return None
    u = url.strip()
    if not u:
        return None
    parsed = parse_github_repo_url(u)
    if not parsed:
        raise ValueError("GitHub URL must look like https://github.com/owner/repo")
    owner, repo = parsed
    return f"https://github.com/{owner}/{repo}"


def _auth_headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        return {"Accept": "application/vnd.github+json"}
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
    }


def _load_state() -> dict[str, Any]:
    p = _state_path()
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        log.warning("github state unreadable at %s", p, exc_info=True)
        return {}


def _save_state(state: dict[str, Any]) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def _state_key(netuid: int, owner: str, repo: str) -> str:
    return f"{netuid}:{owner}/{repo}"


def fetch_latest_commit(owner: str, repo: str) -> dict[str, Any] | None:
    """Latest commit on default branch via GitHub REST API."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/commits"
    r = requests.get(
        url,
        params={"per_page": 1},
        headers=_auth_headers(),
        timeout=_request_timeout(),
    )
    if r.status_code == 404:
        log.warning("github repo not found: %s/%s", owner, repo)
        return None
    if r.status_code >= 400:
        raise RuntimeError(f"GitHub API {r.status_code}: {r.text[:300]}")
    data = r.json()
    if not isinstance(data, list) or not data:
        return None
    return data[0]


def _format_commit_message(
    entry: FavoriteEntry,
    owner: str,
    repo: str,
    commit: dict[str, Any],
) -> str:
    sha = (commit.get("sha") or "")[:7]
    html_url = commit.get("html_url") or f"https://github.com/{owner}/{repo}/commits"
    c = commit.get("commit") or {}
    message = (c.get("message") or "").strip().split("\n")[0]
    author = (c.get("author") or {}).get("name") or "unknown"
    repo_slug = f"{owner}/{repo}"
    return (
        f"**GitHub commit · subnet {entry.netuid}**\n"
        f"Repo: `{repo_slug}`\n"
        f"**[{sha}]({html_url})** — {message}\n"
        f"by {author}"
    )


def _check_entry(entry: FavoriteEntry, state: dict[str, Any]) -> list[str]:
    """Returns Discord messages to send (0 or 1). Updates ``state`` in place."""
    if not entry.github_url:
        return []
    parsed = parse_github_repo_url(entry.github_url)
    if not parsed:
        return []
    owner, repo = parsed
    key = _state_key(entry.netuid, owner, repo)

    try:
        commit = fetch_latest_commit(owner, repo)
    except Exception:  # noqa: BLE001
        log.exception("github fetch failed netuid=%s repo=%s/%s", entry.netuid, owner, repo)
        return []

    if not commit:
        return []

    sha = commit.get("sha")
    if not sha:
        return []

    prev = state.get(key)
    state[key] = {"sha": sha, "repo": f"{owner}/{repo}", "netuid": entry.netuid}

    if prev is None:
        log.info("github monitor: seeded netuid=%s %s/%s @ %s", entry.netuid, owner, repo, sha[:7])
        return []

    if prev.get("sha") == sha:
        return []

    log.info("github monitor: new commit netuid=%s %s/%s @ %s", entry.netuid, owner, repo, sha[:7])
    return [_format_commit_message(entry, owner, repo, commit)]


def _github_commit_active() -> bool:
    return is_discord_channel_configured(GITHUB_COMMIT_DISCORD_CHANNEL) and is_channel_enabled(
        CHANNEL_DISCORD_GITHUB_COMMIT
    )


async def _tick() -> None:
    if not _github_commit_active():
        log.debug("github_monitor: GitHub commit channel not active; skipping")
        return

    entries = [e for e in load_favorites_config() if e.github_url]
    if not entries:
        log.debug("github_monitor: no favorites with github_url")
        return

    state = _load_state()
    messages: list[str] = []

    for entry in entries:
        messages.extend(_check_entry(entry, state))

    if state:
        await asyncio.to_thread(_save_state, state)

    for text in messages:
        try:
            await asyncio.to_thread(
                send_discord_message,
                GITHUB_COMMIT_DISCORD_CHANNEL,
                text,
                username="GitHub commits",
            )
        except Exception:  # noqa: BLE001
            log.exception("github_monitor: Discord send failed")


def github_monitor_configured() -> bool:
    return _github_commit_active()


async def run_github_monitor(*, startup_delay_sec: float = 20.0) -> None:
    interval = poll_interval_sec()
    log.info(
        "github_monitor: started (interval=%ds, discord=%s)",
        interval,
        github_monitor_configured(),
    )
    try:
        await asyncio.sleep(startup_delay_sec)
        while True:
            await _tick()
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        log.info("github_monitor: stopped")
        raise
