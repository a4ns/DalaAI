# Repository-root context. This builds source only; it does not provision a host.
FROM node:24.21.0-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM caddy:2.11.7-alpine AS edge

FROM python:3.12.15-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /service
RUN apt-get update \
    && apt-get install --no-install-recommends -y fonts-dejavu-core=2.37-6 \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.lock ./requirements.lock
RUN python -m pip install --no-cache-dir -r requirements.lock \
    && python -m pip check \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home app \
    && groupadd --gid 10002 edge \
    && useradd --uid 10002 --gid edge --no-create-home edge
COPY --from=edge /usr/bin/caddy /usr/bin/caddy
COPY --from=frontend /build/dist /srv
COPY backend/app ./app
COPY backend/db ./db
COPY ops/provision ./ops/provision
COPY scripts/synthetic ./scripts/synthetic
COPY ops/managed/Caddyfile ops/managed/supervise.py ./ops/managed/
RUN mkdir -p /var/lib/naryadai /tmp/caddy-data /tmp/caddy-config \
    && chown 10002:10002 /tmp/caddy-data /tmp/caddy-config \
    && chmod 700 /tmp/caddy-data /tmp/caddy-config
# Root is needed ONLY for fixed mount initialization + launching different UIDs.
# The fixed supervisor retains root solely to signal both UIDs; no child runs as root.
EXPOSE 10000
CMD ["python", "ops/managed/supervise.py"]
