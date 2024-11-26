import imghdr
import io
import json
import logging
import os
from datetime import date, datetime, time
from pathlib import Path
from time import sleep

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

def send_event(config, event_details, base_filename, image_path=None, max_retries=5):
    # Configuración del primer sitio
    api_url_primary = config["gancio_api"]["url"].rstrip('"')
    api_token_primary = config["gancio_api"].get("token")
    excluded_channels_primary = config["gancio_api"].get("excluded_channels", [])

    # Configuración del segundo sitio (opcional)
    api_url_secondary = config.get("secondary_api", {}).get("url", "").rstrip('"')
    api_token_secondary = config.get("secondary_api", {}).get("token")
    excluded_channels_secondary = config.get("secondary_api", {}).get("excluded_channels", [])

    # Log de URLs y tokens configurados
    logger.debug(f"Primary API URL: {api_url_primary}, Token: {'Present' if api_token_primary else 'Missing'}")
    logger.debug(f"Secondary API URL: {api_url_secondary}, Token: {'Present' if api_token_secondary else 'Missing'}")

    # Obtener el ID del canal del nombre del archivo base
    channel_id = None
    try:
        # Asumimos que el base_filename contiene el ID del canal como prefijo
        channel_id = int(base_filename.split('_')[0])
    except (ValueError, IndexError):
        logger.warning(f"No se pudo extraer el ID del canal del archivo: {base_filename}")

    # Datos del evento
    data = {
        "title": event_details["title"].rstrip("`"),
        "place_name": event_details["place_name"],
        "place_address": event_details["place_address"].rstrip("`"),
        "start_datetime": str(int(event_details["start_datetime"])),
        "multidate": "false",
    }

    if "end_datetime" in event_details:
        data["end_datetime"] = str(int(event_details["end_datetime"]))
        data["multidate"] = "true" if (event_details["end_datetime"] - event_details["start_datetime"]) > 86400 else "false"

    # Preparar archivos para enviar (incluyendo imagen si disponible)
    def prepare_files(image_path):
        files = {key: ("", value) for key, value in data.items()}
        if image_path and Path(image_path).exists():
            # Comprimir imagen en memoria
            image_bytes = compress_image(image_path)
            files["image"] = ("image.jpg", image_bytes, "image/jpeg")
            files["image_name"] = (None, "")
            files["image_focalpoint"] = (None, "0,0")
        return files

    # Función para hacer la solicitud a una API
    def post_event(api_url, headers, files):
        retries = 0
        success = False
        while retries < max_retries:
            try:
                logger.info(f"Attempting to send event to {api_url} (Attempt {retries + 1}/{max_retries})")
                response = requests.post(api_url, files=files, headers=headers if headers else {})
                if response.status_code == 200:
                    logger.info(f"Successfully sent event to {api_url}")
                    success = True
                    break
                elif response.status_code == 429:
                    retries += 1
                    sleep(2**retries)
                else:
                    logger.error(f"Error {response.status_code}: {response.text}")
                    break
            except Exception as e:
                logger.error(f"Failed to send event to {api_url}: {e}")
                break
        return success

    # Enviar al primer sitio si el canal no está excluido
    primary_success = True
    if channel_id not in excluded_channels_primary:
        headers_primary = {"Authorization": f"Bearer {api_token_primary}"} if api_token_primary else None
        primary_success = post_event(api_url_primary, headers_primary, prepare_files(image_path))
    else:
        logger.info(f"Canal {channel_id} excluido de la API primaria. No se enviará el evento.")

    # Enviar al segundo sitio si el canal no está excluido
    secondary_success = True
    if api_url_secondary and channel_id not in excluded_channels_secondary:
        headers_secondary = {"Authorization": f"Bearer {api_token_secondary}"} if api_token_secondary else None
        secondary_success = post_event(api_url_secondary, headers_secondary, prepare_files(image_path))
    else:
        logger.info(f"Canal {channel_id} excluido de la API secundaria o API secundaria no configurada.")

    # Retornar el estado de éxito por separado para cada envío
    return primary_success, secondary_success