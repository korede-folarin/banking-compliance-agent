"""
Offline tests for the claim-checker negative control (src/evaluation/negative_control.py).

Synthetic results, judgments and corpus; a fake claim-check client. No API
calls, no Chroma. Protected docs/ files are hashed before and after, and
docs/ is checked for new files.
"""

import argparse
import hashlib
import json
from types import SimpleNamespace

import pytest

from src.evaluation import claim_verification as cv
from src.evaluation import negative_control as nc
from src.evaluation import run_eval
from tests.fixtures.eval_set import OUTCOME_KEYS

PROTECTED = [run_eval.MAIN_PASS_PATH, run_eval.SUMMARY_PATH, run_eval.DOCS_OUT_DIR / "eval_raw_main_pass_v2.jsonl",
             nc.RESULTS_PATH, nc.JUDGMENTS_PATH]


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module", autouse=True)
def protected_files_untouched():
    before = {p: _sha256(p) for p in PROTECTED}
    docs_before = sorted(p.name for p in nc.DOCS.iterdir())
    yield
    assert {p: _sha256(p) for p in PROTECTED} == before
    assert sorted(p.name for p in nc.DOCS.iterdir()) == docs_before, "a file was created or removed in docs/"


ROWS = 12  # 12 rows x 4 outcomes = 48 eligible claims, 12 per outcome


