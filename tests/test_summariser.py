from datetime import datetime, timezone

from podsummary.models import EpisodeSummary
from podsummary.summariser import Summariser, chunk_text


def test_chunk_text_short_returns_single_chunk():
    assert chunk_text("hello world") == ["hello world"]
    assert chunk_text("") == []


def test_chunk_text_long_splits_on_whitespace():
    text = " ".join(["word"] * 5000)  # ~25k chars
    chunks = chunk_text(text, chunk_chars=1000)
    assert len(chunks) > 1
    assert all(len(c) <= 1000 for c in chunks)
    # No word should be broken across chunks.
    assert all(not c.startswith("ord") for c in chunks)


def test_summarise_episode_short_uses_episode_model(fake_llm, openai_config):
    s = Summariser(fake_llm, openai_config)
    es = s.summarise_episode(
        transcript="A short transcript about testing.",
        title="Testing 101",
        podcast="Dev Show",
        video_id="abc",
        published_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
    )
    assert isinstance(es, EpisodeSummary)
    assert "episode-model" in es.summary
    assert len(fake_llm.calls) == 1
    assert fake_llm.calls[0]["model"] == "episode-model"
    # The episode title and podcast made it into the prompt.
    assert "Testing 101" in fake_llm.calls[0]["user"]
    assert "Dev Show" in fake_llm.calls[0]["user"]


def test_summarise_transcript_long_does_map_reduce(fake_llm, openai_config):
    s = Summariser(fake_llm, openai_config)
    long_text = " ".join(["content"] * 6000)  # forces multiple chunks
    s.summarise_transcript(long_text, title="Big Ep")
    # N chunk calls + 1 reduce call, all on the episode model.
    assert len(fake_llm.calls) >= 3
    assert all(c["model"] == "episode-model" for c in fake_llm.calls)


def test_summarise_period_uses_period_model_and_feeds_episode_summaries(fake_llm, openai_config):
    s = Summariser(fake_llm, openai_config)
    episodes = [
        EpisodeSummary("Ep One", "v1", "u1", datetime(2026, 5, 1, tzinfo=timezone.utc),
                       "agents are great", model="episode-model"),
        EpisodeSummary("Ep Two", "v2", "u2", datetime(2026, 5, 3, tzinfo=timezone.utc),
                       "longevity tips", model="episode-model"),
    ]
    period = s.summarise_period(episodes, "Week of May 1")
    assert "period-model" in period.summary
    last_call = fake_llm.calls[-1]
    assert last_call["model"] == "period-model"
    # Both episode summaries were passed into the period prompt.
    assert "agents are great" in last_call["user"]
    assert "longevity tips" in last_call["user"]
    assert "Ep One" in last_call["user"] and "Ep Two" in last_call["user"]


def test_summarise_period_empty_returns_placeholder(fake_llm, openai_config):
    s = Summariser(fake_llm, openai_config)
    period = s.summarise_period([], "Empty Week")
    assert "No episodes" in period.summary
    assert fake_llm.calls == []  # no LLM call when there is nothing to summarise
