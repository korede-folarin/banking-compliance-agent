"""
Offline tests for deferred-checklist items 4, 10, 12, 14, 15 and 16
(ARCHITECTURE.md "Evaluation notes"), the last batch before the
comprehensive re-run.

- Item 4: the judge's user message includes the full loan agreement text.
- Item 10: groundedness.py and claim_verification.py work on any run, not
  just run 0.
- Item 12: `variants` rows save the same per-outcome fields as `main`.
- Item 14: `variants` skips, and announces, rows it already has.
- Item 15: `summary` warns when a pass is short, and is silent when complete.
- Item 16: `claim_verification judge` (and `ingest`) announce skipped pairs.

No API calls, no Chroma, no embedding model: LLM clients, retrievers,
embeddings and agents are faked, and all files live in temp directories.
The real Phase 8 files are hashed before and after, and docs/ is checked
for new files.
"""

import argparse
import hashlib
import json

import pytest

from src.agent import compliance
from src.agent.compliance import COMPLIANCE_SYSTEM_PROMPT, OutcomeJudgment
from src.agent.first_pass import FirstPassResult
from src.agent.schemas import LoanAgreementFields
from src.evaluation import claim_verification as cv
from src.evaluation import groundedness
from src.evaluation import run_eval
from src.retrieval.query_engine import QueryResult, SourceCitation
from tests.fixtures.eval_set import EVAL_DOCUMENTS, OUTCOME_KEYS

PROTECTED = [
    run_eval.MAIN_PASS_PATH,
    run_eval.SUMMARY_PATH,
    run_eval.DOCS_OUT_DIR / "eval_groundedness.md",
    run_eval.DOCS_OUT_DIR / "eval_results.md",
]
PHASE8_ROWS = [
    json.loads(line) for line in run_eval.MAIN_PASS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()
]
BASE_FIELDS = next(r for r in PHASE8_ROWS if r["run_idx"] == 0)["_cached_fields"]
DOC_TEXT_1 = run_eval._load_doc_text("loan_agreement_1.txt")
GT = {d["id"]: d["ground_truth"] for d in EVAL_DOCUMENTS}
# Per-outcome fields `main` saves since items 3/8, 6 and 9.
MAIN_OUTCOME_KEYS = {
    "llm_status", "status", "confidence", "cited_source_count", "cited_sources",
    "cited_sources_raw", "reasoning", "judgment", "retrieved_sources",
}


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


@pytest.fixture(scope="module", autouse=True)
def protected_files_untouched():
    before = {p: _sha256(p) for p in PROTECTED}
    docs_before = sorted(p.name for p in run_eval.DOCS_OUT_DIR.iterdir())
    yield
    assert {p: _sha256(p) for p in PROTECTED} == before, "a protected docs/ file was modified"
    assert sorted(p.name for p in run_eval.DOCS_OUT_DIR.iterdir()) == docs_before, "a file was created or removed in docs/"


def _fake_main_row(doc_id, run_idx, status="compliant", new_format=True):
    """A main-pass row as `main` writes it now (new_format) or as Phase 8 wrote runs 1/2 (not)."""
    srcs = [
        {"index": i, "node_id": f"{doc_id}-r{run_idx}-n{i}", "file_name": "fake.pdf", "similarity_score": 0.7,
         "text_excerpt": f"Fake excerpt {i} for {doc_id} run {run_idx}: firms must do thing {i}."}
        for i in range(1, 6)
    ]
    outcomes = {}
    for k in OUTCOME_KEYS:
        judgment = {
            "status": status, "reasoning": f"{doc_id} run {run_idx} {k} reasoning", "cited_sources": [1],
            "document_facts": [],
            "regulatory_requirements": [{
                "claim": f"{doc_id} run {run_idx} {k} requirement",
                "sources": [{"excerpt_number": 1, "verbatim_quote": "firms must do thing 1"}],
            }],
            "absences": [],
        }
        o = {"llm_status": status, "status": status, "confidence": 0.7, "cited_source_count": 1,
             "cited_sources": [srcs[0]], "reasoning": judgment["reasoning"]}
        if new_format:
            o.update(cited_sources_raw=[1], judgment=judgment, retrieved_sources=srcs)
        outcomes[k] = o
    row = {"doc_id": doc_id, "run_idx": run_idx, "ground_truth": GT[doc_id], "outcomes": outcomes,
           "needs_human_review": False}
    if new_format:
        row["_cached_fields"] = {**BASE_FIELDS, "fees": f"{doc_id} fees extracted on run {run_idx}"}
    return row


