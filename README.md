# CalGen Bot Project

Este proyecto es un bot de Telegram diseñado para descargar imágenes de un canales específicos, procesarlas utilizando OCR y generar archivos ICS con la información extraída. También se configura un sistema de cron jobs para automatizar estas tareas y enviar correos electrónicos en caso de errores.

## Características

- Descarga de imágenes desde un canal de Telegram.
- Procesamiento de imágenes utilizando OCR.
- Generación de archivos ICS con la información extraída.
- Tareas automatizadas mediante cron jobs.
- Notificación por correo electrónico en caso de errores.

## Requisitos Previos

- Docker y Docker Compose instalados.
- Cuenta de correo electrónico para usar como servidor SMTP.

## Configuración

### Archivo `settings.yaml`

Configura el archivo `settings.yaml` en la raíz del proyecto con los detalles de tu bot de Telegram y el servicio de OCR.


1. **Construir y ejecutar los contenedores:**

   ```sh
   docker-compose up -d --build
   ```

2. **Verificar los logs:**

   ```sh
   docker-compose logs -f calgen_bot
   ```

## Contribución

Si deseas contribuir a este proyecto, por favor crea un fork del repositorio y envía un pull request con tus cambios.

## Licencia

Este proyecto está bajo la licencia MIT. Consulta el archivo `LICENSE` para más detalles.
