from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.analyze_router import router as analyze_router

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Agentic RAG triage API powered by LangGraph, LangChain, FastAPI, ChromaDB (SQLite), and Llama 3.2."
)

# Allow the React dev server (Vite) to call this API from the browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(analyze_router, prefix="/api/v1")

@app.get("/health")
def health_check():
    return {"status": "online", "database": "ChromaDB SQLite Connected"}