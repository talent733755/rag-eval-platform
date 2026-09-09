FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/apps/api/.venv/bin:$PATH"

WORKDIR /app/apps/api

RUN pip install --no-cache-dir --disable-pip-version-check uv==0.7.13

# Keep dependency installation separate from application source for build caching.
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY apps/api/src ./src
RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD ["uvicorn", "rag_eval_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
