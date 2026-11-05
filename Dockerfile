FROM python:3.12.14-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
WORKDIR /app
COPY docker/requirements.lock /app/requirements.lock
# Keep the lab quickstart compatible with Docker's classic builder.
RUN python -m pip install --no-cache-dir --only-binary=:all: --require-hashes -r requirements.lock \
    && python -m pip check
COPY src /app/src
COPY demo /app/demo
COPY scripts/demo_smoke.py /app/scripts/demo_smoke.py
COPY scripts/library_smoke.py /app/scripts/library_smoke.py
RUN mkdir -p /data && chown 10001:10001 /data
ENV INGEST_DATA_DIR=/data
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=12 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["python", "-m", "uvicorn", "rag.api:app", "--host", "0.0.0.0", "--port", "8000"]
