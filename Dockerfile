FROM python:3.13.7-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Actualizar pip
RUN python -m pip install --upgrade pip

# Instalar Poetry con pip
RUN python -m pip install --no-cache-dir "poetry==2.2.0"

# Copiar el archivo de dependencias primero para aprovechar la caché
COPY pyproject.toml ./

# Copiar el resto del código
COPY app/ ./

# Instalar dependencias principales sin crear virtualenv
RUN poetry config virtualenvs.create false \
 && poetry install --no-interaction --no-ansi --only main

EXPOSE 8000

CMD ["python", "server.py"]
