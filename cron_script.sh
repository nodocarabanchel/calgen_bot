#!/bin/bash

LOG_FILE="/app/logs/app.log"
ERROR_LOG_FILE="/app/logs/app_errors.log"

echo "Cron job started at $(date)" >> $LOG_FILE
cd /app

# Use the PATH set in the Dockerfile
export PATH="/app/.venv/bin:/usr/local/bin:/usr/sbin:/usr/bin:$PATH"

echo "Running Python script..." >> $LOG_FILE

# Execute logrotate to rotate logs according to the configuration
if ! flock -n /var/lib/logrotate/status.lock /usr/sbin/logrotate /etc/logrotate.d/app-logs; then
    echo "Logrotate is already running, skipping..." >> $LOG_FILE
fi

# Activate the virtual environment and execute the script directly
/app/.venv/bin/python src/main.py

echo "Python script finished at $(date)" >> $LOG_FILE
echo "Running error check..." >> $LOG_FILE

# Ensure check_errors.sh is executable before running
if [[ -x /app/check_errors.sh ]]; then
    /app/check_errors.sh >> $LOG_FILE 2>> $ERROR_LOG_FILE
else
    echo "Error: check_errors.sh is not executable or not found" >> $ERROR_LOG_FILE
fi

echo "Cron job finished at $(date)" >> $LOG_FILE
echo "----------------------------------------" >> $LOG_FILE
