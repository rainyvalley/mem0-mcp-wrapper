FROM python:3.12-slim
# mcp pinned to 2.x: the server is written against the 2.x API (MCPServer, not
# the removed FastMCP) — an unpinned rebuild broke on 2026-09-30 once already.
RUN pip install --no-cache-dir "mcp[cli]==2.2.0" "httpx==0.28.1"
WORKDIR /app
COPY server.py .
EXPOSE 8300
CMD ["python", "server.py"]