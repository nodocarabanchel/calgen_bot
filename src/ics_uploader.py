import logging
from pathlib import Path
import requests
import json
from icalendar import Calendar
from utils import get_geolocation, save_to_file
import imghdr
from PIL import Image
import io
from time import sleep, time
from datetime import datetime, timedelta

def extract_event_details_from_ics(ics_file):
    try:
        with open(ics_file, 'r') as f:
            gcal = Calendar.from_ical(f.read())
            for component in gcal.walk():
                if component.name == "VEVENT":
                    start = component.get('DTSTART').dt
                    end = component.get('DTEND', component.get('DTSTART')).dt
                    
                    # Manejar eventos de varios días
                    is_multi_day = False
                    if isinstance(start, datetime) and isinstance(end, datetime):
                        duration = end - start
                        is_multi_day = duration.days > 0

                    # Manejar eventos recurrentes
                    recurrence = component.get('RRULE')
                    recurrence_info = None
                    if recurrence:
                        recurrence_info = vRecur.from_ical(recurrence).to_ical().decode()

                    event_details = {
                        'title': str(component.get('SUMMARY')),
                        'description': str(component.get('DESCRIPTION', '')),
                        'place_name': str(component.get('LOCATION')).split(",")[0],
                        'place_address': str(component.get('LOCATION')),
                        'start_datetime': int(start.timestamp()),
                        'end_datetime': int(end.timestamp()) if end else None,
                        'is_multi_day': is_multi_day,
                        'recurrence': recurrence_info
                    }
                    logging.info(f"Event details extracted: {event_details}")
                    return event_details
    except Exception as e:
        logging.error(f"Failed to extract event details from ICS file: {e}")
    return None


def save_to_file(data, file_path):
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"Failed to save data to file: {e}")

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
    api_url = config["gancio_api"]["url"].rstrip('"')  # Remove any trailing quotes
    api_token = config["gancio_api"].get("token")
    lat, lng = get_geolocation(config, event_details['place_address'])
    if lat is not None and lng is not None:
        event_details['place_latitude'] = lat
        event_details['place_longitude'] = lng
    else:
        logging.warning("Geolocation could not be obtained.")

    data = {
        'title': event_details['title'],
        'place_name': event_details['place_name'],
        'place_address': event_details['place_address'],
        'place_latitude': str(event_details.get('place_latitude', '')),
        'place_longitude': str(event_details.get('place_longitude', '')),
        'start_datetime': str(event_details['start_datetime']),
        'tags[]': '',
        'multidate': 'false',
    }

    # Add description if it exists and is not empty
    if event_details.get('description') and event_details['description'].strip():
        data['description'] = event_details['description'].strip()

    headers = {}
    if api_token:
        headers['Authorization'] = f'Bearer {api_token}'

    # Save data to a file
    api_data_directory = Path("api_data")
    api_data_directory.mkdir(exist_ok=True)
    file_path = api_data_directory / f"{base_filename}.json"
    save_to_file(data, file_path)

    # Format the payload for multipart/form-data
    files = {key: ("", value) for key, value in data.items()}

    if image_path and Path(image_path).exists():
        img_type = imghdr.what(image_path)
        if img_type in ['jpeg', 'png', 'gif']:  # Add or remove types as accepted by the API
            compressed_image = compress_image(image_path)
            files['image'] = (f'image.{img_type}', compressed_image, f'image/{img_type}')
            files['image_name'] = (None, '')
            files['image_focalpoint'] = (None, '0,0')
        else:
            logging.warning(f"Unsupported image type: {img_type}")
    else:
        logging.warning("Image path is not provided or does not exist.")

    retries = 0
    total_wait_time = 0
    max_wait_time = 300  # 5 minutes

    while retries < max_retries and total_wait_time < max_wait_time:
        try:
            response = requests.post(api_url, files=files, headers=headers)
            logging.info(f'Event sent. Status Code: {response.status_code}, Response: {response.text}')
            
            if response.status_code == 200:
                return response
            elif response.status_code == 404:
                logging.error(f"404 Not Found: The endpoint {api_url} does not exist.")
                break
            elif response.status_code == 429:
                wait_time = min(2 ** retries, max_wait_time - total_wait_time)
                total_wait_time += wait_time
                logging.warning(f"429 Too Many Requests: Retrying after backoff. Attempt {retries + 1} of {max_retries}. Waiting for {wait_time} seconds.")
                retries += 1
                sleep(wait_time)  # Exponential backoff
            elif response.status_code == 500:
                logging.error(f"500 Internal Server Error: {response.text}")
                break
            else:
                logging.error(f"Error {response.status_code}: {response.text}")
                break
        except Exception as e:
            logging.error(f"Failed to send event: {e}")
            break

    return None
