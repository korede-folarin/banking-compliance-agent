import logging

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
    REGULATORY_CORPUS_DIR,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def load_documents():
    if not any(REGULATORY_CORPUS_DIR.glob("*.pdf")):
        raise FileNotFoundError(f"No PDFs found in {REGULATORY_CORPUS_DIR}")
    reader = SimpleDirectoryReader(input_dir=str(REGULATORY_CORPUS_DIR), required_exts=[".pdf"])
    return reader.load_data()


def build_index() -> VectorStoreIndex:
    documents = load_documents()
    source_files = {doc.metadata.get("file_name") for doc in documents}
    logger.info("Loaded %d source PDF(s), %d page-document(s)", len(source_files), len(documents))

    Settings.embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)
    splitter = SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)

    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    try:
        client.delete_collection(CHROMA_COLLECTION_NAME)
    except Exception:
        pass
    collection = client.create_collection(CHROMA_COLLECTION_NAME)

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
        CHROMA_COLLECTION_NAME,
        CHROMA_PERSIST_DIR,
    )
    return index


if __name__ == "__main__":
    build_index()
