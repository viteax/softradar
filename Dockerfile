# Стадии: base (зависимости) → test (линтер и тесты, CI собирает отдельно) → app (то, что на сервере).
FROM python:3.14-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/venv
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv
WORKDIR /srv
# зависимости отдельным слоем: при правке кода не переустанавливаются
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

FROM base AS test
RUN uv sync --frozen
COPY . .
RUN uv run --frozen ruff check && uv run --frozen ruff format --check && uv run --frozen pytest -q

FROM base AS app
COPY app ./app
RUN useradd --uid 1000 --create-home app && mkdir /data && chown app /data
USER app
ENV PATH=/venv/bin:$PATH DATA_DIR=/data PORT=8080
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s --start-interval=2s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/healthz', timeout=4)"
CMD ["python", "-m", "app"]
