"""TAO Daily news helpers for dashboard alarm content."""

from __future__ import annotations

import html
import os
import re
import copy
import threading
import time
from datetime import datetime, timedelta
from typing import Any

import requests

TAODAILY_API_URL = os.environ.get("TAODAILY_API_URL", "https://taodaily.io").rstrip("/")
TAODAILY_REQUEST_TIMEOUT = float(os.environ.get("TAODAILY_REQUEST_TIMEOUT", "20"))
TAODAILY_POST_LIMIT = int(os.environ.get("TAODAILY_POST_LIMIT", "30"))
TAODAILY_CACHE_TTL_SEC = int(os.environ.get("TAODAILY_CACHE_TTL_SEC", "900"))
TAODAILY_STALE_TTL_SEC = int(os.environ.get("TAODAILY_STALE_TTL_SEC", "86400"))

_NEWS_CACHE_LOCK = threading.Lock()
_NEWS_CACHE: dict[str, Any] | None = None


def _strip_html(value: Any) -> str:
    text = value.get("rendered", "") if isinstance(value, dict) else str(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _image_from_media(item: dict[str, Any]) -> tuple[str | None, str | None]:
    media_details = item.get("media_details")
    if isinstance(media_details, dict):
        sizes = media_details.get("sizes")
        if isinstance(sizes, dict):
            for key in ("medium_large", "large", "mh-magazine-content", "medium"):
                candidate = sizes.get(key)
                if isinstance(candidate, dict) and candidate.get("source_url"):
                    return str(candidate["source_url"]), str(item.get("alt_text") or "")
    source_url = item.get("source_url")
    return (str(source_url), str(item.get("alt_text") or "")) if source_url else (None, None)


def _fetch_media_map(media_ids: set[int]) -> dict[int, dict[str, str | None]]:
    if not media_ids:
        return {}
    url = f"{TAODAILY_API_URL}/wp-json/wp/v2/media"
    response = requests.get(
        url,
        headers={"Accept": "application/json", "User-Agent": "bittensor-tools-dashboard/1.0"},
        params={
            "include": ",".join(str(media_id) for media_id in sorted(media_ids)),
            "per_page": min(100, len(media_ids)),
            "_fields": "id,source_url,alt_text,media_details",
        },
        timeout=TAODAILY_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, list):
        return {}
    out: dict[int, dict[str, str | None]] = {}
    for item in body:
        if not isinstance(item, dict):
            continue
        media_id = item.get("id")
        if not isinstance(media_id, int):
            continue
        image_url, image_alt = _image_from_media(item)
        out[media_id] = {"image_url": image_url, "image_alt": image_alt}
    return out


def _fetch_taodaily_recent_news_live() -> dict[str, Any]:
    """Fetch TAO Daily posts published today and yesterday by the site's post date."""
    today = datetime.now().date()
    allowed_dates = {today, today - timedelta(days=1)}
    url = f"{TAODAILY_API_URL}/wp-json/wp/v2/posts"
    response = requests.get(
        url,
        headers={"Accept": "application/json", "User-Agent": "bittensor-tools-dashboard/1.0"},
        params={
            "per_page": max(1, min(100, TAODAILY_POST_LIMIT)),
            "_fields": "date,title,link,excerpt,featured_media",
        },
        timeout=TAODAILY_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, list):
        raise ValueError("Unexpected TAO Daily response; expected a list of posts.")

    filtered: list[tuple[dict[str, Any], datetime, str]] = []
    media_ids: set[int] = set()
    for item in body:
        if not isinstance(item, dict):
            continue
        raw_date = str(item.get("date") or "")
        try:
            published_at = datetime.fromisoformat(raw_date)
        except ValueError:
            continue
        if published_at.date() not in allowed_dates:
            continue
        featured_media = item.get("featured_media")
        if isinstance(featured_media, int) and featured_media > 0:
            media_ids.add(featured_media)
        filtered.append((item, published_at, raw_date))

    media_map = _fetch_media_map(media_ids)
    posts: list[dict[str, Any]] = []
    for item, published_at, raw_date in filtered:
        featured_media = item.get("featured_media")
        media = media_map.get(featured_media) if isinstance(featured_media, int) else None
        posts.append(
            {
                "title": _strip_html(item.get("title")),
                "excerpt": _strip_html(item.get("excerpt")),
                "link": str(item.get("link") or ""),
                "published_at": raw_date,
                "published_date": published_at.date().isoformat(),
                "image_url": media.get("image_url") if media else None,
                "image_alt": media.get("image_alt") if media else None,
            }
        )

    return {
        "source": TAODAILY_API_URL,
        "fetched_at": int(time.time()),
        "date_range": sorted(day.isoformat() for day in allowed_dates),
        "items": posts,
    }


def fetch_taodaily_recent_news() -> dict[str, Any]:
    """Return cached TAO Daily news, falling back to stale data if the source is unavailable."""
    global _NEWS_CACHE
    now = time.time()
    with _NEWS_CACHE_LOCK:
        if _NEWS_CACHE and now - float(_NEWS_CACHE["cached_at"]) < TAODAILY_CACHE_TTL_SEC:
            payload = copy.deepcopy(_NEWS_CACHE["payload"])
            payload["cache_hit"] = True
            payload["cache_age_sec"] = int(now - float(_NEWS_CACHE["cached_at"]))
            return payload
    try:
        payload = _fetch_taodaily_recent_news_live()
    except Exception as e:  # noqa: BLE001
        with _NEWS_CACHE_LOCK:
            if _NEWS_CACHE:
                age = now - float(_NEWS_CACHE["cached_at"])
                if age <= TAODAILY_STALE_TTL_SEC:
                    payload = copy.deepcopy(_NEWS_CACHE["payload"])
                    payload["cache_hit"] = True
                    payload["cache_stale"] = True
                    payload["cache_age_sec"] = int(age)
                    payload["cache_warning"] = f"Live TAO Daily fetch failed; served cached news instead: {e}"
                    return payload
        raise
    with _NEWS_CACHE_LOCK:
        _NEWS_CACHE = {"cached_at": now, "payload": copy.deepcopy(payload)}
    payload["cache_hit"] = False
    payload["cache_age_sec"] = 0
    return payload
