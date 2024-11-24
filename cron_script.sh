#!/bin/bash

# Exit on error
set -e

# Script variables
LOCKFILE="/var/lock/calendar-generator/cron.lock"
LOCKDIR=$(dirname "$LOCKFILE")
LOG_DIR="/app/logs/app"
CRON_LOG="${LOG_DIR}/cron.log"

# Ensure we can write logs
if [ ! -d "$LOG_DIR" ]; then
    sudo mkdir -p "$LOG_DIR"
    sudo chown appuser:appgroup "$LOG_DIR"
    sudo chmod 775 "$LOG_DIR"
fi

# Ensure lock directory exists and has correct permissions
if [ ! -d "$LOCKDIR" ]; then
    sudo mkdir -p "$LOCKDIR"
    sudo chown appuser:appgroup "$LOCKDIR"
    sudo chmod 775 "$LOCKDIR"
fi

# Create lock file with correct permissions if it doesn't exist
if [ ! -f "$LOCKFILE" ]; then
    touch "$LOCKFILE"
    chown appuser:appgroup "$LOCKFILE"
    chmod 664 "$LOCKFILE"
fi

# Function to log messages
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$CRON_LOG"
}

# Attempt to acquire lock
exec 200>"$LOCKFILE"
if ! flock -n 200; then
    log_message "ERROR: Another instance is running"
    exit 1
fi

# Main execution
log_message "Starting cron job execution"

cd /app || {
    log_message "ERROR: Cannot change to /app directory"
    exit 1
}

# Activate virtual environment and run main script
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
    log_message "Virtual environment activated"
    
    if python src/main.py; then
        log_message "Python script executed successfully"
    else
        log_message "ERROR: Python script execution failed"
        exit 1
    fi
else
    log_message "ERROR: Virtual environment not found"
    exit 1
fi

log_message "Cron job completed successfully"
exit 0