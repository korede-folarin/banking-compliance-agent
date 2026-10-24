"""
Build the always-on static site (GitHub Pages) from the saved results: no server, nothing to wake up.

    python -m src.site.build

Writes site/data/overview.json (the plain-language dashboard, both systems), site/data/samples.json
(the 19 replayable reviews) and copies the self-hosted fonts. site/index.html, app.js and style.css
are hand-written and only read these files. No model calls.
"""

import json
import shutil
import statistics
import sys
from pathlib import Path

from src import config
from src.monitoring import dashboard, overview
from src.review.cases import _document_file
from src.review.replay import replay, sample_title

SITE = config.PROJECT_ROOT / "site"
AGENT_V2 = config.PROJECT_ROOT / "docs" / "eval_agent_v2.jsonl"


def _health() -> dict:
    commands, docs, snapshot_at = dashboard.load_or_snapshot()
    real = [d for d in docs if not d["rehearsal"]]
    done = [d for d in real if not d["failed"]]
    lat = [d["latency_s"] for d in done if d["latency_s"] is not None]
    return {"agent_document_runs": len(real),
            "failure_rate": round(sum(d["failed"] for d in real) / len(real), 4) if real else None,
            "median_latency_s": round(statistics.median(lat)) if lat else None,
            "live_spend_usd": round(sum(c["cost_usd"] for c in commands if not c["rehearsal"]), 2),
            "as_of": (snapshot_at or max(c["started"] for c in commands))[:10] if commands else None}


def build(site: Path = SITE) -> dict:
    data = site / "data"
    data.mkdir(parents=True, exist_ok=True)
    systems = {name: {k: v for k, v in overview.summary(name).items() if k != "people"} for name in overview.SYSTEMS}
    (data / "overview.json").write_text(json.dumps({"systems": systems, "health": _health()}, indent=1) + "\n",
                                        encoding="utf-8")

    labels = overview._labels()
    rows = [json.loads(line) for line in AGENT_V2.read_text(encoding="utf-8").splitlines() if line.strip()]
    samples = []
    for row in sorted((r for r in rows if r["run_idx"] == 0), key=lambda r: r["doc_id"]):
        doc = _document_file(row["doc_id"])
        text = doc.read_text(encoding="utf-8") if doc else ""
        samples.append({"id": row["doc_id"], "title": sample_title(row["doc_id"], row, labels[row["doc_id"]]),
                        "agreement": text, **replay(row, labels[row["doc_id"]], text)})
    (data / "samples.json").write_text(json.dumps(samples, indent=1) + "\n", encoding="utf-8")

    fonts = site / "fonts"
    fonts.mkdir(exist_ok=True)
    for f in (config.PROJECT_ROOT / "src" / "static").iterdir():
        shutil.copy2(f, fonts / f.name)
    return {"systems": list(systems), "samples": len(samples)}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(build())
