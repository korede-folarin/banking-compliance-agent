import chromadb
import pytest
from llama_index.core import Settings, VectorStoreIndex
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore

from src.config import CHROMA_COLLECTION_NAME, CHROMA_PERSIST_DIR, EMBED_MODEL_NAME

EXPECTED_SOURCE_FILES = {
    "FCA Handbook - PRIN 2A The Consumer Duty.pdf",
    "fg22-5.pdf",
    "ps22-9.pdf",
}


@pytest.fixture(scope="module")
def collection():
    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    try:
        col = client.get_collection(CHROMA_COLLECTION_NAME)
    except Exception:
        pytest.skip(
            f"Chroma collection '{CHROMA_COLLECTION_NAME}' not found at "
            f"{CHROMA_PERSIST_DIR} — run `python -m src.ingestion.ingest` first."
        )
    if col.count() == 0:
        pytest.skip("Chroma collection is empty — run `python -m src.ingestion.ingest` first.")
    return col


@pytest.fixture(scope="module")
def retriever(collection):
    Settings.embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)
    vector_store = ChromaVectorStore(chroma_collection=collection)
    index = VectorStoreIndex.from_vector_store(vector_store)
    return index.as_retriever(similarity_top_k=3)


def test_all_source_documents_are_indexed(collection):
    metadatas = collection.get(include=["metadatas"])["metadatas"]
    file_names = {m.get("file_name") for m in metadatas}
    assert file_names == EXPECTED_SOURCE_FILES


def test_chunks_contain_real_text_not_raw_pdf_bytes(collection):
    sample = collection.get(limit=5, include=["documents"])["documents"]
    for text in sample:
        assert "%PDF-" not in text
        assert len(text.strip()) > 0


@pytest.mark.parametrize(
    "query,expected_keyword",
    [
        ("What outcomes must firms deliver under the Consumer Duty?", "outcome"),
        ("How should firms treat vulnerable customers?", "vulnerab"),
        ("price and value outcome requirements", "value"),
    ],
)
def test_retrieval_returns_relevant_grounded_chunks(retriever, query, expected_keyword):
    nodes = retriever.retrieve(query)
    assert len(nodes) > 0

    top = nodes[0]
    assert top.score > 0.5
    assert top.metadata.get("file_name") in EXPECTED_SOURCE_FILES
    assert expected_keyword.lower() in top.text.lower()
