FROM python:3.11-slim-bullseye

# Establecer variables de entorno
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.5.1 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    PYSETUP_PATH="/app" \
    VENV_PATH="/app/.venv"

# Agregar Poetry al PATH
ENV PATH="$POETRY_HOME/bin:$VENV_PATH/bin:$PATH"

WORKDIR /app

# Instalar dependencias del sistema y herramientas de depuración
RUN apt-get update && apt-get install -y \
    cron \
    tesseract-ocr \
    libtesseract-dev \
    msmtp \
    msmtp-mta \
    mailutils \
    sqlite3 \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3-dev \
    gcc \
    procps \
    vim \
    curl \
    logrotate \
    sudo \
    && rm -rf /var/lib/apt/lists/*

# Crear un usuario no root
RUN useradd -m appuser

# Configurar sudo para el usuario appuser
RUN echo "appuser ALL=(ALL) NOPASSWD: /usr/sbin/logrotate, /usr/sbin/cron, /usr/bin/crontab" >> /etc/sudoers.d/appuser

# Instalar Poetry
RUN curl -sSL https://install.python-poetry.org | python3 - --version ${POETRY_VERSION} && \
    chmod a+x "${POETRY_HOME}/bin/poetry"

# Copiar solo los archivos de configuración primero
COPY pyproject.toml poetry.lock ./

# Instalar dependencias
RUN poetry config virtualenvs.create true \
    && poetry config virtualenvs.in-project true \
    && poetry install --no-root --no-dev --no-interaction --no-ansi --verbose

# Copiar el código fuente
COPY src ./src
COPY settings.yaml ./

# Configurar logs
RUN mkdir -p /app/logs \
    && touch /app/logs/app.log /app/logs/cron.log /app/logs/error.log \
    && chown -R appuser:appuser /app \
    && chmod -R 755 /app \
    && chmod 1777 /app/logs

# Copiar y configurar scripts
COPY cron_script.sh check_errors.sh ./
RUN chmod +x /app/cron_script.sh /app/check_errors.sh

# Configurar logrotate
COPY logrotate.conf /etc/logrotate.d/app-logs
RUN chmod 644 /etc/logrotate.d/app-logs

# Ensure logrotate state directory exists and has correct permissions
RUN mkdir -p /var/lib/logrotate && \
    chown appuser:appuser /var/lib/logrotate && \
    chmod 755 /var/lib/logrotate

# Ensure the logrotate state file exists and has correct permissions
RUN touch /var/lib/logrotate/status && \
    chown appuser:appuser /var/lib/logrotate/status && \
    chmod 640 /var/lib/logrotate/status

# Configurar msmtp
COPY msmtprc /etc/msmtprc
RUN chmod 644 /etc/msmtprc

# Definir volúmenes
VOLUME ["/app/images", "/app/ics", "/app/download_tracker", "/app/plain_texts", "/app/sqlite_db", "/app/session", "/app/logs"]

# Crear script de inicio
COPY start.sh ./
RUN chmod +x /app/start.sh

# Asegurarse de que Python y msmtp estén en el PATH
ENV PATH="/home/appuser/.local/bin:/usr/sbin:/usr/bin:$PATH"

# Cambiar al usuario no root
USER appuser

# Comando para iniciar cron y mantener el contenedor en ejecución
CMD ["/app/start.sh"]
