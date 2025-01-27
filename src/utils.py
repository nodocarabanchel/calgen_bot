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

import logging
import numpy as np
from PIL import Image
from pathlib import Path

logger = logging.getLogger(__name__)

class DuplicateDetector:
    def __init__(self, config):
        self.hash_size = config.get("duplicate_detection", {}).get("hash_size", 16)
        self.similarity_threshold = config.get("duplicate_detection", {}).get("similarity_threshold", 4)
        self.region_threshold = config.get("duplicate_detection", {}).get("region_threshold", 30)
        self.grid_size = config.get("duplicate_detection", {}).get("grid_size", 4)
        self.min_differences = config.get("duplicate_detection", {}).get("min_differences", 1)

    def calculate_image_hash(self, image_path):
        """
        Calcula múltiples hashes de la imagen usando diferentes métodos para mayor precisión.
        """
        try:
            with Image.open(image_path) as img:
                # Convertir a escala de grises
                img_gray = img.convert("L")

                # Para phash, redimensionar a (hash_size+1, hash_size)
                img_resized = img_gray.resize((self.hash_size + 1, self.hash_size), Image.LANCZOS)
                pixels = np.array(img_resized)
                diff = pixels[:, 1:] > pixels[:, :-1]
                phash = "".join(["1" if d else "0" for d in diff.flatten()])

                # Hash de media (ahash)
                img_tiny = img_gray.resize((8, 8), Image.LANCZOS)
                pixels = np.array(img_tiny)
                mean = pixels.mean()
                ahash = "".join(["1" if p > mean else "0" for p in pixels.flatten()])

                # Hash de gradiente (ghash)
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
        Compara los hashes usando múltiples métricas y un promedio ponderado.
        Retorna (similar, distance).
        """
        if not (hash1 and hash2):
            return False, float('inf')

        # Distancias Hamming por cada tipo de hash
        distances = {}
        for h_type in hash1.keys():
            dist = sum(h1 != h2 for h1, h2 in zip(hash1[h_type], hash2[h_type]))
            distances[h_type] = dist

        # <-- LOG de distancias Hamming
        logger.debug(f"Distancias Hamming por hash: {distances}")

        # Promedio ponderado (ajusta si lo prefieres)
        weights = {"phash": 0.5, "ahash": 0.3, "ghash": 0.2}
        weighted_distance = sum(distances[k] * weights[k] for k in distances)
        
        logger.debug(f"Distancia ponderada total = {weighted_distance:.2f}, Umbral = {self.similarity_threshold}")

        # Comparar con el umbral
        is_similar = weighted_distance <= self.similarity_threshold
        return is_similar, weighted_distance

    def analyze_image_regions(self, img1_path, img2_path):
        """
        Analiza las diferencias entre regiones de las imágenes usando múltiples métricas
        y retorna la lista de regiones que superan el umbral.
        """
        region_differences = []
        try:
            with Image.open(img1_path) as img1, Image.open(img2_path) as img2:
                img1 = img1.convert("RGB")
                img2 = img2.convert("RGB")

                # Redimensionar img2 si no coincide
                if img1.size != img2.size:
                    img2 = img2.resize(img1.size, Image.LANCZOS)

                img1_array = np.array(img1)
                img2_array = np.array(img2)

                # Dividir en regiones
                height, width, _ = img1_array.shape
                h_step = height // self.grid_size
                w_step = width // self.grid_size

                for i in range(self.grid_size):
                    for j in range(self.grid_size):
                        # Coordenadas de la región
                        top = i * h_step
                        left = j * w_step
                        # Última región podría llegar hasta el borde si no divide exacto
                        bottom = (i + 1) * h_step if i < self.grid_size - 1 else height
                        right = (j + 1) * w_step if j < self.grid_size - 1 else width

                        region1 = img1_array[top:bottom, left:right]
                        region2 = img2_array[top:bottom, left:right]

                        # Múltiples métricas
                        pixel_diff = self._calculate_pixel_difference(region1, region2)
                        hist_diff = self._calculate_histogram_difference(region1, region2)
                        edge_diff = self._calculate_edge_difference(region1, region2)

                        # Pesos ajustables; normalización previa en hist_diff
                        combined_diff = (0.4 * pixel_diff +
                                         0.3 * hist_diff +
                                         0.3 * edge_diff)

                        # <-- LOG de depuración de cada región
                        logger.debug(f"Región ({i},{j}): "
                                     f"pixel_diff={pixel_diff:.2f}, "
                                     f"hist_diff={hist_diff:.2f}, "
                                     f"edge_diff={edge_diff:.2f}, "
                                     f"combined={combined_diff:.2f}")

                        if combined_diff > self.region_threshold:
                            region_differences.append((i, j, combined_diff))
        except Exception as e:
            logger.error(f"Error analizando regiones entre {img1_path} y {img2_path}: {e}")
        
        return region_differences

    def _calculate_pixel_difference(self, region1, region2):
        """
        Diferencia promedio de píxeles (0 a 255).
        """
        return float(np.mean(np.abs(region1 - region2)))

    def _calculate_histogram_difference(self, region1, region2):
        """
        Calcula la diferencia entre histogramas de color con normalización.
        Devolverá un valor en ~[0, 2].
        """
        # <-- NORMALIZACIÓN
        hist1, _ = np.histogram(region1, bins=64, range=(0, 255))
        hist2, _ = np.histogram(region2, bins=64, range=(0, 255))
        hist1 = hist1.astype(float)
        hist2 = hist2.astype(float)

        # Evita que una región grande dispare el hist_diff
        if hist1.sum() > 0:
            hist1 /= hist1.sum()
        if hist2.sum() > 0:
            hist2 /= hist2.sum()

        return float(np.sum(np.abs(hist1 - hist2)))

    def _calculate_edge_difference(self, region1, region2):
        """
        Calcula la diferencia en los bordes usando gradiente Sobel simplificado.
        Se hace con la media en escala de grises de la región.
        """
        gray1 = np.mean(region1, axis=2)
        gray2 = np.mean(region2, axis=2)

        grad1_x = np.gradient(gray1)[0]
        grad2_x = np.gradient(gray2)[0]
        grad1_y = np.gradient(gray1)[1]
        grad2_y = np.gradient(gray2)[1]

        edge_diff_x = np.mean(np.abs(grad1_x - grad2_x))
        edge_diff_y = np.mean(np.abs(grad1_y - grad2_y))

        return float((edge_diff_x + edge_diff_y) / 2)

    def check_duplicate(self, img_path, processed_hashes, processed_files):
        """
        Verifica si una imagen es duplicada usando múltiples criterios:
         1) Distancia de hash <= similarity_threshold
         2) Si pasa el hash, se analiza por regiones; si las regiones distintas <= min_differences => duplicado
        """
        logger.info(f"Verificando duplicados para: {img_path}")
        
        # Hash de la imagen actual
        current_hashes = self.calculate_image_hash(img_path)
        if not current_hashes:
            return False, None

        # 1) Comparar con archivos procesados en esta sesión
        for processed_file in processed_files:
            if str(processed_file) != str(img_path):
                stored_hashes = processed_hashes.get(str(processed_file))
                if not stored_hashes:
                    stored_hashes = self.calculate_image_hash(processed_file)
                
                similar, distance = self.compare_hashes(current_hashes, stored_hashes)
                if similar:
                    logger.debug(f"Hash similar (dist={distance:.2f}) con {processed_file.name}, comprobando regiones...")
                    differences = self.analyze_image_regions(img_path, processed_file)
                    logger.debug(f"{len(differences)} regiones superan el threshold (region_threshold={self.region_threshold})")
                    if len(differences) <= self.min_differences:
                        logger.info(f"Imagen {img_path.name} es duplicado de {processed_file.name}")
                        return True, processed_file

        # 2) Comparar con hashes almacenados previamente (si guardas hashes de ejecuciones anteriores)
        for processed_path, stored_hashes in processed_hashes.items():
            if Path(processed_path).exists():
                similar, distance = self.compare_hashes(current_hashes, stored_hashes)
                if similar:
                    logger.debug(f"Hash similar (dist={distance:.2f}) con {processed_path}, comprobando regiones...")
                    differences = self.analyze_image_regions(img_path, processed_path)
                    logger.debug(f"{len(differences)} regiones superan el threshold (region_threshold={self.region_threshold})")
                    if len(differences) <= self.min_differences:
                        logger.info(f"Imagen {img_path.name} es duplicado (almacenado) de {Path(processed_path).name}")
                        return True, Path(processed_path)

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
        
        MADRID_MUNICIPALITIES = [
                'madrid', 'móstoles', 'alcalá de henares', 'fuenlabrada', 'leganés', 
                'getafe', 'alcorcón', 'torrejón de ardoz', 'parla', 'alcobendas',
                'san sebastián de los reyes', 'pozuelo de alarcón', 'rivas-vaciamadrid',
                'las rozas', 'coslada', 'valdemoro', 'majadahonda', 'collado villalba',
                'aranjuez', 'arganda del rey', 'boadilla del monte', 'pinto', 'colmenar viejo',
                'tres cantos', 'san fernando de henares'
            ]
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
