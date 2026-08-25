FROM golang:1.26.6-bookworm AS tool-builder

ENV CGO_ENABLED=0 \
    GOBIN=/out

RUN mkdir -p /out

ARG SUBFINDER_VERSION=v2.16.0
ARG URLFINDER_VERSION=v0.0.3
ARG HTTPX_VERSION=v1.10.0
ARG KATANA_VERSION=v1.7.0
ARG NAABU_VERSION=v2.6.1
ARG JSLUICE_VERSION=0ddfab153e060a9eeaded4d8669233f7c071e7e4
ARG ALTERX_VERSION=v0.1.0
ARG CDNCHECK_VERSION=v1.2.50

RUN go install github.com/projectdiscovery/subfinder/v2/cmd/subfinder@${SUBFINDER_VERSION}
RUN go install github.com/projectdiscovery/urlfinder/cmd/urlfinder@${URLFINDER_VERSION}
RUN go install github.com/projectdiscovery/httpx/cmd/httpx@${HTTPX_VERSION}
RUN go install github.com/projectdiscovery/katana/cmd/katana@${KATANA_VERSION}
RUN go install github.com/projectdiscovery/naabu/v2/cmd/naabu@${NAABU_VERSION}
RUN CGO_ENABLED=1 go install github.com/BishopFox/jsluice/cmd/jsluice@${JSLUICE_VERSION}
RUN go install github.com/projectdiscovery/alterx/cmd/alterx@${ALTERX_VERSION}
RUN go install github.com/projectdiscovery/cdncheck/cmd/cdncheck@${CDNCHECK_VERSION}

RUN mkdir -p /licenses \
 && cp /go/pkg/mod/github.com/projectdiscovery/subfinder/v2@v2.16.0/LICENSE.md /licenses/subfinder-LICENSE.md \
 && cp /go/pkg/mod/github.com/projectdiscovery/urlfinder@v0.0.3/LICENSE.md /licenses/urlfinder-LICENSE.md \
 && cp /go/pkg/mod/github.com/projectdiscovery/httpx@v1.10.0/LICENSE.md /licenses/httpx-LICENSE.md \
 && cp /go/pkg/mod/github.com/projectdiscovery/katana@v1.7.0/LICENSE.md /licenses/katana-LICENSE.md \
 && cp /go/pkg/mod/github.com/projectdiscovery/naabu/v2@v2.6.1/LICENSE.md /licenses/naabu-LICENSE.md \
 && cp /go/pkg/mod/github.com/\!bishop\!fox/jsluice@v0.0.0-20240110145140-0ddfab153e06/LICENSE /licenses/jsluice-LICENSE \
 && cp /go/pkg/mod/github.com/projectdiscovery/alterx@v0.1.0/LICENSE /licenses/alterx-LICENSE \
 && cp /go/pkg/mod/github.com/projectdiscovery/cdncheck@v1.2.50/LICENSE.md /licenses/cdncheck-LICENSE.md


FROM python:3.11-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="Reconator isolated reconnaissance toolbox" \
      org.opencontainers.image.description="Pinned third-party capability implementations for authorized Reconator scans" \
      org.opencontainers.image.licenses="GPL-3.0-or-later AND MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/usr/local/bin:/usr/bin:/bin \
    TOOLBOX_PORT=7777 \
    TOOLBOX_MAX_CONCURRENT=4

RUN apt-get update -y \
 && apt-get install -y --no-install-recommends ca-certificates passwd \
 && rm -rf /var/lib/apt/lists/* \
 && /usr/sbin/groupadd --gid 10002 toolbox \
 && /usr/sbin/useradd --uid 10002 --gid toolbox --create-home --shell /usr/sbin/nologin toolbox

COPY --from=tool-builder /out/ /usr/local/bin/
COPY --from=tool-builder /licenses/ /usr/share/licenses/reconator-toolbox/
WORKDIR /app
COPY --chown=toolbox:toolbox runner.py /app/runner.py
COPY --chown=toolbox:toolbox THIRD_PARTY_NOTICES.md /app/THIRD_PARTY_NOTICES.md

USER 10002:10002
EXPOSE 7777

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=10 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7777/healthz', timeout=2)"]

CMD ["python", "/app/runner.py"]
