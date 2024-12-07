import json
import logging
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import requests
import yaml
from dateutil.rrule import rrulestr
from PIL import Image

logger = logging.getLogger(__name__)


def load_config():
    with open("settings.yaml", "r") as file:
        return yaml.safe_load(file)


def setup_logging(config, log_name=None):
    log_file = config.get("logging", {}).get("log_file", "logs/app.log")
    log_level_str = config.get("logging", {}).get("log_level", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    # Configurar el logger raíz
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Limpiar handlers existentes
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # Crear el file handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(log_level)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Obtener el logger específico si se proporciona un nombre
    if log_name:
        logger = logging.getLogger(log_name)
    else:
        logger = root_logger

    return logger


def get_image_hash(image_path, hash_size=8):
    with Image.open(image_path) as img:
        img = img.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
        pixels = np.array(img)
        diff = pixels[:, 1:] > pixels[:, :-1]
        # Convertir el hash a una cadena binaria
        return "".join(
            [
                "1" if diff[i // hash_size][i % hash_size] else "0"
                for i in range(hash_size * hash_size)
            ]
        )


def are_images_similar(hash1, hash2, threshold=10):
    if len(hash1) != len(hash2):
        return False, len(hash1)
    distance = sum(c1 != c2 for c1, c2 in zip(hash1, hash2))
    return distance <= threshold, distance


class GooglePlacesService:
    def __init__(self, api_key):
        self.api_key = api_key
        self.autocomplete_url = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
        self.details_url = "https://maps.googleapis.com/maps/api/place/details/json"

    def get_place_details(self, place_id):
        params = {
            "place_id": place_id,
            "key": self.api_key
        }
        try:
            response = requests.get(self.details_url, params=params)
            response.raise_for_status()
            result = response.json()
            if result.get("result"):
                location = result["result"]["geometry"]["location"]
                return {
                    "latitude": location["lat"],
                    "longitude": location["lng"],
                    "formatted": result["result"]["formatted_address"],
                }
            return None
        except requests.RequestException as e:
            logging.error(f"Error in Google Places details: {str(e)}")
            return None

    def geocode(self, address):
        # Autocomplete to get place_id
        params = {
            "input": address,
            "types": "establishment",
            "region": "es",
            "key": self.api_key
        }
        try:
            response = requests.get(self.autocomplete_url, params=params)
            response.raise_for_status()
            result = response.json()
            if result.get("predictions"):
                # Take the first suggestion
                place_id = result["predictions"][0]["place_id"]
                return self.get_place_details(place_id)
            return None
        except requests.RequestException as e:
            logging.error(f"Error in Google Places autocomplete: {str(e)}")
            return None


class GeocodingService:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.opencagedata.com/geocode/v1/json"

    def geocode(self, address):
        params = {
            "q": f"{address}, Madrid, Spain",
            "key": self.api_key,
            "limit": 1,
            "no_annotations": 1,
        }
        try:
            response = requests.get(self.base_url, params=params)
            response.raise_for_status()
            result = response.json()
            if result["results"]:
                location = result["results"][0]
                components = location["components"]
                logging.info(f"Geocoding components: {str(components)}")

                categories = []
                if components.get("suburb"):
                    categories.append(components["suburb"])
                if components.get("quarter"):
                    categories.append(components["quarter"])
                if components.get("neighbourhood"):
                    categories.append(components["neighbourhood"])

                return {
                    "latitude": location["geometry"]["lat"],
                    "longitude": location["geometry"]["lng"],
                    "formatted": location["formatted"],
                    "categories": categories,
                }
            return None
        except requests.RequestException as e:
            logging.error(f"Error in geocoding: {str(e)}")
            return None


def get_geolocation(config, address):
    service = config.get("geocoding_service", "opencage").lower()
    
    if service == "opencage":
        geocoding_service = GeocodingService(api_key=config["opencage_api"]["key"])
        location = geocoding_service.geocode(address)
    elif service == "google":
        google_places_service = GooglePlacesService(api_key=config["google_maps_api"]["key"])
        location = google_places_service.geocode(address)
    else:
        logging.error(f"Unknown geocoding service: {service}")
        return None
    
    return location



def save_to_file(data, file_path):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def clean_directories(directories):
    for directory in directories:
        for item in Path(directory).glob("*"):
            if item.is_file() and item.name != ".gitkeep":
                try:
                    item.unlink()
                except Exception as e:
                    logging.error(f"Failed to delete file {item}: {e}")


def get_next_occurrence(
    rrule_str: str, original_date: datetime, current_date: datetime
) -> datetime:
    try:
        # Usamos la fecha actual pero mantenemos la hora original
        start_date = current_date.replace(
            hour=original_date.hour,
            minute=original_date.minute,
            second=original_date.second,
        )

        rrule = rrulestr(rrule_str, dtstart=start_date)
        next_occurrence = rrule.after(start_date, inc=True)

        # Si la próxima ocurrencia es en el pasado, buscamos la siguiente
        while next_occurrence and next_occurrence < current_date:
            next_occurrence = rrule.after(next_occurrence, inc=False)

        if next_occurrence:
            # Mantenemos la hora original
            return next_occurrence.replace(
                hour=original_date.hour,
                minute=original_date.minute,
                second=original_date.second,
            )
        return None
    except Exception as e:
        logger.error(f"Error al calcular la próxima ocurrencia: {e}")
        return None


def is_recurrent_event(event_data: dict) -> bool:
    return bool(event_data.get("RRULE"))


def parse_recurrence_rule(rrule):
    frequency = re.search(r"FREQ=(\w+)", rrule)
    interval = re.search(r"INTERVAL=(\d+)", rrule)

    if not frequency:
        return None

    freq = frequency.group(1)
    recurrent = {}

    if freq == "WEEKLY":
        recurrent["frequency"] = "1w"
        if interval:
            recurrent["frequency"] = f"{interval.group(1)}w"
    elif freq == "MONTHLY":
        recurrent["frequency"] = "1m"
        byday = re.search(r"BYDAY=([^;]+)", rrule)
        bymonthday = re.search(r"BYMONTHDAY=(\d+)", rrule)
        if bymonthday:
            recurrent["type"] = "ordinal"
        elif byday:
            days = byday.group(1).split(",")
            if len(days) == 1:
                day_match = re.search(r"(-?\d*)(\w+)", days[0])
                if day_match:
                    day_num = day_match.group(1)
                    if day_num:
                        recurrent["type"] = int(day_num)
                    else:
                        recurrent["type"] = 0

    return recurrent


def get_next_valid_date(start_date, rrule):
    byday = re.search(r"BYDAY=([^;]+)", rrule)
    if byday:
        day_map = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
        target_days = [day_map.get(day, 0) for day in byday.group(1).split(",")]

        while start_date.weekday() not in target_days:
            start_date += timedelta(days=1)

    return start_date


def is_recurrent_event(event_data: dict) -> bool:
    return bool(event_data.get("recurrent"))
