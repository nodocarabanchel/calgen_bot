# CalGen Bot Project

Bot de Telegram que descarga imágenes de canales específicos, procesa OCR y genera archivos ICS. Incluye automatización y monitoreo.

## Características

- Descarga automática de imágenes de canales Telegram
- OCR y extracción de información de eventos
- Generación de archivos ICS
- Monitoreo y notificaciones por email
- Rotación automática de logs

## Requisitos

- Docker y Docker Compose
- Cuenta SMTP para notificaciones

## Instalación

1. Configura los archivos necesarios:
```bash
cp settings.yaml.example settings.yaml
# Edita settings.yaml con tus configuraciones
```

2. Inicia el servicio:
```bash
docker-compose up -d --build
```

## Monitoreo

Verificar logs:
```bash
# Logs de supervisor
docker exec calendar_generator cat /app/logs/supervisor/supervisord.log

# Logs de aplicación
docker exec calendar_generator cat /app/logs/app/app.log

# Estado de procesos
docker exec calendar_generator supervisorctl status
```

## Funcionamiento

- Ejecución automática cada hora
- Rotación diaria de logs (7 días de histórico)
- Notificaciones por email en caso de errores
- Los directorios y estructura se crean automáticamente

## Licencia

MIT License