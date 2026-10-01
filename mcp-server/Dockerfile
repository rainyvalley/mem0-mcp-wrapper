FROM python:3.12-slim
# mcp SDK pinned: the server is written against the 2.x API (MCPServer, not the
# removed FastMCP) - an unpinned rebuild already broke once when the API was
# renamed. This pin is OUR OWN code's contract, unrelated to your mem0 install,
# which stays unpinned. httpx pinned likewise (API stable here).
RUN pip install --no-cache-dir "mcp[cli]==2.2.0" "httpx==0.28.1"
WORKDIR /app
COPY server.py .
EXPOSE 8300
CMD ["python", "server.py"]