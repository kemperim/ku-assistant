# 🎓 RAG Abitur Agent

ИИ-агент для ответов на вопросы абитуриентов на основе документов приёмной комиссии.

## Стек

| Компонент | Технология |
|-----------|-----------|
| LLM | **Groq API** (llama-3.3-70b-versatile) |
| Эмбеддинги | **Ollama** (nomic-embed-text) |
| Векторный поиск | **FAISS** (cosine similarity) |
| Документы | **Google Drive** (PDF / DOCX / TXT) |
| Бэкенд | **FastAPI** |
| Деплой | **Docker Compose** |

---

## ⚡ Быстрый старт (5 минут)

### 1. Клонировать / распаковать проект

```bash
cd rag-abitur
```

### 2. Заполнить конфигурацию

```bash
cp .env.example .env
nano .env    # или любой редактор
```

Минимально нужно заполнить:

```env
GROQ_API_KEY=gsk_...          # https://console.groq.com → API Keys
GDRIVE_IDS=1ABC...,1XYZ...    # ID папок/файлов с Google Drive
```

### 3. Запустить

```bash
chmod +x deploy.sh
./deploy.sh
```

Скрипт сам:
- проверит Docker
- соберёт образ
- запустит все контейнеры
- загрузит модель эмбеддингов в Ollama
- дождётся готовности сервиса

### 4. Открыть интерфейс

```
http://localhost:8000
```

---

## 🗂️ Структура проекта

```
rag-abitur/
├── app/
│   ├── main.py          # FastAPI приложение, эндпоинты
│   ├── config.py        # Настройки (читаются из .env)
│   ├── rag_engine.py    # Оркестратор: sync → index → answer
│   ├── vectorstore.py   # FAISS + Ollama embeddings
│   ├── parser.py        # Парсинг PDF / DOCX / TXT
│   └── gdrive.py        # Скачивание с Google Drive
├── static/
│   └── index.html       # Веб-интерфейс чата
├── nginx/
│   └── nginx.conf       # Reverse proxy (production)
├── cli.py               # CLI для управления индексом
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example         # Шаблон конфигурации
└── deploy.sh            # Скрипт быстрого деплоя
```

---

## 🔑 Получение ключей

### Groq API Key

1. Зайдите на [console.groq.com](https://console.groq.com)
2. Регистрация → **API Keys** → **Create API Key**
3. Скопируйте ключ вида `gsk_...` в `.env`

### Google Drive — публичные файлы

Самый простой вариант — сделать папку/файл публичными:

1. ПКМ на папку → **Открыть доступ** → **Все у кого есть ссылка**
2. Скопируйте ссылку: `https://drive.google.com/drive/folders/`**`1ABC123XYZ`**
3. Вставьте **только ID** (часть после `/folders/`) в `GDRIVE_IDS`

Пример с несколькими ID:
```env
GDRIVE_IDS=1ABC123XYZ,1DEF456UVW,1GHI789RST
```

### Google Drive — приватные файлы (Service Account)

1. Откройте [Google Cloud Console](https://console.cloud.google.com)
2. Создайте проект → включите **Google Drive API**
3. **IAM → Service Accounts** → Create → скачайте JSON-ключ
4. Поделитесь нужными папками Drive с email сервисного аккаунта (`...@....iam.gserviceaccount.com`)
5. Укажите путь к JSON в `.env`:

```env
GDRIVE_SERVICE_ACCOUNT_JSON=/app/secrets/service_account.json
```

И пробросьте файл в контейнер через `docker-compose.yml`:
```yaml
volumes:
  - ./secrets:/app/secrets:ro
```

---

## 📡 API эндпоинты

| Метод | URL | Описание |
|-------|-----|----------|
| `GET` | `/` | Веб-интерфейс |
| `POST` | `/ask` | Задать вопрос |
| `POST` | `/sync` | Синхронизировать документы с Drive |
| `GET` | `/status` | Состояние индекса |
| `GET` | `/health` | Health check |
| `GET` | `/docs` | Swagger UI |

### Пример запроса `/ask`

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Какие документы нужны для поступления?", "top_k": 5}'
```

Ответ:
```json
{
  "question": "Какие документы нужны для поступления?",
  "answer": "Для поступления необходимо предоставить...",
  "sources": [
    {
      "file": "pravila_postupleniya_2024.pdf",
      "page": 3,
      "score": 0.892,
      "preview": "Список необходимых документов: 1. Аттестат..."
    }
  ]
}
```

---

## 🛠️ CLI — управление индексом

Внутри контейнера или локально (с установленными зависимостями):

```bash
# Синхронизировать Drive и индексировать новые файлы
docker compose exec app python cli.py sync

# Полная переиндексация (если изменились документы)
docker compose exec app python cli.py sync --force

# Статус индекса
docker compose exec app python cli.py status

# Добавить локальный файл вручную
docker compose exec app python cli.py add /path/to/document.pdf

# Очистить индекс
docker compose exec app python cli.py clear

# Тестовый вопрос без браузера
docker compose exec app python cli.py ask "Когда начинается приём документов?"
```

---

## ⚙️ Все параметры `.env`

```env
# Groq LLM
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile   # или mixtral-8x7b-32768
GROQ_MAX_TOKENS=1024
GROQ_TEMPERATURE=0.2                  # 0.0 = детерминировано, 1.0 = творчески

# Google Drive
GDRIVE_IDS=                           # ID папок/файлов через запятую
GDRIVE_SERVICE_ACCOUNT_JSON=          # путь или JSON для приватного доступа

# Ollama
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_EMBED_MODEL=nomic-embed-text   # или mxbai-embed-large

# RAG
CHUNK_SIZE=800                        # символов в одном чанке
CHUNK_OVERLAP=100                     # перекрытие между чанками

# Приложение
AUTO_SYNC_ON_START=true               # синхронизировать Drive при старте
APP_TITLE=Приёмная комиссия — ИИ-помощник
```

---

## 🚀 Production деплой с Nginx

```bash
docker compose --profile production up -d
```

Nginx будет доступен на порту 80 и проксировать запросы к приложению.

Для HTTPS добавьте Certbot или настройте SSL в `nginx/nginx.conf`.

---

## 🐛 Частые проблемы

**Ollama не запускается**
```bash
docker compose logs ollama
# Если нет GPU: убедитесь что секция deploy закомментирована в docker-compose.yml
```

**Модель эмбеддингов не загружается**
```bash
docker compose exec ollama ollama pull nomic-embed-text
```

**Groq возвращает ошибку 401**
- Проверьте `GROQ_API_KEY` в `.env`
- Убедитесь что ключ активен на console.groq.com

**Документы не скачиваются с Drive**
- Проверьте что папка/файл открыты ("Все у кого есть ссылка")
- Убедитесь что ID в `GDRIVE_IDS` без пробелов
- Попробуйте Service Account для приватных файлов

**Индекс пуст после перезапуска**
- Volumes сохраняются между запусками, но при `docker compose down -v` очищаются
- Для надёжности сделайте: `docker compose down` (без `-v`)
