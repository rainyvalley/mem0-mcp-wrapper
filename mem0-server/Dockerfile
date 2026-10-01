FROM python:3.12-slim
RUN pip install --no-cache-dir "mem0ai==2.2.1" ollama qdrant-client "fastapi>=0.110" "uvicorn[standard]"
WORKDIR /app
COPY server.py .
EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
