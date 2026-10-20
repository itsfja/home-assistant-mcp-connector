FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ha_mcp/ ha_mcp/

ENV HA_MCP_TRANSPORT=http
EXPOSE 8000

CMD ["python", "-m", "ha_mcp"]
