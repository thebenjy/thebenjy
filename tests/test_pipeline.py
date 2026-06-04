from datetime import datetime, timezone

from podsummary.config import Config
from podsummary.models import Episode, Video
from podsummary.pipeline import Pipeline, period_bounds
from podsummary.summariser import Summariser

from tests.conftest import FakeLLM


def _dt(day: int) -> datetime:
    return datetime(2026, 5, day, tzinfo=timezone.utc)


class FakeSpotify:
    def __init__(self, episodes):
        self.episodes = episodes

    def get_episodes_for_show(self, name, start, end):
        return list(self.episodes)


class FakeYouTube:
    def __init__(self, videos):
        self.videos = videos

    def list_videos(self, start, end, channel="", channel_id=""):
        return list(self.videos)


class FakeProvider:
    name = "fake"

    def __init__(self, mapping):
        self.mapping = mapping

    def fetch(self, video_id, languages):
        return self.mapping.get(video_id)


def test_period_bounds_default_seven_days():
    start, end = period_bounds(end=_dt(8), days=7)
    assert (end - start).days == 7
    assert start == _dt(1)


def test_pipeline_matches_summarises_and_rolls_up(monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "secret")
    cfg = Config.from_dict(
        {
            "openai": {"episode_model": "ep", "period_model": "per"},
            "matching": {"title_threshold": 0.5, "date_window_days": 3},
            "podcasts": [{"spotify_name": "My Show", "youtube_channel": "Chan"}],
        }
    )
    episodes = [
        Episode(title="AI Agents", published_at=_dt(10)),
        Episode(title="Longevity", published_at=_dt(12)),
        Episode(title="Unmatched Topic", published_at=_dt(14)),
    ]
    videos = [
        Video(video_id="v1", title="AI Agents Full Episode", published_at=_dt(10)),
        Video(video_id="v2", title="Longevity Basics", published_at=_dt(12)),
    ]
    providers = [FakeProvider({"v1": "transcript one", "v2": "transcript two"})]
    summariser = Summariser(FakeLLM(), cfg.openai)
    pipeline = Pipeline(
        cfg,
        summariser,
        spotify_client=FakeSpotify(episodes),
        youtube_client=FakeYouTube(videos),
        transcript_providers=providers,
    )

    results = pipeline.run(_dt(8), _dt(15))
    assert len(results) == 1
    result = results[0]
    # Two matched + summarised, one skipped (no video match).
    assert len(result.period.episode_summaries) == 2
    assert any("Unmatched Topic" in s for s in result.skipped)
    # Period summary built on the period model from the episode summaries.
    assert "per" in result.period.summary


def test_pipeline_youtube_only_fallback_when_no_spotify(monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    cfg = Config.from_dict(
        {"podcasts": [{"spotify_name": "My Show", "youtube_channel": "Chan"}]}
    )
    videos = [Video(video_id="v1", title="Only From YouTube", published_at=_dt(10))]
    providers = [FakeProvider({"v1": "yt transcript"})]
    pipeline = Pipeline(
        cfg,
        Summariser(FakeLLM(), cfg.openai),
        youtube_client=FakeYouTube(videos),
        transcript_providers=providers,
    )
    results = pipeline.run(_dt(8), _dt(15))
    assert len(results[0].period.episode_summaries) == 1
    assert results[0].period.episode_summaries[0].episode_title == "Only From YouTube"
