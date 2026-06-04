"""Prompt templates for episode and period summarisation.

Templates are kept here (separate from the OpenAI call) so they can be
inspected, tweaked, and exercised against test input files without any
network access. Use :func:`render` to fill a template.
"""

from __future__ import annotations

from typing import Dict

EPISODE_SYSTEM = (
    "You are an expert podcast analyst. You write clear, faithful summaries of "
    "podcast episodes from their transcripts. You never invent facts that are "
    "not supported by the transcript."
)

EPISODE_USER = """\
Summarise the following podcast episode transcript.

Podcast: {podcast}
Episode title: {title}
Published: {published}

Write the summary as:
1. A one-sentence TL;DR.
2. 3-6 bullet points covering the key topics, arguments, and takeaways.
3. Any notable quotes, names, books, or resources mentioned (omit if none).

Keep it concise and grounded strictly in the transcript.

TRANSCRIPT:
\"\"\"
{transcript}
\"\"\"
"""

PERIOD_SYSTEM = (
    "You are an expert editor producing a digest across multiple podcast "
    "episodes. You synthesise per-episode summaries into a single cohesive "
    "overview, drawing out cross-episode themes."
)

PERIOD_USER = """\
Below are individual summaries of podcast episodes from {period_label}.
Produce a single digest for the whole period.

Write the digest as:
1. A short overview paragraph of what was covered across the period.
2. The 3-7 most important cross-cutting themes or stand-out moments, as bullets.
3. A brief "worth your time" recommendation of which episode(s) to listen to and why.

EPISODE SUMMARIES:
{episode_summaries}
"""


def render(template: str, values: Dict[str, str]) -> str:
    """Safely fill a template, leaving unknown placeholders untouched."""

    class _Default(dict):
        def __missing__(self, key: str) -> str:  # noqa: D401
            return "{" + key + "}"

    return template.format_map(_Default(values))


def episode_prompt(podcast: str, title: str, published: str, transcript: str) -> Dict[str, str]:
    return {
        "system": EPISODE_SYSTEM,
        "user": render(
            EPISODE_USER,
            {
                "podcast": podcast or "(unknown)",
                "title": title or "(untitled)",
                "published": published or "(unknown date)",
                "transcript": transcript,
            },
        ),
    }


def period_prompt(period_label: str, episode_summaries: str) -> Dict[str, str]:
    return {
        "system": PERIOD_SYSTEM,
        "user": render(
            PERIOD_USER,
            {"period_label": period_label, "episode_summaries": episode_summaries},
        ),
    }
