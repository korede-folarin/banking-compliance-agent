import logging

import anthropic
import chromadb
from llama_index.core import Settings, VectorStoreIndex
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore
from pydantic import BaseModel

from src.config import (
    ANTHROPIC_MODEL,
    CHROMA_COLLECTION_NAME,
    CHROMA_PERSIST_DIR,
    EMBED_MODEL_NAME,
    QUERY_SIMILARITY_TOP_K,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

NO_ANSWER_MESSAGE = (
    "The provided regulatory corpus does not contain enough information to "
    "answer this question."
)

SYSTEM_PROMPT = (
    "You are a compliance research assistant answering questions about UK "
    "financial regulation using ONLY the numbered context excerpts provided "
    "below. Cite the excerpt number(s) supporting each claim inline, like "
    "[1] or [1][3]. Do not use knowledge from outside the provided context, "
    "and do not guess. If the context does not contain enough information "
    f'to answer, respond with exactly: "{NO_ANSWER_MESSAGE}"'
)


class SourceCitation(BaseModel):
    index: int
    file_name: str
    similarity_score: float
    text_excerpt: str


class QueryResult(BaseModel):
    question: str
    answer: str
    sources: list[SourceCitation]


def load_index() -> VectorStoreIndex:
    Settings.embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)
    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    try:
        collection = client.get_collection(CHROMA_COLLECTION_NAME)
    except Exception as e:
        raise RuntimeError(
            f"Chroma collection '{CHROMA_COLLECTION_NAME}' not found at "
            f"{CHROMA_PERSIST_DIR}. Run `python -m src.ingestion.ingest` first."
        ) from e
    if collection.count() == 0:
        raise RuntimeError(
            "Chroma collection is empty. Run `python -m src.ingestion.ingest` first."
        )
    vector_store = ChromaVectorStore(chroma_collection=collection)
    return VectorStoreIndex.from_vector_store(vector_store)


def _build_context(nodes) -> str:
    parts = []
    for i, node in enumerate(nodes, start=1):
        file_name = node.metadata.get("file_name", "unknown")
        parts.append(f"[{i}] (Source: {file_name})\n{node.text}")
    return "\n\n".join(parts)


class QueryEngine:
    def __init__(self, similarity_top_k: int = QUERY_SIMILARITY_TOP_K):
        self._index = load_index()
        self._retriever = self._index.as_retriever(similarity_top_k=similarity_top_k)
        self._client = anthropic.Anthropic()

    def query(self, question: str) -> QueryResult:
        nodes = self._retriever.retrieve(question)
        if not nodes:
            return QueryResult(question=question, answer=NO_ANSWER_MESSAGE, sources=[])

        context = _build_context(nodes)
        user_message = f"Context:\n{context}\n\nQuestion: {question}"

        response = self._client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        answer_text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )

        sources = [
            SourceCitation(
                index=i,
                file_name=node.metadata.get("file_name", "unknown"),
                similarity_score=node.score or 0.0,
                text_excerpt=node.text[:300],
            )
            for i, node in enumerate(nodes, start=1)
        ]

        return QueryResult(question=question, answer=answer_text, sources=sources)


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")

    question = " ".join(sys.argv[1:]) or "What outcomes must firms deliver under the Consumer Duty?"
    engine = QueryEngine()
    result = engine.query(question)
    print("Q:", result.question)
    print("A:", result.answer)
    print("\nSources:")
    for s in result.sources:
        print(f"  [{s.index}] {s.file_name} (score={s.similarity_score:.3f})")
