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

# Copiar archivos de configuración y código fuente
COPY pyproject.toml poetry.lock ./
COPY src/ ./src/
COPY settings.yaml ./
COPY msmtprc /etc/msmtprc

# Instalar dependencias del proyecto
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi

# Configurar permisos y tareas cron
RUN chmod 600 /etc/msmtprc
RUN touch /var/log/cron.log

# Crear script para cron
RUN echo '#!/bin/bash\n\
cd /app\n\
poetry run python src/main.py >> /var/log/cron.log 2>&1\n\
/app/check_errors.sh' > /app/cron_script.sh

RUN chmod +x /app/cron_script.sh

# Configurar cron para usar el nuevo script
RUN (crontab -l 2>/dev/null; echo "0 * * * * /app/cron_script.sh") | crontab -

# Crear directorio de logs
RUN mkdir -p /app/logs && chmod 755 /app/logs

# Copiar y configurar script de verificación de errores
COPY src/check_errors.sh /app/check_errors.sh
RUN chmod +x /app/check_errors.sh

# Definir volúmenes
VOLUME ["/app/images", "/app/ics", "/app/download_tracker", "/app/plain_text", "/app/sqlite_db"]

# Crear script de inicio
RUN echo '#!/bin/sh\n\
touch /var/log/cron.log\n\
cron\n\
tail -f /var/log/cron.log' > /start.sh
RUN chmod +x /start.sh

# Comando para iniciar cron y mantener el contenedor en ejecución
CMD ["/start.sh"]