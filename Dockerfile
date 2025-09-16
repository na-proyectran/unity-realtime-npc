# syntax=docker/dockerfile:1
FROM python:3.13.7-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src

RUN pip install --upgrade pip \
    && pip install --no-cache-dir \
        ".[realtime]" \
        "fastapi>=0.115,<1" \
        "uvicorn>=0.30,<1"

COPY examples/realtime/unity ./examples/realtime/unity

WORKDIR /app/examples/realtime/unity

EXPOSE 8000

CMD ["python", "server.py"]



FROM python:3.13.7-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ───────────── DEPENDENCIAS DEL SISTEMA ─────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    portaudio19-dev \
    ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# ───────────── INSTALAR POETRY ─────────────
ENV POETRY_VERSION=1.8.2
ENV PATH="/root/.local/bin:$PATH"

RUN curl -sSL https://install.python-poetry.org | python3 -

# ───────────── COPIAR EL PROYECTO ─────────────
WORKDIR /app
COPY . .

# ───────────── INSTALAR DEPENDENCIAS ─────────────
RUN poetry config virtualenvs.create false \
 && poetry install --no-interaction --no-ansi --only main

# ───────────── EXPONER PUERTO ─────────────
EXPOSE 8000

# ───────────── COMANDO POR DEFECTO ─────────────
CMD ["python", "server.py"]