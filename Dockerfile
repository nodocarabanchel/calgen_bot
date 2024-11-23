FROM python:3.11-slim-bullseye

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.5.1 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    VENV_PATH="/app/.venv"

ENV PATH="/opt/poetry/bin:$VENV_PATH/bin:$PATH"

WORKDIR /app

RUN apt-get update && apt-get install -y \
    cron msmtp msmtp-mta mailutils sqlite3 \
    build-essential libssl-dev libffi-dev \
    python3-dev gcc procps vim curl \
    logrotate sudo supervisor \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m appuser

# Crear estructura de directorios y archivos
RUN mkdir -p /app/logs/supervisor \
            /app/logs/app \
            /app/images \
            /app/ics \
            /app/session \
            /app/sqlite_db \
            /var/lock/calendar-generator \
            /var/log/cron \
    && touch /app/logs/app/app.log \
            /app/logs/app/cron.log \
            /app/logs/app/error.log \
            /app/logs/supervisor/supervisord.log \
            /app/logs/supervisor/app.err.log \
            /app/logs/supervisor/app.out.log \
            /app/logs/supervisor/cron.err.log \
            /app/logs/supervisor/cron.out.log \
    && chown -R appuser:appuser /app \
    && chmod -R 755 /app \
    && chmod 666 /app/logs/app/*.log /app/logs/supervisor/*.log \
    && chmod 777 /var/lock/calendar-generator \
    && chmod 777 /var/log/cron

# Instalar Poetry
RUN curl -sSL https://install.python-poetry.org | python3 - --version ${POETRY_VERSION} && \
    chmod a+x "${POETRY_HOME}/bin/poetry" && \
    ln -s "${POETRY_HOME}/bin/poetry" /usr/local/bin/poetry

# Instalar dependencias
COPY pyproject.toml poetry.lock ./
RUN poetry install --no-root --no-dev --no-interaction --no-ansi

# Copiar archivos de la aplicación
COPY src ./src
COPY supervisord.conf /etc/supervisor/conf.d/
COPY logrotate.conf /etc/logrotate.d/app-logs
COPY start.sh cron_script.sh check_errors.sh ./

# Configurar permisos
RUN chmod +x *.sh && \
    chmod 644 /etc/logrotate.d/app-logs && \
    touch /var/lib/logrotate/status && \
    chown appuser:appuser /var/lib/logrotate/status && \
    chmod 640 /var/lib/logrotate/status && \
    echo "appuser ALL=(ALL) NOPASSWD: /usr/sbin/cron, /usr/bin/crontab, /usr/bin/flock" >> /etc/sudoers.d/appuser

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
