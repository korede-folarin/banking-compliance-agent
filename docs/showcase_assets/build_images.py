"""
Renders the failure-evidence images in docs/showcase_assets/images/.

Every line drawn comes from a file or a command run at render time; nothing
is typed by hand except the captions (source, line numbers, status). Long
lines are wrapped to fit the image, never cut; the left gutter shows the
source line number on the first row of each source line. User-specific
paths are replaced with <USER_HOME>. Zero API calls.

Run from the repo root:
    python docs/showcase_assets/build_images.py
"""

import re
import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "images"
EVAL_RUNS = Path.home() / "eval_runs"
WRAP = 118


def redact(text: str) -> str:
    return re.sub(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+", "<USER_HOME>", text)


def file_lines(path: Path, first: int, last: int) -> list[tuple[int, str]]:
    # Numbered as sed/grep number them: split on "\n" only. splitlines() would also split on a bare
    # "\r" (progress-bar output in the console logs) and shift every line number after it.
    lines = [l[:-1] if l.endswith("\r") else l for l in path.read_bytes().decode("utf-8").split("\n")]
    picked = [(n, lines[n - 1]) for n in range(first, last + 1)]
    assert not any("\r" in l for _, l in picked), f"bare carriage return inside {path} L{first}-{last}"
    return [(n, redact(l)) for n, l in picked]


def command_lines(cmd: list[str]) -> list[tuple[int, str]]:
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return [(n, redact(l)) for n, l in enumerate(out.rstrip("\n").split("\n"), 1)]


def rows(numbered: list[tuple[int, str]]) -> list[tuple[str, str]]:
    """(gutter, text) display rows; a source line longer than WRAP continues on the next rows with an empty gutter."""
    out = []
    for n, line in numbered:
        parts = textwrap.wrap(line, WRAP, replace_whitespace=False, drop_whitespace=False,
                              break_long_words=True, break_on_hyphens=False) or [""]
        out.append((str(n), parts[0]))
        out += [("", p) for p in parts[1:]]
    return out


FONTS = Path("C:/Windows/Fonts")
MONO = ImageFont.truetype(str(FONTS / "consola.ttf"), 15)
SERIF = ImageFont.truetype(str(FONTS / "georgiai.ttf"), 15)
SANS = ImageFont.truetype(str(FONTS / "segoeui.ttf"), 15)
SANS_B = ImageFont.truetype(str(FONTS / "segoeuib.ttf"), 16)
LINE, PAD, GUTTER = 22, 24, 60


def render(name: str, panels: list[dict], caption: str) -> None:
    """panels: {title, rows, style: 'log' | 'record'}. Logs: monospace on grey; records: italic serif with a quote bar."""
    width = PAD * 2 + GUTTER + int(MONO.getlength("M" * WRAP)) + 20
    cap = []
    for para in caption.splitlines():
        line = ""
        for word in para.split(" "):
            if line and SANS.getlength(line + " " + word) > width - 2 * PAD:
                cap.append(line)
                line = word
            else:
                line = f"{line} {word}" if line else word
        cap.append(line)
    height = PAD + sum(LINE * (len(p["rows"]) + 2) + PAD for p in panels) + LINE * len(cap) + PAD * 2
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    y = PAD
    for p in panels:
        log = p["style"] == "log"
        d.text((PAD, y), p["title"], font=SANS_B, fill="#111111")
        y += LINE + 10
        top, bottom = y - 6, y + LINE * len(p["rows"]) + 2
        if log:
            d.rectangle([PAD - 6, top, width - PAD + 6, bottom], fill="#f3f3f3", outline="#cccccc")
        else:
            d.rectangle([PAD - 6, top, PAD - 2, bottom], fill="#7a7a7a")
        for gutter, text in p["rows"]:
            g = gutter.rjust(5)
            d.text((PAD, y), g, font=MONO, fill="#888888")
            d.text((PAD + GUTTER, y), text, font=MONO if log else SERIF, fill="#1a1a1a")
            y += LINE
        y += LINE + PAD - 10
    for line in cap:
        d.text((PAD, y), line, font=SANS, fill="#333333")
        y += LINE
    OUT.mkdir(exist_ok=True)
    img.save(OUT / name)
    print("wrote", OUT / name)


def image1() -> None:
    src = EVAL_RUNS / "main_pass_v2.log"
    render("01_parallel_tool_use_400_real_log.png", [{
        "title": "<USER_HOME>/eval_runs/main_pass_v2.log, lines 95-99", "style": "log",
        "rows": rows(file_lines(src, 95, 99)),
    }], "Status: REAL LOG (unaltered except the user path in L99, redacted to <USER_HOME>; long lines wrapped, "
        "gutter = source line number).\n"
        "Source: <USER_HOME>/eval_runs/main_pass_v2.log L95-99, console output of "
        "`python -m src.evaluation.run_eval main` on 2026-10-01, before the fix.\n"
        "L96 = HTTP 400; L97 = 'API call failed on attempt 2'; L98 = retries exhausted; L99 = the run recorded as failed. "
        "The same pattern is at L136-140 (loan_agreement_3 run 0).\n"
        "Fix: disable_parallel_tool_use=True in src/agent/structured_output.py (first committed in 7f63d32).")


def image2() -> None:
    src = ROOT / "docs" / "eval_raw_main_pass_v2_retries.jsonl"
    render("02_placeholder_retries_real_log.png", [{
        "title": "docs/eval_raw_main_pass_v2_retries.jsonl, lines 1-2 (of 49)", "style": "log",
        "rows": rows(file_lines(src, 1, 2)),
    }], "Status: REAL LOG (unaltered JSON lines; long lines wrapped, \\n inside strings shown as written in the file).\n"
        "Source: docs/eval_raw_main_pass_v2_retries.jsonl L1-2, written on 2026-10-07 by the observe-only "
        "instructor hooks in src/agent/retry_log.py during the full main pass.\n"
        "All 49 records are judge calls whose tool arguments were wrapped in a literal placeholder key. "
        "Not fixed: recorded as a known limitation; every one recovered on retry.")


def image3() -> None:
    render("03_garbage_chunks_record.png", [
        {"title": "progress.md, lines 2636-2644 (Session 2, 2026-08-20)", "style": "record",
         "rows": rows(file_lines(ROOT / "progress.md", 2636, 2644))},
        {"title": "Commit message: output of `git show -s --format=%B cb3a7dd` (2026-08-20)", "style": "record",
         "rows": rows(command_lines(["git", "show", "-s", "--format=%B", "cb3a7dd"]))},
    ], "Status: RECORD (a session note and a commit message, quoted as written). Not terminal output: "
       "no log of the failed ingestion run was saved.\n"
       "Gutter = line number in progress.md (top) and in the command output (bottom). "
       "Not reproduced.")


if __name__ == "__main__":
    image1()
    image2()
    image3()
