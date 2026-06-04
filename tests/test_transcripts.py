import os

import pytest

from podsummary.config import TranscriptConfig
from podsummary.transcripts import (
    TranscriptError,
    fetch_transcript,
    parse_vtt,
)


def test_parse_vtt_strips_timing_tags_and_dedupes(fixtures_dir):
    with open(os.path.join(fixtures_dir, "sample.vtt"), encoding="utf-8") as fh:
        text = parse_vtt(fh.read())
    assert "WEBVTT" not in text
    assert "-->" not in text
    assert "<c>" not in text
    # Consecutive duplicate line collapsed to a single occurrence.
    assert text.count("Welcome back to the show.") == 1
    assert "great episode" in text


class _Provider:
    def __init__(self, name, value):
        self.name = name
        self._value = value

    def fetch(self, video_id, languages):
        return self._value


def test_fetch_transcript_uses_first_successful_provider():
    cfg = TranscriptConfig(providers=["a", "b"], languages=["en"])
    providers = [_Provider("a", None), _Provider("b", "got it")]
    assert fetch_transcript("vid", cfg, providers) == "got it"


def test_fetch_transcript_raises_when_all_fail():
    cfg = TranscriptConfig(providers=["a"], languages=["en"])
    providers = [_Provider("a", None)]
    with pytest.raises(TranscriptError):
        fetch_transcript("vid", cfg, providers)
