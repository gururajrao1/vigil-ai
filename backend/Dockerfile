FROM python:3.11-slim

# System deps for scipy, psycopg2, feedparser
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (cache layer)
COPY requirements-deploy.txt .
RUN pip install --no-cache-dir -r requirements-deploy.txt

# Copy application code
COPY . .

# NLP feature flags — disable heavy ML in production by default
# Override via Railway/Render environment variables if you want transformer NER
ENV USE_TRANSFORMER_NER=false \
    USE_PRESIDIO=false \
    USE_ONLINE_TRANSLATION=true \
    USE_LLM=true \
    PYTHONUNBUFFERED=1 \
    MALLOC_ARENA_MAX=2 \
    WEB_CONCURRENCY=1 \
    PORT=8000

# Expose port (Railway / Render inject $PORT)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -f http://localhost:${PORT}/api/health || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --timeout-keep-alive 5"]
