import logging
from pathlib import Path

import chromadb
from llama_index.core import Settings, SimpleDirectoryReader, StorageContext, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore

from src.config import (
    CHROMA_COLLECTION_NAME,
    CHROMA_PERSIST_DIR,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    EMBED_MODEL_NAME,
    INTERNAL_POLICY_COLLECTION_NAME,
    INTERNAL_POLICY_CORPUS_DIR,
    REGULATORY_CORPUS_DIR,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

SUPPORTED_EXTS = [".pdf", ".txt"]


def load_documents(corpus_dir: Path):
    if not any(corpus_dir.glob(f"*{ext}") for ext in SUPPORTED_EXTS):
        raise FileNotFoundError(f"No supported documents ({SUPPORTED_EXTS}) found in {corpus_dir}")
    reader = SimpleDirectoryReader(input_dir=str(corpus_dir), required_exts=SUPPORTED_EXTS)
    return reader.load_data()


def build_index(
    corpus_dir: Path = REGULATORY_CORPUS_DIR,
    collection_name: str = CHROMA_COLLECTION_NAME,
) -> VectorStoreIndex:
    documents = load_documents(corpus_dir)
    source_files = {doc.metadata.get("file_name") for doc in documents}
    logger.info("Loaded %d source document(s), %d page-document(s)", len(source_files), len(documents))

    Settings.embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)
    splitter = SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)

    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass
    collection = client.create_collection(collection_name)

    vector_store = ChromaVectorStore(chroma_collection=collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    index = VectorStoreIndex.from_documents(
        documents,
        storage_context=storage_context,
        transformations=[splitter],
        show_progress=True,
    )

    logger.info(
        "Indexed %d chunks into Chroma collection '%s' at %s",
        collection.count(),
        collection_name,
        CHROMA_PERSIST_DIR,
    )
    return index


def build_internal_policy_index() -> VectorStoreIndex:
    return build_index(
        corpus_dir=INTERNAL_POLICY_CORPUS_DIR,
        collection_name=INTERNAL_POLICY_COLLECTION_NAME,
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--internal-policy":
        build_internal_policy_index()
    else:
        build_index()
