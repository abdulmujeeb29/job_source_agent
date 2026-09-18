FROM node:24-bookworm-slim AS browser-cli
RUN npm install -g agent-browser@0.33.2 && npm cache clean --force

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    CHROMIUM_EXECUTABLE=/usr/bin/chromium CHROMIUM_NO_SANDBOX=true \
    DATA_DIR=/app/data PATH="/app/.venv/bin:$PATH" \
    UV_CACHE_DIR=/tmp/uv-cache

RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium ca-certificates fonts-liberation tini \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.11.6

COPY --from=browser-cli /usr/local/bin/node /usr/local/bin/node
COPY --from=browser-cli /usr/local/lib/node_modules/agent-browser /usr/local/lib/node_modules/agent-browser
RUN ln -s /usr/local/lib/node_modules/agent-browser/bin/agent-browser.js /usr/local/bin/agent-browser

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8085
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8085/healthz', timeout=3)"
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8085", "--workers", "1"]
