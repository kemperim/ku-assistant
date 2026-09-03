# KU Assistant

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

При первом запуске приложение автоматически создаст индекс. Принудительная пересборка при необходимости:

```bash
curl -X POST http://localhost:8000/sync \
  -H "Content-Type: application/json" \
  -d "{\"force\":true}"
```

Проверить статус:

```bash
curl http://localhost:8000/status
```

Ожидаемо после завершения индексации:

- `docs_count`: `10`;
- `chunks_count`: около `270` (число может немного меняться после обновления данных).

## База Знаний

В рабочей базе находятся 10 очищенных тематических файлов: сведения об университете, контакты, факультеты, поступление, бакалавриат и цены, послевузовское обучение, студенческая поддержка, карьера, наука и международные программы. Карта файлов и правила дополнения находятся в `docs/README.md`.

Сырой краул хранится локально в `data/raw_ku_site` и не индексируется и не загружается в GitHub.

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
  -d "{\"question\":\"Сколько факультетов в университете?\",\"top_k\":8}"
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
│   ├── 01_ku_ob_universitete.txt
│   ├── ...
│   ├── 10_ku_mezhdunarodnye_programmy.txt
│   └── README.md
├── scripts/
│   └── organize_ku_docs.py
├── static/
│   └── index.html
├── tools/
│   └── scrape_ku.py
├── cli.py
├── Dockerfile
├── docker-compose.yml
├── deploy.sh
├── requirements.txt
└── .env.example
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
docker compose exec app python tools/scrape_ku.py --max-pages 120 --output /data/raw_ku_site/ku_site_crawl.txt
```

Очистить и разложить новый краул по темам:

```bash
docker compose exec app python scripts/organize_ku_docs.py --source /data/raw_ku_site --reference-dir /data/docs --output /data/docs
docker compose restart app
```

При обычном ручном дополнении TXT-файлов достаточно выполнить `docker compose restart app`: изменение будет найдено по хэшу, после чего индекс перестроится автоматически.

Для паспорта проекта используйте название: `KU Assistant`.
