#!/bin/bash

# Exit on error
set -e

# Script variables
LOCK_FILE="/var/lock/calendar-generator/error_check.lock"
LOCK_DIR=$(dirname "$LOCK_FILE")
LOG_DIR="/app/logs/app"
SUPERVISOR_LOG_DIR="/app/logs/supervisor"
REPORTED_ERRORS_FILE="${LOG_DIR}/reported_errors.txt"
ERROR_LOG="${LOG_DIR}/error.log"

# Function to log messages
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$ERROR_LOG"
}

# Ensure directory structure exists with correct permissions
for DIR in "$LOCK_DIR" "$LOG_DIR" "$SUPERVISOR_LOG_DIR"; do
    if [ ! -d "$DIR" ]; then
        sudo mkdir -p "$DIR"
        sudo chown appuser:appgroup "$DIR"
        sudo chmod 775 "$DIR"
        log_message "Created directory: $DIR"
    fi
done

# Create necessary files with correct permissions
for FILE in "$LOCK_FILE" "$REPORTED_ERRORS_FILE" "$ERROR_LOG"; do
    if [ ! -f "$FILE" ]; then
        touch "$FILE"
        chown appuser:appgroup "$FILE"
        chmod 664 "$FILE"
        log_message "Created file: $FILE"
    fi
done

# Attempt to acquire lock
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    log_message "ERROR: Another instance of error check is running"
    exit 1
fi

# Function to check log file for errors
check_logs() {
    local log_file=$1
    local log_name=$2
    
    if [ ! -f "$log_file" ]; then
        log_message "WARNING: Log file not found: $log_file"
        return
    }
    
    log_message "Checking $log_name for errors"
    
    grep -i "error\|exception\|failed" "$log_file" 2>/dev/null | while read -r error; do
        if ! grep -Fq "$error" "$REPORTED_ERRORS_FILE"; then
            echo "$error" >> "$REPORTED_ERRORS_FILE"
            
            # Prepare email content
            {
                echo "Subject: Error en Calendar Generator"
                echo "From: $SMTP_FROM"
                echo "To: $SMTP_TO"
                echo
                echo "Se detectó un nuevo error en $log_name:"
                echo "$error"
                echo
                echo "Timestamp: $(date '+%Y-%m-%d %H:%M:%S')"
            } > /tmp/error_mail
            
            # Send email and check result
            if msmtp -a default "$SMTP_TO" < /tmp/error_mail; then
                log_message "Error notification sent successfully"
            else
                log_message "Failed to send error notification email"
            fi
            
            # Clean up
            rm -f /tmp/error_mail
        fi
    done
}

# Check each log file
check_logs "${LOG_DIR}/app.log" "Application Log"
check_logs "${LOG_DIR}/cron.log" "Cron Log"
check_logs "${SUPERVISOR_LOG_DIR}/app.err.log" "Supervisor Error Log"

# Clean up old reported errors (older than 7 days)
find "$REPORTED_ERRORS_FILE" -mtime +7 -delete 2>/dev/null || log_message "WARNING: Failed to clean up old reported errors"

log_message "Error check completed successfully"
exit 0