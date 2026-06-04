# podsummary

Summarise **Spotify podcasts** by matching each episode to its **YouTube**
counterpart, pulling the YouTube transcript, and producing summaries with
**OpenAI**.

Spotify doesn't expose podcast transcripts, so this tool bridges the gap. You
maintain a small manual mapping of *Spotify show name → YouTube channel*, and
for a given time window (e.g. the past week) it discovers the episodes, finds
the matching YouTube videos, grabs their transcripts, and writes one summary per
episode plus a single roll-up summary for the whole period.

---

## Contents

- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Install](#install)
- [Getting API keys](#getting-api-keys)
- [Configure](#configure)
- [Usage](#usage)
  - [`run` — full pipeline for a period](#run--full-pipeline-for-a-period)
  - [`summarise-files` — summarise local transcripts](#summarise-files--summarise-local-transcripts)
  - [`prompt` — run a single prompt against a test input](#prompt--run-a-single-prompt-against-a-test-input)
- [Output](#output)
- [Configuration reference](#configuration-reference)
- [Project layout](#project-layout)
- [Tests](#tests)
- [Troubleshooting](#troubleshooting)
- [Limitations & notes](#limitations--notes)

---

## How it works

For each configured podcast and a date range (`--days`, optionally ending at
`--end`), the pipeline runs five stages:

1. **Discover episodes.** Lists the show's **Spotify episodes** released in the
   window via the Spotify Web API (Client Credentials flow). If Spotify isn't
   configured — or a mapping is flagged `youtube_only` — it falls back to using
   the **YouTube** channel's videos as the episode source.
2. **List YouTube videos.** Lists the mapped channel's videos in the same window
   using the YouTube Data API (when `YOUTUBE_API_KEY` is set) or the keyless
   `yt-dlp` backend.
3. **Match.** Pairs each episode to a video using **fuzzy title similarity
   constrained to a date window**. Titles are normalised (episode numbers,
   bracketed asides, punctuation and stopwords stripped) and scored with
   `difflib`; only videos published within `date_window_days` of the episode are
   considered. Each video is claimed by at most one episode.
4. **Fetch transcripts.** Retrieves the transcript for each matched video
   through a pluggable provider chain: `youtube-transcript-api` first (no key,
   no download), then `yt-dlp` subtitle download + VTT parsing as a fallback.
5. **Summarise hierarchically.** Writes a **summary per episode** (long
   transcripts are chunked and map-reduced to stay within model limits), then
   feeds those per-episode summaries into a second call that produces the
   **period (weekly) summary**. The per-episode and period stages use separate,
   independently configurable models.

```
Spotify episodes ─┐
                  ├─▶ match (title + date) ─▶ transcript ─▶ episode summary ─┐
YouTube videos  ──┘                                                          ├─▶ period summary
                                                                             ┘
```

Network clients and the LLM are accessed through small, injectable interfaces,
so every stage is unit-tested offline with fakes — no API keys or network
required to run the test suite.

---

## Requirements

- **Python 3.9+**
- An **OpenAI API key** (required for any summarisation).
- *Optional:* **Spotify API credentials** (to use Spotify as the episode source).
- *Optional:* a **YouTube Data API key** (otherwise the keyless `yt-dlp` backend
  is used to list channel videos).
- *Optional:* **`yt-dlp`** installed (for the transcript fallback and the keyless
  YouTube listing backend) — included via the `ytdlp` extra.

---

## Install

```bash
# Core + dev tools (pytest) + optional yt-dlp backend
pip install -e ".[dev,ytdlp]"

# Or just the core runtime
pip install -e .
```

This installs the `podsummary` console command. You can also run it as a module:
`python -m podsummary.cli ...`.

---

## Getting API keys

**OpenAI** — create a key at <https://platform.openai.com/api-keys> and set
`OPENAI_API_KEY`.

**Spotify** *(optional)* — create an app in the
[Spotify Developer Dashboard](https://developer.spotify.com/dashboard). Copy the
**Client ID** and **Client Secret** into `SPOTIFY_CLIENT_ID` /
`SPOTIFY_CLIENT_SECRET`. No redirect URI or user login is needed — the tool uses
the Client Credentials flow for public catalogue reads.

**YouTube Data API** *(optional)* — in the
[Google Cloud Console](https://console.cloud.google.com/) create a project,
enable **YouTube Data API v3**, create an API key, and set `YOUTUBE_API_KEY`. If
you skip this, set `youtube.prefer: yt_dlp` in the config (or just leave the key
unset) to list channel videos without a key.

---

## Configure

```bash
cp config.example.yaml config.yaml   # models, thresholds, podcast→channel mapping
cp .env.example .env                 # API keys (read from the environment)
```

`config.yaml` holds non-secret settings: the **models** (separate
`episode_model` and `period_model`), matching thresholds, transcript provider
order, and the manual podcast mapping. **Secrets live in the environment** (see
`.env.example`) and are never committed — `config.yaml` and `.env` are
git-ignored.

Load the env file into your shell before running, e.g.:

```bash
set -a && source .env && set +a
```

A minimal `config.yaml`:

```yaml
openai:
  episode_model: gpt-4o-mini   # per-episode summaries (cheaper/faster, at scale)
  period_model: gpt-4o         # weekly/period roll-up (higher quality)

matching:
  title_threshold: 0.6
  date_window_days: 3

podcasts:
  - spotify_name: "Lex Fridman Podcast"
    youtube_channel: "Lex Fridman"
    youtube_channel_id: "UCSHZKyawb77ixDdsGog4iWA"   # optional but most reliable
  - spotify_name: "My YouTube-first show"
    youtube_channel: "@SomeChannel"
    youtube_only: true                                # skip Spotify entirely
```

See [Configuration reference](#configuration-reference) for every option.

---

## Usage

`podsummary` has three subcommands. `run` is the full online pipeline;
`summarise-files` and `prompt` work entirely offline (apart from the OpenAI call)
and are ideal for developing prompts against test inputs.

### `run` — full pipeline for a period

```bash
# Summarise the past week for every podcast in the config.
podsummary run -c config.yaml --days 7 -o summaries/

# A specific podcast, a custom 14-day window ending on a date.
podsummary run -c config.yaml --podcast "Lex Fridman Podcast" --days 14 --end 2026-06-01

# Verbose logging (shows episode/video counts and matching decisions).
podsummary -v run -c config.yaml --days 7
```

| Flag | Default | Description |
| --- | --- | --- |
| `-c, --config` | *(required)* | Path to the config YAML. |
| `--days` | `7` | Period length in days. |
| `--end` | now (UTC) | Period end date, ISO format (`YYYY-MM-DD`). |
| `--podcast` | all | Limit to a named podcast; repeatable. |
| `-o, --outdir` | `summaries` | Output directory. |

### `summarise-files` — summarise local transcripts

Drop transcripts into `.txt` files and summarise them directly — no
Spotify/YouTube needed. Pass files and/or directories (directories are scanned
for `*.txt`). With `--period`, the per-file summaries are rolled up into a
single period summary, exactly like the full pipeline's final stage.

```bash
# Summarise every .txt in a folder, then produce a period roll-up.
podsummary summarise-files sample_inputs/ --period --period-label "Week of June 1" -o out/

# Specific files, overriding the episode model.
podsummary summarise-files a.txt b.txt --model gpt-4o-mini --period
```

| Flag | Default | Description |
| --- | --- | --- |
| `files` | *(required)* | One or more `.txt` files or directories. |
| `-c, --config` | *(none)* | Optional config YAML (for model defaults). |
| `--model` | config / `gpt-4o-mini` | Override the episode model. |
| `--period-model` | config | Override the period model. |
| `--podcast` | *(none)* | Podcast label for prompt context. |
| `--title` | filename | Force a title for all files. |
| `--period` | off | Also produce a period roll-up summary. |
| `--period-label` | `this period` | Label used in the period summary. |
| `-o, --outdir` | *(stdout only)* | Write summaries to this directory. |

### `prompt` — run a single prompt against a test input

Iterate on prompt wording with test text files. Use `--dry-run` to render the
prompt without calling OpenAI, or `--show-prompt` to print the prompt and then
call the model.

```bash
# Render the episode prompt only (no API call):
podsummary prompt sample_inputs/episode_ai_agents.txt --template episode --dry-run

# Inspect the rendered prompt, call the model, and write the output:
podsummary prompt sample_inputs/episode_longevity.txt --show-prompt --model gpt-4o-mini -o out.md

# Run the period template against a file of concatenated episode summaries:
podsummary prompt summaries.txt --template period --period-label "Week of June 1"
```

| Flag | Default | Description |
| --- | --- | --- |
| `file` | *(required)* | Input text file. |
| `-c, --config` | *(none)* | Optional config YAML. |
| `--template` | `episode` | `episode` or `period`. |
| `--model` | config / `gpt-4o-mini` | Model to use. |
| `--podcast` | *(none)* | Podcast label (episode template). |
| `--title` | filename | Title (episode template). |
| `--period-label` | `this period` | Period label (period template). |
| `--show-prompt` | off | Print the rendered prompt. |
| `--dry-run` | off | Render only; do not call OpenAI. |
| `-o, --out` | stdout | Write model output to a file. |

---

## Output

`run` writes, per podcast, into the output directory:

- `"<podcast-slug>__<episode-slug>.txt"` — one file per summarised episode
  (Markdown: title, date, summary, source link).
- `"<podcast-slug>__PERIOD.md"` — the period digest, followed by all the
  episode summaries.

Episodes that can't be matched to a video, or whose transcript can't be fetched,
are **skipped** and reported on stdout (and in `-v` logs) with the reason — the
run still completes for everything else.

`summarise-files` prints each summary to stdout and, with `-o`, writes
`<name>.summary.md` per file plus `PERIOD.md` when `--period` is set.

---

## Configuration reference

```yaml
openai:
  episode_model: gpt-4o-mini   # model for per-episode summaries
  period_model: gpt-4o         # model for the period roll-up
  api_key_env: OPENAI_API_KEY  # env var to read the OpenAI key from
  temperature: 0.3
  max_output_tokens: 1200

matching:
  title_threshold: 0.6   # 0..1 minimum normalised-title similarity to accept a match
  date_window_days: 3    # only consider videos published within ±N days of the episode

transcripts:
  providers:             # tried in order; first hit wins
    - youtube_transcript_api
    - yt_dlp
  languages: [en]        # preferred caption languages

youtube:
  prefer: api                  # "api" (needs YOUTUBE_API_KEY) or "yt_dlp" (keyless)
  api_key_env: YOUTUBE_API_KEY
  max_results: 50

spotify:
  client_id_env: SPOTIFY_CLIENT_ID
  client_secret_env: SPOTIFY_CLIENT_SECRET
  market: US

podcasts:
  - spotify_name: "The Tim Ferriss Show"  # name as it appears on Spotify
    youtube_channel: "Tim Ferriss"        # channel name or @handle
    youtube_channel_id: ""                # optional; most reliable when set
    youtube_only: false                   # true = ignore Spotify, use YouTube as source
```

**Notes**

- Secrets are read from the environment using the `*_env` names, so you can point
  at different variables per deployment.
- `youtube_channel_id` is the most reliable matcher; the channel name/`@handle`
  is resolved via search when no id is given.
- If `spotify.client_id`/`secret` are unset, the tool automatically uses YouTube
  as the episode source for every podcast (equivalent to `youtube_only`).

---

## Project layout

| Path | Responsibility |
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
| `tests/` | Offline unit tests with injected fakes |
| `sample_inputs/` | Example transcripts for `summarise-files` / `prompt` |
| `config.example.yaml`, `.env.example` | Templates to copy |

---

## Tests

```bash
pytest
```

The suite (32 tests) covers title normalisation/matching, VTT parsing and
provider fallback, transcript chunking + map-reduce, the hierarchical
summariser, the Spotify/YouTube clients (with a fake HTTP session), the pipeline
end to end, and the CLI subcommands — all without network access or API keys.

---

## Troubleshooting

- **`OpenAI API key missing`** — set `OPENAI_API_KEY` (or the var named by
  `openai.api_key_env`). Remember to `source .env`.
- **`Spotify credentials missing`** — set `SPOTIFY_CLIENT_ID` /
  `SPOTIFY_CLIENT_SECRET`, or remove the need for them by setting `youtube_only:
  true` on the podcast (or omitting Spotify entirely to use the YouTube source).
- **Episodes summarised as 0 / everything skipped** — usually a matching miss.
  Lower `matching.title_threshold` or widen `matching.date_window_days`, and set
  `youtube_channel_id` for the podcast. Run with `-v` to see the counts and
  per-episode skip reasons.
- **`no transcript available`** — the video has captions disabled. Ensure
  `yt_dlp` is in `transcripts.providers` (and installed) as a fallback.
- **YouTube listing returns nothing** — check the channel id/handle, or switch
  `youtube.prefer` to `yt_dlp` if you don't have a Data API key.

---

## Limitations & notes

- Matching is heuristic. Shows that publish to YouTube under very different
  titles, or far from the audio release date, may need a wider date window or a
  lower threshold.
- Transcript availability and accuracy depend on YouTube captions (often
  auto-generated).
- OpenAI usage incurs cost; the per-episode/period model split lets you keep
  per-episode runs cheap (`gpt-4o-mini`) while using a stronger model for the
  roll-up.
- Respect the terms of service of Spotify, YouTube, and OpenAI for your use case.
