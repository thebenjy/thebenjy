from datetime import datetime, timezone

from podsummary.config import SpotifyConfig, YouTubeConfig
from podsummary.spotify_client import SpotifyClient, _parse_release_date
from podsummary.youtube_client import YouTubeClient, _parse_iso8601

from tests.conftest import FakeSession


def test_parse_release_date_precisions():
    assert _parse_release_date("2026-05-10", "day").day == 10
    assert _parse_release_date("2026-05", "month").month == 5
    assert _parse_release_date("2026", "year").year == 2026


def test_spotify_lists_episodes_in_window(monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "secret")
    session = FakeSession()
    session.add_post("accounts.spotify.com", {"access_token": "tok"})
    session.add_get("/search", {"shows": {"items": [{"name": "My Show", "id": "show1"}]}})
    session.add_get(
        "/shows/show1/episodes",
        {
            "items": [
                {"name": "In window", "id": "e1", "release_date": "2026-05-10",
                 "release_date_precision": "day", "external_urls": {"spotify": "u"}},
                {"name": "Too old", "id": "e2", "release_date": "2026-04-01",
                 "release_date_precision": "day"},
            ],
            "next": None,
        },
    )
    client = SpotifyClient(SpotifyConfig(), session=session)
    start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    end = datetime(2026, 5, 31, tzinfo=timezone.utc)
    episodes = client.get_episodes_for_show("My Show", start, end)
    titles = [e.title for e in episodes]
    assert titles == ["In window"]


def test_youtube_api_lists_videos(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    session = FakeSession()
    session.add_get(
        "/search",
        {
            "items": [
                {
                    "id": {"videoId": "vid1"},
                    "snippet": {
                        "title": "Great Video",
                        "publishedAt": "2026-05-10T12:00:00Z",
                        "channelTitle": "Chan",
                    },
                }
            ],
            "nextPageToken": None,
        },
    )
    client = YouTubeClient(YouTubeConfig(prefer="api"), session=session)
    start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    end = datetime(2026, 5, 31, tzinfo=timezone.utc)
    videos = client.list_videos(start, end, channel_id="chan1")
    assert len(videos) == 1
    assert videos[0].video_id == "vid1"
    assert videos[0].url == "https://www.youtube.com/watch?v=vid1"


def test_parse_iso8601_handles_z():
    dt = _parse_iso8601("2026-05-10T12:00:00Z")
    assert dt.tzinfo is not None
    assert dt.year == 2026 and dt.hour == 12
