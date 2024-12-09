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
    """Envía un evento a las APIs configuradas."""
    # Configuración de APIs
    api_url_primary = config["gancio_api"]["url"].rstrip('"')
    api_token_primary = config["gancio_api"].get("token")
    excluded_channels_primary = config["gancio_api"].get("excluded_channels", [])

    api_url_secondary = config.get("secondary_api", {}).get("url", "").rstrip('"')
    api_token_secondary = config.get("secondary_api", {}).get("token")
    excluded_channels_secondary = config.get("secondary_api", {}).get("excluded_channels", [])

    logger.debug(f"Primary API URL: {api_url_primary}, Token present: {'Yes' if api_token_primary else 'No'}")
    logger.debug(f"Secondary API URL: {api_url_secondary}, Token present: {'Yes' if api_token_secondary else 'No'}")

    # Extraer información del canal
    channel_id = None
    channel_name = None
    try:
        channel_parts = base_filename.split('_')
        if len(channel_parts) > 0:
            channel_id = int(channel_parts[0])
            for channel in config["telegram_bot"]["channels"]:
                if int(channel["id"]) == channel_id:
                    channel_name = channel["name"]
                    break
    except (ValueError, IndexError) as e:
        logger.warning(f"Error extracting channel info from {base_filename}: {e}")

    # Preparar datos del evento
    try:
        # Asegurar que los timestamps son enteros válidos
        start_timestamp = int(float(event_details["start_datetime"]))
        end_timestamp = int(float(event_details.get("end_datetime", start_timestamp + 7200)))

        description = []

        if event_details.get("description"):
            description_text = event_details["description"].strip()
            description_text += "\n\n"
            description.append(description_text)

        data = {
            "title": str(event_details.get("title", "")).strip(),
            "description": "".join(description),  
            "place_name": str(event_details.get("place_name", "")).strip(),
            "place_address": str(event_details.get("place_address", "")).strip(),
            "start_datetime": str(start_timestamp),
            "end_datetime": str(end_timestamp),
            "online": "false",
            "multidate": str((end_timestamp - start_timestamp) > 86400).lower(),
            "tags": [
                "Generado automáticamente",
                channel_name if channel_name else "CalGen"
            ] + event_details.get("categories", [])
        }

        # Añadir geolocalización si está disponible
        if "place_latitude" in event_details and "place_longitude" in event_details:
            data["place_latitude"] = str(event_details["place_latitude"])
            data["place_longitude"] = str(event_details["place_longitude"])

        logger.debug(f"Prepared event data: {json.dumps(data, indent=2, ensure_ascii=False)}")

        def prepare_files(image_path, data):
            """Prepara los archivos para el envío multipart/form-data."""
            try:
                files = []
                
                # Agregar campos base como form-data
                files.extend([
                    ("title", (None, data["title"])),
                    ("description", (None, data["description"])),
                    ("place_name", (None, data["place_name"])),
                    ("place_address", (None, data["place_address"])),
                    ("start_datetime", (None, data["start_datetime"])),
                    ("end_datetime", (None, data["end_datetime"])),
                    ("online", (None, data["online"])),
                    ("multidate", (None, data["multidate"]))
                ])

                # Agregar coordenadas si existen
                if "place_latitude" in data and "place_longitude" in data:
                    files.extend([
                        ("place_latitude", (None, data["place_latitude"])),
                        ("place_longitude", (None, data["place_longitude"]))
                    ])

                # Agregar tags como campos separados
                for tag in data["tags"]:
                    files.append(("tags", (None, str(tag))))

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
                        logger.error(f"Error processing image {image_path}: {e}")

                return files

            except Exception as e:
                logger.error(f"Error preparing files: {e}", exc_info=True)
                return None

        def post_event(api_url, headers, files):
            """Envía el evento a una API específica con reintentos."""
            if not files:
                logger.error("No files prepared for sending")
                return False

            retries = 0
            while retries < max_retries:
                try:
                    logger.info(f"Sending event to {api_url} (Attempt {retries + 1}/{max_retries})")
                    
                    response = requests.post(
                        api_url,
                        files=files,
                        headers=headers if headers else {},
                        timeout=30
                    )
                    
                    if response.status_code == 200:
                        logger.info(f"Successfully sent event: {data['title']}")
                        return True
                    else:
                        logger.error(f"Error {response.status_code} sending event to {api_url}")
                        logger.error(f"Response: {response.text}")
                        
                        if response.status_code == 400:
                            logger.error("Bad Request. Form data being sent:")
                            for field in files:
                                if field[0] == "image":
                                    logger.error(f"Field: {field[0]}, Type: image/jpeg")
                                else:
                                    logger.error(f"Field: {field[0]}, Value: {field[1][1]}")
                            break
                        elif response.status_code == 429:
                            wait_time = 2 ** retries
                            logger.warning(f"Rate limited. Waiting {wait_time} seconds...")
                            sleep(wait_time)
                            retries += 1
                            continue
                        break

                except requests.exceptions.Timeout:
                    logger.error("Request timed out")
                    retries += 1
                except requests.exceptions.RequestException as e:
                    logger.error(f"Request error: {e}")
                    retries += 1
                except Exception as e:
                    logger.error(f"Unexpected error: {e}", exc_info=True)
                    break

                if retries < max_retries:
                    sleep(2 ** retries)
                    continue

            return False

        # Envío a API primaria
        primary_success = False
        if channel_id not in excluded_channels_primary:
            headers_primary = {"Authorization": f"Bearer {api_token_primary}"} if api_token_primary else None
            files = prepare_files(image_path, data)
            primary_success = post_event(api_url_primary, headers_primary, files)
        else:
            logger.info(f"Channel {channel_id} ({channel_name}) excluded from primary API")

        # Envío a API secundaria
        secondary_success = False
        if api_url_secondary and channel_id not in excluded_channels_secondary:
            headers_secondary = {"Authorization": f"Bearer {api_token_secondary}"} if api_token_secondary else None
            files = prepare_files(image_path, data)
            secondary_success = post_event(api_url_secondary, headers_secondary, files)
        else:
            logger.info(f"Channel {channel_id} ({channel_name}) excluded from secondary API")

        return primary_success, secondary_success

    except Exception as e:
        logger.error(f"Error in send_event: {e}", exc_info=True)
        return False, False