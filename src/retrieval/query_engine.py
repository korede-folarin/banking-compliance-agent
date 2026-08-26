import logging
import re

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
    CONFIDENCE_THRESHOLD,
    EMBED_MODEL_NAME,
    QUERY_SIMILARITY_TOP_K,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

NO_ANSWER_MESSAGE = (
    "The provided regulatory corpus does not contain enough information to "
    "answer this question."
)


def _build_system_prompt(corpus_description: str, no_answer_message: str) -> str:
    return (
        f"You are a compliance research assistant answering questions about "
        f"{corpus_description} using ONLY the numbered context excerpts "
        "provided below. Cite the excerpt number(s) supporting each claim "
        "inline, like [1] or [1][3]. Do not use knowledge from outside the "
        "provided context, and do not guess. If the context does not "
        f'contain enough information to answer, respond with exactly: '
        f'"{no_answer_message}"'
    )


SYSTEM_PROMPT = _build_system_prompt("UK financial regulation", NO_ANSWER_MESSAGE)


class SourceCitation(BaseModel):
    index: int
    file_name: str
    similarity_score: float
    text_excerpt: str


class QueryResult(BaseModel):
    question: str
    answer: str
    sources: list[SourceCitation]
    confidence: float
    needs_human_review: bool


def _extract_cited_indices(answer_text: str) -> set[int]:
    return {int(n) for n in re.findall(r"\[(\d+)\]", answer_text)}


def compute_confidence(sources: list[SourceCitation], cited_indices: set[int]) -> float:
    """
    Deterministic confidence: the MINIMUM similarity score among the
    sources actually cited inline (via [n] markers) in the answer, not
    all retrieved candidates and not anything the LLM self-reports. Same
    "minimum, not average" reasoning as the compliance layer
    (src/agent/compliance.py): a claim resting on one weakly-matched
    citation shouldn't count as well-supported just because the answer
    also cites stronger ones elsewhere.
    """
    cited = [s for s in sources if s.index in cited_indices]
    if not cited:
        return 0.0
    return min(s.similarity_score for s in cited)


def load_index(collection_name: str = CHROMA_COLLECTION_NAME) -> VectorStoreIndex:
    Settings.embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)
    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    try:
        collection = client.get_collection(collection_name)
    except Exception as e:
        raise RuntimeError(
            f"Chroma collection '{collection_name}' not found at "
            f"{CHROMA_PERSIST_DIR}. Run `python -m src.ingestion.ingest` first."
        ) from e
    if collection.count() == 0:
        raise RuntimeError(
            f"Chroma collection '{collection_name}' is empty. Run "
            "`python -m src.ingestion.ingest` first."
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
    def __init__(
        self,
        similarity_top_k: int = QUERY_SIMILARITY_TOP_K,
        collection_name: str = CHROMA_COLLECTION_NAME,
        corpus_description: str = "UK financial regulation",
        no_answer_message: str = NO_ANSWER_MESSAGE,
    ):
        self._index = load_index(collection_name=collection_name)
        self._retriever = self._index.as_retriever(similarity_top_k=similarity_top_k)
        self._client = anthropic.Anthropic()
        self._no_answer_message = no_answer_message
        self._system_prompt = _build_system_prompt(corpus_description, no_answer_message)

    def query(self, question: str) -> QueryResult:
        nodes = self._retriever.retrieve(question)
        if not nodes:
            return QueryResult(
                question=question,
                answer=self._no_answer_message,
                sources=[],
                confidence=0.0,
                needs_human_review=True,
            )

        context = _build_context(nodes)
        user_message = f"Context:\n{context}\n\nQuestion: {question}"

        response = self._client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1024,
            system=self._system_prompt,
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

        # Deterministic confidence signal, same computation as the
        # compliance layer's P4-02 (minimum similarity of cited sources).
        # Deliberately NOT enforced as a hard override here the way P4-02
        # enforces it for compliance judgments: doing so was tried and
        # empirically caused a real regression — a plainly answerable,
        # on-topic question ("What is the price and value outcome?",
        # answered by content literally titled "The price and value
        # outcome") got refused, because its retrieval scores (0.55-0.60)
        # sit below CONFIDENCE_THRESHOLD, which ARCHITECTURE.md already
        # documents as never validated against real evaluation data. The
        # signal is exposed so callers have it; forcing enforcement on an
        # untuned threshold would trade a working capability for false
        # consistency. See ARCHITECTURE.md "Uncertainty handling" for the
        # full account.
        confidence = compute_confidence(sources, _extract_cited_indices(answer_text))
        needs_human_review = confidence < CONFIDENCE_THRESHOLD or answer_text.strip() == self._no_answer_message

        return QueryResult(
            question=question,
            answer=answer_text,
            sources=sources,
            confidence=confidence,
            needs_human_review=needs_human_review,
        )


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
