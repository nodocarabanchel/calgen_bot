#!/bin/bash

LOCKFILE="/var/lock/calendar-generator/cron.lock"

# Adquirir bloqueo utilizando exec y flock
exec 200>"$LOCKFILE"
if ! flock -n 200; then
    echo "$(date) - Another instance is running" >> /app/logs/app/cron.log
    exit 1
fi

# Capturar errores y limpiar bloqueo al salir
trap 'rm -f "$LOCKFILE"; exit' INT TERM EXIT

# Cambiar al directorio de la aplicación
cd /app || exit 1

# Activar el entorno virtual
source .venv/bin/activate

# Ejecutar el script principal
python src/main.py

# Log de la ejecución
echo "Cron job ejecutado: $(date)" >> /app/logs/app/cron.log

# Limpieza final
rm -f "$LOCKFILE"
trap - INT TERM EXIT
