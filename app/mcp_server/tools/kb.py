"""Knowledge Base tool for FAISS vector search and upsert."""

import os
import uuid
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS

try:
    from langchain_ollama import OllamaEmbeddings
except ImportError:
    from langchain_community.embeddings import OllamaEmbeddings

load_dotenv()

KB_INDEX_DIR = os.getenv("KB_INDEX_DIR", "kb_index")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

_vectorstore_instance: Optional[FAISS] = None


def get_embeddings() -> Any:
    """Return configured Ollama embeddings instance."""
    return OllamaEmbeddings(model=EMBED_MODEL)


def get_vectorstore(reload: bool = False) -> FAISS:
    """Load and cache the FAISS vectorstore from local directory."""
    global _vectorstore_instance
    if _vectorstore_instance is None or reload:
        if not os.path.exists(KB_INDEX_DIR):
            raise FileNotFoundError(
                f"Knowledge base index directory '{KB_INDEX_DIR}' not found. "
                "Run scripts/build_index.py first."
            )
        embeddings = get_embeddings()
        _vectorstore_instance = FAISS.load_local(
            KB_INDEX_DIR,
            embeddings,
            allow_dangerous_deserialization=True,
        )
    return _vectorstore_instance


def search_kb(
    query: str,
    k: int = 5,
    category: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Search the knowledge base for relevant documents.

    Args:
        query: Search string or incident description.
        k: Number of documents to return.
        category: Optional category filter (e.g., 'db-lock', 'queue-backlog').

    Returns:
        List of dicts with keys: 'id', 'text', 'score', 'metadata'.
    """
    vs = get_vectorstore()

    # If filtering by category, search for extra candidates to ensure k items after filtering
    search_k = k * 3 if category else k
    docs_and_scores = vs.similarity_search_with_score(query, k=search_k)

    results = []
    for doc, score in docs_and_scores:
        doc_category = doc.metadata.get("category")
        if category and doc_category != category:
            continue

        item_id = doc.metadata.get("id") or getattr(doc, "id", None) or "unknown"
        results.append({
            "id": item_id,
            "text": doc.page_content,
            "score": float(score),
            "metadata": doc.metadata,
        })
        if len(results) >= k:
            break

    return results


def kb_upsert(
    text: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Upsert a document into the knowledge base and persist to disk.

    Args:
        text: Document content to index.
        metadata: Associated metadata (source_type, category, file, etc.).

    Returns:
        Dict confirming upsert status and assigned id.
    """
    if metadata is None:
        metadata = {}

    doc_id = metadata.get("id") or f"upsert-{uuid.uuid4().hex[:8]}"
    metadata["id"] = doc_id
    if "source_type" not in metadata:
        metadata["source_type"] = "user_upsert"

    doc = Document(page_content=text, metadata=metadata, id=doc_id)
    vs = get_vectorstore()
    vs.add_documents([doc], ids=[doc_id])

    os.makedirs(KB_INDEX_DIR, exist_ok=True)
    vs.save_local(KB_INDEX_DIR)

    return {
        "id": doc_id,
        "status": "upserted",
        "metadata": metadata,
    }
