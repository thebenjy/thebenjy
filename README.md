# podsummary

Summarise **Spotify podcasts** by matching each episode to its **YouTube**
counterpart, pulling the YouTube transcript, and producing summaries with
**OpenAI**.

Spotify doesn't expose transcripts, so the tool bridges the gap: you maintain a
small manual mapping of *Spotify show name → YouTube channel*, and for a given
time window (e.g. the past week) it:

1. Lists the show's **Spotify episodes** in the period (or uses YouTube directly
   if Spotify isn't configured).
2. Lists the channel's **YouTube videos** in the same period.
3. **Matches** each episode to a video using fuzzy title similarity constrained
   to a date window.
4. Fetches the **transcript** for each matched video.
5. Writes a **summary per episode**, then rolls those per-episode summaries up
   into a single **period (weekly) summary**.

## Architecture

| Module | Responsibility |
| --- | --- |
| `podsummary/config.py` | Load YAML settings + secrets from the environment |
| `podsummary/models.py` | Dataclasses passed between stages |
| `podsummary/spotify_client.py` | List a show's episodes for a period (Client Credentials) |
| `podsummary/youtube_client.py` | List a channel's videos (YouTube Data API **or** keyless yt-dlp) |
| `podsummary/transcripts.py` | Pluggable transcripts (`youtube-transcript-api` → `yt-dlp` fallback) |
| `podsummary/matching.py` | Fuzzy title + date-window episode→video matching |
| `podsummary/prompts.py` | Editable prompt templates |
| `podsummary/summariser.py` | Hierarchical summarisation: per-episode → period roll-up |
| `podsummary/pipeline.py` | End-to-end orchestration |
| `podsummary/cli.py` | Command line entry point |

Network clients and the LLM are injected through small interfaces, so the whole
pipeline is unit-tested offline with fakes (no API keys, no network).

## Install

```bash
pip install -e ".[dev,ytdlp]"     # dev = pytest, ytdlp = optional yt-dlp backend
```

## Configure

```bash
cp config.example.yaml config.yaml   # models, thresholds, podcast→channel mapping
cp .env.example .env                 # API keys (read from the environment)
```

`config.yaml` holds the **models** (separate `episode_model` and `period_model`),
matching thresholds, transcript provider order, and the manual podcast mapping.
Secrets live in the environment:

- `OPENAI_API_KEY` — required for summarisation.
- `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` — optional; without them the tool
  falls back to using YouTube as the episode source.
- `YOUTUBE_API_KEY` — optional; without it (or with `youtube.prefer: yt_dlp`) the
  keyless yt-dlp backend lists channel videos.

## Usage

### Full pipeline for a period

```bash
# Summarise the past week for every podcast in the config.
podsummary run -c config.yaml --days 7 -o summaries/

# A specific podcast, a custom window ending on a date.
podsummary run -c config.yaml --podcast "Lex Fridman Podcast" --days 14 --end 2026-06-01
```

Outputs one `*.txt` file per episode plus a `*__PERIOD.md` digest per podcast.

### Summarise local transcript files (offline, no Spotify/YouTube)

Drop transcripts into `.txt` files and summarise them directly — ideal for
iterating without the data-collection stages:

```bash
podsummary summarise-files sample_inputs/ --period --period-label "Week of June 1" -o out/
podsummary summarise-files a.txt b.txt --model gpt-4o-mini --period
```

Produces a per-file summary and (with `--period`) a combined period summary
built from those per-episode summaries.

### Run a single prompt against a test input

Iterate on prompt wording with test text files:

```bash
# Render the prompt only (no API call):
podsummary prompt sample_inputs/episode_ai_agents.txt --template episode --dry-run

# Inspect the rendered prompt and then call the model:
podsummary prompt sample_inputs/episode_longevity.txt --show-prompt --model gpt-4o-mini -o out.md

# The period template against a file of concatenated episode summaries:
podsummary prompt summaries.txt --template period --period-label "Week of June 1"
```

## Tests

```bash
pytest
```

The suite covers title normalisation/matching, VTT parsing and provider
fallback, transcript chunking + map-reduce, the hierarchical summariser, the
Spotify/YouTube clients (with a fake HTTP session), the pipeline end to end, and
the CLI subcommands — all without network access.
