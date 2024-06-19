#!/bin/bash

# Archivo de log de cron
LOG_FILE="/var/log/cron.log"

# Archivo para registrar la última posición leída
LAST_POS_FILE="/var/log/cron_last_pos"

# Obtener la última posición leída (si existe)
if [ -f $LAST_POS_FILE ]; then
    LAST_POS=$(cat $LAST_POS_FILE)
else
    LAST_POS=0
fi

# Obtener el tamaño actual del archivo de log
LOG_SIZE=$(stat -c%s "$LOG_FILE")

# Leer nuevas líneas desde la última posición
if [ $LOG_SIZE -ge $LAST_POS ]; then
    tail -c +$(($LAST_POS + 1)) $LOG_FILE | grep -i "error" > /tmp/errors.txt
    NEW_POS=$LOG_SIZE
else
    # Si el archivo de log se ha rotado, leer desde el inicio
    grep -i "error" $LOG_FILE > /tmp/errors.txt
    NEW_POS=$LOG_SIZE
fi

# Actualizar la posición para la próxima lectura
echo $NEW_POS > $LAST_POS_FILE

# Si hay errores, enviar un correo electrónico
if [ -s /tmp/errors.txt ]; then
    cat /tmp/errors.txt | msmtp -a default -- from="$SMTP_FROM" -- to="$SMTP_TO" -- subject="Cron Job Errors Detected" -- body="Se han detectado errores en los cron jobs de calendar_generator. Verifique el archivo de log adjunto." -t
fi
