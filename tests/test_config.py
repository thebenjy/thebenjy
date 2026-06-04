import textwrap

from podsummary.config import Config


def test_defaults_when_empty():
    cfg = Config.from_dict({})
    assert cfg.openai.episode_model == "gpt-4o-mini"
    assert cfg.matching.title_threshold == 0.6
    assert cfg.transcripts.providers == ["youtube_transcript_api", "yt_dlp"]
    assert cfg.podcasts == []


def test_load_from_yaml(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        textwrap.dedent(
            """
            openai:
              episode_model: m1
              period_model: m2
            matching:
              title_threshold: 0.8
              date_window_days: 5
            podcasts:
              - spotify_name: "Show A"
                youtube_channel: "Chan A"
              - spotify_name: "Show B"
                youtube_only: true
            """
        ),
        encoding="utf-8",
    )
    cfg = Config.load(str(path))
    assert cfg.openai.episode_model == "m1"
    assert cfg.openai.period_model == "m2"
    assert cfg.matching.date_window_days == 5
    assert len(cfg.podcasts) == 2
    assert cfg.podcasts[1].youtube_only is True


def test_find_podcast_by_either_name():
    cfg = Config.from_dict(
        {"podcasts": [{"spotify_name": "Show A", "youtube_channel": "Chan A"}]}
    )
    assert cfg.find_podcast("show a") is not None
    assert cfg.find_podcast("Chan A") is not None
    assert cfg.find_podcast("nope") is None


def test_spotify_configured_reflects_env(monkeypatch):
    cfg = Config.from_dict({})
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    assert cfg.spotify.configured is False
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "secret")
    assert cfg.spotify.configured is True
