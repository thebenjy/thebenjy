"""Pluggable YouTube transcript retrieval.

Two providers are supported behind a common :class:`TranscriptProvider`
interface so they can be tried in order and unit tested in isolation:

* ``YouTubeTranscriptApiProvider`` - uses ``youtube-transcript-api`` (no key,
  no download; fails when captions are disabled).
* ``YtDlpProvider`` - uses ``yt-dlp`` to download auto/manual subtitles and
  parses the resulting VTT. Heavier but handles more videos.

Heavy third-party imports are deferred to call time so the module (and the
tests for VTT parsing / provider selection) import with only the stdlib.
"""

from __future__ import annotations

import os
import re
import tempfile
from typing import List, Optional, Protocol

from .config import TranscriptConfig


class TranscriptError(Exception):
    """Raised when no provider could retrieve a transcript."""


class TranscriptProvider(Protocol):
    name: str

    def fetch(self, video_id: str, languages: List[str]) -> Optional[str]:
        """Return transcript text, or ``None`` if unavailable from this provider."""


def parse_vtt(vtt_text: str) -> str:
    """Extract spoken text from a WebVTT subtitle blob.

    Drops the ``WEBVTT`` header, cue timing lines, cue numbers and inline tags,
    and de-duplicates consecutive identical lines (common in rolling auto-caps).
    """
    lines: List[str] = []
    for raw in vtt_text.splitlines():
        line = raw.strip()
        if not line or line == "WEBVTT" or line.startswith(("NOTE", "Kind:", "Language:")):
            continue
        if "-->" in line:  # timing cue
            continue
        if line.isdigit():  # cue index
            continue
        line = re.sub(r"<[^>]+>", "", line)  # strip <c>, <00:00:00.000> tags
        line = re.sub(r"&nbsp;?", " ", line).strip()
        if not line:
            continue
        if lines and lines[-1] == line:
            continue
        lines.append(line)
    return " ".join(lines).strip()


class YouTubeTranscriptApiProvider:
    name = "youtube_transcript_api"

    def fetch(self, video_id: str, languages: List[str]) -> Optional[str]:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
        except ImportError:  # pragma: no cover - environment dependent
            return None
        try:
            chunks = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
        except Exception:
            return None
        text = " ".join(c.get("text", "") for c in chunks if c.get("text"))
        text = re.sub(r"\s+", " ", text).strip()
        return text or None


class YtDlpProvider:
    name = "yt_dlp"

    def fetch(self, video_id: str, languages: List[str]) -> Optional[str]:
        try:
            import yt_dlp  # type: ignore
        except ImportError:  # pragma: no cover - optional dependency
            return None
        url = f"https://www.youtube.com/watch?v={video_id}"
        with tempfile.TemporaryDirectory() as tmp:
            outtmpl = os.path.join(tmp, "%(id)s")
            opts = {
                "skip_download": True,
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": languages or ["en"],
                "subtitlesformat": "vtt",
                "outtmpl": outtmpl,
                "quiet": True,
                "no_warnings": True,
            }
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])
            except Exception:
                return None
            for fname in sorted(os.listdir(tmp)):
                if fname.endswith(".vtt"):
                    with open(os.path.join(tmp, fname), "r", encoding="utf-8") as fh:
                        text = parse_vtt(fh.read())
                    if text:
                        return text
        return None


_PROVIDER_REGISTRY = {
    YouTubeTranscriptApiProvider.name: YouTubeTranscriptApiProvider,
    YtDlpProvider.name: YtDlpProvider,
}


def build_providers(config: TranscriptConfig) -> List[TranscriptProvider]:
    providers: List[TranscriptProvider] = []
    for name in config.providers:
        factory = _PROVIDER_REGISTRY.get(name)
        if factory is not None:
            providers.append(factory())
    return providers


def fetch_transcript(
    video_id: str,
    config: TranscriptConfig,
    providers: Optional[List[TranscriptProvider]] = None,
) -> str:
    """Try each configured provider in order; return the first transcript found."""
    providers = providers if providers is not None else build_providers(config)
    for provider in providers:
        text = provider.fetch(video_id, config.languages)
        if text:
            return text
    raise TranscriptError(f"no transcript available for video {video_id}")
