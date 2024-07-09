#!/bin/bash
LOG_FILE="/app/logs/cron_job.log"
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