#!/bin/bash

# Exit on any error
set -e

# Function to log messages
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] HEALTHCHECK: $1" >> /app/logs/app/app.log
}

# Check if a process is running
check_process() {
    pgrep -f "$1" >/dev/null
    return $?
}

# Check file permissions
check_permissions() {
    local path=$1
    local expected_owner=$2
    local expected_group=$3
    local owner=$(stat -c %U "$path")
    local group=$(stat -c %G "$path")
    [ "$owner" = "$expected_owner" ] && [ "$group" = "$expected_group" ]
    return $?
}

# Check directory exists and is writable
check_directory() {
    local dir=$1
    [ -d "$dir" ] && [ -w "$dir" ]
    return $?
}

# Main health check
main() {
    # Check critical processes
    for process in "supervisord" "cron" "start.sh"; do
        if ! check_process "$process"; then
            log_message "ERROR: Process $process is not running"
            exit 1
        fi
    done

    # Check lock files
    for lockfile in /var/lock/calendar-generator/*.lock; do
        if ! check_permissions "$lockfile" "appuser" "appgroup"; then
            log_message "ERROR: Incorrect permissions on $lockfile"
            exit 1
        fi
    done

    # Check critical directories
    for dir in "/app/logs/app" "/app/logs/supervisor" "/app/images" "/app/ics" "/app/session" "/app/sqlite_db"; do
        if ! check_directory "$dir"; then
            log_message "ERROR: Directory $dir is not accessible"
            exit 1
        fi
    done

    # Check Python virtual environment
    if [ ! -d "/app/.venv" ]; then
        log_message "ERROR: Python virtual environment not found"
        exit 1
    fi

    # All checks passed
    log_message "All health checks passed successfully"
    exit 0
}

# Run main function
main