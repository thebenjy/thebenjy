"""Minimal Spotify Web API client to enumerate a show's episodes in a period.

Uses the Client Credentials flow (no user login required), which is sufficient
for reading public catalogue data. Network access goes through an injectable
``session`` so the client can be unit tested without hitting Spotify.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import List, Optional

import requests

from .config import SpotifyConfig
from .models import Episode

_TOKEN_URL = "https://accounts.spotify.com/api/token"
_API_BASE = "https://api.spotify.com/v1"


def _parse_release_date(value: str, precision: str = "day") -> datetime:
    """Spotify release_date may be YYYY, YYYY-MM or YYYY-MM-DD depending on precision."""
    value = (value or "").strip()
    fmt = {"day": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}.get(precision, "%Y-%m-%d")
    try:
        dt = datetime.strptime(value, fmt)
    except ValueError:
        # Fall back to taking just the leading year if the format is unexpected.
        dt = datetime.strptime(value[:4], "%Y")
    return dt.replace(tzinfo=timezone.utc)


class SpotifyClient:
    def __init__(self, config: SpotifyConfig, session: Optional[requests.Session] = None):
        self.config = config
        self.session = session or requests.Session()
        self._token: Optional[str] = None

    def _authenticate(self) -> str:
        if self._token:
            return self._token
        if not self.config.configured:
            raise RuntimeError(
                "Spotify credentials missing: set "
                f"{self.config.client_id_env} and {self.config.client_secret_env}"
            )
        creds = f"{self.config.client_id}:{self.config.client_secret}".encode("utf-8")
        headers = {"Authorization": "Basic " + base64.b64encode(creds).decode("ascii")}
        resp = self.session.post(
            _TOKEN_URL, data={"grant_type": "client_credentials"}, headers=headers, timeout=30
        )
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        return self._token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._authenticate()}"}

    def find_show_id(self, name: str) -> Optional[str]:
        resp = self.session.get(
            f"{_API_BASE}/search",
            params={"q": name, "type": "show", "market": self.config.market, "limit": 5},
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        items = resp.json().get("shows", {}).get("items", [])
        if not items:
            return None
        # Prefer an exact (case-insensitive) name match, else the top hit.
        for item in items:
            if item.get("name", "").strip().lower() == name.strip().lower():
                return item.get("id")
        return items[0].get("id")

    def list_episodes(
        self, show_id: str, start: datetime, end: datetime
    ) -> List[Episode]:
        """Return episodes released within [start, end], paging through results."""
        episodes: List[Episode] = []
        offset = 0
        while True:
            resp = self.session.get(
                f"{_API_BASE}/shows/{show_id}/episodes",
                params={"market": self.config.market, "limit": 50, "offset": offset},
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            body = resp.json()
            items = body.get("items", []) or []
            for item in items:
                if not item:
                    continue
                released = _parse_release_date(
                    item.get("release_date", ""),
                    item.get("release_date_precision", "day"),
                )
                if start <= released <= end:
                    episodes.append(
                        Episode(
                            title=item.get("name", ""),
                            published_at=released,
                            source="spotify",
                            spotify_id=item.get("id"),
                            description=item.get("description", ""),
                            duration_ms=item.get("duration_ms"),
                            url=(item.get("external_urls") or {}).get("spotify"),
                        )
                    )
            # Episodes are returned newest-first; stop once we page past the window.
            if items and _parse_release_date(
                items[-1].get("release_date", ""),
                items[-1].get("release_date_precision", "day"),
            ) < start:
                break
            if not body.get("next"):
                break
            offset += 50
        episodes.sort(key=lambda e: e.published_at)
        return episodes

    def get_episodes_for_show(
        self, name: str, start: datetime, end: datetime
    ) -> List[Episode]:
        show_id = self.find_show_id(name)
        if not show_id:
            return []
        return self.list_episodes(show_id, start, end)
