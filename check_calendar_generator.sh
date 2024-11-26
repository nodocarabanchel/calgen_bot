#!/bin/bash

LOG_FILE="/app/logs/containers_check.log"
TEMP_ERROR_FILE="/tmp/container_errors.txt"
REPORTED_ERRORS_FILE="/app/logs/reported_container_errors.txt"

# Cargar configuración SMTP
SMTP_CONFIG=$(python3 -c "
import yaml
with open('/app/settings.yaml', 'r') as f:
    config = yaml.safe_load(f)
    smtp = config.get('smtp', {})
    print(f\"host={smtp.get('host')};port={smtp.get('port')};user={smtp.get('user')};password={smtp.get('password')};from={smtp.get('from')};to={smtp.get('to')}\")")

eval $(echo "$SMTP_CONFIG" | tr ';' '\n')

# Registrar y notificar errores
log_and_notify() {
    local error_msg=$1
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    echo "[$timestamp] $error_msg" >> "$LOG_FILE"
    
    if ! grep -Fq "$error_msg" "$REPORTED_ERRORS_FILE" 2>/dev/null; then
        (
            echo "To: $to"
            echo "From: $from"
            echo "Subject: Error en Calendar Generator"
            echo "Content-Type: text/plain; charset=UTF-8"
            echo
            echo "Error detectado:"
            echo "Timestamp: $timestamp"
            echo "Error: $error_msg"
        ) | msmtp --host="$host" \
                  --port="$port" \
                  --user="$user" \
                  --passwordeval="echo $password" \
                  --from="$from" \
                  --auth=on \
                  --tls=on \
                  --tls-starttls=on \
                  "$to"
        
        echo "$error_msg" >> "$REPORTED_ERRORS_FILE"
    fi
}

# Verificar logs de errores
recent_errors=$(tail -n 100 /app/logs/app.log | grep -i "error")
if [ ! -z "$recent_errors" ]; then
    log_and_notify "Errores en logs: $recent_errors"
fi

exit 0