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


def get_image_hash(image_path, hash_size=32):
    with Image.open(image_path) as img:
        img = img.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
        pixels = np.array(img)
        diff = pixels[:, 1:] > pixels[:, :-1]
        return "".join(["1" if diff[i // hash_size][i % hash_size] else "0" 
                       for i in range(hash_size * hash_size)])

def are_images_similar(hash1, hash2, threshold=8):
    if len(hash1) != len(hash2):
        return False, len(hash1)
    distance = sum(c1 != c2 for c1, c2 in zip(hash1, hash2))
    return distance <= threshold, distance

def compare_image_regions(img1_path, img2_path, grid_size=3, threshold=30):
    with Image.open(img1_path) as img1, Image.open(img2_path) as img2:
        img1 = img1.convert("L")
        img2 = img2.convert("L")
        
        if img1.size != img2.size:
            img2 = img2.resize(img1.size, Image.LANCZOS)
        
        width, height = img1.size
        region_width = width // grid_size
        region_height = height // grid_size
        
        differences = []
        total_diff = 0
        
        for i in range(grid_size):
            for j in range(grid_size):
                x1 = j * region_width
                y1 = i * region_height
                x2 = x1 + region_width
                y2 = y1 + region_height
                
                region1 = np.array(img1.crop((x1, y1, x2, y2)))
                region2 = np.array(img2.crop((x1, y1, x2, y2)))
                
                diff = np.mean(np.abs(region1 - region2))
                total_diff += diff
                
                if diff > threshold:
                    differences.append((i, j, diff))
        
        avg_diff = total_diff / (grid_size * grid_size)
        if avg_diff > threshold * 0.7:
            return [(i, j, avg_diff) for i in range(grid_size) for j in range(grid_size)]
            
        return differences

def check_duplicate(img_path, processed_hashes, processed_files, config):
    logger.info(f"Verificando duplicados para: {img_path}")

    duplicate_config = config.get("duplicate_detection", {})
    hash_size = duplicate_config.get("hash_size", 32)
    similarity_threshold = duplicate_config.get("similarity_threshold", 8)
    region_threshold = duplicate_config.get("region_threshold", 30)
    grid_size = duplicate_config.get("grid_size", 3)
    min_differences = duplicate_config.get("min_differences", 2)
    
    image_hash = get_image_hash(img_path, hash_size=hash_size)
    logger.info(f"Hash generado para {img_path}")
    
    # Primero verificar contra los archivos procesados en esta sesión
    for processed_file in processed_files:
        if str(processed_file) != str(img_path):  # Evitar comparar con sí mismo
            processed_hash = get_image_hash(processed_file, hash_size=hash_size)
            similar, distance = are_images_similar(image_hash, processed_hash, similarity_threshold)
            
            if similar:
                logger.info(f"Hash similar encontrado con {processed_file} (distancia: {distance})")
                try:
                    differences = compare_image_regions(
                        img_path, 
                        processed_file,
                        grid_size=grid_size,
                        threshold=region_threshold
                    )
                    
                    if not differences:
                        logger.info(f"Imagen {img_path} es duplicado exacto de {processed_file}")
                        logger.info(f"Distancia de hash: {distance}")
                        return True, processed_file
                    
                    if len(differences) <= min_differences:
                        logger.info(f"Imagen {img_path} es similar a {processed_file}")
                        logger.info(f"Diferencias encontradas en {len(differences)} regiones")
                        logger.debug(f"Detalles de diferencias: {differences}")
                        return True, processed_file
                        
                except Exception as e:
                    logger.error(f"Error comparando regiones entre {img_path} y {processed_file}: {e}")
                    continue
    
    # Luego verificar contra los hashes almacenados previamente
    for processed_path, stored_hash in processed_hashes.items():
        similar, distance = are_images_similar(image_hash, stored_hash, similarity_threshold)
        if similar and Path(processed_path).exists():
            try:
                differences = compare_image_regions(
                    img_path, 
                    processed_path,
                    grid_size=grid_size,
                    threshold=region_threshold
                )
                
                if not differences:
                    logger.info(f"Imagen {img_path} es duplicado exacto (almacenado) de {processed_path}")
                    logger.info(f"Distancia de hash: {distance}")
                    return True, processed_path
                
                if len(differences) <= min_differences:
                    logger.info(f"Imagen {img_path} es similar (almacenado) a {processed_path}")
                    logger.info(f"Diferencias encontradas en {len(differences)} regiones")
                    logger.debug(f"Detalles de diferencias: {differences}")
                    return True, processed_path
                    
            except Exception as e:
                logger.error(f"Error comparando regiones entre {img_path} y {processed_path}: {e}")
                continue
    
    return False, None

class GooglePlacesService:
    def __init__(self, api_key):
        self.api_key = api_key
        self.places_autocomplete_url = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
        self.places_details_url = "https://maps.googleapis.com/maps/api/place/details/json"
        self.geocoding_url = "https://maps.googleapis.com/maps/api/geocode/json"
        self.logger = logging.getLogger(__name__)

    def get_place_details(self, place_id):
        params = {
            "place_id": place_id,
            "key": self.api_key,
            "fields": "geometry,formatted_address,address_components,types"
        }
        try:
            self.logger.info(f"Getting place details for place_id: {place_id}")
            self.logger.debug(f"Places Details API request: {self.places_details_url} with params: {params}")
            
            response = requests.get(self.places_details_url, params=params)
            response.raise_for_status()
            result = response.json()
            
            self.logger.debug(f"Places Details API response: {result}")
            
            if result.get("result"):
                formatted_result = self._format_location_result(result["result"])
                self.logger.info(f"Successfully retrieved and formatted place details: {formatted_result}")
                return formatted_result
            
            self.logger.warning(f"No results found for place_id: {place_id}")
            return None
        except requests.RequestException as e:
            self.logger.error(f"Error in Google Places details request: {str(e)}")
            return None

    def geocode(self, address):
        self.logger.info(f"Starting geocoding process for address: {address}")
        
        center_lat = 40.4168
        center_lng = -3.7038
        radius = 70000  # 70km para cubrir toda la Comunidad de Madrid

        # Intento 1: Buscar como establecimiento
        try:
            base_params = {
                "input": f"{address}, Comunidad de Madrid",
                "location": f"{center_lat},{center_lng}",
                "radius": f"{radius}",
                "strictbounds": True,
                "key": self.api_key,
                "region": "es"
            }
            
            # Intento con tipo establecimiento
            params = {**base_params, "types": "establishment"}
            
            self.logger.info("Attempting to find location as establishment")
            self.logger.debug(f"Places Autocomplete API request: {self.places_autocomplete_url} with params: {params}")
            
            response = requests.get(self.places_autocomplete_url, params=params)
            response.raise_for_status()
            result = response.json()
            
            self.logger.debug(f"Places Autocomplete API response: {result}")
            
            if result.get("predictions"):
                place_id = result["predictions"][0]["place_id"]
                self.logger.info(f"Found establishment place_id: {place_id}")
                place_result = self.get_place_details(place_id)
                if place_result:
                    self.logger.info("Successfully found location as establishment")
                    return place_result
            
            # Intento 2: Buscar como dirección
            self.logger.info("Attempting to find location as address")
            params = {**base_params, "types": "address"}
            
            self.logger.debug(f"Places Autocomplete API request (address): {self.places_autocomplete_url} with params: {params}")
            
            response = requests.get(self.places_autocomplete_url, params=params)
            response.raise_for_status()
            result = response.json()
            
            self.logger.debug(f"Places Autocomplete API response (address): {result}")
            
            if result.get("predictions"):
                place_id = result["predictions"][0]["place_id"]
                self.logger.info(f"Found address place_id: {place_id}")
                place_result = self.get_place_details(place_id)
                if place_result:
                    self.logger.info("Successfully found location as address")
                    return place_result
            
            # Intento 3: Usar geocoding directo como último recurso
            self.logger.info("Attempting direct geocoding as fallback")
            return self.geocode_address(address)
            
        except requests.RequestException as e:
            self.logger.error(f"Error in geocoding process: {str(e)}")
            return None

    def geocode_address(self, address):
        params = {
            "address": f"{address}, Comunidad de Madrid, España",
            "bounds": "39.8847,-4.5790|41.1665,-3.0527",  # Bounds para toda la Comunidad de Madrid
            "key": self.api_key,
            "region": "es"
        }
        try:
            self.logger.info(f"Geocoding address: {address}")
            self.logger.debug(f"Geocoding API request: {self.geocoding_url} with params: {params}")
            
            response = requests.get(self.geocoding_url, params=params)
            response.raise_for_status()
            result = response.json()
            
            self.logger.debug(f"Geocoding API response: {result}")
            
            if result.get("results"):
                formatted_result = self._format_location_result(result["results"][0])
                self.logger.info(f"Successfully geocoded address: {formatted_result}")
                return formatted_result
            
            self.logger.warning(f"No geocoding results found for address: {address}")
            return None
        except requests.RequestException as e:
            self.logger.error(f"Error in Google Geocoding request: {str(e)}")
            return None

    def _format_location_result(self, result):
        """
        Formatea el resultado de la API de Google Places/Geocoding en un formato estandarizado.
        """
        location = result["geometry"]["location"]
        categories = []
        
        if "address_components" in result:
            district = None
            neighborhood = None
            locality = None
            
            for component in result["address_components"]:
                types = component["types"]
                name = component["long_name"]
                
                if "sublocality_level_1" in types:
                    district = name
                elif "neighborhood" in types:
                    neighborhood = name
                elif "locality" in types and name != "Madrid":
                    locality = name
            
            if district:
                categories.append(district)
            if neighborhood and neighborhood != district:
                categories.append(neighborhood)
            if locality and locality not in categories:
                categories.append(locality)

        return {
            "latitude": location["lat"],
            "longitude": location["lng"],
            "formatted": result["formatted_address"],
            "categories": categories
        }

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
    """
    Obtiene la geolocalización y categorías para una dirección.
    Retorna:
    - None si la ubicación está fuera de la Comunidad de Madrid
    - dict con is_online=True si es un evento online
    - dict con datos de geolocalización si es un evento presencial en Madrid
    """
    logger.info(f"Getting geolocation for address: {address}")
    
    # Verificar si es un evento online
    online_keywords = ['online', 'zoom', 'virtual', 'teams', 'meet', 'skype', 'discord', 'jitsi']
    if any(keyword.lower() in address.lower() for keyword in online_keywords):
        logger.info(f"Detected online event: {address}")
        return {"is_online": True}

    service = config.get("geocoding_service", "opencage").lower()
    
    if service == "opencage":
        geocoding_service = GeocodingService(api_key=config["opencage_api"]["key"])
        location = geocoding_service.geocode(address)
    elif service == "google":
        google_places_service = GooglePlacesService(api_key=config["google_maps_api"]["key"])
        location = google_places_service.geocode(address)
    else:
        logger.error(f"Unknown geocoding service: {service}")
        return None
    
    if location:
        # Verificar coordenadas dentro del bounding box de la Comunidad de Madrid
        lat = location.get('latitude')
        lon = location.get('longitude')
        
        if lat and lon:
            MADRID_BOUNDS = {
                'min_lat': 39.8847,
                'max_lat': 41.1665,
                'min_lon': -4.5790,
                'max_lon': -3.0527
            }
            
            is_in_bounds = (MADRID_BOUNDS['min_lat'] <= lat <= MADRID_BOUNDS['max_lat'] and 
                          MADRID_BOUNDS['min_lon'] <= lon <= MADRID_BOUNDS['max_lon'])
            
            if not is_in_bounds:
                logger.info(f"Coordinates outside Madrid Community bounds: {lat}, {lon}")
                return None
        
        # Verificación secundaria de municipios
        formatted_address = location.get('formatted', '').lower()
        has_madrid_mention = ('madrid' in formatted_address or 
                            any(municipality in formatted_address 
                                for municipality in MADRID_MUNICIPALITIES))
                                
        if not has_madrid_mention:
            logger.warning(f"Location in Madrid bounds but no municipality mentioned: {formatted_address}")
            
        location['is_online'] = False
        return location
    
    logger.warning(f"No location found for address: {address}")
    return None



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
