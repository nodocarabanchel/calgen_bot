#!/bin/bash

LOG_DIR="/app/logs/app"
ERROR_LOG="${LOG_DIR}/error.log"
REPORTED_ERRORS_FILE="${LOG_DIR}/reported_errors.txt"

# Crear archivo de errores reportados si no existe
touch "$REPORTED_ERRORS_FILE"

# Verificar logs
check_logs() {
    local log_file=$1
    
    grep -i "error\|exception\|failed" "$log_file" | while read -r error; do
        if ! grep -Fq "$error" "$REPORTED_ERRORS_FILE"; then
            echo "$error" >> "$REPORTED_ERRORS_FILE"
            
            # Enviar email
            {
                echo "Subject: Error en Calendar Generator"
                echo "From: $SMTP_FROM"
                echo "To: $SMTP_TO"
                echo
                echo "Se detectó un nuevo error:"
                echo "$error"
                echo
                echo "Timestamp: $(date '+%Y-%m-%d %H:%M:%S')"
            } | msmtp -a default "$SMTP_TO"
        fi
    done
}

# Verificar cada archivo de log
for log_file in "${LOG_DIR}"/*.log; do
    [ -f "$log_file" ] && check_logs "$log_file"
done

# Limpiar errores antiguos (más de 7 días)
find "$REPORTED_ERRORS_FILE" -mtime +7 -delete