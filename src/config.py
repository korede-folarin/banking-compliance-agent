import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REGULATORY_CORPUS_DIR = PROJECT_ROOT / "data" / "regulatory_corpus"

CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")
CHROMA_COLLECTION_NAME = "regulatory_corpus"

EMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"
CHUNK_SIZE = 512
CHUNK_OVERLAP = 50
