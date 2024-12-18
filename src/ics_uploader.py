import imghdr
import io
import json
import logging
import os
from datetime import date, datetime
from pathlib import Path
import time

import pytz
import requests
from icalendar import Calendar, vRecur
from PIL import Image

from utils import (
    get_geolocation,
    get_next_occurrence,
    get_next_valid_date,
    load_config,
    parse_recurrence_rule,
    save_to_file,
)

logger = logging.getLogger(__name__)

def extract_event_details_from_ics(ics_file):
    events = []
    try:
        with open(ics_file, "r") as f:
            gcal = Calendar.from_ical(f.read())
            for component in gcal.walk():
                if component.name == "VEVENT":
                    try:
                        start = component.get("DTSTART").dt
                        end = component.get("DTEND").dt if component.get("DTEND") else None

                        # Convertir date a datetime si es necesario
                        if isinstance(start, date) and not isinstance(start, datetime):
                            start = datetime.combine(start, time.min)

                        # Asegurar que las fechas están en UTC
                        madrid_tz = pytz.timezone("Europe/Madrid")
                        if start.tzinfo is None:
                            start = madrid_tz.localize(start)
                        start = start.astimezone(pytz.UTC)

                        event_details = {
                            "title": str(component.get("SUMMARY")),
                            "description": str(component.get("DESCRIPTION", "")),
                            "place_name": str(component.get("LOCATION")).split(",")[0],
                            "place_address": str(component.get("LOCATION")),
                            "start_datetime": int(start.timestamp()),
                            "recurrent": None,
                            "categories": [],
                        }

                        if end:
                            if isinstance(end, date) and not isinstance(end, datetime):
                                end = datetime.combine(end, time.max)
                            if end.tzinfo is None:
                                end = madrid_tz.localize(end)
                            end = end.astimezone(pytz.UTC)
                            event_details["end_datetime"] = int(end.timestamp())
                            event_details["multidate"] = (end.date() - start.date()).days > 0
                        else:
                            event_details["multidate"] = False

                        # Manejar eventos recurrentes
                        recurrence = component.get("RRULE")
                        if recurrence:
                            rrule_string = vRecur.from_ical(recurrence).to_ical().decode()
                            event_details["recurrent"] = parse_recurrence_rule(rrule_string)

                            # Ajustar la fecha de inicio para eventos recurrentes
                            current_date = datetime.now(pytz.UTC)
                            adjusted_start = get_next_valid_date(start, rrule_string)
                            next_occurrence = get_next_occurrence(rrule_string, adjusted_start, current_date)

                            if next_occurrence:
                                event_details["start_datetime"] = int(next_occurrence.timestamp())
                                if end:
                                    duration = end - start
                                    event_details["end_datetime"] = int((next_occurrence + duration).timestamp())

                        # Añadir geolocalización y categorías si están disponibles
                        config = load_config()
                        location = get_geolocation(config, event_details["place_address"])
                        if location:
                            event_details["place_latitude"] = location["latitude"]
                            event_details["place_longitude"] = location["longitude"]
                            event_details["categories"] = location["categories"]

                        logger.info(f"Event details extracted: {event_details}")
                        events.append(event_details)
                    except Exception as e:
                        logger.error(f"Error processing event in ICS file: {e}", exc_info=True)
        return events
    except Exception as e:
        logger.error(f"Failed to extract event details from ICS file: {e}", exc_info=True)
    return []

def compress_image(image_path, max_size_kb=500):
    """Compresses an image and returns it as bytes."""
    with Image.open(image_path) as img:
        img_byte_arr = io.BytesIO()
        quality = 90
        img.save(img_byte_arr, format="JPEG", quality=quality)
        while img_byte_arr.tell() > max_size_kb * 1024 and quality > 20:
            quality -= 10
            img_byte_arr.seek(0)
            img_byte_arr.truncate()
            img.save(img_byte_arr, format="JPEG", quality=quality)
        return img_byte_arr.getvalue()

