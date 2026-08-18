FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app/apps/api
COPY packages/graph /app/packages/graph
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY apps/api/README.md apps/api/alembic.ini ./
COPY apps/api/alembic ./alembic
COPY apps/api/src ./src
RUN uv sync --frozen --no-dev
COPY apps/api/docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh
EXPOSE 8000
CMD ["./docker-entrypoint.sh"]
