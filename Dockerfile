FROM python:3.11-slim

# pdftotext (xpdf) — lo usa pipeline/backfill_votaciones.py
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp_server/ mcp_server/
COPY pipeline/ pipeline/
COPY config/ config/

# data/ se monta como volumen (no bakear DBs en la imagen)
VOLUME /app/data

# MCP stdio — el host conecta stdin/stdout
ENTRYPOINT ["python", "mcp_server/server.py"]
