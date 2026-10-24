"""The static site (GitHub Pages): its data matches the published results, and the committed copy is current."""

import json

from src import config
from src.site import build


def test_build_matches_the_published_results(tmp_path):
    build.build(tmp_path)
    ov = json.loads((tmp_path / "data" / "overview.json").read_text(encoding="utf-8"))
    agent = ov["systems"]["AI agent (chooses its own tools)"]
    base = ov["systems"]["Fixed workflow (baseline)"]
    assert (agent["agreements"], agent["missed"], agent["false_alarms"]) == (34, 6, 17)
    assert (base["caught"], base["real_problems"], base["missed"]) == (36, 36, 0)
    samples = json.loads((tmp_path / "data" / "samples.json").read_text(encoding="utf-8"))
    assert len(samples) == 19 and all(len(s["answer_key"]) >= 4 for s in samples)
    letter = next(s for s in samples if s["id"] == "v2_d19")
    assert "The AI is not called at all" in letter["gate"]
    mismatch = next(s for s in samples if s["id"] == "v2_d14")
    assert mismatch["escalation"]["decision"].startswith("Can't tell") and "belongs to" in mismatch["escalation"]["rule"]
    assert (tmp_path / "fonts" / "bricolage-grotesque-latin-wght-normal.woff2").exists()


def test_committed_site_data_is_up_to_date(tmp_path):
    """Rebuild and compare: if this fails, run `python -m src.site.build` and commit site/data/."""
    build.build(tmp_path)
    for name in ("overview.json", "samples.json"):
        committed = (config.PROJECT_ROOT / "site" / "data" / name).read_text(encoding="utf-8")
        assert committed == (tmp_path / "data" / name).read_text(encoding="utf-8"), name
