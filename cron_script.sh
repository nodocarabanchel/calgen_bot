#!/bin/bash

LOG_FILE="/app/logs/app.log"
MAX_LOGS=3

# Función para rotar logs
function rotate_logs {
    if [ -f "$LOG_FILE" ]; then
        for i in $(seq $((MAX_LOGS-1)) -1 1); do
            if [ -f "${LOG_FILE}.$i" ]; then
                mv "${LOG_FILE}.$i" "${LOG_FILE}.$((i+1))"
            fi
        done
        mv "$LOG_FILE" "${LOG_FILE}.1"
    fi
    touch "$LOG_FILE"
}

# Rotar logs antes de comenzar
rotate_logs

# Ejecutar el script principal
echo "Cron job started at $(date)" >> $LOG_FILE 2>&1
cd /app
export PATH="/root/.local/bin:/usr/local/bin:$PATH"
POETRY_PATH=$(which poetry)
echo "Poetry path: $POETRY_PATH" >> $LOG_FILE 2>&1
echo "Running Python script..." >> $LOG_FILE 2>&1
$POETRY_PATH run python src/main.py >> $LOG_FILE 2>&1
echo "Python script finished at $(date)" >> $LOG_FILE 2>&1
echo "Running error check..." >> $LOG_FILE 2>&1
/app/check_errors.sh >> $LOG_FILE 2>&1
echo "Cron job finished at $(date)" >> $LOG_FILE 2>&1
echo "----------------------------------------" >> $LOG_FILE 2>&1

# Eliminar logs más antiguos que 3 días
find /app/logs -name "app.log.*" -type f -mtime +3 -delete