#!/bin/bash

# Exit on error
set -e

# Variables
LOG_DIR="/app/logs/app"
CONFIG_FILE="/app/settings.yaml"
LOCK_DIR="/var/lock/calendar-generator"

# Function to log messages
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "${LOG_DIR}/app.log"
}

# Initialize directories and files
initialize_environment() {
    # Check and create directories
    for dir in "$LOG_DIR" "$LOCK_DIR"; do
        if [ ! -d "$dir" ]; then
            sudo mkdir -p "$dir"
            sudo chown appuser:appgroup "$dir"
            sudo chmod 775 "$dir"
            log_message "Created directory: $dir"
        fi
    done

    # Check and create lock files
    for lock_file in "$LOCK_DIR/cron.lock" "$LOCK_DIR/error_check.lock"; do
        if [ ! -f "$lock_file" ] || [ "$(stat -c %U:%G $lock_file)" != "appuser:appgroup" ]; then
            sudo touch "$lock_file"
            sudo chown appuser:appgroup "$lock_file"
            sudo chmod 664 "$lock_file"
            log_message "Created/fixed lock file: $lock_file"
        fi
    done
}

# Initialize Python environment
initialize_python() {
    source /app/.venv/bin/activate
    python_version=$(python --version 2>&1)
    log_message "Virtual environment activated"
    log_message "Using Python: $python_version"
    log_message "Virtual env path: $VIRTUAL_ENV"
}

# Configure SMTP
configure_smtp() {
    log_message "Loading SMTP configuration"
    if [ ! -f "$CONFIG_FILE" ]; then
        log_message "ERROR: Configuration file not found at $CONFIG_FILE"
        return 1
    fi

    # Load SMTP configuration
    export SMTP_HOST=$(python -c "import yaml; print(yaml.safe_load(open('$CONFIG_FILE'))['smtp']['host'])" 2>/dev/null)
    export SMTP_PORT=$(python -c "import yaml; print(yaml.safe_load(open('$CONFIG_FILE'))['smtp']['port'])" 2>/dev/null)
    export SMTP_USER=$(python -c "import yaml; print(yaml.safe_load(open('$CONFIG_FILE'))['smtp']['user'])" 2>/dev/null)
    export SMTP_PASS=$(python -c "import yaml; print(yaml.safe_load(open('$CONFIG_FILE'))['smtp']['password'])" 2>/dev/null)
    export SMTP_FROM=$(python -c "import yaml; print(yaml.safe_load(open('$CONFIG_FILE'))['smtp']['from'])" 2>/dev/null)
    export SMTP_TO=$(python -c "import yaml; print(yaml.safe_load(open('$CONFIG_FILE'))['smtp']['to'])" 2>/dev/null)

    if [ -n "$SMTP_HOST" ]; then
        log_message "SMTP configuration loaded successfully"
    else
        log_message "WARNING: SMTP configuration incomplete"
    fi
}

# Setup cron jobs
setup_cron() {
    log_message "Setting up cron jobs"
    (
cat << 'EOF'
0 * * * * /usr/sbin/logrotate /etc/logrotate.d/app-logs
0 * * * * /app/cron_script.sh >> /app/logs/app/cron.log 2>&1
5 * * * * /app/check_errors.sh
EOF
    ) | sudo -u appuser crontab -

    # Verificar la configuración
    crontab_verify=$(sudo -u appuser crontab -l)
    log_message "Cron configuration verified:"
    log_message "$crontab_verify"
}

# Main execution
main() {
    initialize_environment
    initialize_python
    configure_smtp
    setup_cron
    log_message "Container initialization completed"

    # Keep container running with heartbeat
    while true; do
        log_message "Heartbeat check - Container running"
        sleep 300
    done
}

# Run main function
main