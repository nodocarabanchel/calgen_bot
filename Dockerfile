FROM python:3.11-slim-bullseye

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.5.1 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    VENV_PATH="/app/.venv"

ENV PATH="/opt/poetry/bin:$VENV_PATH/bin:$PATH"

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    cron msmtp msmtp-mta mailutils sqlite3 \
    build-essential libssl-dev libffi-dev \
    python3-dev gcc procps vim curl \
    logrotate sudo supervisor dos2unix \
    && rm -rf /var/lib/apt/lists/*

# Create appuser with specific UID/GID
RUN groupadd -g 1000 appgroup && \
    useradd -u 1000 -g appgroup -m appuser

# Create directory structure
RUN mkdir -p /app/logs/supervisor \
            /app/logs/app \
            /app/images \
            /app/ics \
            /app/session \
            /app/sqlite_db \
            /var/lock/calendar-generator \
            /var/run \
    && touch /app/logs/app/app.log \
            /app/logs/app/cron.log \
            /app/logs/app/error.log \
            /app/logs/supervisor/supervisord.log \
            /app/logs/supervisor/app.err.log \
            /app/logs/supervisor/app.out.log \
            /app/logs/supervisor/cron.err.log \
            /app/logs/supervisor/cron.out.log \
            /var/lock/calendar-generator/cron.lock \
            /var/lock/calendar-generator/error_check.lock

# Set directory permissions
RUN chown -R appuser:appgroup /app \
    && chown -R appuser:appgroup /var/lock/calendar-generator \
    && chmod -R 775 /app \
    && chmod 775 /var/lock/calendar-generator \
    && chmod 664 /app/logs/app/*.log \
    && chmod 664 /app/logs/supervisor/*.log \
    && chmod 664 /var/lock/calendar-generator/*.lock \
    && chmod 755 /var/run \
    && chown root:root /var/run

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 - --version ${POETRY_VERSION} && \
    chmod a+x "${POETRY_HOME}/bin/poetry" && \
    ln -s "${POETRY_HOME}/bin/poetry" /usr/local/bin/poetry

# Install dependencies
COPY --chown=appuser:appgroup pyproject.toml poetry.lock ./
RUN poetry install --no-root --no-dev --no-interaction --no-ansi

# Copy application files
COPY --chown=appuser:appgroup src ./src
COPY --chown=root:root supervisord.conf /etc/supervisor/conf.d/
COPY --chown=root:root logrotate.conf /etc/logrotate.d/app-logs

# Copy and set permissions for scripts
COPY start.sh cron_script.sh check_errors.sh healthcheck.sh ./
RUN chown appuser:appgroup /app/*.sh && \
    chmod +x /app/*.sh && \
    dos2unix /app/*.sh

# Configure permissions and sudo access
RUN chmod 644 /etc/logrotate.d/app-logs && \
    touch /var/lib/logrotate/status && \
    chown appuser:appgroup /var/lib/logrotate/status && \
    chmod 664 /var/lib/logrotate/status && \
    echo "appuser ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/appuser && \
    chmod 0440 /etc/sudoers.d/appuser

# Final permission verification
RUN find /app/logs -type d -exec chmod 775 {} \; && \
    find /app/logs -type f -exec chmod 664 {} \; && \
    find /app/logs -type d -exec chown appuser:appgroup {} \; && \
    find /app/logs -type f -exec chown appuser:appgroup {} \;

# Verify script permissions
RUN ls -la /app/*.sh && \
    test -x /app/start.sh && \
    test -x /app/cron_script.sh && \
    test -x /app/check_errors.sh && \
    test -x /app/healthcheck.sh

# Healthcheck
HEALTHCHECK --interval=1m --timeout=10s --start-period=30s --retries=3 \
    CMD ["/app/healthcheck.sh"]

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]