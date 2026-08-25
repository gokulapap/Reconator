# Combined non-root image for platforms that run the API and worker from one
# artifact (for example Heroku). Docker Compose uses the smaller service images.
FROM node:22-alpine AS web-builder

WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/. .
RUN npm run build


FROM python:3.11-slim-bookworm AS python-builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY backend/requirements.txt ./
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install -r requirements.txt


FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app \
    RESULTS_DIR=/app/results \
    SERVE_STATIC_WEB=1 \
    STATIC_WEB_DIR=/app/static_web

RUN apt-get update -y \
 && apt-get install -y --no-install-recommends ca-certificates dnsutils \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --gid 10001 reconator \
 && useradd --uid 10001 --gid reconator --create-home --shell /usr/sbin/nologin reconator

COPY --from=python-builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=reconator:reconator backend /app
COPY --from=web-builder --chown=reconator:reconator /web/dist /app/static_web
RUN mkdir -p /app/results && chown reconator:reconator /app/results

USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "app.container_entrypoint"]
