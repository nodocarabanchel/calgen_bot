#!/bin/bash

echo "Configurando el entorno de CalGen Bot..."

# Crear directorios que necesita Docker Compose si no existen
echo "Creando estructura de directorios..."
mkdir -p logs session sqlite_db src download_tracker ics plain_texts images

# Ajustar permisos para evitar problemas de acceso desde el contenedor
echo "Ajustando permisos de los directorios..."
for dir in logs session sqlite_db download_tracker ics plain_texts images; do
    if [ -d "$dir" ]; then
        sudo chmod -R 777 "$dir"
    fi
done

# Cambiar propiedad de los directorios y archivos, si es necesario
echo "Cambiando propiedad de los directorios para evitar problemas de permisos..."
for dir in logs session sqlite_db download_tracker ics plain_texts images; do
    if [ -d "$dir" ]; then
        sudo chown -R $(whoami):$(whoami) "$dir"
    fi
done

# Crear el archivo de configuración desde el ejemplo, si no existe
if [ ! -f settings.yaml ]; then
    echo "Copiando archivo de configuración predeterminado..."
    cp settings.yaml.example settings.yaml
fi

# Mostrar mensaje de finalización
echo "Configuración completada. Ahora puedes construir y ejecutar el contenedor con Docker Compose."
