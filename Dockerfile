# syntax=docker/dockerfile:1
FROM python:3.13.7-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        build-essential \
        curl \
        git \
        portaudio19-dev \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Attempt to upgrade pip to the requested version, falling back to the latest available release.
RUN python -m pip install --upgrade "pip==2.52" || python -m pip install --upgrade pip

ENV POETRY_VERSION=1.8.2 \
    POETRY_HOME="/opt/poetry" \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PATH="${POETRY_HOME}/bin:${PATH}"

RUN curl -sSL https://install.python-poetry.org | python3 -

COPY pyproject.toml ./

RUN poetry install --no-root --only main

COPY app ./app
COPY rag_docs ./rag_docs

RUN mkdir -p /app/rag_docs

WORKDIR /app/app

EXPOSE 8000

CMD ["python", "server.py"]
