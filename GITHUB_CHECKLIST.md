# Чеклист перед загрузкой на GitHub

## Обязательно проверить

- `.env` не должен попадать в репозиторий.
- В `.env.example` должны быть только пустые значения и примеры без реальных ключей.
- Папка `.venv/` не должна попадать в репозиторий.
- Папка `data/` не должна попадать в репозиторий: индекс можно пересоздать из документов.
- В `docs/` должны быть только официальные TXT-файлы базы KU.
- Тестовые PDF не должны попадать в репозиторий.

## Команды

```bash
git status --short
git add .
git commit -m "Prepare RAG Abitur MVP for submission"
git remote add origin <URL_ВАШЕГО_REPO>
git push -u origin main
```

## Docker-проверка

```bash
cp .env.example .env
nano .env
chmod +x deploy.sh
./deploy.sh
```

Открыть: http://localhost:8000