def _synthetic():
    """Corpus of one file, 5 chunks per (row, outcome); each claim's quote is only in its named chunk."""
    corpus, results, judgments = [], [], {}
    idx = 0
    for r in range(ROWS):
        outcomes, res_outcomes = {}, []
        for k in OUTCOME_KEYS:
            sources = []
            for e in range(1, 6):
                cid = f"c{idx:04d}"
                quote = f"unique requirement {r} {k} alpha beta gamma delta epsilon"
                text = (f"Background sentence for chunk {idx}. " + (quote + ". " if e == 1 else "")
                        + "Other regulatory text without the phrase.")
                corpus.append({"id": cid, "text": text, "file_name": "reg.pdf", "page_label": str(idx // 3 + 1),
                               "start_char_idx": (idx % 3) * 1000})
                sources.append({"index": e, "node_id": cid, "file_name": "reg.pdf", "similarity_score": 0.7,
                                "text_excerpt": text})
                idx += 1
            outcomes[k] = {"sources": sources}
            res_outcomes.append({
                "doc_id": f"loan_agreement_{r + 1}", "run_idx": 0, "outcome": k,
                "regulatory_requirements": [{
                    "claim": f"Claim about requirement {r} {k}.", "source_count": 1,
                    "llm_check": {"verdict": "yes"},
                    "sources": [{"excerpt_number": 1, "verbatim_quote": f"unique requirement {r} {k} alpha beta gamma delta epsilon",
                                 "quote_location": "named_chunk", "match_type": "exact"}],
                }],
            })
        judgments[(f"loan_agreement_{r + 1}", 0)] = {"outcomes": outcomes}
        results.extend(res_outcomes)
    return results, judgments, corpus


def test_quote_absent_and_present_rules():
    text = "Firms must do A. Later, firms must also do B carefully and promptly."
    assert nc.quote_present("Firms must do A.", text)["present"]
    assert nc.quote_absent("completely different words that never appear anywhere here", text)["absent"]
    spliced = "Firms must do A ... firms must also do B carefully and promptly"
    chk = nc.quote_absent(spliced, text)
    assert not chk["absent"] and chk["parts_present"]  # a long enough part appears, so not absent


def test_corpus_order_neighbours_stay_within_a_file():
    meta = [
        {"id": "a2", "file_name": "x.pdf", "page_label": "2", "start_char_idx": 0},
        {"id": "a1", "file_name": "x.pdf", "page_label": "1", "start_char_idx": 500},
        {"id": "a0", "file_name": "x.pdf", "page_label": "1", "start_char_idx": 0},
        {"id": "b0", "file_name": "y.pdf", "page_label": "1", "start_char_idx": 0},
    ]
    n = nc.corpus_order(meta)
    assert n["a0"] == (None, "a1") and n["a1"] == ("a0", "a2") and n["a2"] == ("a1", None)
    assert n["b0"] == (None, None)  # no neighbours across files


def test_selection_meets_every_rule_and_is_deterministic():
    results, judgments, corpus = _synthetic()
    pairs, _ = nc.select_pairs(results, judgments, corpus)
    again, _ = nc.select_pairs(results, judgments, corpus)
    assert pairs == again
    assert [sum(p["group"] == g for p in pairs) for g in nc.GROUPS] == [10, 10, 10]
    assert len({p["claim"] for p in pairs}) == 30  # 30 distinct claims
    for g in nc.GROUPS:  # spread across outcomes as evenly as 10 allows
        counts = sorted(sum(1 for p in pairs if p["group"] == g and p["outcome"] == k) for k in OUTCOME_KEYS)
        assert counts == [2, 2, 3, 3]
    for p in pairs:
        if p["group"] == "positive":
            assert p["check"]["present"] and p["quote"] in p["chunk_text"]
        else:
            assert p["check"]["absent"] and p["quote"] not in p["chunk_text"]
            assert p["chunk_node_id"] != p["named_node_id"]
    for p in pairs:
        if p["group"] == "unrelated":
            own = {s["node_id"] for s in judgments[(p["doc_id"], 0)]["outcomes"][p["outcome"]]["sources"]}
            assert p["chunk_node_id"] not in own and p["chunk_origin"].startswith("retrieved for ")
        if p["group"] == "neighbouring":
            prev_id, next_id = nc.corpus_order(corpus)[p["named_node_id"]]
            assert p["chunk_node_id"] in (prev_id, next_id)


def test_build_refuses_to_overwrite_frozen_pairs(tmp_path):
    existing = tmp_path / "pairs.jsonl"
    existing.write_text("{}\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="Refusing to overwrite"):
        nc.cmd_build(argparse.Namespace(pairs=str(existing)))


class _FakeClient:
    def __init__(self, verdicts):
        self.verdicts, self.calls = verdicts, []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return cv.ClaimCheck(verdict=self.verdicts[len(self.calls) - 1], supporting_sentence="s")


def _pairs_file(tmp_path):
    results, judgments, corpus = _synthetic()
    pairs, _ = nc.select_pairs(results, judgments, corpus)
    path = tmp_path / "pairs.jsonl"
    path.write_text("".join(json.dumps(p) + "\n" for p in pairs), encoding="utf-8")
    return pairs, path


def test_run_calls_the_same_checker_once_per_pair_and_resumes(tmp_path, monkeypatch, capsys):
    import anthropic
    import instructor

    pairs, path = _pairs_file(tmp_path)
    client = _FakeClient(["no"] * 30)
    monkeypatch.setattr(instructor, "from_anthropic", lambda *_a, **_k: client)
    monkeypatch.setattr(anthropic, "Anthropic", lambda *_a, **_k: None)
    out = tmp_path / "results.jsonl"
    nc.cmd_run(argparse.Namespace(pairs=str(path), output=str(out)))
    assert len(client.calls) == 30
    for kw, p in zip(client.calls, pairs):  # same system prompt and tool settings as the full pass
        assert kw["system"] == cv.CLAIM_CHECK_SYSTEM_PROMPT and kw["response_model"] is cv.ClaimCheck
        assert kw["tool_choice"]["disable_parallel_tool_use"] is True
        assert p["claim"] in kw["messages"][0]["content"] and p["chunk_text"] in kw["messages"][0]["content"]
    assert len(out.read_text(encoding="utf-8").splitlines()) == 30
    capsys.readouterr()
    nc.cmd_run(argparse.Namespace(pairs=str(path), output=str(out)))  # nothing left to do
    assert len(client.calls) == 30 and "NO API calls" in capsys.readouterr().out


def _results(pairs, verdict_for):
    return [{"pair_id": p["pair_id"], "group": p["group"], "verdict": verdict_for(p)} for p in pairs]


def test_scoring_follows_the_written_criteria(tmp_path):
    pairs, _ = _pairs_file(tmp_path)
    ideal = _results(pairs, lambda p: "yes" if p["group"] == "positive" else "no")
    assert nc.score(pairs, ideal)["all_pass"]

    # Neighbouring at exactly 7/10 rejected still passes; positives at 9/10 still pass.
    n_ids = [p["pair_id"] for p in pairs if p["group"] == "neighbouring"][:3]
    p_ids = [p["pair_id"] for p in pairs if p["group"] == "positive"][:1]
    edge = _results(pairs, lambda p: "partially" if p["pair_id"] in n_ids + p_ids
                    else ("yes" if p["group"] == "positive" else "no"))
    s = nc.score(pairs, edge)
    assert s["neighbouring"]["met"] == 7 and s["neighbouring"]["passes"]
    assert s["positive"]["met"] == 9 and s["positive"]["passes"] and s["all_pass"]

    # One unrelated `partially` fails (partially is not a rejection).
    u_id = next(p["pair_id"] for p in pairs if p["group"] == "unrelated")
    one_partial = _results(pairs, lambda p: "partially" if p["pair_id"] == u_id
                           else ("yes" if p["group"] == "positive" else "no"))
    s = nc.score(pairs, one_partial)
    assert not s["unrelated"]["passes"] and s["unrelated"]["partially"] == 1 and not s["all_pass"]

    # 8/10 positives accepted fails.
    p2 = [p["pair_id"] for p in pairs if p["group"] == "positive"][:2]
    low = _results(pairs, lambda p: "partially" if p["pair_id"] in p2 else ("yes" if p["group"] == "positive" else "no"))
    assert not nc.score(pairs, low)["positive"]["passes"]

    # A missing result means the group cannot pass.
    assert not nc.score(pairs, ideal[:-1])["all_pass"]


def test_report_is_written_where_asked(tmp_path):
    pairs, path = _pairs_file(tmp_path)
    out = tmp_path / "results.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in _results(pairs, lambda p: "no")), encoding="utf-8")
    rep = tmp_path / "report.md"
    nc.cmd_report(argparse.Namespace(pairs=str(path), output=str(out), report=str(rep)))
    text = rep.read_text(encoding="utf-8")
    assert "LLM-only overall: FAIL" in text and "| positive |" in text  # all-`no` fails the positives


# --- criteria addendum (2026-10-08): what the checker sees, combined gate, annotations ---

def test_checker_sees_only_claim_and_chunk(tmp_path, monkeypatch):
    import anthropic
    import instructor

    pairs, path = _pairs_file(tmp_path)
    client = _FakeClient(["no"] * 30)
    monkeypatch.setattr(instructor, "from_anthropic", lambda *_a, **_k: client)
    monkeypatch.setattr(anthropic, "Anthropic", lambda *_a, **_k: None)
    nc.cmd_run(argparse.Namespace(pairs=str(path), output=str(tmp_path / "r.jsonl")))
    for kw, p in zip(client.calls, pairs):
        assert kw["messages"] == [{"role": "user", "content": f"SOURCE TEXT:\n{p['chunk_text']}\n\nCLAIM:\n{p['claim']}"}]
        if p["group"] != "positive":
            assert p["quote"] not in kw["messages"][0]["content"]  # the quote is never shown


def test_gate_decision_rules():
    found = {"quote": "alpha beta gamma delta epsilon", "chunk_text": "x alpha beta gamma delta epsilon y"}
    absent = {"quote": "alpha beta gamma delta epsilon", "chunk_text": "nothing relevant here at all today"}
    assert [nc.gate_decision(found, v) for v in ("yes", "partially", "no")] == ["accepted", "neither", "rejected"]
    assert [nc.gate_decision(absent, v) for v in ("yes", "partially", "no")] == ["rejected"] * 3


def test_combined_gate_and_checker_failures(tmp_path):
    pairs, _ = _pairs_file(tmp_path)
    # LLM says yes to everything: LLM-only fails both negative groups; the gate still rejects every negative.
    all_yes = _results(pairs, lambda p: "yes")
    llm, gate = nc.score(pairs, all_yes), nc.score_gate(pairs, all_yes)
    assert not llm["unrelated"]["passes"] and not llm["neighbouring"]["passes"] and llm["positive"]["passes"]
    assert gate["unrelated"]["counts"]["rejected"] == 10 and gate["neighbouring"]["counts"]["rejected"] == 10
    assert gate["positive"]["counts"]["accepted"] == 10 and gate["all_pass"]
    assert len(nc.checker_failures(pairs, all_yes)) == 20
    # A positive marked `partially` is neither under the gate (and not accepted by the LLM-only rule).
    p2 = [p["pair_id"] for p in pairs if p["group"] == "positive"][:2]
    some = _results(pairs, lambda p: "partially" if p["pair_id"] in p2 else ("yes" if p["group"] == "positive" else "no"))
    g = nc.score_gate(pairs, some)["positive"]
    assert g["counts"] == {"accepted": 8, "neither": 2, "rejected": 0} and not g["passes"]


def test_annotations_never_change_any_result(tmp_path):
    pairs, path = _pairs_file(tmp_path)
    out = tmp_path / "results.jsonl"
    rows = _results(pairs, lambda p: "yes")  # 20 checker failures
    out.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    failing = [p["pair_id"] for p in nc.checker_failures(pairs, rows)]
    ann = tmp_path / "ann.jsonl"
    ann.write_text("".join(json.dumps({"pair_id": i, "chunk_supports_claim": "yes", "note": "general principle"}) + "\n"
                           for i in failing), encoding="utf-8")
    plain, annotated = tmp_path / "plain.md", tmp_path / "annotated.md"
    nc.cmd_report(argparse.Namespace(pairs=str(path), output=str(out), report=str(plain),
                                     annotations=str(tmp_path / "none.jsonl")))
    nc.cmd_report(argparse.Namespace(pairs=str(path), output=str(out), report=str(annotated), annotations=str(ann)))
    a, b = plain.read_text(encoding="utf-8"), annotated.read_text(encoding="utf-8")
    tables = lambda t: t.split("## Checker failures")[0]
    assert tables(a) == tables(b)  # every count and PASS/FAIL identical
    assert "annotation pending" in a and "chunk supports claim: `yes`" in b
    assert b.count("CHECKER FAILURE") == 20 and "LLM-only overall: FAIL" in b and "Combined gate overall: PASS" in b
