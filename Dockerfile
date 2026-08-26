FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp/assetcore-home \
    XDG_CACHE_HOME=/tmp/assetcore-cache \
    XDG_CONFIG_HOME=/tmp/assetcore-config \
    XDG_DATA_HOME=/tmp/assetcore-data
WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core libreoffice-writer postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r backend/requirements.txt \
    && groupadd --system --gid 10001 assetcore \
    && useradd --system --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin assetcore
COPY backend/ ./backend/
COPY --from=frontend /app/frontend/dist ./frontend/dist
RUN chmod -R a-w /app
ENV PYTHONPATH=/app/backend
EXPOSE 10000
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','10000')+'/api/ready', timeout=4)" || exit 1
CMD ["sh", "-c", "uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-10000}"]
