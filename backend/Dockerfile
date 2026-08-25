FROM python:3.11-slim-bookworm AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONWARNINGS=ignore

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install -r /app/requirements.txt


FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/venv/bin:$PATH

RUN apt-get update -y \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      dnsutils \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --gid 10001 reconator \
 && useradd --uid 10001 --gid reconator --create-home --shell /usr/sbin/nologin reconator

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

COPY --chown=reconator:reconator . /app

RUN mkdir -p /app/results \
 && chown -R reconator:reconator /app/results

ENV PYTHONPATH=/app \
    RESULTS_DIR=/app/results

EXPOSE 8000

USER 10001:10001

CMD ["gunicorn", "app.main:app", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:8000", "--workers", "2", "--timeout", "120"]
