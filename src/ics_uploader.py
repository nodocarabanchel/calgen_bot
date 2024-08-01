import logging
from pathlib import Path
import requests
import json
from icalendar import Calendar, vRecur
from utils import get_geolocation, save_to_file, load_config, parse_recurrence_rule, get_next_valid_date, get_next_occurrence
import imghdr
from PIL import Image
import io
from time import sleep
from datetime import datetime, date, time, timedelta
import pytz

logger = logging.getLogger(__name__)

def extract_event_details_from_ics(ics_file):
    events = []
    try:
        with open(ics_file, 'r') as f:
            gcal = Calendar.from_ical(f.read())
            for component in gcal.walk():
                if component.name == "VEVENT":
                    try:
                        start = component.get('DTSTART').dt
                        end = component.get('DTEND').dt if component.get('DTEND') else None
                        
                        # Convertir date a datetime si es necesario
                        if isinstance(start, date) and not isinstance(start, datetime):
                            start = datetime.combine(start, time.min)

                        # Asegurar que las fechas están en UTC
                        madrid_tz = pytz.timezone('Europe/Madrid')
                        if start.tzinfo is None:
                            start = madrid_tz.localize(start)
                        start = start.astimezone(pytz.UTC)

                        event_details = {
                            'title': str(component.get('SUMMARY')),
                            'description': str(component.get('DESCRIPTION', '')),
                            'place_name': str(component.get('LOCATION')).split(",")[0],
                            'place_address': str(component.get('LOCATION')),
                            'start_datetime': int(start.timestamp()),
                            'recurrent': None,
                            'categories': []
                        }

                        if end:
                            if isinstance(end, date) and not isinstance(end, datetime):
                                end = datetime.combine(end, time.max)
                            if end.tzinfo is None:
                                end = madrid_tz.localize(end)
                            end = end.astimezone(pytz.UTC)
                            event_details['end_datetime'] = int(end.timestamp())
                            event_details['multidate'] = (end.date() - start.date()).days > 0
                        else:
                            event_details['multidate'] = False

                        # Manejar eventos recurrentes
                        recurrence = component.get('RRULE')
                        if recurrence:
                            rrule_string = vRecur.from_ical(recurrence).to_ical().decode()
                            event_details['recurrent'] = parse_recurrence_rule(rrule_string)
                            
                            # Ajustar la fecha de inicio para eventos recurrentes
                            current_date = datetime.now(pytz.UTC)
                            adjusted_start = get_next_valid_date(start, rrule_string)
                            next_occurrence = get_next_occurrence(rrule_string, adjusted_start, current_date)
                            
                            if next_occurrence:
                                event_details['start_datetime'] = int(next_occurrence.timestamp())
                                if end:
                                    duration = end - start
                                    event_details['end_datetime'] = int((next_occurrence + duration).timestamp())

                        # Add geolocation and categories if available
                        config = load_config()
                        location = get_geolocation(config, event_details['place_address'])
                        if location:
                            event_details['place_latitude'] = location['latitude']
                            event_details['place_longitude'] = location['longitude']
                            event_details['categories'] = location['categories']

                        logger.info(f"Event details extracted: {event_details}")
                        events.append(event_details)
                    except Exception as e:
                        logger.error(f"Error processing event in ICS file: {e}", exc_info=True)
        return events
    except Exception as e:
        logger.error(f"Failed to extract event details from ICS file: {e}", exc_info=True)
    return []

def compress_image(image_path, max_size_kb=500):
    img = Image.open(image_path)
    img_byte_arr = io.BytesIO()
    quality = 90
    img.save(img_byte_arr, format='JPEG', quality=quality)
    while img_byte_arr.tell() > max_size_kb * 1024 and quality > 20:
        quality -= 10
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='JPEG', quality=quality)
    img_byte_arr.seek(0)
    return img_byte_arr

