#!/bin/bash

LOCKFILE="/var/lock/calendar-generator/cron.lock"

if ! flock -n 200; then
    echo "Another instance is running"
    exit 1
fi 200>"$LOCKFILE"

cd /app
source .venv/bin/activate
python src/main.py

echo "Cron job ejecutado: $(date)" >> /app/logs/app/cron.log