class _NoIndex:
    """load_index stand-in that fails if anything tries to replay retrieval."""

    def __call__(self, *a, **k):
        raise AssertionError("retrieval replay should not be needed: saved retrieved_sources exist")


class _FakeLLM:
    """instructor client stand-in: records each call, returns a fixed judgment."""

    def __init__(self):
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return OutcomeJudgment(
            status="compliant", reasoning="fake", cited_sources=[1, 9],
            document_facts=[], regulatory_requirements=[], absences=[],
        )


@pytest.fixture
def fake_llm(monkeypatch):
    import anthropic
    import instructor

    client = _FakeLLM()
    monkeypatch.setattr(instructor, "from_anthropic", lambda *_a, **_k: client)
    monkeypatch.setattr(anthropic, "Anthropic", lambda *_a, **_k: None)
    return client


# ---------------------------------------------------------------- item 4 ---

def _first_pass():
    contexts = {
        f"{k}_context": QueryResult(
            question="q", answer="a", confidence=0.7, needs_human_review=False,
            sources=[SourceCitation(index=1, file_name="f.pdf", similarity_score=0.7, text_excerpt=f"{k} excerpt")],
        )
        for k in OUTCOME_KEYS
    }
    return FirstPassResult(document_fields=LoanAgreementFields(**BASE_FIELDS), **contexts)


def test_item4_user_message_contains_full_document_statement_and_excerpts():
    msg = compliance.build_judgment_user_message(
        "Price and Value", "Stated fees: x", DOC_TEXT_1,
        [SourceCitation(index=1, file_name="f.pdf", similarity_score=0.7, text_excerpt="excerpt one")],
    )
    assert DOC_TEXT_1 in msg  # the whole document, verbatim
    assert "Full text of the loan agreement under review" in msg
    assert '"Stated fees: x"' in msg
    assert "[1] (Source: f.pdf)\nexcerpt one" in msg


def test_item4_every_judgment_call_sends_the_full_document():
    agent = compliance.ComplianceAgent.__new__(compliance.ComplianceAgent)  # no real client
    agent._client = _FakeLLM()
    agent.evaluate(_first_pass(), DOC_TEXT_1)

    assert len(agent._client.calls) == 4
    for call in agent._client.calls:
        assert call["system"] == COMPLIANCE_SYSTEM_PROMPT  # system prompt unchanged
        assert DOC_TEXT_1 in call["messages"][0]["content"]
    fields = LoanAgreementFields(**BASE_FIELDS)
    for k, call in zip(OUTCOME_KEYS, agent._client.calls):
        assert compliance.build_document_statement(k, fields) in call["messages"][0]["content"]


def test_item4_document_text_is_required():
    agent = compliance.ComplianceAgent.__new__(compliance.ComplianceAgent)
    agent._client = _FakeLLM()
    with pytest.raises(TypeError):
        agent.evaluate(_first_pass())


def test_item4_pipeline_passes_the_document_through():
    seen = {}

    class FakeFirstPassAgent:
        def run(self, text):
            return _first_pass()

    class FakeComplianceAgent:
        def evaluate(self, first_pass, document_text):
            seen["text"] = document_text
            return {k: OutcomeJudgment(status="compliant", reasoning="r", cited_sources=[1], document_facts=[],
                                       regulatory_requirements=[], absences=[]) for k in OUTCOME_KEYS}

    pipeline = compliance.ComplianceCheckAgent.__new__(compliance.ComplianceCheckAgent)
    pipeline._first_pass_agent = FakeFirstPassAgent()
    pipeline._compliance_agent = FakeComplianceAgent()
    pipeline.run(DOC_TEXT_1)
    assert seen["text"] == DOC_TEXT_1


# --------------------------------------------------------------- item 10 ---

