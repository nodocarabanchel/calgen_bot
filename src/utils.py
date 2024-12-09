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
        self.places_autocomplete_url = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
        self.places_details_url = "https://maps.googleapis.com/maps/api/place/details/json"
        self.geocoding_url = "https://maps.googleapis.com/maps/api/geocode/json"

    def get_place_details(self, place_id):
        params = {
            "place_id": place_id,
            "key": self.api_key,
            "fields": "geometry,formatted_address,address_component,type"
        }
        try:
            response = requests.get(self.places_details_url, params=params)
            response.raise_for_status()
            result = response.json()
            
            if result.get("result"):
                return self._format_location_result(result["result"])
            return None
        except requests.RequestException as e:
            logging.error(f"Error in Google Places details: {str(e)}")
            return None

    def geocode_address(self, address):
        params = {
            "input": address,
            "types": "establishment",
            "bounds": "39.8847,-4.5790|41.1665,-3.0527",  # Bounds para toda la Comunidad de Madrid
            "strictbounds": True,
            "key": self.api_key,
            "components": "country:es|administrative_area:Comunidad de Madrid"
        }
        try:
            response = requests.get(self.geocoding_url, params=params)
            response.raise_for_status()
            result = response.json()
            
            if result.get("results"):
                return self._format_location_result(result["results"][0])
            return None
        except requests.RequestException as e:
            logging.error(f"Error in Google Geocoding: {str(e)}")
            return None

    def _format_location_result(self, result):
        location = result["geometry"]["location"]
        categories = []
        
        if "address_components" in result:
            # Almacenamos temporalmente diferentes tipos de componentes
            district = None
            neighborhood = None
            locality = None
            
            for component in result["address_components"]:
                types = component["types"]
                name = component["long_name"]
                
                # Priorización de componentes (excluimos routes)
                if "sublocality_level_1" in types:
                    district = name
                elif "neighborhood" in types:
                    neighborhood = name
                elif "locality" in types and name != "Madrid":
                    locality = name
            
            # Añadir componentes en orden de prioridad
            if district:
                categories.append(district)
            if neighborhood and neighborhood != district:
                categories.append(neighborhood)
            if locality and locality not in categories:
                categories.append(locality)
            
            # Si después de todo no tenemos categorías, intentar con el tipo de lugar
            if not categories and "types" in result:
                relevant_types = [t for t in result["types"] 
                                if t not in ["point_of_interest", "establishment", 
                                           "street_address", "premise", "route"]]
                if relevant_types:
                    categories.extend(relevant_types)

        return {
            "latitude": location["lat"],
            "longitude": location["lng"],
            "formatted": result["formatted_address"],
            "categories": categories
        }

    def geocode(self, address):
        # Centro aproximado de la Comunidad de Madrid y radio que cubra toda la región
        center_lat = 40.4168
        center_lng = -3.7038
        radius = 50000  # 50km para cubrir toda la Comunidad de Madrid

        # Intento 1: Buscar como establecimiento
        try:
            params = {
                "input": address,
                "types": "establishment",
                "location": f"{center_lat},{center_lng}",
                "radius": f"{radius}",
                "strictbounds": True,
                "key": self.api_key,
                "components": "country:es"
            }
            
            response = requests.get(self.places_autocomplete_url, params=params)
            response.raise_for_status()
            result = response.json()
            
            if result.get("predictions"):
                place_id = result["predictions"][0]["place_id"]
                place_result = self.get_place_details(place_id)
                if place_result:
                    return place_result
            
            # Intento 2: Buscar como dirección
            params["types"] = "address"
            response = requests.get(self.places_autocomplete_url, params=params)
            response.raise_for_status()
            result = response.json()
            
            if result.get("predictions"):
                place_id = result["predictions"][0]["place_id"]
                place_result = self.get_place_details(place_id)
                if place_result:
                    return place_result
            
            # Intento 3: Usar geocoding directo
            return self.geocode_address(address)
            
        except requests.RequestException as e:
            logging.error(f"Error in geocoding: {str(e)}")
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
