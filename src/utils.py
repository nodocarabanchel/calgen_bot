import yaml
import logging
import requests
import json
from pathlib import Path

def load_config():
    with open("settings.yaml", "r") as file:
        return yaml.safe_load(file)

import logging
import sys

def setup_logging(config):
    log_file = config.get("logging", {}).get("log_file", "/app/app.log")
    log_level_str = config.get("logging", {}).get("log_level", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )

    # Configurar loggers específicos
    logging.getLogger('httpx').setLevel(logging.WARNING)

    # Verificar la configuración
    root_logger = logging.getLogger()
    root_logger.info(f"Logging setup complete. Root logger level: {logging.getLevelName(root_logger.level)}")
    root_logger.info(f"Log file: {log_file}")

    # Forzar la salida del buffer
    sys.stdout.flush()

def get_geolocation(config, address):
    api_key = config["opencage_api"]["key"]
    api_url = f"https://api.opencagedata.com/geocode/v1/json?q={address}&key={api_key}"
    response = requests.get(api_url)
    if response.status_code == 200:
        results = response.json().get('results')
        if results:
            geometry = results[0].get('geometry')
            return geometry['lat'], geometry['lng']
    return None, None

def save_to_file(data, file_path):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def clean_directories(directories):
    for directory in directories:
        for item in Path(directory).glob('*'):
            if item.is_file() and item.name != '.gitkeep':
                try:
                    item.unlink()
                except Exception as e:
                    logging.error(f"Failed to delete file {item}: {e}")