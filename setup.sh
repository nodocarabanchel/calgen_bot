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
    local dir=$1
    echo "Creando directorio: $dir"
    mkdir -p "$dir" || error_exit "No se pudo crear el directorio $dir"
    chmod 775 "$dir" || error_exit "No se pudieron ajustar permisos para $dir"
    chown -R $APP_USER:$APP_GROUP "$dir" || error_exit "No se pudo cambiar la propiedad de $dir"
}

# Función para crear archivos de log
create_log_file() {
    local file=$1
    echo "Creando archivo de log: $file"
    touch "$file" || error_exit "No se pudo crear el archivo $file"
    chmod 666 "$file" || error_exit "No se pudieron ajustar permisos para $file"
    chown $APP_USER:$APP_GROUP "$file" || error_exit "No se pudo cambiar la propiedad de $file"
}

# Inicio de la configuración
echo "Configurando el entorno de CalGen Bot..."

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

# Crear archivo de configuración si no existe
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Creando archivo de configuración predeterminado desde la plantilla..."
    cp "$CONFIG_TEMPLATE" "$CONFIG_FILE" || error_exit "No se pudo copiar el archivo de configuración predeterminado"
else
    echo "El archivo de configuración ya existe: $CONFIG_FILE"
fi

# Mostrar mensaje de finalización
echo "Configuración completada. Ahora puedes construir y ejecutar el contenedor con Docker Compose."