@pytest.fixture
def no_embeddings(monkeypatch):
    monkeypatch.setattr(groundedness, "compute_signal1", lambda reasoning, sources: 0.5)
    monkeypatch.setattr(groundedness, "compute_signal1_cited", lambda reasoning, cited: {"per_chunk": [], "min": None, "mean": None})
    monkeypatch.setattr(cv, "load_corpus", lambda: [])
    monkeypatch.setattr(cv, "_embed", lambda text: [float(len(text) % 7 + 1), 1.0, 0.5])
    monkeypatch.setattr(cv, "compute_signal1_cited", lambda reasoning, cited: {"per_chunk": [], "min": None, "mean": None})


def test_item10_groundedness_scope_includes_runs_1_and_2(no_embeddings, monkeypatch):
    monkeypatch.setattr(groundedness, "load_index", _NoIndex())
    rows = [_fake_main_row("loan_agreement_1", i) for i in range(3)]
    scope = groundedness.build_scope(rows)
    assert {j["run_idx"] for j in scope} == {0, 1, 2}
    assert len(scope) == 3 * len(OUTCOME_KEYS)
    run2 = next(j for j in scope if j["run_idx"] == 2)
    assert run2["sources"] == rows[2]["outcomes"][run2["outcome"]]["retrieved_sources"]  # saved, not replayed


def test_item10_groundedness_skips_and_reports_rows_without_sources_or_fields(no_embeddings, monkeypatch, capsys):
    monkeypatch.setattr(groundedness, "load_index", _NoIndex())
    rows = [_fake_main_row("loan_agreement_1", 0), _fake_main_row("loan_agreement_1", 1, new_format=False)]
    scope = groundedness.build_scope(rows)
    assert {j["run_idx"] for j in scope} == {0}
    assert "skipped 1 main-pass row(s)" in capsys.readouterr().out


def test_item10_groundedness_phase8_scope_unchanged(no_embeddings, monkeypatch):
    class _Retriever:
        def as_retriever(self, similarity_top_k):
            return self

        def retrieve(self, q):
            return []

    monkeypatch.setattr(groundedness, "load_index", lambda: _Retriever())
    scope = groundedness.build_scope(PHASE8_ROWS)
    assert {j["run_idx"] for j in scope} == {0}
    assert len(scope) == 51  # the P8-05 scope, reproduced


@pytest.fixture
def cv_paths(tmp_path, monkeypatch):
    main = tmp_path / "eval_raw_main_pass_v2.jsonl"
    judgments = tmp_path / "pilot_judgments.jsonl"
    monkeypatch.setattr(run_eval, "MAIN_PASS_V2_PATH", main)
    monkeypatch.setattr(cv, "PILOT_JUDGMENTS_PATH", judgments)
    monkeypatch.setattr(cv, "PILOT_CHECKS_PATH", tmp_path / "pilot_checks.jsonl")
    return {"main": main, "judgments": judgments, "tmp": tmp_path}


def _ns(**kw):
    base = {"docs": None, "runs": None, "judgments": None, "input": None, "output": None}
    base.update(kw)
    return argparse.Namespace(**base)


def test_item10_ingest_reads_every_run_and_skips_old_format_rows(cv_paths, capsys):
    _write(cv_paths["main"], [_fake_main_row("loan_agreement_1", i) for i in range(3)]
           + [_fake_main_row("loan_agreement_2", 1, new_format=False)])
    out_path = cv_paths["tmp"] / "ingested.jsonl"
    cv.cmd_ingest(_ns(judgments=str(out_path)))
    out = capsys.readouterr().out

    rows = _rows(out_path)
    assert sorted(r["run_idx"] for r in rows) == [0, 1, 2]
    assert all(r["origin"] == "main_pass" and r["doc_id"] == "loan_agreement_1" for r in rows)
    r2 = next(r for r in rows if r["run_idx"] == 2)
    assert r2["fields"]["fees"] == "loan_agreement_1 fees extracted on run 2"
    assert r2["outcomes"]["price_and_value"]["sources"][0]["node_id"] == "loan_agreement_1-r2-n1"
    assert "loan_agreement_2 run 1: missing" in out


def test_item10_ingest_default_path_is_derived_and_main_files_are_refused(cv_paths):
    _write(cv_paths["main"], [_fake_main_row("loan_agreement_1", 0)])
    cv.cmd_ingest(_ns())
    assert (cv_paths["tmp"] / "eval_raw_main_pass_v2_claim_judgments.jsonl").exists()
    with pytest.raises(SystemExit, match="Refusing"):
        cv.cmd_ingest(_ns(judgments=str(run_eval.MAIN_PASS_PATH)))


