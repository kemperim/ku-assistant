#!/bin/bash
set -e

echo "Starting Ollama..."
ollama serve &
OLLAMA_PID=$!

echo "Waiting for Ollama to be ready..."
until curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; do
  sleep 2
done
echo "Ollama is ready."

echo "Pulling embedding model..."
ollama pull nomic-embed-text
echo "Model ready."

echo "Starting FastAPI..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000