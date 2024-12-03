FROM python:3.11-slim-bullseye

WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y \
    msmtp \
    logrotate \
    && rm -rf /var/lib/apt/lists/*

# Crear directorios y establecer permisos para logrotate
RUN mkdir -p /var/lib/logrotate && \
    touch /var/lib/logrotate/status && \
    groupadd -r appgroup && useradd -r -m -g appgroup appuser && \
    chown -R appuser:appgroup /var/lib/logrotate && \
    chmod 600 /var/lib/logrotate/status && \
    chmod 755 /var/lib/logrotate

# Crear directorios necesarios
RUN mkdir -p /app/logs /app/session /app/sqlite_db /app/plain_texts /app/ics /app/src /app/images && \
    chown -R appuser:appgroup /app/logs /app/session /app/sqlite_db /app/plain_texts /app/ics /app/src /app/images

# Configurar logrotate
COPY config/logrotate.conf /etc/logrotate.conf
RUN chmod 644 /etc/logrotate.conf

# Copiar scripts y configuraciones
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copiar el resto de archivos
COPY --chown=appuser:appgroup . .

# Hacer ejecutables los scripts
RUN chmod +x /app/check_calendar_generator.sh

# Configurar permisos específicos para logs
RUN touch /app/logs/app.log /app/logs/containers_check.log /app/logs/logrotate_cron.log && \
    chmod 666 /app/logs/*.log && \
    chown appuser:appgroup /app/logs/*.log

# Cambiar al usuario appuser
USER appuser

CMD ["tail", "-f", "/dev/null"]