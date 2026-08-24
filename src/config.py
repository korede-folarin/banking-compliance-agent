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
