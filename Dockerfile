FROM python:3.12.3-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    cron \
    tesseract-ocr \
    libtesseract-dev \
    msmtp \
    mailutils

COPY pyproject.toml poetry.lock ./
COPY src/ ./src/
COPY settings.yaml ./
COPY msmtprc /etc/msmtprc

RUN pip install --no-cache-dir poetry
RUN poetry install

RUN chmod 600 /etc/msmtprc

RUN echo "0 0 * * 0 find /app/images/* -mtime +7 -delete && find /app/ics/* -mtime +7 -delete" > /etc/cron.d/cleanup_cron
RUN echo "0 0 * * 0 > /var/log/cron.log" >> /etc/cron.d/cleanup_cron
RUN echo "0 0 * * * cd /app && poetry run python src/main.py >> /var/log/cron.log 2>&1" > /etc/cron.d/calendar_generator_cron
RUN echo "*/10 * * * * /app/check_errors.sh" > /etc/cron.d/error_checker_cron

RUN chmod 0644 /etc/cron.d/cleanup_cron /etc/cron.d/calendar_generator_cron /etc/cron.d/error_checker_cron
RUN touch /var/log/cron.log

COPY src/check_errors.sh /app/check_errors.sh
RUN chmod +x /app/check_errors.sh

VOLUME ["/app/images", "/app/ics", "/app/download_tracker", "/app/plain_text"]

CMD cron && tail -f /var/log/cron.log
