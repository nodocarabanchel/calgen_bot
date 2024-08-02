#!/bin/bash

LOG_FILE="/app/logs/app.log"

echo "Cron job started at $(date)" >> $LOG_FILE 2>&1
cd /app
export PATH="/root/.local/bin:/usr/local/bin:$PATH"
POETRY_PATH=$(which poetry)
echo "Poetry path: $POETRY_PATH" >> $LOG_FILE 2>&1
echo "Running Python script..." >> $LOG_FILE 2>&1

# Ejecutar logrotate para rotar los logs según la configuración
logrotate /mnt/data/logrotate.conf >> $LOG_FILE 2>&1

# Activar el entorno virtual y ejecutar el script
source $VENV_PATH/bin/activate
python src/main.py >> $LOG_FILE 2>&1

echo "Python script finished at $(date)" >> $LOG_FILE 2>&1
echo "Running error check..." >> $LOG_FILE 2>&1
/app/check_errors.sh >> $LOG_FILE 2>&1
echo "Cron job finished at $(date)" >> $LOG_FILE 2>&1
echo "----------------------------------------" >> $LOG_FILE 2>&1
