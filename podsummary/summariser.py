"""Hierarchical summarisation: per-episode summaries feed a period roll-up.

The LLM is accessed through a small :class:`LLMClient` protocol so the
summariser can be unit tested with a fake client and so the OpenAI dependency
is only imported when actually used.

Long transcripts are chunked and reduced (map-reduce) before the final
per-episode summary, keeping each request within model limits.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Protocol

from . import prompts
from .config import OpenAIConfig
from .models import EpisodeSummary, PeriodSummary

# Rough character budget per transcript chunk (~ a few thousand tokens).
_CHUNK_CHARS = 12000


class LLMClient(Protocol):
    def complete(self, system: str, user: str, model: str, **kwargs) -> str:
        ...


class OpenAILLM:
    """LLMClient backed by the OpenAI Chat Completions API (lazy import)."""

    def __init__(self, config: OpenAIConfig, client=None):
        self.config = config
        self._client = client

    def _ensure_client(self):
        if self._client is None:
            from openai import OpenAI  # type: ignore

            api_key = self.config.api_key
            if not api_key:
                raise RuntimeError(
                    f"OpenAI API key missing: set {self.config.api_key_env}"
                )
            self._client = OpenAI(api_key=api_key)
        return self._client

    def complete(self, system: str, user: str, model: str, **kwargs) -> str:
        client = self._ensure_client()
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=kwargs.get("temperature", self.config.temperature),
            max_tokens=kwargs.get("max_tokens", self.config.max_output_tokens),
        )
        return resp.choices[0].message.content or ""


def chunk_text(text: str, chunk_chars: int = _CHUNK_CHARS) -> List[str]:
    """Split text into <= chunk_chars pieces, preferring whitespace boundaries."""
    text = text.strip()
    if len(text) <= chunk_chars:
        return [text] if text else []
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_chars, len(text))
        if end < len(text):
            split = text.rfind(" ", start, end)
            if split > start:
                end = split
        chunks.append(text[start:end].strip())
        start = end
    return [c for c in chunks if c]


class Summariser:
    def __init__(self, llm: LLMClient, config: OpenAIConfig):
        self.llm = llm
        self.config = config

    # -- per-episode ---------------------------------------------------------------
    def summarise_transcript(
        self,
        transcript: str,
        title: str = "",
        podcast: str = "",
        published: str = "",
    ) -> str:
        """Summarise one transcript, chunking + reducing if it's long."""
        chunks = chunk_text(transcript)
        if not chunks:
            return ""
        if len(chunks) == 1:
            p = prompts.episode_prompt(podcast, title, published, chunks[0])
            return self.llm.complete(
                p["system"], p["user"], self.config.episode_model
            ).strip()

        # Map: summarise each chunk; Reduce: summarise the concatenated chunk notes.
        partials: List[str] = []
        for i, chunk in enumerate(chunks, 1):
            p = prompts.episode_prompt(
                podcast, f"{title} (part {i}/{len(chunks)})", published, chunk
            )
            partials.append(self.llm.complete(p["system"], p["user"], self.config.episode_model))
        combined = "\n\n".join(partials)
        p = prompts.episode_prompt(podcast, title, published, combined)
        return self.llm.complete(p["system"], p["user"], self.config.episode_model).strip()

    def summarise_episode(
        self,
        transcript: str,
        title: str = "",
        podcast: str = "",
        video_id: Optional[str] = None,
        video_url: Optional[str] = None,
        published_at: Optional[datetime] = None,
    ) -> EpisodeSummary:
        published_str = published_at.date().isoformat() if published_at else ""
        summary = self.summarise_transcript(transcript, title, podcast, published_str)
        return EpisodeSummary(
            episode_title=title,
            video_id=video_id,
            video_url=video_url,
            published_at=published_at,
            summary=summary,
            transcript_chars=len(transcript),
            model=self.config.episode_model,
        )

    # -- period roll-up ------------------------------------------------------------
    def summarise_period(
        self, episode_summaries: List[EpisodeSummary], period_label: str
    ) -> PeriodSummary:
        """Combine per-episode summaries into a single period digest."""
        if not episode_summaries:
            return PeriodSummary(
                period_label=period_label,
                summary="No episodes were summarised for this period.",
                episode_summaries=[],
                model=self.config.period_model,
            )
        blocks = []
        for es in episode_summaries:
            date = es.published_at.date().isoformat() if es.published_at else "unknown date"
            blocks.append(f"### {es.episode_title} ({date})\n{es.summary}")
        p = prompts.period_prompt(period_label, "\n\n".join(blocks))
        digest = self.llm.complete(
            p["system"], p["user"], self.config.period_model
        ).strip()
        return PeriodSummary(
            period_label=period_label,
            summary=digest,
            episode_summaries=episode_summaries,
            model=self.config.period_model,
        )
