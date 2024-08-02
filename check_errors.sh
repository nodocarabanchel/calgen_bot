#!/bin/bash

# Función para leer configuración del archivo YAML
get_config_value() {
    local key=$1
    python -c "import yaml; import sys; config=yaml.safe_load(open('/app/settings.yaml')); print(config$key)" 2>/dev/null
}

# Leer configuración SMTP
SMTP_HOST=$(get_config_value "['smtp']['host']")
SMTP_PORT=$(get_config_value "['smtp']['port']")
SMTP_USER=$(get_config_value "['smtp']['user']")
SMTP_PASS=$(get_config_value "['smtp']['password']")
SMTP_FROM=$(get_config_value "['smtp']['from']")
SMTP_TO=$(get_config_value "['smtp']['to']")

APP_LOG_FILE="/app/logs/app.log"
LAST_POS_FILE="/app/logs/last_pos.txt"
TEMP_ERROR_FILE="/tmp/new_errors.txt"
REPORTED_ERRORS_FILE="/app/logs/reported_errors.txt"

check_errors() {
    local log_file=$1
    local last_pos_key=$2

    if [ ! -f "$LAST_POS_FILE" ]; then
        echo "${last_pos_key}:0" > "$LAST_POS_FILE"
    fi

    last_pos=$(grep "^${last_pos_key}:" "$LAST_POS_FILE" | cut -d':' -f2)
    if [ -z "$last_pos" ]; then
        last_pos=0
    fi

    log_size=$(wc -c < "$log_file")

    if [ "$log_size" -gt "$last_pos" ]; then
        tail -c +$((last_pos + 1)) "$log_file" | grep -i "error" | grep -v "check_errors.sh" > "$TEMP_ERROR_FILE"
        echo "${last_pos_key}:${log_size}" > "$LAST_POS_FILE"
    fi
}

check_errors "$APP_LOG_FILE" "app_log"

# Filtrar los errores ya reportados anteriormente
if [ -s "$TEMP_ERROR_FILE" ]; then
    if [ ! -f "$REPORTED_ERRORS_FILE" ]; then
        touch "$REPORTED_ERRORS_FILE"
    fi
    
    new_errors=$(grep -Fxvf "$REPORTED_ERRORS_FILE" "$TEMP_ERROR_FILE")
    
    if [ -n "$new_errors" ]; then
        echo "$new_errors" >> "$REPORTED_ERRORS_FILE"
        echo "Se encontraron nuevos errores. Enviando correo..."
        (
            echo "To: $SMTP_TO"
            echo "From: $SMTP_FROM"
            echo "Subject: Nuevos Errores Detectados en Calendar Generator"
            echo "Content-Type: text/plain; charset=UTF-8"
            echo
            echo "Se han detectado los siguientes nuevos errores en Calendar Generator:"
            echo
            echo "$new_errors"
            echo
            echo "Este es un mensaje automático. Por favor, revise y tome las acciones necesarias."
        ) | msmtp \
            --host="$SMTP_HOST" \
            --port="$SMTP_PORT" \
            --user="$SMTP_USER" \
            --passwordeval="echo $SMTP_PASS" \
            --from="$SMTP_FROM" \
            --auth=on \
            --tls=on \
            --tls-starttls=on \
            "$SMTP_TO"
        
        if [ $? -eq 0 ]; then
            echo "Correo enviado exitosamente."
        else
            echo "Error al enviar el correo."
        fi
    else
        echo "No se encontraron nuevos errores no reportados."
    fi
else
    echo "No se encontraron nuevos errores."
fi

rm -f "$TEMP_ERROR_FILE"
