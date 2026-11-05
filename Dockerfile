# syntax=docker/dockerfile:1
FROM python:3.12.14-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
WORKDIR /app
COPY docker/requirements.lock /app/requirements.lock
# Optional CA for managed build environments; never retained in the image.
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    python -m pip install --no-cache-dir --only-binary=:all: --require-hashes -r requirements.lock \
    && python -m pip check
COPY src /app/src
COPY demo /app/demo
COPY scripts/demo_smoke.py /app/scripts/demo_smoke.py
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=12 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["python", "-m", "uvicorn", "rag.api:app", "--host", "0.0.0.0", "--port", "8000"]
