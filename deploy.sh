#!/bin/bash
# ================================================================
#  deploy.sh — быстрый запуск RAG Abitur Agent на сервере
# ================================================================
set -e

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

info()    { echo -e "${GREEN}[✓]${NC} $1"; }
warning() { echo -e "${YELLOW}[!]${NC} $1"; }
error()   { echo -e "${RED}[✗]${NC} $1"; exit 1; }

echo ""
echo "  🎓  RAG Abitur Agent — Деплой"
echo "  ================================"
echo ""

# 1. Проверить Docker
command -v docker &>/dev/null || error "Docker не установлен. Установите: https://docs.docker.com/engine/install/"
command -v docker &>/dev/null && docker compose version &>/dev/null || \
  error "Docker Compose (v2) не найден. Установите плагин compose."
info "Docker найден: $(docker --version)"

# 2. Создать .env из примера
if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    warning ".env создан из .env.example — ОБЯЗАТЕЛЬНО заполните GROQ_API_KEY!"
    echo ""
    echo "  Откройте файл .env и укажите:"
    echo "    GROQ_API_KEY=gsk_..."
    echo "    GDRIVE_IDS=<ID папки или файла на Google Drive>  # опционально"
    echo ""
    read -p "  Нажмите Enter после редактирования .env, или Ctrl+C для отмены..." _
  else
    error "Файл .env.example не найден. Убедитесь, что вы в директории проекта."
  fi
else
  info ".env уже существует"
fi

# 3. Проверить GROQ_API_KEY
source .env 2>/dev/null || true
if [ -z "$GROQ_API_KEY" ] || [ "$GROQ_API_KEY" = "gsk_ВАШ_КЛЮЧ_ЗДЕСЬ" ]; then
  warning "GROQ_API_KEY не задан в .env! Агент будет запущен, но ответы работать не будут."
fi

# 4. Создать нужные директории
mkdir -p docs data/vectorstore nginx
info "Директории созданы"

# 5. Собрать образ
info "Сборка Docker-образа приложения..."
docker compose build --no-cache app

# 6. Запустить
info "Запуск контейнеров..."
docker compose up -d

# 7. Ждать Ollama
echo ""
info "Ждём готовности Ollama (может занять 1-2 минуты при первом запуске)..."
attempt=0
until docker compose exec -T ollama ollama list &>/dev/null; do
  attempt=$((attempt+1))
  if [ $attempt -ge 24 ]; then
    error "Ollama не запустилась за 2 минуты. Проверьте: docker compose logs ollama"
  fi
  echo -n "."
  sleep 5
done
echo ""
info "Ollama готова"

# 8. Подтянуть модель эмбеддингов
EMBED_MODEL="${OLLAMA_EMBED_MODEL:-nomic-embed-text}"
info "Загрузка модели эмбеддингов: $EMBED_MODEL (может занять несколько минут)..."
docker compose exec -T ollama ollama pull "$EMBED_MODEL" || \
  warning "Модель уже загружена или ошибка — проверьте docker compose logs ollama-init"

# 9. Ждать приложение
info "Ждём готовности приложения..."
attempt=0
until curl -sf http://localhost:8000/health &>/dev/null; do
  attempt=$((attempt+1))
  if [ $attempt -ge 18 ]; then
    error "Приложение не запустилось. Проверьте: docker compose logs app"
  fi
  echo -n "."
  sleep 5
done
echo ""

# 10. Готово!
echo ""
echo "  ✅  Готово! Система запущена."
echo ""
echo "  🌐  Веб-интерфейс:  http://localhost:8000"
echo "  📡  API docs:       http://localhost:8000/docs"
echo "  📋  Статус:         http://localhost:8000/status"
echo ""
echo "  Полезные команды:"
echo "    docker compose logs -f app        — логи приложения"
echo "    docker compose logs -f ollama     — логи Ollama"
echo "    docker compose restart app        — перезапустить приложение"
echo "    docker compose down               — остановить всё"
echo ""
echo "  📂  Чтобы добавить документы вручную:"
echo "      Скопируйте PDF/DOCX в ./docs или добавьте ID в .env → GDRIVE_IDS"
echo "      Затем вызовите: curl -X POST http://localhost:8000/sync -H 'Content-Type: application/json' -d '{\"force\":true}'"
echo ""
