# CalGen Bot Project

Este proyecto es un bot de Telegram diseñado para descargar imágenes de un canal específico, procesarlas utilizando OCR y generar archivos ICS con la información extraída. También se configura un sistema de cron jobs para automatizar estas tareas y enviar correos electrónicos en caso de errores.

## Características

- Descarga de imágenes desde un canal de Telegram.
- Procesamiento de imágenes utilizando OCR.
- Generación de archivos ICS con la información extraída.
- Tareas automatizadas mediante cron jobs.
- Notificación por correo electrónico en caso de errores.

## Requisitos Previos

- Docker y Docker Compose instalados.
- Cuenta de correo electrónico para usar como servidor SMTP.

## Configuración

### Archivo `settings.yaml`

Configura el archivo `settings.yaml` en la raíz del proyecto con los detalles de tu bot de Telegram y el servicio de OCR.

### Archivo `msmtprc`

Crea el archivo `msmtprc` en la raíz del proyecto con la configuración de tu servidor SMTP.

```plaintext
# Example msmtprc file using environment variables
defaults
auth           on
tls            on
tls_trust_file /etc/ssl/certs/ca-certificates.crt
logfile        ~/.msmtp.log

account        default
host           $SMTP_HOST
port           $SMTP_PORT
from           $SMTP_FROM
user           $SMTP_USER
password       $SMTP_PASS
```

### Script `check_errors.sh`

Crea el script `check_errors.sh` en el directorio `src/`.

```sh
#!/bin/bash

# Archivo de log de cron
LOG_FILE="/var/log/cron.log"

# Archivo para registrar la última posición leída
LAST_POS_FILE="/var/log/cron_last_pos"

# Obtener la última posición leída (si existe)
if [ -f $LAST_POS_FILE ]; then
    LAST_POS=$(cat $LAST_POS_FILE)
else
    LAST_POS=0
fi

# Obtener el tamaño actual del archivo de log
LOG_SIZE=$(stat -c%s "$LOG_FILE")

# Leer nuevas líneas desde la última posición
if [ $LOG_SIZE -ge $LAST_POS ]; then
    tail -c +$(($LAST_POS + 1)) $LOG_FILE | grep -i "error" > /tmp/errors.txt
    NEW_POS=$LOG_SIZE
else
    # Si el archivo de log se ha rotado, leer desde el inicio
    grep -i "error" $LOG_FILE > /tmp/errors.txt
    NEW_POS=$LOG_SIZE
fi

# Actualizar la posición para la próxima lectura
echo $NEW_POS > $LAST_POS_FILE

# Si hay errores, enviar un correo electrónico
if [ -s /tmp/errors.txt ]; then
    cat /tmp/errors.txt | mail -s "Cron Job Errors Detected" $SMTP_TO
fi
```

### Dockerfile

Aquí está el Dockerfile completo para tu proyecto:

```Dockerfile
# Utilizar una imagen base de Python
FROM python:3.12.3-slim

# Establecer el directorio de trabajo
WORKDIR /app

# Instalar cron, las dependencias necesarias para OCR y herramientas adicionales
RUN apt-get update && apt-get install -y \
    cron \
    tesseract-ocr \
    libtesseract-dev \
    msmtp \
    mailutils

# Copiar los archivos del proyecto
COPY pyproject.toml poetry.lock ./
COPY src/ ./src/
COPY settings.yaml ./
COPY msmtprc /etc/msmtprc

# Instalar dependencias del proyecto usando poetry
RUN pip install --no-cache-dir poetry
RUN poetry install

# Configurar msmtp para enviar correos
RUN chmod 600 /etc/msmtprc

# Crear un script para limpiar archivos viejos y el archivo de log de cron
RUN echo "0 0 * * 0 find /app/images/* -mtime +7 -delete && find /app/ics/* -mtime +7 -delete" > /etc/cron.d/cleanup_cron
RUN echo "0 0 * * 0 > /var/log/cron.log" >> /etc/cron.d/cleanup_cron

# Crear un trabajo cron para ejecutar el script principal
RUN echo "0 0 * * * cd /app && poetry run python src/main.py >> /var/log/cron.log 2>&1" > /etc/cron.d/calendar_generator_cron

# Crear un trabajo cron para verificar errores en el log y enviar correo
RUN echo "*/10 * * * * /app/check_errors.sh" > /etc/cron.d/error_checker_cron

# Dar permisos de ejecución a los cron jobs
RUN chmod 0644 /etc/cron.d/cleanup_cron /etc/cron.d/calendar_generator_cron /etc/cron.d/error_checker_cron

# Crear un archivo log para almacenar la salida del cron
RUN touch /var/log/cron.log

# Copiar el script para verificar errores
COPY src/check_errors.sh /app/check_errors.sh
RUN chmod +x /app/check_errors.sh

# Configurar volúmenes
VOLUME ["/app/images", "/app/ics", "/app/download_tracker", "/app/plain_texts"]

# Comando para iniciar cron y mantener el contenedor en ejecución
CMD cron && tail -f /var/log/cron.log
```

### Docker Compose

Aquí está el archivo `docker-compose.yml` para tu proyecto:

```yaml
version: '3.8'

services:
  calgen_bot:
    build: .
    container_name: calgen_bot
    volumes:
      - ./images:/app/images
      - ./ics:/app/ics
      - ./download_tracker:/app/download_tracker
      - ./plain_texts:/app/plain_texts
    environment:
      - SMTP_HOST=smtp.gmail.com
      - SMTP_PORT=587
      - SMTP_USER=youremail@gmail.com
      - SMTP_PASS=yourapppassword
      - SMTP_FROM=youremail@gmail.com
      - SMTP_TO=youremail@gmail.com
```

## Instrucciones de Ejecución

1. **Clonar el repositorio:**

   ```sh
   git clone https://github.com/tu_usuario/tu_repositorio.git
   cd tu_repositorio
   ```

2. **Configurar los archivos:**

   - Completa el archivo `settings.yaml` con los detalles de tu bot de Telegram y el servicio de OCR.
   - Crea el archivo `msmtprc` con la configuración de tu servidor SMTP.
   - Asegúrate de que el script `check_errors.sh` esté en el directorio `src/`.

3. **Construir y ejecutar los contenedores:**

   ```sh
   docker-compose up -d --build
   ```

4. **Verificar los logs:**

   ```sh
   docker-compose logs -f calgen_bot
   ```

## Contribución

Si deseas contribuir a este proyecto, por favor crea un fork del repositorio y envía un pull request con tus cambios.

## Licencia

Este proyecto está bajo la licencia MIT. Consulta el archivo `LICENSE` para más detalles.
