# Backend API. The SQLite database, archived PDFs, and run logs live under /data, which
# must be a persistent disk so they survive redeploys.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    REGULATION_DATA_DIR=/data \
    REGULATION_ARTIFACTS_DIR=/data/artifacts

WORKDIR /app
COPY requirements-dev.lock pyproject.toml README.md ./
RUN pip install -r requirements-dev.lock
COPY src ./src
RUN pip install --no-deps . && useradd --create-home analyst && mkdir /data && chown analyst /data

USER analyst
EXPOSE 8000
# PORT is set by most hosts; the API falls back to 8000.
CMD ["sh", "-c", "regulation-analyst --db /data/research.sqlite3 api --host 0.0.0.0 --port ${PORT:-8000}"]
