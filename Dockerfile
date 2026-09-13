FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

# Authenticate PGDG with its published signing key, scoped to this repository.
# Bootstrap utilities remain outside the production runtime.
FROM python:3.12-slim-trixie AS postgres-key
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && curl --fail --silent --show-error --location --proto '=https' \
       https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /pgdg.asc \
    && test "$(gpg --batch --show-keys --with-colons /pgdg.asc | awk -F: '$1 == "fpr" {print $10; exit}')" \
       = B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8

FROM python:3.12-slim-trixie AS runtime
ARG ASSETCORE_RELEASE_SHA=development
LABEL org.opencontainers.image.revision=$ASSETCORE_RELEASE_SHA
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp/assetcore-home \
    XDG_CACHE_HOME=/tmp/assetcore-cache \
    XDG_CONFIG_HOME=/tmp/assetcore-config \
    XDG_DATA_HOME=/tmp/assetcore-data \
    PATH=/usr/lib/postgresql/16/bin:$PATH
WORKDIR /app
COPY --from=postgres-key /pgdg.asc /usr/share/keyrings/pgdg.asc
COPY backend/requirements.txt ./backend/requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && printf '%s\n' 'Types: deb' 'URIs: https://apt.postgresql.org/pub/repos/apt' \
       'Suites: trixie-pgdg' 'Components: main' 'Signed-By: /usr/share/keyrings/pgdg.asc' \
       > /etc/apt/sources.list.d/pgdg.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core libreoffice-writer postgresql-client-16 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r backend/requirements.txt \
    && groupadd --system --gid 10001 assetcore \
    && useradd --system --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin assetcore
COPY backend/ ./backend/
COPY scripts/backup_database.py \
     scripts/backup_assetcore.py \
     scripts/verify_backup.py \
     scripts/restore_database.py \
     scripts/restore_assetcore.py \
     scripts/operations_audit.py \
     scripts/postgres_toolchain.py \
     scripts/production_container.py \
     ./scripts/
RUN python scripts/postgres_toolchain.py --clients-only
COPY --from=frontend /app/frontend/dist ./frontend/dist
RUN chmod -R a-w /app
ENV PYTHONPATH=/app/backend
EXPOSE 10000
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','10000')+'/api/ready', timeout=4)" || exit 1
CMD ["sh", "-c", "uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-10000}"]
