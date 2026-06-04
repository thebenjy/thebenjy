"""Command line interface for podsummary.

Subcommands
-----------
* ``run``            - full pipeline for a period (Spotify -> YouTube -> summaries).
* ``summarise-files``- summarise local transcript ``.txt`` files (per-file + a
                       combined period summary). Great for offline iteration.
* ``prompt``         - run a single prompt template against one input text file,
                       to iterate on prompt wording with test inputs.

The two offline subcommands let you develop prompts and summarisation without
touching Spotify/YouTube.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from . import prompts
from .config import Config, OpenAIConfig
from .models import EpisodeSummary
from .pipeline import Pipeline, period_bounds
from .summariser import OpenAILLM, Summariser


def _build_summariser(config: Config) -> Summariser:
    return Summariser(OpenAILLM(config.openai), config.openai)


def _write_output(text: str, out: Optional[str]) -> None:
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text, encoding="utf-8")
        print(f"Wrote {out}")
    else:
        print(text)


# --------------------------------------------------------------------------- run
def cmd_run(args: argparse.Namespace) -> int:
    config = Config.load(args.config)
    end = (
        datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
        if args.end
        else datetime.now(timezone.utc)
    )
    start, end = period_bounds(end=end, days=args.days)
    pipeline = Pipeline(config, _build_summariser(config))
    results = pipeline.run(start, end, podcasts=args.podcast or None)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    for result in results:
        slug = "".join(c if c.isalnum() else "-" for c in result.podcast).strip("-").lower()
        # Per-episode files.
        for es in result.period.episode_summaries:
            es_slug = "".join(c if c.isalnum() else "-" for c in es.episode_title)[:60].strip("-")
            path = outdir / f"{slug}__{es_slug or es.video_id}.txt"
            path.write_text(es.to_markdown(), encoding="utf-8")
        # Period digest.
        (outdir / f"{slug}__PERIOD.md").write_text(
            result.period.to_markdown(), encoding="utf-8"
        )
        print(
            f"{result.podcast}: {len(result.period.episode_summaries)} summarised, "
            f"{len(result.skipped)} skipped -> {outdir}"
        )
        for skip in result.skipped:
            print(f"  - skipped {skip}")
    return 0


# ----------------------------------------------------------------- summarise-files
def cmd_summarise_files(args: argparse.Namespace) -> int:
    config = _config_with_overrides(args)
    summariser = _build_summariser(config)
    files = _expand_files(args.files)
    if not files:
        print("No input files found.", file=sys.stderr)
        return 1

    episode_summaries: List[EpisodeSummary] = []
    outdir = Path(args.outdir) if args.outdir else None
    for path in files:
        text = Path(path).read_text(encoding="utf-8")
        title = args.title or Path(path).stem
        es = summariser.summarise_episode(
            transcript=text, title=title, podcast=args.podcast or ""
        )
        episode_summaries.append(es)
        if outdir:
            outdir.mkdir(parents=True, exist_ok=True)
            (outdir / f"{Path(path).stem}.summary.md").write_text(
                es.to_markdown(), encoding="utf-8"
            )
        print(f"\n=== {title} ===\n{es.summary}\n")

    if args.period and len(episode_summaries) >= 1:
        period = summariser.summarise_period(episode_summaries, args.period_label)
        if outdir:
            (outdir / "PERIOD.md").write_text(period.to_markdown(), encoding="utf-8")
        print(f"\n=== PERIOD SUMMARY ({args.period_label}) ===\n{period.summary}\n")
    return 0


# --------------------------------------------------------------------------- prompt
def cmd_prompt(args: argparse.Namespace) -> int:
    config = _config_with_overrides(args)
    text = Path(args.file).read_text(encoding="utf-8")
    if args.template == "episode":
        rendered = prompts.episode_prompt(
            podcast=args.podcast or "", title=args.title or Path(args.file).stem,
            published="", transcript=text,
        )
    else:
        rendered = prompts.period_prompt(args.period_label, text)

    if args.show_prompt:
        print("----- SYSTEM -----")
        print(rendered["system"])
        print("\n----- USER -----")
        print(rendered["user"])
        if args.dry_run:
            return 0

    if args.dry_run:
        print(rendered["user"])
        return 0

    llm = OpenAILLM(config.openai)
    model = args.model or config.openai.episode_model
    output = llm.complete(rendered["system"], rendered["user"], model)
    _write_output(output, args.out)
    return 0


# --------------------------------------------------------------------------- utils
def _expand_files(paths: List[str]) -> List[str]:
    out: List[str] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            out.extend(sorted(str(f) for f in path.glob("*.txt")))
        elif path.exists():
            out.append(str(path))
    return out


def _config_with_overrides(args: argparse.Namespace) -> Config:
    if getattr(args, "config", None) and os.path.exists(args.config):
        config = Config.load(args.config)
    else:
        config = Config(openai=OpenAIConfig())
    if getattr(args, "model", None):
        config.openai.episode_model = args.model
    if getattr(args, "period_model", None):
        config.openai.period_model = args.period_model
    return config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="podsummary", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="verbose logging")
    sub = parser.add_subparsers(dest="command", required=True)

    # run
    p_run = sub.add_parser("run", help="full pipeline for a period")
    p_run.add_argument("-c", "--config", required=True, help="path to config YAML")
    p_run.add_argument("--days", type=int, default=7, help="period length in days (default 7)")
    p_run.add_argument("--end", help="period end date ISO (default: now)")
    p_run.add_argument("--podcast", action="append", help="limit to named podcast(s)")
    p_run.add_argument("-o", "--outdir", default="summaries", help="output directory")
    p_run.set_defaults(func=cmd_run)

    # summarise-files
    p_sf = sub.add_parser("summarise-files", help="summarise local transcript text files")
    p_sf.add_argument("files", nargs="+", help="text files or directories of .txt files")
    p_sf.add_argument("-c", "--config", help="optional config YAML")
    p_sf.add_argument("--model", help="override episode model")
    p_sf.add_argument("--period-model", dest="period_model", help="override period model")
    p_sf.add_argument("--podcast", help="podcast label for context")
    p_sf.add_argument("--title", help="force a title for all files")
    p_sf.add_argument("--period", action="store_true", help="also produce a period roll-up")
    p_sf.add_argument("--period-label", default="this period", help="label for the period summary")
    p_sf.add_argument("-o", "--outdir", help="write summaries to this directory")
    p_sf.set_defaults(func=cmd_summarise_files)

    # prompt
    p_pr = sub.add_parser("prompt", help="run one prompt template against a text file")
    p_pr.add_argument("file", help="input text file")
    p_pr.add_argument("-c", "--config", help="optional config YAML")
    p_pr.add_argument("--template", choices=["episode", "period"], default="episode")
    p_pr.add_argument("--model", help="model to use")
    p_pr.add_argument("--podcast", help="podcast label (episode template)")
    p_pr.add_argument("--title", help="title (episode template)")
    p_pr.add_argument("--period-label", default="this period", help="period label (period template)")
    p_pr.add_argument("--show-prompt", action="store_true", help="print the rendered prompt")
    p_pr.add_argument("--dry-run", action="store_true", help="render only, do not call OpenAI")
    p_pr.add_argument("-o", "--out", help="write model output to a file")
    p_pr.set_defaults(func=cmd_prompt)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
