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
ENV PATH="/root/.local/bin:$PATH"

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
RUN touch /var/log/cron.log && chmod 666 /var/log/cron.log

# Crear directorio de logs
RUN mkdir -p /app/logs && chmod 755 /app/logs

# Crear script para cron
RUN echo '#!/bin/bash\n\
echo "Cron job started at $(date)" >> /var/log/cron.log 2>&1\n\
cd /app\n\
export PATH="/root/.local/bin:$PATH"\n\
echo "Running Python script..." >> /var/log/cron.log 2>&1\n\
poetry run python src/main.py >> /var/log/cron.log 2>&1\n\
echo "Python script finished at $(date)" >> /var/log/cron.log 2>&1\n\
echo "Running error check..." >> /var/log/cron.log 2>&1\n\
/app/check_errors.sh >> /var/log/cron.log 2>&1\n\
echo "Cron job finished at $(date)" >> /var/log/cron.log 2>&1\n\
echo "----------------------------------------" >> /var/log/cron.log 2>&1' > /app/cron_script.sh

RUN chmod +x /app/cron_script.sh

# Configurar cron para usar el nuevo script
RUN (crontab -l 2>/dev/null; echo "0 * * * * /app/cron_script.sh") | crontab -

# Copiar y configurar script de verificación de errores
COPY src/check_errors.sh /app/check_errors.sh
RUN chmod +x /app/check_errors.sh

# Definir volúmenes
VOLUME ["/app/images", "/app/ics", "/app/download_tracker", "/app/plain_text", "/app/sqlite_db"]

# Crear script de inicio
RUN echo '#!/bin/bash\n\
touch /var/log/cron.log\n\
echo "Container started at $(date)" >> /var/log/cron.log 2>&1\n\
echo "PATH: $PATH" >> /var/log/cron.log 2>&1\n\
echo "Poetry version: $(poetry --version)" >> /var/log/cron.log 2>&1\n\
cron\n\
tail -f /var/log/cron.log' > /start.sh

RUN chmod +x /start.sh

# Comando para iniciar cron y mantener el contenedor en ejecución
CMD ["/start.sh"]