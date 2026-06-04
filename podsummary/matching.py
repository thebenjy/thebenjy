"""Match Spotify episodes to YouTube videos using fuzzy titles + a date window.

The approach (chosen for robustness):

1. Restrict candidate videos to those published within ``date_window_days`` of
   the episode's release date.
2. Within that window, score each candidate by normalised-title similarity
   (``difflib.SequenceMatcher`` — stdlib, no extra dependency).
3. Accept the best candidate if it clears ``title_threshold``.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Iterable, List, Optional

from .config import MatchingConfig
from .models import Episode, Match, Video

# Noise commonly found in podcast / video titles that hurts naive comparison.
_EPISODE_PREFIX = re.compile(r"^\s*(ep(isode)?\.?\s*#?\d+|#\d+)[:\-\s]*", re.IGNORECASE)
_BRACKETS = re.compile(r"[\(\[\{].*?[\)\]\}]")
_NON_ALNUM = re.compile(r"[^a-z0-9\s]")
_WS = re.compile(r"\s+")
_STOPWORDS = {"the", "a", "an", "with", "and", "podcast", "episode", "ep", "feat", "ft"}


def normalize_title(title: str) -> str:
    """Lower-case and strip episode numbers, bracketed asides, punctuation, stopwords."""
    text = (title or "").lower()
    text = _EPISODE_PREFIX.sub("", text)
    text = _BRACKETS.sub(" ", text)
    text = _NON_ALNUM.sub(" ", text)
    tokens = [t for t in _WS.sub(" ", text).strip().split(" ") if t and t not in _STOPWORDS]
    return " ".join(tokens)


def title_similarity(a: str, b: str) -> float:
    """Return a 0..1 similarity score between two titles after normalisation."""
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    # Reward token containment (e.g. a YouTube title that embeds the episode name).
    sa, sb = set(na.split()), set(nb.split())
    if sa and sb:
        overlap = len(sa & sb) / min(len(sa), len(sb))
    else:
        overlap = 0.0
    return max(ratio, overlap)


def match_episode(
    episode: Episode,
    videos: Iterable[Video],
    config: MatchingConfig,
) -> Match:
    """Find the best video for a single episode within the configured constraints."""
    window = abs(config.date_window_days)
    best: Optional[Video] = None
    best_score = 0.0
    for video in videos:
        delta_days = abs((video.published_at - episode.published_at).days)
        if delta_days > window:
            continue
        score = title_similarity(episode.title, video.title)
        # Slight tie-break preference for closer publish dates.
        adjusted = score - (delta_days * 0.01)
        if adjusted > best_score:
            best_score = adjusted
            best = video

    if best is not None and best_score >= config.title_threshold:
        return Match(
            episode=episode,
            video=best,
            score=round(best_score, 4),
            reason=f"title+date match within {window}d",
        )
    return Match(
        episode=episode,
        video=None,
        score=round(best_score, 4),
        reason="no candidate cleared threshold" if best else "no candidate in date window",
    )


def match_episodes(
    episodes: Iterable[Episode],
    videos: Iterable[Video],
    config: MatchingConfig,
) -> List[Match]:
    """Match every episode; each video may be reused only once (best score wins)."""
    videos = list(videos)
    used: set[str] = set()
    matches: List[Match] = []
    # Greedy assignment: process episodes, skipping already-claimed videos.
    for episode in episodes:
        available = [v for v in videos if v.video_id not in used]
        match = match_episode(episode, available, config)
        if match.matched and match.video is not None:
            used.add(match.video.video_id)
        matches.append(match)
    return matches
