#!/bin/bash

# Rutas de archivos
LOG_FILE="/app/logs/containers_check.log"
REPORTED_ERRORS_FILE="/app/logs/reported_container_errors.txt"

# Verificar que somos appuser
if [ "$(whoami)" != "appuser" ]; then
    exec su -s /bin/bash appuser -c "$0 $*"
fi

# Escribir encabezado del log
timestamp=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$timestamp] ======= Inicio de verificación =======" >> "$LOG_FILE"
echo "[$timestamp] Usuario: $(whoami)" >> "$LOG_FILE"

# Cargar configuración SMTP
echo "[$timestamp] Cargando configuración SMTP..." >> "$LOG_FILE"
SMTP_CONFIG=$(python3 -c '
import yaml
try:
    with open("/app/settings.yaml", "r") as f:
        config = yaml.safe_load(f)
        smtp = config.get("smtp", {})
        host = smtp.get("host", "")
        port = smtp.get("port", "")
        user = smtp.get("user", "")
        password = smtp.get("password", "")
        from_email = smtp.get("from", "")
        to_email = smtp.get("to", "")
        print(f"host={host};port={port};user={user};password={password};from={from_email};to={to_email}")
except Exception as e:
    print(f"ERROR: {str(e)}")
')

if [[ $SMTP_CONFIG == ERROR:* ]]; then
    echo "[$timestamp] Error al cargar configuración SMTP: $SMTP_CONFIG" >> "$LOG_FILE"
    exit 1
fi

eval $(echo "$SMTP_CONFIG" | tr ';' '\n')

# Función para enviar correo
send_email() {
    local error_msg="$1"
    local email_content="
To: $to
From: $from
Subject: Error en Calendar Generator
Content-Type: text/plain; charset=UTF-8

Error detectado:
Timestamp: $timestamp
Error: $error_msg
"
    echo "$email_content" | msmtp --host="$host" \
                                 --port="$port" \
                                 --user="$user" \
                                 --passwordeval="echo $password" \
                                 --from="$from" \
                                 --auth=on \
                                 --tls=on \
                                 --tls-starttls=on \
                                 "$to"
    
    if [ $? -eq 0 ]; then
        echo "[$timestamp] Correo enviado exitosamente" >> "$LOG_FILE"
    else
        echo "[$timestamp] Error al enviar correo" >> "$LOG_FILE"
    fi
}

# Verificar logs de errores
if [ -f "/app/logs/app.log" ]; then
    recent_errors=$(tail -n 100 /app/logs/app.log | grep -i "error")
    if [ ! -z "$recent_errors" ]; then
        echo "[$timestamp] Errores encontrados en app.log:" >> "$LOG_FILE"
        echo "$recent_errors" >> "$LOG_FILE"
        
        # Verificar si el error ya fue reportado
        if ! grep -Fq "$recent_errors" "$REPORTED_ERRORS_FILE" 2>/dev/null; then
            echo "[$timestamp] Nuevo error detectado, enviando correo..." >> "$LOG_FILE"
            send_email "$recent_errors"
            echo "[$timestamp] $recent_errors" >> "$REPORTED_ERRORS_FILE"
        else
            echo "[$timestamp] Error ya reportado previamente" >> "$LOG_FILE"
        fi
    else
        echo "[$timestamp] No se encontraron errores recientes" >> "$LOG_FILE"
    fi
else
    echo "[$timestamp] ADVERTENCIA: No se encuentra app.log" >> "$LOG_FILE"
fi

echo "[$timestamp] ======= Fin de verificación =======" >> "$LOG_FILE"
exit 0