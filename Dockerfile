FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN useradd --create-home --uid 10001 appuser

# Install the package first for dependency layer caching, then sources.
COPY pyproject.toml README.md ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

# Non-root, read-only-friendly runtime.
USER appuser
EXPOSE 8000

# Migrations are applied by the entrypoint; the app refuses to serve
# on a schema-mismatched database (health/ready gates the traffic).
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
