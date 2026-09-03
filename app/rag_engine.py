"""
RAG Engine: orchestrates document sync, indexing, and QA.
"""

import logging
import asyncio
import hashlib
import re
from pathlib import Path
from typing import List, Dict, Any, Tuple

import aiohttp

from .config import settings
from .gdrive import sync_gdrive
from .parser import document_to_chunks, TextChunk
from .vectorstore import VectorStore, VectorChunk

logger = logging.getLogger(__name__)

CURATED_SOURCE_RE = re.compile(r"^\d{2}_ku_.+\.txt$")

ADMISSION_CONTACTS = (
    "Приёмная комиссия Kozybayev University:\n"
    "• телефон: +7 (7152) 49-30-37;\n"
    "• call-центр: +7 (7152) 35-00-09;\n"
    "• электронная почта: admission@ku.edu.kz."
)

TOPIC_ROUTES = {
    "01_ku_ob_universitete.txt": (
        "университет", "вуз", "ску", "kozybayev", "козыбаев", "история", "миссия",
    ),
    "02_ku_kontakty_i_upravlenie.txt": (
        "контакт", "телефон", "почта", "email", "адрес", "где находится", "приемн", "приёмн",
    ),
    "03_ku_fakultety_i_kampus.txt": (
        "факультет", "институт", "кафедр", "кампус", "корпус", "структур",
    ),
    "04_ku_postuplenie.txt": (
        "поступ", "документ", "зачисл", "грант", "ент", "порог", "срок", "прием", "приём",
    ),
    "05_ku_bakalavriat_programmy_i_ceny.txt": (
        "бакалавр", "программ", "специальност", "профильн", "предмет", "стоим", "цен", "оплат",
    ),
    "06_ku_magistratura_i_doktorantura.txt": (
        "магистр", "докторан", "phd", "резидент", "послевуз", "комплексн", "ielts", "toefl",
    ),
    "07_ku_studentam_stipendii_i_obshchezhitiya.txt": (
        "общежит", "стипенд", "студент", "заселен", "льгот", "вакантн", "клуб",
    ),
    "08_ku_praktika_karera_i_vozmozhnosti.txt": (
        "практик", "работ", "трудоустр", "карьер", "отработ", "военн", "двудиплом", "курс",
    ),
    "09_ku_nauka_i_innovacii.txt": (
        "наук", "исслед", "проект", "лаборатор", "инновац", "диссертац", "ai sana", "ии",
    ),
    "10_ku_mezhdunarodnye_programmy.txt": (
        "международ", "мобильност", "обмен", "зарубеж", "иностран", "партнер", "партнёр", "двудиплом",
    ),
}