def send_event(config, event_details, base_filename, image_path=None, max_retries=5):
    api_url = config["gancio_api"]["url"].rstrip('"')
    api_token = config["gancio_api"].get("token")

    start_datetime = datetime.fromtimestamp(event_details['start_datetime'], tz=pytz.UTC)

    data = {
        'title': event_details['title'].rstrip('`'),
        'place_name': event_details['place_name'],
        'place_address': event_details['place_address'].rstrip('`'),
        'start_datetime': str(int(start_datetime.timestamp())),
        'multidate': 'false'
    }

    if 'end_datetime' in event_details:
        end_datetime = datetime.fromtimestamp(event_details['end_datetime'], tz=pytz.UTC)
        data['end_datetime'] = str(int(end_datetime.timestamp()))
        data['multidate'] = 'true' if (end_datetime.date() - start_datetime.date()).days > 0 else 'false'
    else:
        logger.info(f"No end_datetime provided for event '{event_details['title']}'. Event will have no end time.")

    if 'recurrent' in event_details and event_details['recurrent']:
        data['recurrent'] = json.dumps(event_details['recurrent'])
    else:
        data['recurrent'] = ''

    if 'place_latitude' in event_details and 'place_longitude' in event_details:
        data['place_latitude'] = str(event_details['place_latitude'])
        data['place_longitude'] = str(event_details['place_longitude'])

    if 'description' in event_details and event_details['description'].strip():
        data['description'] = event_details['description'].strip()

    categories = event_details.get('categories', [])
    if categories:
        for i, category in enumerate(categories):
            data[f'tags[{i}]'] = category

    headers = {}
    if api_token:
        headers['Authorization'] = f'Bearer {api_token}'

    api_data_directory = Path("api_data")
    api_data_directory.mkdir(exist_ok=True)
    file_path = api_data_directory / f"{base_filename}.json"
    save_to_file(data, file_path)

    files = {key: ("", value) for key, value in data.items()}

    if image_path and Path(image_path).exists():
        img_type = imghdr.what(image_path)
        if img_type in ['jpeg', 'png', 'gif']:
            compressed_image = compress_image(image_path)
            files['image'] = (f'image.{img_type}', compressed_image, f'image/{img_type}')
            files['image_name'] = (None, '')
            files['image_focalpoint'] = (None, '0,0')
        else:
            logger.warning(f"Unsupported image type: {img_type}")
    else:
        logger.warning("Image path is not provided or does not exist.")

    # Imprimir los datos que se van a enviar para depuración
    logger.debug(f"Datos a enviar a la API: {json.dumps(data, indent=2)}")

    retries = 0
    total_wait_time = 0
    max_wait_time = 300  # 5 minutes

    while retries < max_retries and total_wait_time < max_wait_time:
        try:
            logger.info(f"Attempting to send event: {event_details['title']} (Attempt {retries + 1}/{max_retries})")
            response = requests.post(api_url, files=files, headers=headers)
            logger.info(f'Event sent. Status Code: {response.status_code}, Response: {response.text}')
            
            if response.status_code == 200:
                logger.info(f"Successfully sent event: {event_details['title']}")
                return response
            elif response.status_code == 404:
                logger.error(f"404 Not Found: The endpoint {api_url} does not exist.")
                break
            elif response.status_code == 429:
                wait_time = min(2 ** retries, max_wait_time - total_wait_time)
                total_wait_time += wait_time
                logger.warning(f"429 Too Many Requests: Retrying after backoff. Attempt {retries + 1} of {max_retries}. Waiting for {wait_time} seconds.")
                retries += 1
                sleep(wait_time)  # Exponential backoff
            elif response.status_code == 500:
                logger.error(f"500 Internal Server Error: {response.text}")
                break
            else:
                logger.error(f"Error {response.status_code}: {response.text}")
                break
        except Exception as e:
            logger.error(f"Failed to send event {event_details['title']}: {e}")
            break

    logger.warning(f"Failed to send event {event_details['title']} after {retries} attempts")
    return None