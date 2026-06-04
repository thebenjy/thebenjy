from pathlib import Path

import podsummary.cli as cli
from podsummary.summariser import Summariser

from tests.conftest import FakeLLM


def _patch_fake_summariser(monkeypatch):
    """Make the CLI build a Summariser backed by FakeLLM (no OpenAI calls)."""

    def _build(config):
        return Summariser(FakeLLM(), config.openai)

    monkeypatch.setattr(cli, "_build_summariser", _build)


def test_summarise_files_writes_per_file_and_period(monkeypatch, tmp_path, capsys):
    _patch_fake_summariser(monkeypatch)
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("transcript a", encoding="utf-8")
    f2.write_text("transcript b", encoding="utf-8")
    outdir = tmp_path / "out"

    rc = cli.main(
        [
            "summarise-files",
            str(f1),
            str(f2),
            "--period",
            "--period-label",
            "Week 1",
            "-o",
            str(outdir),
        ]
    )
    assert rc == 0
    assert (outdir / "a.summary.md").exists()
    assert (outdir / "b.summary.md").exists()
    assert (outdir / "PERIOD.md").exists()
    out = capsys.readouterr().out
    assert "PERIOD SUMMARY (Week 1)" in out


def test_summarise_files_accepts_a_directory(monkeypatch, tmp_path):
    _patch_fake_summariser(monkeypatch)
    (tmp_path / "one.txt").write_text("x", encoding="utf-8")
    (tmp_path / "two.txt").write_text("y", encoding="utf-8")
    outdir = tmp_path / "out"
    rc = cli.main(["summarise-files", str(tmp_path), "-o", str(outdir)])
    assert rc == 0
    assert (outdir / "one.summary.md").exists()
    assert (outdir / "two.summary.md").exists()


def test_prompt_dry_run_renders_without_network(tmp_path, capsys):
    f = tmp_path / "t.txt"
    f.write_text("the transcript body", encoding="utf-8")
    rc = cli.main(["prompt", str(f), "--template", "episode", "--title", "My Ep", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "the transcript body" in out
    assert "My Ep" in out


def test_prompt_calls_llm_when_not_dry_run(monkeypatch, tmp_path, capsys):
    captured = {}

    class FakeOpenAILLM:
        def __init__(self, config):
            captured["config"] = config

        def complete(self, system, user, model, **kwargs):
            captured["model"] = model
            return "MODEL OUTPUT"

    monkeypatch.setattr(cli, "OpenAILLM", FakeOpenAILLM)
    f = tmp_path / "t.txt"
    f.write_text("body", encoding="utf-8")
    rc = cli.main(["prompt", str(f), "--model", "gpt-test"])
    assert rc == 0
    assert captured["model"] == "gpt-test"
    assert "MODEL OUTPUT" in capsys.readouterr().out
