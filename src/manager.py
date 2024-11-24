import os
import time
import logging
import schedule
from datetime import datetime
import docker

# Configuración de logging
logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/app/logs/manager.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('calendar-manager')

class CalendarManager:
    def __init__(self):
        self.client = docker.from_env()
        self.container_name = os.getenv('APP_CONTAINER', 'calendar_generator')
        self.process_hour = os.getenv('PROCESS_HOUR', '*')
        self.check_delay = int(os.getenv('CHECK_DELAY', '5'))
        self.rotate_hour = int(os.getenv('ROTATE_HOUR', '3'))
        
    def process_images(self):
        """Procesar imágenes"""
        try:
            logger.info("Iniciando procesamiento de imágenes")
            container = self.client.containers.get(self.container_name)
            container.start()
            container.wait()  # Esperar a que termine
            logger.info("Procesamiento de imágenes completado")
        except Exception as e:
            logger.error(f"Error en procesamiento de imágenes: {e}")
            self.notify_error("Procesamiento de imágenes", str(e))

    def check_errors(self):
        """Verificar errores"""
        try:
            logger.info("Iniciando verificación de errores")
            container = self.client.containers.get(self.container_name)
            result = container.exec_run("/app/check_errors.sh")
            if result.exit_code != 0:
                raise Exception(f"Exit code: {result.exit_code}")
            logger.info("Verificación de errores completada")
        except Exception as e:
            logger.error(f"Error en verificación: {e}")
            self.notify_error("Verificación de errores", str(e))

    def rotate_logs(self):
        """Rotar logs"""
        try:
            logger.info("Iniciando rotación de logs")
            container = self.client.containers.get(self.container_name)
            result = container.exec_run("logrotate -f /etc/logrotate.d/app-logs")
            if result.exit_code != 0:
                raise Exception(f"Exit code: {result.exit_code}")
            logger.info("Rotación de logs completada")
        except Exception as e:
            logger.error(f"Error en rotación de logs: {e}")
            self.notify_error("Rotación de logs", str(e))

    def notify_error(self, operation, error):
        """Notificar errores"""
        try:
            container = self.client.containers.get(self.container_name)
            message = f"Error en {operation}: {error}"
            cmd = f'echo "{message}" | msmtp -a default "$SMTP_TO"'
            container.exec_run(["/bin/sh", "-c", cmd])
        except Exception as e:
            logger.error(f"Error enviando notificación: {e}")

def main():
    manager = CalendarManager()
    
    # Programar tareas
    schedule.every().hour.at(":00").do(manager.process_images)
    schedule.every().hour.at(f":{manager.check_delay:02d}").do(manager.check_errors)
    schedule.every().day.at(f"{manager.rotate_hour:02d}:00").do(manager.rotate_logs)
    
    logger.info("Gestor de calendario iniciado")
    logger.info(f"Configuración: Proceso cada hora, Check a los {manager.check_delay} minutos, "
                f"Rotación a las {manager.rotate_hour}:00")
    
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()