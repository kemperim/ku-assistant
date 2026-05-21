"""
RAG Engine: orchestrates document sync, indexing, and QA.
"""

import logging
import asyncio
from pathlib import Path
from typing import List, Dict, Any

import aiohttp

from .config import settings
from .gdrive import sync_gdrive
from .parser import document_to_chunks, TextChunk
from .vectorstore import VectorStore, VectorChunk

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — ИИ-помощник приёмной комиссии университета. 
Твоя задача — отвечать на вопросы абитуриентов точно, кратко и по делу.

Правила:
1. Отвечай ТОЛЬКО на основе предоставленного контекста из документов.
2. Если информации в контексте нет — скажи: "В имеющихся документах такой информации не нашлось. Пожалуйста, обратитесь в приёмную комиссию напрямую."
3. Не придумывай факты, даты, условия поступления или цифры.
4. Отвечай на том же языке, на котором задан вопрос (русский или казахский).
5. Будь вежлив и чёток. Без лишних слов.
6. НИКОГДА не упоминай названия файлов, документов или их источники в ответе. Просто отвечай на вопрос как живой консультант.
7. Не пиши фразы вроде "согласно документу", "в файле указано", "как написано в PDF" и подобные.

"""


class RAGEngine:
    def __init__(self):
        self.vectorstore = VectorStore(
            store_path=settings.VECTORSTORE_PATH,
            ollama_url=settings.OLLAMA_BASE_URL,
            embed_model=settings.OLLAMA_EMBED_MODEL,
        )
        self._docs_indexed: Dict[str, int] = {}  # filename -> chunk count
        self._initialized = False

    async def initialize(self):
        """Load existing index or build from local docs."""
        loaded = self.vectorstore.load()
        if loaded:
            logger.info("Loaded existing vector store from disk.")
            for chunk in self.vectorstore.chunks:
                self._docs_indexed[chunk.source] = self._docs_indexed.get(chunk.source, 0) + 1
        
        if settings.AUTO_SYNC_ON_START:
            await self.sync_documents(force=False)
        
        self._initialized = True

    # ------------------------------------------------------------------ #
    # Document sync & indexing                                             #
    # ------------------------------------------------------------------ #

    async def sync_documents(self, force: bool = False) -> Dict[str, Any]:
        """Download from Google Drive and index new documents."""
        result = {"downloaded": 0, "indexed": 0, "skipped": 0, "errors": []}

        # Download from Google Drive
        if settings.GDRIVE_IDS:
            try:
                downloaded_paths = await sync_gdrive(
                    gdrive_ids=settings.GDRIVE_IDS,
                    docs_path=settings.DOCS_PATH,
                    service_account_json=settings.GDRIVE_SERVICE_ACCOUNT_JSON,
                )
                result["downloaded"] = len(downloaded_paths)
                logger.info(f"Downloaded {len(downloaded_paths)} files from Google Drive")
            except Exception as e:
                logger.error(f"Google Drive sync failed: {e}")
                result["errors"].append(str(e))
        else:
            logger.info("No GDRIVE_IDS configured, using local docs only.")

        # Index documents from docs folder
        docs_dir = Path(settings.DOCS_PATH)
        docs_dir.mkdir(parents=True, exist_ok=True)
        
        supported_exts = {".pdf", ".docx", ".doc", ".txt"}
        all_docs = [f for f in docs_dir.iterdir() if f.suffix.lower() in supported_exts]
        
        if not all_docs:
            logger.warning(f"No documents found in {docs_dir}")
            return result

        if force:
            logger.info("Force re-indexing: clearing vector store")
            self.vectorstore.clear()
            self._docs_indexed = {}

        indexed_sources = set(self.vectorstore.get_indexed_sources())
        to_index = [f for f in all_docs if f.name not in indexed_sources]

        if not to_index:
            logger.info("All documents already indexed.")
            result["skipped"] = len(all_docs)
            return result

        logger.info(f"Indexing {len(to_index)} new documents...")
        for doc_path in to_index:
            try:
                chunks = document_to_chunks(
                    doc_path,
                    chunk_size=settings.CHUNK_SIZE,
                    overlap=settings.CHUNK_OVERLAP,
                )
                if not chunks:
                    logger.warning(f"No chunks extracted from {doc_path.name}")
                    result["skipped"] += 1
                    continue

                vector_chunks = [
                    VectorChunk(
                        text=c.text,
                        source=c.source,
                        page=c.page,
                        chunk_idx=c.chunk_idx,
                    )
                    for c in chunks
                ]
                await self.vectorstore.add_chunks(vector_chunks)
                self._docs_indexed[doc_path.name] = len(vector_chunks)
                result["indexed"] += 1
                logger.info(f"Indexed {doc_path.name}: {len(vector_chunks)} chunks")
            except Exception as e:
                logger.error(f"Error indexing {doc_path.name}: {e}")
                result["errors"].append(f"{doc_path.name}: {str(e)}")

        if result["indexed"] > 0:
            self.vectorstore.save()

        return result

    # ------------------------------------------------------------------ #
    # QA                                                                   #
    # ------------------------------------------------------------------ #

    async def answer(self, question: str, top_k: int = 5) -> Dict[str, Any]:
        """Retrieve relevant chunks and generate answer via Groq."""
        # Retrieve
        results = await self.vectorstore.search(question, top_k=top_k)

        if not results:
            return {
                "question": question,
                "answer": "К сожалению, в загруженных документах информации по вашему вопросу не найдено. "
                          "Пожалуйста, обратитесь в приёмную комиссию напрямую.",
                "sources": [],
            }

        # Build context
        context_parts = []
        sources = []
        seen_sources = set()
        for chunk, score in results:
            context_parts.append(f"[Источник: {chunk.source}, стр. {chunk.page}]\n{chunk.text}")
            src_key = f"{chunk.source}:{chunk.page}"
            if src_key not in seen_sources:
                seen_sources.add(src_key)
                sources.append({
                    "file": chunk.source,
                    "page": chunk.page,
                    "score": round(score, 4),
                    "preview": chunk.text[:200] + "..." if len(chunk.text) > 200 else chunk.text,
                })

        context = "\n\n---\n\n".join(context_parts)
        user_message = f"Контекст из документов:\n{context}\n\nВопрос абитуриента: {question}"

        # Call Groq
        answer_text = await self._call_groq(user_message)
        return {
            "question": question,
            "answer": answer_text,
            "sources": sources,
        }

    async def _call_groq(self, user_message: str) -> str:
        """Call Groq API."""
        if not settings.GROQ_API_KEY:
            return "Ошибка: GROQ_API_KEY не настроен. Пожалуйста, добавьте ключ в файл .env"

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.GROQ_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": settings.GROQ_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "max_tokens": settings.GROQ_MAX_TOKENS,
            "temperature": settings.GROQ_TEMPERATURE,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, headers=headers, json=payload,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(f"Groq error {resp.status}: {body}")
                        return f"Ошибка LLM (код {resp.status}). Проверьте GROQ_API_KEY и модель."
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"Groq API call failed: {e}")
            return f"Не удалось получить ответ от LLM: {e}"

    # ------------------------------------------------------------------ #
    # Status                                                               #
    # ------------------------------------------------------------------ #

    async def get_status(self) -> Dict[str, Any]:
        return {
            "status": "ready" if self._initialized else "initializing",
            "docs_count": len(self._docs_indexed),
            "chunks_count": len(self.vectorstore.chunks),
            "indexed_files": list(self._docs_indexed.keys()),
            "embed_model": settings.OLLAMA_EMBED_MODEL,
            "llm_model": settings.GROQ_MODEL,
            "gdrive_configured": bool(settings.GDRIVE_IDS),
        }
