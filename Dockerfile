FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
# --no-install-project: instala solo dependencias de terceros aquí (cachea bien mientras
# pyproject.toml/uv.lock no cambien). cv_agent es un paquete editable local — uv necesita
# ver src/ para instalarlo, así que ese paso va después de copiar el código.
RUN uv sync --frozen --no-dev --no-install-project
COPY src/ src/
COPY data/ data/
COPY web/ web/
RUN uv sync --frozen --no-dev

FROM python:3.12-slim
RUN useradd -m -u 1000 app
WORKDIR /app
COPY --from=builder --chown=app:app /app /app
USER app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
EXPOSE 8080
CMD exec uvicorn cv_agent.api.app:app --host 0.0.0.0 --port ${PORT:-8080}
