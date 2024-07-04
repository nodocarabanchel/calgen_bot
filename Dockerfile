FROM python:3.11-slim-bullseye

WORKDIR /app

# Instalar dependencias del sistema
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
    gcc

# Copiar archivos de configuración y código fuente
COPY pyproject.toml poetry.lock ./
COPY src/ ./src/
COPY settings.yaml ./
COPY msmtprc /etc/msmtprc

# Instalar Poetry y dependencias del proyecto
RUN pip install --no-cache-dir poetry
RUN poetry config virtualenvs.create false
RUN poetry install

# Configurar permisos y tareas cron
RUN chmod 600 /etc/msmtprc
RUN echo "0 0 * * * cd /app && poetry run python src/main.py >> /var/log/cron.log 2>&1 && /app/check_errors.sh" > /etc/cron.d/calendar_generator_cron
RUN echo "" >> /etc/cron.d/calendar_generator_cron
RUN chmod 0644 /etc/cron.d/calendar_generator_cron

# Copiar y configurar script de verificación de errores
COPY src/check_errors.sh /app/check_errors.sh
RUN chmod +x /app/check_errors.sh

# Definir volúmenes
VOLUME ["/app/images", "/app/ics", "/app/download_tracker", "/app/plain_text", "/app/sqlite_db"]

# Crear script de inicio
RUN echo "#!/bin/sh\n\
cron\n\
tail -f /var/log/cron.log" > /start.sh
RUN chmod +x /start.sh

# Comando para iniciar cron y mantener el contenedor en ejecución
CMD ["/start.sh"]