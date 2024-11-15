FROM python:3.11-slim-bullseye

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.5.1 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    PYSETUP_PATH="/app" \
    VENV_PATH="/app/.venv"

# Add Poetry to PATH
ENV PATH="$POETRY_HOME/bin:$VENV_PATH/bin:$PATH"

WORKDIR /app

# Install system dependencies and debugging tools
RUN apt-get update && apt-get install -y \
    cron \
    msmtp \
    msmtp-mta \
    mailutils \
    sqlite3 \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3-dev \
    gcc \
    procps \
    vim \
    curl \
    logrotate \
    sudo \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN useradd -m appuser

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 - --version ${POETRY_VERSION} && \
    chmod a+x "${POETRY_HOME}/bin/poetry"

# Copy only configuration files first
COPY --chown=appuser:appuser pyproject.toml poetry.lock ./

# Install dependencies
RUN poetry config virtualenvs.create true \
    && poetry config virtualenvs.in-project true \
    && poetry install --no-root --no-dev --no-interaction --no-ansi --verbose

# Copy the source code
COPY --chown=appuser:appuser src ./src
COPY --chown=appuser:appuser settings.yaml ./

# Configure logs and directories
RUN mkdir -p /app/logs /app/images /app/ics /app/download_tracker /app/plain_texts /app/sqlite_db /app/session \
    && touch /app/logs/app.log /app/logs/cron.log /app/logs/error.log \
    && chown -R appuser:appuser /app /var/log /var/lib/logrotate \
    && chmod -R 755 /app \
    && chmod 1777 /app/logs /var/log

# Copy and configure scripts
COPY --chown=appuser:appuser cron_script.sh check_errors.sh ./
RUN chmod +x /app/cron_script.sh /app/check_errors.sh

# Configure logrotate
COPY --chown=root:root logrotate.conf /etc/logrotate.d/app-logs
RUN chmod 644 /etc/logrotate.d/app-logs

# Ensure logrotate state file exists and has correct permissions
RUN touch /var/lib/logrotate/status && \
    chown appuser:appuser /var/lib/logrotate/status && \
    chmod 640 /var/lib/logrotate/status

# Configure msmtp
COPY --chown=root:root msmtprc /etc/msmtprc
RUN chmod 644 /etc/msmtprc

# Create start script
COPY start.sh ./
RUN chmod +x /app/start.sh

# Ensure Python and msmtp are in the PATH
ENV PATH="/home/appuser/.local/bin:/usr/sbin:/usr/bin:$PATH"

# Allow appuser to use sudo for specific commands
RUN echo "appuser ALL=(ALL) NOPASSWD: /usr/sbin/cron, /usr/bin/crontab" >> /etc/sudoers.d/appuser

# Command to start cron and keep the container running
CMD ["/app/start.sh"]