#!/usr/bin/env python3
"""Build FAISS knowledge base index from runbooks and incidents."""

import glob
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS

# Prefer langchain_ollama if available, fallback to langchain_community
try:
    from langchain_ollama import OllamaEmbeddings
except ImportError:
    from langchain_community.embeddings import OllamaEmbeddings

load_dotenv()

KB_INDEX_DIR = os.getenv("KB_INDEX_DIR", "kb_index")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")


def load_runbook_documents() -> list[Document]:
    """Load and chunk runbooks by markdown headings and character count."""
    runbook_files = glob.glob(os.path.join("data", "runbooks", "*.md"))
    documents = []

    headers_to_split = [
        ("#", "Header 1"),
        ("##", "Header 2"),
    ]
    header_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split)
    char_splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)

    for file_path in runbook_files:
        path = Path(file_path)
        stem = path.stem  # e.g., 'db-lock'
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        header_splits = header_splitter.split_text(content)
        chunks = char_splitter.split_documents(header_splits)

        for i, chunk in enumerate(chunks):
            chunk_id = f"rb-{stem}-{i+1}"
            metadata = {
                "id": chunk_id,
                "category": stem,
                "source_type": "runbook",
                "file": str(path.as_posix()),
            }
            # Keep header info in metadata if present
            if "Header 1" in chunk.metadata:
                metadata["title"] = chunk.metadata["Header 1"]
            if "Header 2" in chunk.metadata:
                metadata["section"] = chunk.metadata["Header 2"]

            doc = Document(page_content=chunk.page_content, metadata=metadata, id=chunk_id)
            documents.append(doc)

    print(f"Loaded {len(documents)} runbook chunks from {len(runbook_files)} runbooks.")
    return documents


def load_incident_documents() -> list[Document]:
    """Load past incidents as individual documents."""
    incidents_path = os.path.join("data", "incidents.json")
    if not os.path.exists(incidents_path):
        print(f"Warning: {incidents_path} not found.")
        return []

    with open(incidents_path, "r", encoding="utf-8") as f:
        incidents = json.load(f)

    documents = []
    for inc in incidents:
        inc_id = inc.get("id", "INC-UNKNOWN")
        content = (
            f"Incident ID: {inc_id}\n"
            f"Category: {inc.get('category', '')}\n"
            f"Symptom: {inc.get('symptom', '')}\n"
            f"Root Cause: {inc.get('root_cause', '')}\n"
            f"Fix: {inc.get('fix', '')}\n"
            f"Owner Team: {inc.get('owner_team', '')}\n"
            f"Resolution Minutes: {inc.get('resolution_minutes', 0)}"
        )
        metadata = {
            "id": inc_id,
            "category": inc.get("category", ""),
            "source_type": "incident",
            "file": "data/incidents.json",
        }
        doc = Document(page_content=content, metadata=metadata, id=inc_id)
        documents.append(doc)

    print(f"Loaded {len(documents)} incident documents from {incidents_path}.")
    return documents


def build_index():
    """Build and persist the FAISS knowledge base index."""
    print(f"Initializing embedding model '{EMBED_MODEL}' via Ollama...")
    embeddings = OllamaEmbeddings(model=EMBED_MODEL)

    runbook_docs = load_runbook_documents()
    incident_docs = load_incident_documents()
    all_docs = runbook_docs + incident_docs

    if not all_docs:
        print("Error: No documents found to index.")
        sys.exit(1)

    ids = [doc.id for doc in all_docs]
    print(f"Embedding {len(all_docs)} total documents into FAISS index...")

    vectorstore = FAISS.from_documents(all_docs, embeddings, ids=ids)

    os.makedirs(KB_INDEX_DIR, exist_ok=True)
    vectorstore.save_local(KB_INDEX_DIR)
    print(f"Knowledge base index successfully saved to '{KB_INDEX_DIR}'.")


if __name__ == "__main__":
    build_index()
