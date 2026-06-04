"""Plain data structures shared across the pipeline stages.

Keeping these as simple dataclasses (rather than tying them to any one API
client) makes every stage easy to unit test with hand-built fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class Episode:
    """A podcast episode discovered on Spotify (or a YouTube-only fallback)."""

    title: str
    published_at: datetime
    source: str = "spotify"  # "spotify" or "youtube"
    spotify_id: Optional[str] = None
    description: str = ""
    duration_ms: Optional[int] = None
    url: Optional[str] = None


@dataclass
class Video:
    """A YouTube video belonging to a configured channel."""

    video_id: str
    title: str
    published_at: datetime
    channel: str = ""
    url: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        if not self.url and self.video_id:
            self.url = f"https://www.youtube.com/watch?v={self.video_id}"


@dataclass
class Match:
    """An episode paired with its best-matching YouTube video."""

    episode: Episode
    video: Optional[Video]
    score: float = 0.0
    reason: str = ""

    @property
    def matched(self) -> bool:
        return self.video is not None


@dataclass
class EpisodeSummary:
    """The per-episode summary produced from a single transcript."""

    episode_title: str
    video_id: Optional[str]
    video_url: Optional[str]
    published_at: Optional[datetime]
    summary: str
    transcript_chars: int = 0
    model: str = ""

    def to_markdown(self) -> str:
        date = self.published_at.date().isoformat() if self.published_at else "unknown date"
        link = f"\n\nSource: {self.video_url}" if self.video_url else ""
        return f"## {self.episode_title}\n\n*{date}*\n\n{self.summary}{link}\n"


@dataclass
class PeriodSummary:
    """The roll-up summary spanning all episode summaries in a period."""

    period_label: str
    summary: str
    episode_summaries: List[EpisodeSummary] = field(default_factory=list)
    model: str = ""

    def to_markdown(self) -> str:
        parts = [f"# Podcast summary — {self.period_label}\n", self.summary, "\n\n---\n"]
        parts.extend(es.to_markdown() for es in self.episode_summaries)
        return "\n".join(parts)
