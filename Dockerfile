FROM python:3.11-slim-bullseye

# Establecer el directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema operativo necesarias
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

# Crear directorios adicionales en /app (esto se hará antes de montar los volúmenes)
RUN mkdir -p /app/logs /app/session /app/sqlite_db /app/plain_texts /app/ics /app/src /app/images && \
    chown -R appuser:appgroup /app/logs /app/session /app/sqlite_db /app/plain_texts /app/ics /app/src /app/images

# Instalar las dependencias de Python
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copiar el archivo de configuración de logrotate
COPY config/logrotate.conf /etc/logrotate.conf

# Copiar el resto del contenido de la aplicación, asignando propiedad al usuario appuser
COPY --chown=appuser:appgroup . .

# Hacer ejecutable el script de chequeo (si se usa)
RUN chmod +x /app/check_calendar_generator.sh

# Cambiar al usuario appuser
USER appuser

# Comando por defecto para mantener el contenedor en ejecución
CMD ["tail", "-f", "/dev/null"]
