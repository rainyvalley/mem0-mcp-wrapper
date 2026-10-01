FROM python:3.12-slim
# NOTE: mem0ai is intentionally UNPINNED - mem0 is its own product and moves fast.
# This server is a minimal reference implementation of the REST surface the
# wrapper expects; install whatever current mem0ai release you prefer and
# check its changelog before upgrading.
RUN pip install --no-cache-dir mem0ai ollama qdrant-client "fastapi>=0.110" "uvicorn[standard]"
WORKDIR /app
COPY server.py .
EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
