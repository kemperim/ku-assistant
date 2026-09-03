FROM python:3.11-slim

WORKDIR /app

# System deps for pdfplumber / python-docx
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpoppler-cpp-dev poppler-utils \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app source
COPY app/ ./app/
COPY static/ ./static/
COPY tools/ ./tools/
COPY scripts/ ./scripts/

# Data dirs (will be mounted as volumes)
RUN mkdir -p /data/docs /data/vectorstore /data/raw_ku_site

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
