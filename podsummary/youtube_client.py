"""List a YouTube channel's videos within a period.

Two backends behind one entry point (mirrors the transcript strategy):

* YouTube Data API v3 (``prefer: api``) - precise publish timestamps, needs an
  API key. Resolves a channel name to a channel id when an id is not supplied.
* yt-dlp (``prefer: yt_dlp`` or as a keyless fallback) - scrapes the channel's
  uploads tab.

Network/3rd-party access is injectable / deferred so the parsing logic is
testable offline.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

import requests

from .config import YouTubeConfig
from .models import Video

_API_BASE = "https://www.googleapis.com/youtube/v3"


def _parse_iso8601(value: str) -> datetime:
    value = (value or "").replace("Z", "+00:00")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class YouTubeClient:
    def __init__(self, config: YouTubeConfig, session: Optional[requests.Session] = None):
        self.config = config
        self.session = session or requests.Session()

    # -- YouTube Data API backend -------------------------------------------------
    def resolve_channel_id(self, channel_name: str) -> Optional[str]:
        resp = self.session.get(
            f"{_API_BASE}/search",
            params={
                "part": "snippet",
                "q": channel_name,
                "type": "channel",
                "maxResults": 1,
                "key": self.config.api_key,
            },
            timeout=30,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            return None
        return items[0]["snippet"]["channelId"]

    def _list_via_api(
        self, channel_id: str, start: datetime, end: datetime
    ) -> List[Video]:
        videos: List[Video] = []
        page_token: Optional[str] = None
        while True:
            params = {
                "part": "snippet",
                "channelId": channel_id,
                "type": "video",
                "order": "date",
                "maxResults": min(self.config.max_results, 50),
                "publishedAfter": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "publishedBefore": end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "key": self.config.api_key,
            }
            if page_token:
                params["pageToken"] = page_token
            resp = self.session.get(f"{_API_BASE}/search", params=params, timeout=30)
            resp.raise_for_status()
            body = resp.json()
            for item in body.get("items", []):
                snippet = item.get("snippet", {})
                vid = (item.get("id") or {}).get("videoId")
                if not vid:
                    continue
                videos.append(
                    Video(
                        video_id=vid,
                        title=snippet.get("title", ""),
                        published_at=_parse_iso8601(snippet.get("publishedAt", "")),
                        channel=snippet.get("channelTitle", ""),
                        description=snippet.get("description", ""),
                    )
                )
            page_token = body.get("nextPageToken")
            if not page_token:
                break
        return videos

    # -- yt-dlp backend -----------------------------------------------------------
    def _list_via_ytdlp(
        self, channel: str, channel_id: str, start: datetime, end: datetime
    ) -> List[Video]:
        try:
            import yt_dlp  # type: ignore
        except ImportError:  # pragma: no cover - optional dependency
            return []
        if channel_id:
            url = f"https://www.youtube.com/channel/{channel_id}/videos"
        else:
            handle = channel if channel.startswith("@") else "@" + channel.replace(" ", "")
            url = f"https://www.youtube.com/{handle}/videos"
        opts = {"quiet": True, "no_warnings": True, "extract_flat": False, "skip_download": True}
        videos: List[Video] = []
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception:  # pragma: no cover - network dependent
            return []
        for entry in (info or {}).get("entries", []) or []:
            if not entry:
                continue
            ts = entry.get("timestamp") or entry.get("release_timestamp")
            if ts is None:
                upload = entry.get("upload_date")  # YYYYMMDD
                if not upload:
                    continue
                published = datetime.strptime(upload, "%Y%m%d").replace(tzinfo=timezone.utc)
            else:
                published = datetime.fromtimestamp(ts, tz=timezone.utc)
            if not (start <= published <= end):
                continue
            videos.append(
                Video(
                    video_id=entry.get("id", ""),
                    title=entry.get("title", ""),
                    published_at=published,
                    channel=entry.get("channel", channel),
                    description=entry.get("description", "") or "",
                )
            )
        return videos

    # -- public entry point -------------------------------------------------------
    def list_videos(
        self,
        start: datetime,
        end: datetime,
        channel: str = "",
        channel_id: str = "",
    ) -> List[Video]:
        use_api = self.config.prefer == "api" and self.config.api_key
        if use_api:
            cid = channel_id or (self.resolve_channel_id(channel) if channel else None)
            if cid:
                videos = self._list_via_api(cid, start, end)
                if videos:
                    return sorted(videos, key=lambda v: v.published_at)
        videos = self._list_via_ytdlp(channel, channel_id, start, end)
        return sorted(videos, key=lambda v: v.published_at)
