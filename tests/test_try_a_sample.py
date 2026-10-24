"""Try a sample: the replay page renders every saved sample offline, and shows the code rules' result."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

PAGE = str(Path(__file__).resolve().parents[1] / "src" / "pages" / "2_Try_a_sample.py")


def _page(doc_id=None):
    at = AppTest.from_file(PAGE)
    at.run(timeout=60)
    if doc_id:
        at.selectbox(key="sample").set_value(doc_id).run(timeout=60)
    assert not at.exception, at.exception
    return at


@pytest.mark.parametrize("doc_id", [f"v2_d{i:02d}" for i in range(1, 20)])
def test_every_sample_renders(doc_id):
    at = _page(doc_id)
    assert any(s.value.startswith("7 · The answer key") for s in at.subheader)


def test_rules_are_replayed_on_the_spot():
    text = " ".join(m.value for m in at_markdown(_page("v2_d14")))
    assert "Can't tell: a person must check" in text  # account in another person's name, set by code
    letter = _page("v2_d19")
    assert any("The AI is not called at all" in i.value for i in letter.info)


def at_markdown(at):
    return list(at.markdown) + list(at.caption)
