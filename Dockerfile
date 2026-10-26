# Multi-stage build for agently-web — runtime image is tiny because the
# application needs only the Python standard library. The builder stage
# runs the test suite so a broken PR cannot ship.
#
# Build:    docker build -t ghcr.io/<you>/agently-web:latest .
# Run live: docker run --rm -p 8787:8787 ghcr.io/<you>/agently-web:latest
# Run demo: docker run --rm -p 8787:8787 -e AGENTLY_WEB_DEMO=1 ghcr.io/<you>/agently-web:latest

# --------------------------------------------------------------------------- #
# Builder — install pytest, run the test suite, then drop dev tooling
# --------------------------------------------------------------------------- #
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY tests ./tests
COPY agently ./agently
COPY server.py ./
COPY static ./static

RUN pip install --no-cache-dir pytest==9.1.1 \
    && python -m pytest tests -q

# --------------------------------------------------------------------------- #
# Runtime — final image
# --------------------------------------------------------------------------- #
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8787 \
    HOST=0.0.0.0 \
    AGENTLY_WEB_DATA_DIR=/data

# Non-root user for the runtime
RUN groupadd --system agently && useradd --system --gid agently --uid 10001 agently \
    && mkdir -p /data /app && chown -R agently:agently /data /app

WORKDIR /app

COPY --chown=agently:agently --from=builder /app/agently ./agently
COPY --chown=agently:agently server.py ./
COPY --chown=agently:agently static ./static
COPY --chown=agently:agently pyproject.toml README.md LICENSE ./

USER agently

EXPOSE 8787

VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8787/healthz', timeout=3).status == 200 else 1)"

CMD ["python", "server.py"]
