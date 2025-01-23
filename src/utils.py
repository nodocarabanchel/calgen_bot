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

class DuplicateDetector:
    def __init__(self, config):
        self.hash_size = config.get("duplicate_detection", {}).get("hash_size", 64)
        self.similarity_threshold = config.get("duplicate_detection", {}).get("similarity_threshold", 4)
        self.region_threshold = config.get("duplicate_detection", {}).get("region_threshold", 30)
        self.grid_size = config.get("duplicate_detection", {}).get("grid_size", 4)
        self.min_differences = config.get("duplicate_detection", {}).get("min_differences", 1)

    def calculate_image_hash(self, image_path):
        """
        Calcula múltiples hashes de la imagen usando diferentes métodos para mayor precisión
        """
        try:
            with Image.open(image_path) as img:
                # Convertir a escala de grises y redimensionar
                img_gray = img.convert("L")
                
                # Hash perceptual básico
                img_resized = img_gray.resize((self.hash_size + 1, self.hash_size), Image.LANCZOS)
                pixels = np.array(img_resized)
                diff = pixels[:, 1:] > pixels[:, :-1]
                phash = "".join(["1" if d else "0" for d in diff.flatten()])
                
                # Hash de media
                img_tiny = img_gray.resize((8, 8), Image.LANCZOS)
                pixels = np.array(img_tiny)
                mean = pixels.mean()
                ahash = "".join(["1" if p > mean else "0" for p in pixels.flatten()])
                
                # Hash de gradiente
                gradient = np.gradient(pixels)[0]
                ghash = "".join(["1" if g > 0 else "0" for g in gradient.flatten()])
                
                return {
                    "phash": phash,
                    "ahash": ahash,
                    "ghash": ghash
                }
        except Exception as e:
            logger.error(f"Error calculando hash para {image_path}: {e}")
            return None

    def compare_hashes(self, hash1, hash2):
        """
        Compara los hashes usando múltiples métricas
        """
        if not (hash1 and hash2):
            return False, float('inf')
            
        # Calcular distancia Hamming para cada tipo de hash
        distances = {
            hash_type: sum(h1 != h2 for h1, h2 in zip(hash1[hash_type], hash2[hash_type]))
            for hash_type in hash1.keys()
        }
        
        # Usar el promedio ponderado de las distancias
        weights = {"phash": 0.5, "ahash": 0.3, "ghash": 0.2}
        weighted_distance = sum(distances[k] * weights[k] for k in distances)
        
        return weighted_distance <= self.similarity_threshold, weighted_distance

    def analyze_image_regions(self, img1_path, img2_path):
        """
        Analiza las diferencias entre regiones de las imágenes usando múltiples métricas
        """
        try:
            with Image.open(img1_path) as img1, Image.open(img2_path) as img2:
                img1 = img1.convert("RGB")
                img2 = img2.convert("RGB")
                
                if img1.size != img2.size:
                    img2 = img2.resize(img1.size, Image.LANCZOS)
                
                # Convertir a arrays numpy para análisis
                img1_array = np.array(img1)
                img2_array = np.array(img2)
                
                # Dividir en regiones
                region_differences = []
                h_regions = np.array_split(range(img1.size[1]), self.grid_size)
                w_regions = np.array_split(range(img1.size[0]), self.grid_size)
                
                for i, h_region in enumerate(h_regions):
                    for j, w_region in enumerate(w_regions):
                        region1 = img1_array[h_region[0]:h_region[-1]+1, 
                                           w_region[0]:w_region[-1]+1]
                        region2 = img2_array[h_region[0]:h_region[-1]+1,
                                           w_region[0]:w_region[-1]+1]
                        
                        # Calcular múltiples métricas de diferencia
                        pixel_diff = np.mean(np.abs(region1 - region2))
                        hist_diff = self._calculate_histogram_difference(region1, region2)
                        edge_diff = self._calculate_edge_difference(region1, region2)
                        
                        # Combinar métricas con pesos
                        combined_diff = (0.4 * pixel_diff + 
                                       0.3 * hist_diff + 
                                       0.3 * edge_diff)
                        
                        if combined_diff > self.region_threshold:
                            region_differences.append((i, j, combined_diff))
                
                return region_differences
                
        except Exception as e:
            logger.error(f"Error analizando regiones entre {img1_path} y {img2_path}: {e}")
            return []

    def _calculate_histogram_difference(self, region1, region2):
        """
        Calcula la diferencia entre histogramas de color
        """
        hist1 = np.histogram(region1, bins=64, range=(0,255))[0]
        hist2 = np.histogram(region2, bins=64, range=(0,255))[0]
        return np.mean(np.abs(hist1 - hist2))

    def _calculate_edge_difference(self, region1, region2):
        """
        Calcula la diferencia en los bordes usando el gradiente Sobel
        """
        grad1_x = np.gradient(region1.mean(axis=2))[0]
        grad2_x = np.gradient(region2.mean(axis=2))[0]
        grad1_y = np.gradient(region1.mean(axis=2))[1]
        grad2_y = np.gradient(region2.mean(axis=2))[1]
        
        edge_diff_x = np.mean(np.abs(grad1_x - grad2_x))
        edge_diff_y = np.mean(np.abs(grad1_y - grad2_y))
        
        return (edge_diff_x + edge_diff_y) / 2

    def check_duplicate(self, img_path, processed_hashes, processed_files):
        """
        Verifica si una imagen es duplicada usando múltiples criterios
        """
        logger.info(f"Verificando duplicados para: {img_path}")
        
        # Calcular hashes de la imagen actual
        current_hashes = self.calculate_image_hash(img_path)
        if not current_hashes:
            return False, None
            
        # Verificar contra archivos procesados en esta sesión
        for processed_file in processed_files:
            if str(processed_file) != str(img_path):
                processed_hashes_current = self.calculate_image_hash(processed_file)
                similar, distance = self.compare_hashes(current_hashes, processed_hashes_current)
                
                if similar:
                    logger.info(f"Hash similar encontrado con {processed_file} (distancia: {distance})")
                    differences = self.analyze_image_regions(img_path, processed_file)
                    
                    if len(differences) <= self.min_differences:
                        logger.info(f"Imagen {img_path} es duplicado de {processed_file}")
                        logger.info(f"Diferencias encontradas en {len(differences)} regiones")
                        return True, processed_file
        
        # Verificar contra hashes almacenados previamente
        for processed_path, stored_hashes in processed_hashes.items():
            if Path(processed_path).exists():
                similar, distance = self.compare_hashes(current_hashes, stored_hashes)
                
                if similar:
                    differences = self.analyze_image_regions(img_path, processed_path)
                    
                    if len(differences) <= self.min_differences:
                        logger.info(f"Imagen {img_path} es duplicado (almacenado) de {processed_path}")
                        return True, processed_path
        
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
