#!/bin/bash

# Variables de configuración
APP_USER=$(whoami)  # Usuario actual (puedes cambiarlo si el contenedor usa otro usuario)
APP_GROUP=$(whoami)  # Grupo actual
BASE_DIR=$(pwd)  # Directorio base donde se ejecuta el script
LOG_DIR="$BASE_DIR/logs"
SESSION_DIR="$BASE_DIR/session"
DB_DIR="$BASE_DIR/sqlite_db"
SRC_DIR="$BASE_DIR/src"
DOWNLOAD_DIR="$BASE_DIR/download_tracker"
ICS_DIR="$BASE_DIR/ics"
PLAINTEXT_DIR="$BASE_DIR/plain_texts"
IMAGES_DIR="$BASE_DIR/images"
CONFIG_FILE="$BASE_DIR/settings.yaml"
CONFIG_TEMPLATE="$BASE_DIR/settings.yaml.example"

# Función para manejar errores
error_exit() {
    echo "[ERROR] $1"
    exit 1
}

# Función para crear directorios si no existen
create_directory() {
    local dir="$1"
    echo "Creando directorio: $dir"
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir" || error_exit "No se pudo crear el directorio $dir"
    fi
    chmod 775 "$dir" || error_exit "No se pudieron ajustar permisos para $dir"
    chown -R "$APP_USER:$APP_GROUP" "$dir" || error_exit "No se pudo cambiar la propiedad de $dir"
}

# Función para crear archivos de log
create_log_file() {
    local file="$1"
    echo "Creando archivo de log: $file"
    touch "$file" || error_exit "No se pudo crear el archivo $file"
    chmod 666 "$file" || error_exit "No se pudieron ajustar permisos para $file"
    chown "$APP_USER:$APP_GROUP" "$file" || error_exit "No se pudo cambiar la propiedad de $file"
}

# Inicio de la configuración
echo "Configurando el entorno de CalGen Bot..."

# Crear directorio config si no existe
mkdir -p "$BASE_DIR/config"

# Crear directorios necesarios
create_directory "$LOG_DIR"
create_directory "$SESSION_DIR"
create_directory "$DB_DIR"
create_directory "$SRC_DIR"
create_directory "$DOWNLOAD_DIR"
create_directory "$ICS_DIR"
create_directory "$PLAINTEXT_DIR"
create_directory "$IMAGES_DIR"

# Crear archivos de log predeterminados
create_log_file "$LOG_DIR/app.log"
create_log_file "$LOG_DIR/containers_check.log"
create_log_file "$LOG_DIR/logrotate_cron.log"
create_log_file "$LOG_DIR/reported_container_errors.txt"

# Configurar logrotate
echo "Configurando logrotate..."
cat > "$BASE_DIR/config/logrotate.conf" << EOF
/app/logs/*.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    su appuser appgroup
    create 664 appuser appgroup
    postrotate
        chown appuser:appgroup /app/logs/*.log
    endscript
}
EOF

# Crear el archivo de estado de logrotate
touch "$LOG_DIR/logrotate.status"
chmod 644 "$LOG_DIR/logrotate.status"

# Configurar crontab para el usuario actual
echo "Configurando crontab..."
(crontab -l 2>/dev/null; echo "*/30 * * * * docker exec calendar_generator bash -c \"python3 /app/src/main.py >> /app/logs/app.log 2>&1 && /app/check_calendar_generator.sh >> /app/logs/containers_check.log 2>&1\"") | crontab -
(crontab -l 2>/dev/null; echo "0 0 * * * docker exec calendar_generator bash -c \"/usr/sbin/logrotate /etc/logrotate.conf >> /app/logs/logrotate_cron.log 2>&1\"") | crontab -

# Crear archivo de configuración si no existe
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Creando archivo de configuración predeterminado desde la plantilla..."
    cp "$CONFIG_TEMPLATE" "$CONFIG_FILE" || error_exit "No se pudo copiar el archivo de configuración predeterminado"
else
    echo "El archivo de configuración ya existe: $CONFIG_FILE"
fi

echo "Configuración completada. Ahora puedes construir y ejecutar el contenedor con Docker Compose."