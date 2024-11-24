FROM python:3.11-slim-bullseye

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.7.1 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    POETRY_CACHE_DIR=/opt/poetry/cache \
    VENV_PATH="/app/.venv"

ENV PATH="/opt/poetry/bin:$VENV_PATH/bin:$PATH"

WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y \
    python3-dev \
    gcc \
    g++ \
    make \
    sqlite3 \
    msmtp \
    msmtp-mta \
    mailutils \
    logrotate \
    curl \
    libffi-dev \
    gfortran \
    libblas-dev \
    liblapack-dev \
    libatlas-base-dev \
    && rm -rf /var/lib/apt/lists/*

# Crear usuario y grupo con home directory
RUN groupadd -r appgroup && \
    useradd -r -m -g appgroup -d /home/appuser appuser && \
    mkdir -p /home/appuser/.cache && \
    mkdir -p /home/appuser/.local && \
    mkdir -p /home/appuser/.config && \
    chown -R appuser:appgroup /home/appuser && \
    chmod -R 755 /home/appuser

# Instalar Poetry y configurar cache
RUN curl -sSL https://install.python-poetry.org | python3 - --version ${POETRY_VERSION} && \
    chmod a+x "${POETRY_HOME}/bin/poetry" && \
    mkdir -p $POETRY_CACHE_DIR && \
    chown -R appuser:appgroup $POETRY_CACHE_DIR

# Crear estructura de directorios y establecer permisos
RUN mkdir -p /app/images \
            /app/ics \
            /app/download_tracker \
            /app/plain_texts \
            /app/sqlite_db \
            /app/session \
            /app/logs/app \
            /app/logs/supervisor \
            /app/.venv \
    && chown -R appuser:appgroup /app \
    && chmod -R 777 /app

# Cambiar al usuario no privilegiado
USER appuser

# Configurar Poetry
RUN mkdir -p /home/appuser/.config/pypoetry && \
    poetry config cache-dir $POETRY_CACHE_DIR

# Copiar archivos del proyecto
COPY --chown=appuser:appgroup pyproject.toml poetry.lock ./
COPY --chown=appuser:appgroup src ./src
COPY --chown=appuser:appgroup config/logrotate.conf /etc/logrotate.d/app-logs

# Instalar dependencias con Poetry
RUN poetry install --only main --no-root --no-interaction

USER root
# Crear script de inicio
RUN echo '#!/bin/bash\n\
umask 0000\n\
\n\
# Asegurar permisos de directorios\n\
chmod -R 777 /app/images\n\
chmod -R 777 /app/ics\n\
chmod -R 777 /app/download_tracker\n\
chmod -R 777 /app/plain_texts\n\
chmod -R 777 /app/sqlite_db\n\
chmod -R 777 /app/logs\n\
chmod -R 777 /app/session\n\
\n\
# Asegurar permisos de archivos de configuración\n\
chmod 666 /app/key.json\n\
chmod 666 /app/settings.yaml\n\
\n\
# Ejecutar como usuario appuser\n\
exec su -s /bin/bash -c "poetry run python src/main.py" appuser\n\
' > /app/start.sh && \
    chmod +x /app/start.sh

CMD ["/app/start.sh"]