def test_item10_judge_uses_runs_1_and_2_with_their_own_fields_and_sources(cv_paths, monkeypatch):
    statuses = ["compliant", "potentially_non_compliant", "insufficient_evidence"]
    _write(cv_paths["main"], [_fake_main_row("loan_agreement_1", i, status=statuses[i]) for i in range(3)])
    seen = []

    class FakeAgent:
        def evaluate(self, first_pass, document_text):
            seen.append((first_pass.document_fields.fees, first_pass.price_and_value_context.sources[0].node_id,
                         document_text))
            return {k: OutcomeJudgment(status="compliant", reasoning="r", cited_sources=[1], document_facts=[],
                                       regulatory_requirements=[], absences=[]) for k in OUTCOME_KEYS}

    monkeypatch.setattr(cv, "ComplianceAgent", FakeAgent)
    monkeypatch.setattr(cv, "load_index", _NoIndex())
    cv.cmd_judge(_ns(docs=["loan_agreement_1"], runs=[1, 2]))

    rows = _rows(cv_paths["judgments"])
    assert [r["run_idx"] for r in rows] == [1, 2]
    assert [s[0] for s in seen] == ["loan_agreement_1 fees extracted on run 1", "loan_agreement_1 fees extracted on run 2"]
    assert [s[1] for s in seen] == ["loan_agreement_1-r1-n1", "loan_agreement_1-r2-n1"]
    assert all(s[2] == DOC_TEXT_1 for s in seen)  # item 4 via the pilot path
    for r in rows:
        assert r["outcomes"]["price_and_value"]["reference_llm_status"] == statuses[r["run_idx"]]


def test_item10_check_handles_every_run(cv_paths, no_embeddings, fake_llm):
    fake_llm.create = lambda **kw: cv.ClaimCheck(verdict="yes", supporting_sentence="")
    _write(cv_paths["main"], [_fake_main_row("loan_agreement_1", i) for i in range(3)])
    judgments = cv_paths["tmp"] / "ingested.jsonl"
    cv.cmd_ingest(_ns(judgments=str(judgments)))
    cv.cmd_check(_ns(judgments=str(judgments)))

    store = cv_paths["tmp"] / "ingested_checks.jsonl"  # derived from the judgments file name
    assert sorted({r["run_idx"] for r in _rows(store)}) == [0, 1, 2]
    assert len(_rows(store)) == 3 * len(OUTCOME_KEYS)
    report = (cv_paths["tmp"] / "ingested_checks_report.md").read_text(encoding="utf-8")
    assert "runs [0, 1, 2]" in report and "main_pass: 12" in report


# --------------------------------------------------------- items 12 / 14 ---

@pytest.fixture
def variants_env(tmp_path, monkeypatch, fake_llm):
    v2 = tmp_path / "eval_raw_main_pass_v2.jsonl"
    _write(v2, [r for r in PHASE8_ROWS if r["run_idx"] == 0])  # all 15 docs have cached run-0 context
    monkeypatch.setattr(run_eval, "MAIN_PASS_V2_PATH", v2)
    return {"v2": v2, "out": tmp_path / "eval_raw_main_pass_v2_variants.jsonl", "llm": fake_llm}


def test_item12_variant_rows_carry_the_same_fields_as_main_records(variants_env):
    run_eval.cmd_variants(argparse.Namespace(n_runs=1, input=None, output=None))
    rows = _rows(variants_env["out"])
    assert len(rows) == len(EVAL_DOCUMENTS) * len(run_eval.VARIANTS)
    for r in rows:
        assert MAIN_OUTCOME_KEYS <= set(r)
        assert OutcomeJudgment.model_validate(r["judgment"]).model_dump() == r["judgment"]
        assert r["cited_sources_raw"] == [1, 9]  # raw list kept
        assert [s["index"] for s in r["cited_sources"]] == [1]  # 9 resolved away
        assert len(r["retrieved_sources"]) == 5
        assert r["_cached_fields"] and r["main_pass_input"] == variants_env["v2"].name


