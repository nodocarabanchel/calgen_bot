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

# Verificar que las variables SMTP estén configuradas
echo "Configuración SMTP:"
echo "SMTP_HOST: $SMTP_HOST"
echo "SMTP_PORT: $SMTP_PORT"
echo "SMTP_USER: $SMTP_USER"
echo "SMTP_FROM: $SMTP_FROM"
echo "SMTP_TO: $SMTP_TO"

# Asegurar permisos correctos para los archivos de log
sudo chown -R appuser:appuser /app/logs
sudo chmod -R 755 /app/logs
sudo touch /app/logs/last_pos.txt
sudo chmod 666 /app/logs/last_pos.txt /app/logs/*.log

# Función para verificar y rotar logs si es necesario
check_and_rotate_logs() {
    if [ ! -f "/var/lib/logrotate/status" ] || [ "$(sudo find /var/lib/logrotate/status -mtime +1)" ]; then
        sudo /usr/sbin/logrotate /etc/logrotate.d/app-logs --force
    fi
}

# Verificar y rotar logs al inicio
check_and_rotate_logs

# Configurar cron para logrotate y el script principal
echo "0 * * * * /usr/sbin/logrotate /etc/logrotate.d/app-logs" | sudo crontab -
echo "0 * * * * /app/cron_script.sh" | crontab -

# Iniciar cron
sudo service cron start

# Mantener el contenedor en ejecución
tail -f /dev/null