"""End-to-end orchestration: episodes -> matched videos -> transcripts -> summaries.

Per configured podcast and date range:

1. Get episodes from Spotify (or directly from YouTube if Spotify is not
   configured / the mapping is ``youtube_only``).
2. List the YouTube channel's videos for the same range.
3. Match episodes to videos (fuzzy title + date window).
4. Fetch the transcript for each matched video.
5. Summarise each episode, then roll those summaries up into a period digest.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from .config import Config, PodcastMapping
from .matching import match_episodes
from .models import Episode, Match, PeriodSummary, Video
from .summariser import Summariser
from .transcripts import TranscriptError, build_providers, fetch_transcript

logger = logging.getLogger("podsummary")


def period_bounds(end: Optional[datetime] = None, days: int = 7) -> tuple[datetime, datetime]:
    """Return (start, end) covering the last ``days`` ending at ``end`` (default now)."""
    end = end or datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return end - timedelta(days=days), end


@dataclass
class PodcastResult:
    podcast: str
    period: PeriodSummary
    matches: List[Match] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)


class Pipeline:
    def __init__(
        self,
        config: Config,
        summariser: Summariser,
        spotify_client=None,
        youtube_client=None,
        transcript_providers=None,
    ):
        self.config = config
        self.summariser = summariser
        self._spotify = spotify_client
        self._youtube = youtube_client
        self._providers = (
            transcript_providers
            if transcript_providers is not None
            else build_providers(config.transcripts)
        )

    # Lazily construct the network clients so offline tests can inject fakes.
    @property
    def spotify(self):
        if self._spotify is None:
            from .spotify_client import SpotifyClient

            self._spotify = SpotifyClient(self.config.spotify)
        return self._spotify

    @property
    def youtube(self):
        if self._youtube is None:
            from .youtube_client import YouTubeClient

            self._youtube = YouTubeClient(self.config.youtube)
        return self._youtube

    def _episodes_for(
        self, mapping: PodcastMapping, start: datetime, end: datetime, videos: List[Video]
    ) -> List[Episode]:
        if mapping.youtube_only or not self.config.spotify.configured:
            logger.info("Using YouTube videos as episode source for %s", mapping.label)
            return [
                Episode(
                    title=v.title,
                    published_at=v.published_at,
                    source="youtube",
                    description=v.description,
                    url=v.url,
                )
                for v in videos
            ]
        return self.spotify.get_episodes_for_show(mapping.spotify_name, start, end)

    def run_podcast(
        self, mapping: PodcastMapping, start: datetime, end: datetime
    ) -> PodcastResult:
        period_label = f"{start.date().isoformat()} to {end.date().isoformat()}"
        videos = self.youtube.list_videos(
            start, end, channel=mapping.youtube_channel, channel_id=mapping.youtube_channel_id
        )
        episodes = self._episodes_for(mapping, start, end, videos)
        logger.info(
            "%s: %d episode(s), %d video(s)", mapping.label, len(episodes), len(videos)
        )

        # For youtube_only there's a 1:1 episode/video correspondence already.
        if mapping.youtube_only or not self.config.spotify.configured:
            matches = [
                Match(episode=e, video=v, score=1.0, reason="youtube source")
                for e, v in zip(episodes, videos)
            ]
        else:
            matches = match_episodes(episodes, videos, self.config.matching)

        episode_summaries = []
        skipped: List[str] = []
        for match in matches:
            if not match.matched or match.video is None:
                skipped.append(f"{match.episode.title}: no YouTube match")
                continue
            try:
                transcript = fetch_transcript(
                    match.video.video_id, self.config.transcripts, self._providers
                )
            except TranscriptError as exc:
                skipped.append(f"{match.episode.title}: {exc}")
                continue
            summary = self.summariser.summarise_episode(
                transcript=transcript,
                title=match.episode.title,
                podcast=mapping.label,
                video_id=match.video.video_id,
                video_url=match.video.url,
                published_at=match.episode.published_at,
            )
            episode_summaries.append(summary)

        period = self.summariser.summarise_period(
            episode_summaries, f"{mapping.label} — {period_label}"
        )
        return PodcastResult(
            podcast=mapping.label, period=period, matches=matches, skipped=skipped
        )

    def run(
        self, start: datetime, end: datetime, podcasts: Optional[List[str]] = None
    ) -> List[PodcastResult]:
        mappings = self.config.podcasts
        if podcasts:
            wanted = {p.strip().lower() for p in podcasts}
            mappings = [
                m
                for m in mappings
                if m.spotify_name.lower() in wanted or m.youtube_channel.lower() in wanted
            ]
        results = []
        for mapping in mappings:
            results.append(self.run_podcast(mapping, start, end))
        return results
