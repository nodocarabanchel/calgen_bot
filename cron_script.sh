#!/bin/bash

LOG_FILE="/app/logs/app.log"

echo "Cron job started at $(date)" >> $LOG_FILE
cd /app

# Use the PATH set in the Dockerfile
export PATH="/app/.venv/bin:/usr/local/bin:/usr/sbin:/usr/bin:$PATH"

echo "Running Python script..." >> $LOG_FILE

# Execute logrotate to rotate logs according to the configuration
/usr/sbin/logrotate /etc/logrotate.d/app-logs >> $LOG_FILE 2>&1

# Activate the virtual environment and execute the script
source /app/.venv/bin/activate
python src/main.py

echo "Python script finished at $(date)" >> $LOG_FILE
echo "Running error check..." >> $LOG_FILE
/app/check_errors.sh >> $LOG_FILE 2>&1
echo "Cron job finished at $(date)" >> $LOG_FILE
echo "----------------------------------------" >> $LOG_FILE