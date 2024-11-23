#!/bin/bash

# Configurar el entorno virtual de Poetry
export VIRTUAL_ENV="/app/.venv"
export PATH="$VIRTUAL_ENV/bin:$PATH"

source $VIRTUAL_ENV/bin/activate

# Eliminar archivos de bloqueo huérfanos al inicio
rm -f /var/lock/calendar-generator/*.lock

# Función para leer configuración
get_config_value() {
    local key=$1
    python -c "import yaml; print(yaml.safe_load(open('/app/settings.yaml'))$key)" 2>/dev/null
}

# Exportar variables de entorno desde settings.yaml
export SMTP_HOST=$(get_config_value "['smtp']['host']")
export SMTP_PORT=$(get_config_value "['smtp']['port']")
export SMTP_USER=$(get_config_value "['smtp']['user']")
export SMTP_PASS=$(get_config_value "['smtp']['password']")
export SMTP_FROM=$(get_config_value "['smtp']['from']")
export SMTP_TO=$(get_config_value "['smtp']['to']")

echo "Configuración SMTP cargada." >> /app/logs/app/app.log

# Configurar cron jobs
if ! crontab -l 2>/dev/null | grep -q '/app/cron_script.sh'; then
    (
    echo "0 * * * * /usr/sbin/logrotate /etc/logrotate.d/app-logs"
    echo "0 * * * * sudo -u appuser flock -n /var/lock/calendar-generator/cron.lock /app/cron_script.sh >> /app/logs/app/cron.log 2>&1"
    echo "5 * * * * sudo -u appuser flock -n /var/lock/calendar-generator/error_check.lock /app/check_errors.sh >> /app/logs/app/cron.log 2>&1"
    ) | sudo -u appuser crontab -
fi

# Crear archivos de log necesarios
for log_file in app.log cron.log error.log; do
    touch "/app/logs/app/$log_file"
    chmod 666 "/app/logs/app/$log_file"
done

echo "Container started at $(date)" >> /app/logs/app/app.log

# Mantener el contenedor ejecutándose
tail -f /dev/null
