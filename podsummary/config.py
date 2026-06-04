"""Configuration loading for podsummary.

Configuration is split between a YAML file (non-secret settings: model names,
matching thresholds, the manual podcast<->channel mapping) and environment
variables (secrets: API keys). This keeps secrets out of the committed config.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class PodcastMapping:
    """Manual mapping between a Spotify show name and a YouTube channel."""

    spotify_name: str
    youtube_channel: str = ""
    youtube_channel_id: str = ""
    # Optional override: pull episodes straight from YouTube, ignoring Spotify.
    youtube_only: bool = False

    @property
    def label(self) -> str:
        return self.spotify_name or self.youtube_channel or self.youtube_channel_id


@dataclass
class OpenAIConfig:
    episode_model: str = "gpt-4o-mini"
    period_model: str = "gpt-4o-mini"
    api_key_env: str = "OPENAI_API_KEY"
    temperature: float = 0.3
    max_output_tokens: int = 1200

    @property
    def api_key(self) -> Optional[str]:
        return os.environ.get(self.api_key_env)


@dataclass
class MatchingConfig:
    title_threshold: float = 0.6
    date_window_days: int = 3


@dataclass
class TranscriptConfig:
    # Ordered list of providers to try: "youtube_transcript_api", "yt_dlp".
    providers: List[str] = field(default_factory=lambda: ["youtube_transcript_api", "yt_dlp"])
    languages: List[str] = field(default_factory=lambda: ["en"])


@dataclass
class YouTubeConfig:
    # "api" uses the YouTube Data API (needs api_key_env); "yt_dlp" is keyless.
    prefer: str = "api"
    api_key_env: str = "YOUTUBE_API_KEY"
    max_results: int = 50

    @property
    def api_key(self) -> Optional[str]:
        return os.environ.get(self.api_key_env)


@dataclass
class SpotifyConfig:
    client_id_env: str = "SPOTIFY_CLIENT_ID"
    client_secret_env: str = "SPOTIFY_CLIENT_SECRET"
    market: str = "US"

    @property
    def client_id(self) -> Optional[str]:
        return os.environ.get(self.client_id_env)

    @property
    def client_secret(self) -> Optional[str]:
        return os.environ.get(self.client_secret_env)

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


@dataclass
class Config:
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    matching: MatchingConfig = field(default_factory=MatchingConfig)
    transcripts: TranscriptConfig = field(default_factory=TranscriptConfig)
    youtube: YouTubeConfig = field(default_factory=YouTubeConfig)
    spotify: SpotifyConfig = field(default_factory=SpotifyConfig)
    podcasts: List[PodcastMapping] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Config":
        data = data or {}
        return cls(
            openai=OpenAIConfig(**(data.get("openai") or {})),
            matching=MatchingConfig(**(data.get("matching") or {})),
            transcripts=TranscriptConfig(**(data.get("transcripts") or {})),
            youtube=YouTubeConfig(**(data.get("youtube") or {})),
            spotify=SpotifyConfig(**(data.get("spotify") or {})),
            podcasts=[PodcastMapping(**p) for p in (data.get("podcasts") or [])],
        )

    @classmethod
    def load(cls, path: str) -> "Config":
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return cls.from_dict(data)

    def find_podcast(self, name: str) -> Optional[PodcastMapping]:
        name_lc = name.strip().lower()
        for pod in self.podcasts:
            if pod.spotify_name.strip().lower() == name_lc:
                return pod
            if pod.youtube_channel.strip().lower() == name_lc:
                return pod
        return None