def process_events_batch(config, events, db_manager):
    """
    Procesa un lote de eventos respetando los límites de la API.
    Máximo 6 eventos cada 5 minutos.
    """
    MAX_BATCH_SIZE = 5  # Dejamos uno de margen del límite de 6
    WAIT_TIME = 60      # 60 segundos entre eventos
    
    logger.info(f"Iniciando procesamiento de {len(events)} eventos")
    
    # Procesar en lotes
    for i in range(0, len(events), MAX_BATCH_SIZE):
        batch = events[i:i + MAX_BATCH_SIZE]
        logger.info(f"Procesando lote {i//MAX_BATCH_SIZE + 1}, {len(batch)} eventos")
        
        for event_details in batch:
            base_filename = event_details.get('base_filename', '')
            event_id = f"{event_details['title']}_{event_details['start_datetime']}_{event_details['place_name']}"
            
            if not db_manager.is_event_sent(event_id):
                try:
                    image_path = f"{config['directories']['images']}/{base_filename}.jpg"
                    success = send_event(config, event_details, base_filename, image_path)
                    
                    if success:
                        db_manager.mark_event_as_sent(event_id)
                        logger.info(f"Evento enviado y marcado: {event_id}")
                    else:
                        logger.warning(f"Fallo al enviar evento: {event_id}")
                    
                    # Esperar entre eventos del mismo lote
                    time.sleep(WAIT_TIME)
                    
                except Exception as e:
                    logger.error(f"Error procesando evento {event_id}: {e}")
            else:
                logger.info(f"Evento ya enviado anteriormente: {event_id}")
        
        # Si hay más lotes por procesar, esperar 5 minutos antes del siguiente
        if i + MAX_BATCH_SIZE < len(events):
            wait_time = 300  # 5 minutos
            logger.info(f"Esperando {wait_time} segundos antes del siguiente lote...")
            time.sleep(wait_time)

def prepare_files(image_path, data):
    """Prepara los archivos para el envío multipart/form-data."""
    try:
        files = []
        
        # Agregar campos base como form-data
        for key, value in data.items():
            if key != "tags":
                files.append((key, (None, str(value))))

        # Agregar tags como campos separados
        for tag in data["tags"]:
            files.append(("tags", (None, str(tag))))

        # Agregar coordenadas si existen
        if "place_latitude" in data and "place_longitude" in data:
            files.extend([
                ("place_latitude", (None, str(data["place_latitude"]))),
                ("place_longitude", (None, str(data["place_longitude"])))
            ])

        # Agregar imagen si existe
        if image_path and Path(image_path).exists():
            try:
                image_bytes = compress_image(image_path)
                files.extend([
                    ("image", ("image.jpg", image_bytes, "image/jpeg")),
                    ("image_name", (None, "")),
                    ("image_focalpoint", (None, "0,0"))
                ])
            except Exception as e:
                logger.error(f"Error procesando imagen {image_path}: {e}")

        return files

    except Exception as e:
        logger.error(f"Error preparando archivos: {e}")
        return None

def send_event(config, event_details, base_filename, image_path=None, max_retries=3):
    """Envía un evento a la API con manejo de rate limit."""
    api_url = config["gancio_api"]["url"].rstrip('"')
    api_token = config["gancio_api"].get("token")
    
    def handle_rate_limit(retry_count):
        """Maneja el rate limit con espera exponencial"""
        wait_time = min(300, 60 * (2 ** retry_count))
        logger.warning(f"Rate limit alcanzado. Esperando {wait_time} segundos...")
        time.sleep(wait_time)

    try:
        # Preparar datos del evento
        data = {
            "title": str(event_details.get("title", "")).strip(),
            "description": event_details.get("description", ""),
            "place_name": str(event_details.get("place_name", "")).strip(),
            "place_address": str(event_details.get("place_address", "")).strip(),
            "start_datetime": str(event_details.get("start_datetime")),
            "end_datetime": str(event_details.get("end_datetime", "")),
            "online": "false",
            "multidate": str(event_details.get("multidate", False)).lower(),
            "tags": event_details.get("tags", ["Generado automáticamente"])
        }

        # Añadir coordenadas si existen
        if "place_latitude" in event_details and "place_longitude" in event_details:
            data["place_latitude"] = event_details["place_latitude"]
            data["place_longitude"] = event_details["place_longitude"]

        files = prepare_files(image_path, data)
        if not files:
            return False

        headers = {"Authorization": f"Bearer {api_token}"} if api_token else {}
        
        for retry in range(max_retries):
            try:
                response = requests.post(
                    api_url,
                    files=files,
                    headers=headers,
                    timeout=30
                )
                
                if response.status_code == 200:
                    logger.info(f"Evento enviado exitosamente: {data['title']}")
                    return True
                elif response.status_code == 429:
                    if retry < max_retries - 1:
                        handle_rate_limit(retry)
                        continue
                    logger.error("Se alcanzó el límite de reintentos por rate limit")
                    return False
                else:
                    logger.error(f"Error {response.status_code}: {response.text}")
                    return False
                    
            except requests.exceptions.Timeout:
                logger.error("Timeout en la petición")
                if retry < max_retries - 1:
                    time.sleep(30)
                    continue
            except Exception as e:
                logger.error(f"Error inesperado: {e}")
                return False

        return False
        
    except Exception as e:
        logger.error(f"Error en send_event: {e}", exc_info=True)
        return False