def test_item12_variant_a_is_the_production_prompt_and_message(variants_env):
    run_eval.cmd_variants(argparse.Namespace(n_runs=1, input=None, output=None))
    call = variants_env["llm"].calls[0]  # loan_agreement_1, variant A, run 0
    assert call["system"] == COMPLIANCE_SYSTEM_PROMPT
    row1 = next(r for r in PHASE8_ROWS if r["doc_id"] == "loan_agreement_1" and r["run_idx"] == 0)
    expected = compliance.build_judgment_user_message(
        "Price and Value",
        compliance.build_document_statement("price_and_value", LoanAgreementFields(**row1["_cached_fields"])),
        DOC_TEXT_1,
        [SourceCitation(**s) for s in row1["_cached_price_and_value_context"]["sources"]],
    )
    assert call["messages"][0]["content"] == expected


def test_item14_default_output_is_derived_and_main_files_are_refused(variants_env):
    assert run_eval._variants_output_for(run_eval.MAIN_PASS_V2_PATH) == variants_env["out"]
    for bad in (str(variants_env["v2"]), str(run_eval.MAIN_PASS_PATH)):
        with pytest.raises(SystemExit, match="Refusing"):
            run_eval.cmd_variants(argparse.Namespace(n_runs=1, input=None, output=bad))


def test_item14_second_run_makes_no_calls_and_announces_it(variants_env, capsys):
    run_eval.cmd_variants(argparse.Namespace(n_runs=1, input=None, output=None))
    first = variants_env["out"].read_text(encoding="utf-8")
    n_first = len(variants_env["llm"].calls)
    capsys.readouterr()

    run_eval.cmd_variants(argparse.Namespace(n_runs=1, input=None, output=None))
    out = capsys.readouterr().out
    assert len(variants_env["llm"].calls) == n_first  # no new calls
    assert variants_env["out"].read_text(encoding="utf-8") == first  # no duplicates
    assert f"{n_first} of the {n_first} requested" in out and "NO API calls" in out


def test_item14_partial_file_resumes_and_lists_skips(variants_env, capsys):
    run_eval.cmd_variants(argparse.Namespace(n_runs=1, input=None, output=None))
    rows = _rows(variants_env["out"])
    _write(variants_env["out"], rows[:5])
    variants_env["llm"].calls.clear()
    capsys.readouterr()

    run_eval.cmd_variants(argparse.Namespace(n_runs=1, input=None, output=None))
    out = capsys.readouterr().out
    assert len(variants_env["llm"].calls) == len(rows) - 5
    keys = [(r["doc_id"], r["variant"], r["run_idx"]) for r in _rows(variants_env["out"])]
    assert len(keys) == len(rows) == len(set(keys))
    assert f"5 of the {len(rows)} requested" in out
    for r in rows[:5]:
        assert f"{r['doc_id']} {r['variant']} run {r['run_idx']}" in out
    assert "NO API calls" not in out


# --------------------------------------------------------------- item 15 ---

@pytest.fixture
def complete_pass(tmp_path):
    path = tmp_path / "pass.jsonl"
    _write(path, [r for r in PHASE8_ROWS if r["run_idx"] == 0])  # 15 docs x 1 run, complete
    return path


def _summary(path, capsys, **kw):
    run_eval.cmd_summary(argparse.Namespace(input=str(path), expected_runs=kw.get("expected_runs")))
    out = capsys.readouterr().out
    return json.loads(path.with_name(f"{path.stem}_summary.json").read_text(encoding="utf-8")), out


def test_item15_complete_pass_is_silent(complete_pass, capsys):
    summary, out = _summary(complete_pass, capsys)
    assert "WARNING" not in out
    assert "completeness_warnings" not in summary


def test_item15_short_pass_warns_and_names_missing_rows(complete_pass, capsys):
    rows = _rows(complete_pass)
    _write(complete_pass, [r for r in rows if r["doc_id"] not in ("loan_agreement_3", "loan_agreement_7")])
    summary, out = _summary(complete_pass, capsys)
    assert "WARNING (incomplete pass)" in out
    assert "13 of 15 expected" in out
    assert "loan_agreement_3 run 0" in out and "loan_agreement_7 run 0" in out
    assert summary["completeness_warnings"]


