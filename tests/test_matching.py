from datetime import datetime, timezone

from podsummary.config import MatchingConfig
from podsummary.matching import (
    match_episode,
    match_episodes,
    normalize_title,
    title_similarity,
)
from podsummary.models import Episode, Video


def _dt(day: int) -> datetime:
    return datetime(2026, 5, day, tzinfo=timezone.utc)


def test_normalize_strips_episode_numbers_and_stopwords():
    assert normalize_title("Ep. 42: The Great Podcast Episode!") == "great"
    # Bracketed asides are dropped entirely as noise.
    assert normalize_title("#7 - AI Agents (with a Guest)") == "ai agents"


def test_title_similarity_handles_embedding_and_exact():
    assert title_similarity("AI Agents", "AI Agents") == 1.0
    # YouTube title embeds the episode name plus extra noise.
    assert title_similarity("AI Agents", "AI Agents in Production | Full Episode") >= 0.6
    assert title_similarity("Longevity Basics", "Cooking with cast iron") < 0.4


def test_match_episode_respects_date_window():
    cfg = MatchingConfig(title_threshold=0.6, date_window_days=2)
    ep = Episode(title="AI Agents", published_at=_dt(10))
    near = Video(video_id="near", title="AI Agents Full Episode", published_at=_dt(11))
    far = Video(video_id="far", title="AI Agents Full Episode", published_at=_dt(20))

    match = match_episode(ep, [far, near], cfg)
    assert match.matched
    assert match.video.video_id == "near"


def test_match_episode_below_threshold_returns_unmatched():
    cfg = MatchingConfig(title_threshold=0.9, date_window_days=3)
    ep = Episode(title="Longevity and Healthspan", published_at=_dt(10))
    vid = Video(video_id="v", title="Completely Different Topic", published_at=_dt(10))
    match = match_episode(ep, [vid], cfg)
    assert not match.matched
    assert match.video is None


def test_match_episodes_does_not_reuse_a_video():
    cfg = MatchingConfig(title_threshold=0.5, date_window_days=5)
    e1 = Episode(title="AI Agents", published_at=_dt(10))
    e2 = Episode(title="AI Agents", published_at=_dt(11))
    only = Video(video_id="only", title="AI Agents", published_at=_dt(10))
    matches = match_episodes([e1, e2], [only], cfg)
    matched = [m for m in matches if m.matched]
    assert len(matched) == 1  # the single video is claimed once
