import os
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma
from app.core.config import settings

print(f"[chroma] Connecting to existing SQLite ChromaDB at: {settings.CHROMA_DB_DIR}")

# Initialize the embedding model
embedding_model = OllamaEmbeddings(model=settings.EMBEDDING_MODEL)

# Attach to the existing persisted collection
vector_db = Chroma(
    collection_name=settings.CHROMA_COLLECTION,
    embedding_function=embedding_model,
    persist_directory=settings.CHROMA_DB_DIR
)

# Fail loudly at import time instead of silently returning zero matches:
# a wrong collection name makes Chroma create an empty collection on the fly.
_doc_count = vector_db._collection.count()
print(f"[chroma] Collection '{settings.CHROMA_COLLECTION}' loaded with {_doc_count} documents")
if _doc_count == 0:
    raise RuntimeError(
        f"ChromaDB collection '{settings.CHROMA_COLLECTION}' at {settings.CHROMA_DB_DIR} is empty. "
        "Check CHROMA_COLLECTION / CHROMA_DB_DIR in app/core/config.py."
    )

def retrieve_similar_cases(query: str, top_k: int = 3):
    """Fetches top-k similar complaints directly from disk."""
    results = vector_db.similarity_search(query, k=top_k)
    return results