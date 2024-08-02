#!/bin/bash

LOG_FILE="/app/logs/app.log"

echo "Cron job started at $(date)" >> $LOG_FILE
cd /app
export PATH="/root/.local/bin:/usr/local/bin:$PATH"
POETRY_PATH=$(which poetry)
echo "Poetry path: $POETRY_PATH" >> $LOG_FILE
echo "Running Python script..." >> $LOG_FILE

# Ejecutar logrotate para rotar los logs según la configuración
/usr/sbin/logrotate /etc/logrotate.d/app-logs >> $LOG_FILE

# Activar el entorno virtual y ejecutar el script
source $VENV_PATH/bin/activate
python src/main.py

echo "Python script finished at $(date)" >> $LOG_FILE
echo "Running error check..." >> $LOG_FILE
/app/check_errors.sh >> $LOG_FILE
echo "Cron job finished at $(date)" >> $LOG_FILE
echo "----------------------------------------" >> $LOG_FILE
