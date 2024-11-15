#!/bin/bash

# Configurar el entorno virtual de Poetry
export VIRTUAL_ENV="/app/.venv"
export PATH="$VIRTUAL_ENV/bin:$PATH"

# Activar el entorno virtual
source $VIRTUAL_ENV/bin/activate

# Función para leer configuración del archivo YAML
get_config_value() {
    local key=$1
    python -c "import yaml; print(yaml.safe_load(open('/app/settings.yaml'))$key)" 2>/dev/null
}

# Configurar variables de entorno para SMTP
export SMTP_HOST=$(get_config_value "['smtp']['host']")
export SMTP_PORT=$(get_config_value "['smtp']['port']")
export SMTP_USER=$(get_config_value "['smtp']['user']")
export SMTP_PASS=$(get_config_value "['smtp']['password']")
export SMTP_FROM=$(get_config_value "['smtp']['from']")
export SMTP_TO=$(get_config_value "['smtp']['to']")

# Verificar que las variables SMTP estén configuradas (log to a file instead of stdout)
echo "Configuración SMTP cargada." >> /app/logs/container.log

# Asegurar permisos correctos para los archivos de log
touch /app/logs/last_pos.txt
chmod 666 /app/logs/last_pos.txt /app/logs/*.log

# Función para verificar y rotar logs si es necesario
check_and_rotate_logs() {
    if [ ! -f "/var/lib/logrotate/status" ] || [ "$(find /var/lib/logrotate/status -mtime +1)" ]; then
        /usr/sbin/logrotate /etc/logrotate.d/app-logs --force
    fi
}

# Verificar y rotar logs al inicio
check_and_rotate_logs

# Configurar cron para logrotate y el script principal
echo "0 * * * * /usr/sbin/logrotate /etc/logrotate.d/app-logs" | sudo crontab -
echo "0 * * * * su - appuser -c '/app/cron_script.sh >> /app/logs/cron.log 2>&1'" | sudo crontab -

# Iniciar cron como root
sudo cron

# Log that the script has started
echo "Container started at $(date)" >> /app/logs/container.log

# Mantener el contenedor en ejecución
tail -f /dev/null