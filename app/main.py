import os
import logging
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from typing import Literal
from contextlib import asynccontextmanager

from .rag_engine import RAGEngine
from .config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

rag_engine: RAGEngine = None
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global rag_engine
    logger.info("Initializing RAG engine...")
    rag_engine = RAGEngine()
    await rag_engine.initialize()
    logger.info("RAG engine ready.")
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="Abitur RAG Agent",
    description="ИИ-агент для ответов на вопросы абитуриентов",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=6000)


class QuestionRequest(BaseModel):
    question: str
    top_k: int = 8
    history: list[ChatMessage] = Field(default_factory=list, max_length=4)


class QuestionResponse(BaseModel):
    answer: str
    sources: list[dict]
    question: str


class SyncRequest(BaseModel):
    force: bool = False


@app.get("/")
async def root():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@app.post("/ask", response_model=QuestionResponse)
async def ask_question(req: QuestionRequest):
    if not rag_engine:
        raise HTTPException(status_code=503, detail="RAG engine not initialized")
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    try:
        history = [message.model_dump() for message in req.history]
        result = await rag_engine.answer(
            req.question.strip(),
            top_k=max(1, min(req.top_k, 12)),
            history=history,
        )
        return result
    except Exception as e:
        logger.error(f"Error answering question: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sync")
async def sync_documents(req: SyncRequest):
    """Download docs from Google Drive and re-index"""
    if not rag_engine:
        raise HTTPException(status_code=503, detail="RAG engine not initialized")
    try:
        result = await rag_engine.sync_documents(force=req.force)
        return result
    except Exception as e:
        logger.error(f"Error syncing documents: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/status")
async def status():
    if not rag_engine:
        return {"status": "initializing", "docs_count": 0, "chunks_count": 0}
    return await rag_engine.get_status()


@app.get("/health")
async def health():
    return {"status": "ok"}
