#!/bin/bash

LOCK_FILE="/var/lock/calendar-generator/error_check.lock"
LOG_DIR="/app/logs/app"
SUPERVISOR_LOG_DIR="/app/logs/supervisor"
REPORTED_ERRORS_FILE="${LOG_DIR}/reported_errors.txt"

# Crear el archivo reported_errors.txt si no existe
if [ ! -f "$REPORTED_ERRORS_FILE" ]; then
    touch "$REPORTED_ERRORS_FILE"
    chmod 666 "$REPORTED_ERRORS_FILE"
fi

exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
    exit 1
fi

check_logs() {
    local log_file=$1
    grep -i "error\|exception\|failed" "$log_file" | while read -r error; do
        if ! grep -Fq "$error" "$REPORTED_ERRORS_FILE"; then
            echo "$error" >> "$REPORTED_ERRORS_FILE"
            echo "Subject: Error en Calendar Generator" > /tmp/error_mail
            echo "From: $SMTP_FROM" >> /tmp/error_mail
            echo "To: $SMTP_TO" >> /tmp/error_mail
            echo >> /tmp/error_mail
            echo "Se detectó un nuevo error:" >> /tmp/error_mail
            echo "$error" >> /tmp/error_mail
            
            msmtp -a default "$SMTP_TO" < /tmp/error_mail
            rm /tmp/error_mail
        fi
    done
}

check_logs "${LOG_DIR}/app.log"
check_logs "${LOG_DIR}/cron.log"
check_logs "${SUPERVISOR_LOG_DIR}/app.err.log"

# Limpia errores reportados antiguos
find "$REPORTED_ERRORS_FILE" -mtime +7 -delete

exit 0
