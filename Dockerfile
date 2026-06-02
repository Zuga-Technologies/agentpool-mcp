FROM python:3.11-slim

WORKDIR /app

# System deps for sqlite-vec / onnxruntime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/

# Pre-download the embedding model so first request isn't slow
ENV FASTEMBED_CACHE_PATH=/app/.fastembed_cache
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"

ENV PYTHONPATH=/app/src
ENV HOST=0.0.0.0
ENV AGENTPOOL_DB=/app/data/agentpool.db

# Ensure the DB dir exists even when no volume is mounted (a mounted volume
# at /app/data transparently overrides this with persistent storage).
RUN mkdir -p /app/data

EXPOSE 8000

CMD ["python", "-m", "agentpool.server"]
