FROM python:3.11-slim-bullseye
WORKDIR /app

# Instalar dependencias del sistema y herramientas de depuración
RUN apt-get update && apt-get install -y \
    cron \
    tesseract-ocr \
    libtesseract-dev \
    msmtp \
    mailutils \
    sqlite3 \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3-dev \
    gcc \
    procps \
    vim \
    curl

# Instalar Poetry
RUN pip install poetry
ENV PATH="/root/.local/bin:/usr/local/bin:$PATH"

# Copiar archivos de configuración y código fuente
COPY pyproject.toml poetry.lock ./
COPY src/ ./src/
COPY settings.yaml ./

# Instalar dependencias del proyecto
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi

# Configurar permisos y tareas cron
RUN touch /var/log/cron.log && chmod 666 /var/log/cron.log

# Crear directorio de logs
RUN mkdir -p /app/logs && chmod 755 /app/logs

# Crear archivo de log para el cron job
RUN touch /app/logs/cron_job.log && chmod 666 /app/logs/cron_job.log

# Crear archivo de log para la aplicación
RUN touch /app/logs/app.log && chmod 666 /app/logs/app.log

# Crear script para cron
COPY cron_script.sh /app/cron_script.sh
RUN chmod +x /app/cron_script.sh

# Configurar cron para usar el nuevo script
RUN (crontab -l 2>/dev/null; echo "0 * * * * /app/cron_script.sh") | crontab -

# Copiar y configurar script de verificación de errores
COPY src/check_errors.sh /app/check_errors.sh
RUN chmod +x /app/check_errors.sh

# Definir volúmenes
VOLUME ["/app/images", "/app/ics", "/app/download_tracker", "/app/plain_texts", "/app/sqlite_db", "/app/sesion"]

# Crear script de inicio
RUN echo '#!/bin/bash\n\
touch /var/log/cron.log\n\
echo "Container started at $(date)" >> /var/log/cron.log 2>&1\n\
echo "PATH: $PATH" >> /var/log/cron.log 2>&1\n\
POETRY_PATH=$(which poetry)\n\
echo "Poetry path: $POETRY_PATH" >> /var/log/cron.log 2>&1\n\
echo "Poetry version: $($POETRY_PATH --version)" >> /var/log/cron.log 2>&1\n\
cron\n\
tail -f /var/log/cron.log' > /start.sh
RUN chmod +x /start.sh

# Comando para iniciar cron y mantener el contenedor en ejecución
CMD ["/start.sh"]