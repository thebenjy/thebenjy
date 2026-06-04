from podsummary import prompts


def test_render_leaves_unknown_placeholders():
    out = prompts.render("Hello {name}, missing {gone}", {"name": "Ben"})
    assert out == "Hello Ben, missing {gone}"


def test_episode_prompt_contains_fields():
    p = prompts.episode_prompt("Pod", "Title", "2026-05-10", "the transcript")
    assert "Pod" in p["user"]
    assert "Title" in p["user"]
    assert "2026-05-10" in p["user"]
    assert "the transcript" in p["user"]
    assert "TL;DR" in p["user"]


def test_period_prompt_contains_summaries_and_label():
    p = prompts.period_prompt("Week of May 1", "summary block here")
    assert "Week of May 1" in p["user"]
    assert "summary block here" in p["user"]
    assert "digest" in p["user"].lower()
