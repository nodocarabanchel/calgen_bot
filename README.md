# CalGen Bot Project

Este proyecto es un bot que descarga imágenes de canales de Telegram específicos, las procesa usando OCR y genera archivos ICS con la información extraída. Incluye sistema de cron jobs para automatización y notificaciones por correo.

## Características

- Descarga de imágenes desde canales de Telegram
- Procesamiento de imágenes con OCR
- Extracción de texto de las publicaciones
- Generación de archivos ICS
- Tareas automatizadas cada 30 minutos
- Sistema de monitorización y alertas por correo
- Rotación automática de logs

## Requisitos

- Docker y Docker Compose
- Cuenta SMTP para notificaciones (Brevo u otro servicio)

## Configuración

1. **Clonar el repositorio**:
    ```bash
    git clone <repositorio>
    cd calgen_bot
    ```

2. **Configurar el entorno**:
    Ejecuta el script `setup.sh` para crear la estructura de directorios necesaria y ajustar los permisos:
    
    Primero, asegúrate de que el script tenga permisos de ejecución:
    
    ```bash
    chmod +x setup.sh
    ```
    
    Luego, ejecuta el script para configurar el entorno:
    
    ```bash
    sudo ./setup.sh
    ```

3. **Configurar crontab**:
    ```bash
    crontab -e
    ```
    Añadir:
    ```bash
    # Ejecutar script principal cada 30 minutos y check de errores
    0,30 * * * * docker exec calendar_generator bash -c "python3 /app/src/main.py >> /app/logs/app.log 2>&1 && /app/check_calendar_generator.sh >> /app/logs/containers_check.log 2>&1"

    # Logrotate diario
    45 2 * * * docker exec calendar_generator bash -c "/usr/sbin/logrotate -fv /etc/logrotate.conf >> /app/logs/logrotate_cron.log 2>&1"
    ```

## Despliegue

1. **Construir y arrancar contenedor**:
    ```bash
    docker-compose up -d --build
    ```

2. **Verificar logs**:
    ```bash
    docker exec calendar_generator tail -f /app/logs/app.log
    ```

## Mantenimiento

- Los logs se rotan diariamente
- Se mantienen 7 días de histórico
- Las notificaciones de error se envían por correo
- Los textos de las publicaciones se usan como descripción en la API

## Estructura

```
calgen_bot/
├── logs/           # Logs del sistema
├── session/        # Sesión de Telegram
├── sqlite_db/      # Base de datos
├── src/            # Código fuente
├── plain_texts/    # Textos extraídos del OCR
├── download_tracker/  # Registro de descargas de Telegram
├── ics/            # Archivos ICS generados
└── settings.yaml   # Configuración
```

## Pruebas Manuales

```bash
# Probar script principal
docker exec calendar_generator python3 /app/src/main.py

# Probar check de errores
docker exec calendar_generator /app/check_calendar_generator.sh

# Probar rotación de logs
docker exec calendar_generator /usr/sbin/logrotate -fv /etc/logrotate.conf
```

## Licencia

MIT License