SYSTEM_PROMPT = """Ты — KU Assistant, доброжелательный сотрудник приёмной комиссии Северо-Казахстанского университета имени Манаша Козыбаева.
Помогай абитуриентам и студентам, используя только факты из переданного контекста.

Правила ответа:
1. Сначала дай короткий прямой ответ, затем добавь только полезные подробности. Не повторяй вопрос и не используй канцелярское вступление.
2. Используй все релевантные фрагменты совместно и объединяй сведения, относящиеся к одному вопросу.
3. Не смешивай бакалавриат, магистратуру, докторантуру и резидентуру. Не переноси цену, срок, предмет ЕНТ или условие одной программы на другую.
4. Не делай вывод о наличии набора только по упоминанию программы или факультета. Не называй приблизительную цену точной и не смешивай сведения разных учебных годов.
5. Если вопрос неоднозначен и для точного ответа не хватает уровня обучения, программы или учебного года, задай один короткий уточняющий вопрос. Не задавай уточнение, если ответ однозначно следует из контекста.
6. Не придумывай факты, даты, документы, условия, контакты или цифры. Если точных сведений нет, честно скажи об этом и заверши ответ контактами приёмной комиссии из контекста.
7. Если сведения противоречат друг другу, коротко назови расхождение и предложи уточнить актуальное значение в приёмной комиссии.
8. Можно рекомендовать программы только на основании интересов пользователя, профильных предметов ЕНТ и программ из контекста. Предложи не более пяти вариантов, кратко объясни каждый и не обещай поступление.
9. Отвечай на языке последнего вопроса: по-русски или по-казахски. Русский контекст можно перевести на казахский, не изменяя факты.
10. Для документов, этапов, цен, программ и контактов используй короткие списки. Для цены обязательно указывай программу, учебный год и сумму, если все эти данные известны.
11. Никогда не упоминай RAG, поиск, контекст, названия файлов, документы-источники или внутренние оценки релевантности. Не пиши «согласно документу», «в файле указано» и подобные фразы.
12. История диалога нужна только для понимания уточнений. Факты из истории не имеют приоритета над актуальным контекстом.

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

        current_hashes = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in all_docs
        }
        indexed_sources = set(self.vectorstore.get_indexed_sources())
        stored_hashes = self.vectorstore.source_hashes
        documents_changed = indexed_sources != set(current_hashes) or any(
            stored_hashes.get(name) != digest
            for name, digest in current_hashes.items()
        )
        if indexed_sources and documents_changed:
            logger.info("Document set changed; rebuilding vector store.")
            force = True

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
                added_count = await self.vectorstore.add_chunks(vector_chunks)
                if added_count == 0:
                    logger.warning(f"No embeddings created for {doc_path.name}")
                    result["errors"].append(
                        f"{doc_path.name}: не удалось создать эмбеддинги. Проверьте настройки индекса и попробуйте sync --force."
                    )
                    continue

                self._docs_indexed[doc_path.name] = added_count
                self.vectorstore.source_hashes[doc_path.name] = current_hashes[doc_path.name]
                result["indexed"] += 1
                logger.info(f"Indexed {doc_path.name}: {added_count} chunks")
            except Exception as e:
                logger.error(f"Error indexing {doc_path.name}: {e}")
                result["errors"].append(f"{doc_path.name}: {str(e)}")

        if result["indexed"] > 0:
            self.vectorstore.save()

        return result

    # ------------------------------------------------------------------ #
    # QA                                                                   #
    # ------------------------------------------------------------------ #

    async def answer(
        self,
        question: str,
        top_k: int = 8,
        history: List[Dict[str, str]] | None = None,
    ) -> Dict[str, Any]:
        """Retrieve relevant chunks and generate answer via Groq."""
        safe_history = self._sanitize_history(history or [])
        search_query = self._build_search_query(question, safe_history)
        retrieval_k = max(top_k, settings.RETRIEVAL_TOP_K)
        results = await self.vectorstore.search(search_query, top_k=retrieval_k)
        results = [
            (chunk, score)
            for chunk, score in results
            if score >= settings.MIN_RELEVANCE_SCORE
        ]
        results = self._rerank_results(question, results)[:top_k]

        if not results:
            return {
                "question": question,
                "answer": self._fallback_answer(question),
                "sources": [],
            }

        context_results = self._expand_with_neighbors(
            results,
            max_chunks=settings.MAX_CONTEXT_CHUNKS,
        )

        # Build context
        context_parts = []
        sources = []
        seen_sources = set()
        for chunk, score in context_results:
            label = "тематическая база KU" if CURATED_SOURCE_RE.match(chunk.source) else "официальная страница KU"
            context_parts.append(f"[{label}, раздел {chunk.page}]\n{chunk.text}")
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
        user_message = (
            f"Актуальный справочный контекст:\n{context}\n\n"
            f"Если точного ответа здесь нет, используй этот контактный блок:\n{ADMISSION_CONTACTS}\n\n"
            f"Последний вопрос пользователя: {question}"
        )

        # Call Groq
        answer_text = await self._call_groq(user_message, safe_history)
        answer_text = self._ensure_admission_contacts(answer_text)
        return {
            "question": question,
            "answer": answer_text,
            "sources": sources,
        }

    def _rerank_results(self, question: str, results: List[Tuple[VectorChunk, float]]) -> List[Tuple[VectorChunk, float]]:
        """Prioritize curated documents and the topic implied by the question."""
        query_terms = {
            token
            for token in re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9]+", question.lower())
            if len(token) >= 3
        }

        reranked = []
        for chunk, score in results:
            adjusted = float(score)
            text_lower = chunk.text.lower()

            if CURATED_SOURCE_RE.match(chunk.source):
                adjusted += 0.14

            route_terms = TOPIC_ROUTES.get(chunk.source, ())
            route_matches = sum(1 for term in route_terms if term in question.lower())
            adjusted += min(route_matches * 0.08, 0.24)

            if query_terms:
                matches = sum(1 for term in query_terms if term in text_lower)
                adjusted += min(matches * 0.015, 0.09)

            program_codes = re.findall(r"\b[678][A-Za-zА-Яа-я0-9]{5,}\b", question)
            if any(code.lower() in text_lower for code in program_codes):
                adjusted += 0.30

            reranked.append((chunk, adjusted))

        reranked.sort(key=lambda item: item[1], reverse=True)
        return reranked

    def _expand_with_neighbors(
        self,
        results: List[Tuple[VectorChunk, float]],
        max_chunks: int,
    ) -> List[Tuple[VectorChunk, float]]:
        """Add adjacent chunks when a relevant passage crosses a chunk boundary."""
        chunk_lookup = {
            (chunk.source, chunk.chunk_idx): chunk
            for chunk in self.vectorstore.chunks
        }
        expanded = []
        seen = set()

        for chunk, score in results:
            candidates = [(chunk, score)]
            for offset in (-1, 1):
                neighbor = chunk_lookup.get((chunk.source, chunk.chunk_idx + offset))
                if neighbor is not None:
                    candidates.append((neighbor, score - 0.01))

            for candidate, candidate_score in candidates:
                key = (candidate.source, candidate.chunk_idx)
                if key in seen:
                    continue
                seen.add(key)
                expanded.append((candidate, candidate_score))
                if len(expanded) >= max_chunks:
                    return expanded

        return expanded

    @staticmethod
    def _sanitize_history(history: List[Dict[str, str]]) -> List[Dict[str, str]]:
        cleaned = []
        for message in history[-4:]:
            role = message.get("role")
            content = str(message.get("content", "")).strip()
            if role in {"user", "assistant"} and content:
                cleaned.append({"role": role, "content": content[:6000]})
        return cleaned

    @staticmethod
    def _build_search_query(question: str, history: List[Dict[str, str]]) -> str:
        """Use recent user turns for short or referential follow-up questions."""
        lowered = question.lower()
        referential_terms = (
            "это", "эта", "этот", "эти", "там", "туда", "для неё", "для него",
            "оған", "осы", "сол", "онда", "ал ",
        )
        needs_history = len(question.split()) <= 8 or any(term in lowered for term in referential_terms)
        if not needs_history:
            return question

        prior_questions = [
            message["content"]
            for message in history
            if message["role"] == "user"
        ][-2:]
        return "\n".join([*prior_questions, question])

    @staticmethod
    def _fallback_answer(question: str) -> str:
        kazakh = bool(re.search(r"[ӘәҒғҚқҢңӨөҰұҮүҺһІі]", question))
        if kazakh:
            return (
                "Бұл сұрақ бойынша нақты ақпарат табылмады. Қабылдау комиссиясынан нақтылаңыз.\n\n"
                + ADMISSION_CONTACTS
            )
        return (
            "По этому вопросу точной информации не нашлось. Уточните её в приёмной комиссии.\n\n"
            + ADMISSION_CONTACTS
        )

    @staticmethod
    def _ensure_admission_contacts(answer: str) -> str:
        missing_information_markers = (
            "не нашлось", "не найден", "нет информации", "не указано", "неизвестн",
            "уточнить в приёмной", "уточнить в приемной", "обратитесь в приёмную",
            "обратитесь в приемную", "ақпарат табылмады", "қабылдау комиссиясынан",
        )
        lowered = answer.lower()
        needs_contacts = any(marker in lowered for marker in missing_information_markers)
        if needs_contacts and "admission@ku.edu.kz" not in lowered:
            return f"{answer.rstrip()}\n\n{ADMISSION_CONTACTS}"
        return answer

    async def _call_groq(
        self,
        user_message: str,
        history: List[Dict[str, str]] | None = None,
    ) -> str:
        """Call Groq API."""
        if not settings.GROQ_API_KEY:
            return "Ошибка: GROQ_API_KEY не настроен. Пожалуйста, добавьте ключ в файл .env"

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.GROQ_API_KEY}",
            "Content-Type": "application/json",
        }
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history or [])
        messages.append({"role": "user", "content": user_message})
        payload = {
            "model": settings.GROQ_MODEL,
            "messages": messages,
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
