import os

class Settings:
    PROJECT_NAME: str = "Cybercrime Triage AI API"
    VERSION: str = "1.0.0"
    
    # Path pointing to data/ChromaDB on disk
    BASE_DIR: str = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    CHROMA_DB_DIR: str = os.path.join(BASE_DIR, "data", "ChromaDB_Indian")
    # Collection the ingest script wrote into (LangChain's default name)
    CHROMA_COLLECTION: str = "langchain"

    EMBEDDING_MODEL: str = "nomic-embed-text"
    LLM_MODEL: str = "llama3.2"

settings = Settings()