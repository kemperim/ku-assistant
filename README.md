# RAG Abitur Agent

ИИ-помощник абитуриента для Северо-Казахстанского университета имени Манаша Козыбаева. Проект отвечает на вопросы по официальной базе знаний, собранной с `ku.edu.kz` и `apply.ku.edu.kz`.

## Стек

| Компонент | Технология |
|-----------|------------|
| Backend | FastAPI |
| LLM | Groq API |
| Embeddings | Ollama `nomic-embed-text` |
| Vector search | FAISS |
| Documents | `docs/*.txt`, опционально Google Drive |
| Deploy | Docker Compose |

## Быстрый Запуск

1. Создайте `.env`:

```bash
cp .env.example .env
```

2. Укажите в `.env` ключ Groq:

```env
GROQ_API_KEY=gsk_...
```

3. Запустите проект:

```bash
docker compose up --build
```

При первом запуске Docker Compose поднимет:

- `ollama` для эмбеддингов;
- `ollama-init` для загрузки модели `nomic-embed-text`;
- `app` с FastAPI-приложением.

4. Откройте интерфейс:

```text
http://localhost:8000
```

## Индексация Базы

После запуска пересоберите индекс:

```bash
curl -X POST http://localhost:8000/sync \
  -H "Content-Type: application/json" \
  -d "{\"force\":true}"
```

Проверить статус:

```bash
curl http://localhost:8000/status
```

Ожидаемо в базе:

- `docs_count`: `2`;
- `chunks_count`: больше `0`.

## База Знаний

В рабочей базе остались только официальные материалы KU:

- `docs/00_ku_official_reference.txt` - подготовленная справка с ключевыми фактами: факультеты, программы, стоимость, контакты, стипендии, общежития.
- `docs/ku_site_crawl.txt` - выгрузка 120 публичных страниц с `ku.edu.kz` и `apply.ku.edu.kz`.

## API

| Метод | URL | Описание |
|-------|-----|----------|
| `GET` | `/` | Веб-интерфейс |
| `POST` | `/ask` | Задать вопрос |
| `POST` | `/sync` | Синхронизировать и проиндексировать документы |
| `GET` | `/status` | Статус индекса |
| `GET` | `/health` | Health check |
| `GET` | `/docs` | Swagger UI |

Пример:

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"Сколько факультетов в университете?\",\"top_k\":5}"
```

## Структура

```text
rag-abitur/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── rag_engine.py
│   ├── vectorstore.py
│   ├── parser.py
│   └── gdrive.py
├── docs/
│   ├── 00_ku_official_reference.txt
│   └── ku_site_crawl.txt
├── static/
│   └── index.html
├── tools/
│   └── scrape_ku.py
├── nginx/
│   └── nginx.conf
├── cli.py
├── Dockerfile
├── docker-compose.yml
├── deploy.sh
├── requirements.txt
├── .env.example
├── PROJECT_PASSPORT.md
└── GITHUB_CHECKLIST.md
```

## CLI В Контейнере

```bash
docker compose exec app python cli.py status
docker compose exec app python cli.py sync --force
docker compose exec app python cli.py ask "Какая стоимость обучения на Информационные системы?"
```

## Обновление Данных KU

Скрипт выгрузки официальных страниц:

```bash
docker compose exec app python tools/scrape_ku.py --max-pages 120 --output /data/docs/ku_site_crawl.txt
```

После обновления:

```bash
docker compose exec app python cli.py sync --force
```




