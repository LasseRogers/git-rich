FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY gitrich ./gitrich
RUN pip install --no-cache-dir .

COPY alembic.ini ./
COPY migrations ./migrations
