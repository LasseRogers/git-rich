FROM python:3.12-slim

# LightGBM needs the OpenMP runtime.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY gitrich ./gitrich
RUN pip install --no-cache-dir .

COPY alembic.ini ./
COPY migrations ./migrations