def test_item15_expected_runs_catches_a_missing_final_run(complete_pass, capsys):
    summary, out = _summary(complete_pass, capsys, expected_runs=3)
    assert "15 of 45 expected" in out
    assert "loan_agreement_1 run 2" in out


def test_item15_missing_outcomes_duplicates_and_logged_errors_warn(complete_pass, capsys):
    rows = _rows(complete_pass)
    del rows[0]["outcomes"]["consumer_support"]
    rows.append(rows[1])
    _write(complete_pass, rows)
    _write(complete_pass.with_name(f"{complete_pass.stem}_errors.jsonl"), [{"doc_id": "x", "run_idx": 0, "error": "e"}])
    with pytest.raises(KeyError):  # metrics can't be computed on a row with a missing outcome...
        _summary(complete_pass, capsys)
    out = capsys.readouterr().out
    # ...but the warnings are printed first, so the cause is visible.
    assert "missing outcomes" in out and "consumer_support" in out
    assert "duplicate rows" in out
    assert "1 failure(s) logged" in out


def test_item15_short_variant_file_warns(complete_pass, capsys):
    variants = complete_pass.with_name(f"{complete_pass.stem}_variants.jsonl")
    _write(variants, [{"doc_id": "loan_agreement_1", "variant": v, "run_idx": 0, "ground_truth": "compliant",
                       "llm_status": "compliant", "status": "compliant"} for v in run_eval.VARIANTS])
    summary, out = _summary(complete_pass, capsys)
    assert f"variants: 2 of {len(EVAL_DOCUMENTS) * 2} expected" in out


# --------------------------------------------------------------- item 16 ---

def test_item16_judge_announces_skipped_pairs(cv_paths, monkeypatch, capsys):
    _write(cv_paths["main"], [_fake_main_row("loan_agreement_1", i) for i in range(2)])
    _write(cv_paths["judgments"], [{"doc_id": "loan_agreement_1", "run_idx": 0, "outcomes": {}}])
    calls = []

    class FakeAgent:
        def evaluate(self, first_pass, document_text):
            calls.append(first_pass.document_fields.fees)
            return {k: OutcomeJudgment(status="compliant", reasoning="r", cited_sources=[1], document_facts=[],
                                       regulatory_requirements=[], absences=[]) for k in OUTCOME_KEYS}

    monkeypatch.setattr(cv, "ComplianceAgent", FakeAgent)
    monkeypatch.setattr(cv, "load_index", _NoIndex())
    cv.cmd_judge(_ns(docs=["loan_agreement_1"], runs=[0, 1]))
    out = capsys.readouterr().out
    assert "1 of the 2 requested (doc, run) pairs" in out
    assert "loan_agreement_1 run 0" in out
    assert calls == ["loan_agreement_1 fees extracted on run 1"]  # only the new pair was judged
    assert "NO API calls" not in out


def test_item16_judge_with_nothing_new_says_so_and_makes_no_calls(cv_paths, monkeypatch, capsys):
    _write(cv_paths["main"], [_fake_main_row("loan_agreement_1", 0)])
    _write(cv_paths["judgments"], [{"doc_id": "loan_agreement_1", "run_idx": 0, "outcomes": {}}])

    class ExplodingAgent:
        def __init__(self):
            raise AssertionError("no agent should be built when nothing is left to judge")

    monkeypatch.setattr(cv, "ComplianceAgent", ExplodingAgent)
    cv.cmd_judge(_ns(docs=["loan_agreement_1"], runs=[0]))
    out = capsys.readouterr().out
    assert "1 of the 1 requested (doc, run) pairs" in out and "NO API calls" in out


def test_item16_ingest_announces_skipped_pairs(cv_paths, capsys):
    _write(cv_paths["main"], [_fake_main_row("loan_agreement_1", i) for i in range(2)])
    target = cv_paths["tmp"] / "ingested.jsonl"
    cv.cmd_ingest(_ns(judgments=str(target), runs=[0]))
    capsys.readouterr()
    cv.cmd_ingest(_ns(judgments=str(target)))
    out = capsys.readouterr().out
    assert "1 of the 2 requested (doc, run) pairs" in out and "loan_agreement_1 run 0" in out
    assert len(_rows(target)) == 2
