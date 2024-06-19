import yaml
import logging
import requests
import json

def load_config():
    with open("settings.yaml", "r") as file:
        return yaml.safe_load(file)

def setup_logging(config):
    log_file = config.get("logging", {}).get("log_file", "default.log")
    log_level = config.get("logging", {}).get("log_level", "INFO").upper()

    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )

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
