import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REGULATORY_CORPUS_DIR = PROJECT_ROOT / "data" / "regulatory_corpus"
INTERNAL_POLICY_CORPUS_DIR = PROJECT_ROOT / "data" / "internal_policy"
MOCK_ACCOUNTS_PATH = PROJECT_ROOT / "data" / "mock_accounts" / "accounts.json"

CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")
CHROMA_COLLECTION_NAME = "regulatory_corpus"
INTERNAL_POLICY_COLLECTION_NAME = "internal_policy"

EMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"
CHUNK_SIZE = 512
CHUNK_OVERLAP = 50

ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
QUERY_SIMILARITY_TOP_K = 5
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.65"))

# --- Agentic tool loop (docs/agent_tool_use_design.md; limits decided 2026-10-13) ---
AGENT_MAX_TOOL_CALLS = 8          # per document run, all tools together
AGENT_MAX_CALLS_PER_TOOL = 3      # repeated identical calls still count
# Exceptions to the per-tool limit (2026-10-14, user decision): one regulation search per Consumer
# Duty outcome, each call naming exactly one outcome.
AGENT_CALL_LIMIT_BY_TOOL = {"search_regulation": 4}
AGENT_MAX_TURNS = 6               # model requests per document run
AGENT_MAX_OUTPUT_TOKENS = 16000   # the final assessment covers 4 outcomes plus escalation
AGENT_REVIEW_DATE = os.getenv("AGENT_REVIEW_DATE", "2026-10-01")  # "trailing 12 months" ends here
# "Recent" in escalation trigger 2.1(c) (the procedure does not define it): within this many months
# before the review date. User decision, 2026-10-14. Same window as 2.1(a)'s "trailing 12 months".
AGENT_RECENT_WINDOW_MONTHS = 12
# Auto-approval (a case skipping human review). OFF until a per-category gate has been calibrated on
# the design split against a stated risk target and met it on held-out data (decision 2026-10-14:
# on today's data no category qualifies). While off, every agent case goes to a human, and the
# confidence score is reported, never used to replace the agent's verdict.
AGENT_AUTO_APPROVAL_ENABLED = False

# --- Human review (P7-01) ---
# Append-only review decisions. Gitignored: they hold reviewer names. Relative to the repo root.
REVIEW_DIR = Path(os.getenv("REVIEW_DIR", "reviews"))
# Public hosted demo (P10-02): shows a banner that the data is synthetic and decisions are not kept.
DEMO_MODE = os.getenv("DEMO_MODE", "0") == "1"
if not REVIEW_DIR.is_absolute():
    REVIEW_DIR = PROJECT_ROOT / REVIEW_DIR

# --- Audit logging (docs/audit_logging_design.md) ---
# Relative paths resolve against the repo root, not the working directory, so
# a run started from anywhere logs to the same place. ./logs/ is gitignored.
LOG_DIR = Path(os.getenv("LOG_DIR", "logs"))
if not LOG_DIR.is_absolute():
    LOG_DIR = PROJECT_ROOT / LOG_DIR

# Price per million tokens (input, output), used only for the cost ESTIMATE in
# a run's end event. Cache reads bill at 0.1x input and cache writes at 1.25x.
PRICE_PER_MTOK = {"claude-sonnet-5": (2.00, 10.00)}

# Retrieval check (warn only): a top score below this suggests an off-topic
# query. Real questions score 0.67-0.74 in the ingestion smoke test.
RETRIEVAL_OFF_TOPIC_SCORE = 0.5

# --- Ingestion sanity checks (design section 6) ---
# Set from the known-good index (558 chunks over 344 PDF pages; 0.055% bad
# characters; every page yields text; smoke-test top scores 0.67-0.74).
INGEST_MAX_BAD_CHAR_SHARE = 0.01        # non-printable or U+FFFD-replacement characters
INGEST_CHUNKS_PER_PAGE_MIN = 0.5
INGEST_CHUNKS_PER_PAGE_MAX = 5.0        # the 5,540-chunk run was ~16 per page
INGEST_MIN_CHARS_FOR_TEXT_PAGE = 20     # a PDF page "yields text" at this many non-space characters
INGEST_MIN_PAGES_WITH_TEXT_SHARE = 0.90
INGEST_MAX_FILE_SHARE_RATIO = 2.0       # warn only: a file's chunk share vs its page share
INGEST_SMOKE_TOP_K = 5
INGEST_SMOKE_MIN_SCORE = 0.6
# Known questions and the source file each must retrieve in the top k. Only
# the regulatory corpus has them; other collections log the check as not
# applicable rather than skipping it silently.
INGEST_SMOKE_QUERIES = {
    CHROMA_COLLECTION_NAME: [
        ("What outcomes must firms deliver under the Consumer Duty?", "fg22-5.pdf"),
        ("How should firms treat vulnerable customers?", "fg22-5.pdf"),
        ("price and value outcome requirements", "ps22-9.pdf"),
    ],
}
