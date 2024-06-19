import logging
from pathlib import Path
from icalendar import Calendar
import requests
import json
from utils import get_geolocation, save_to_file

def extract_event_details_from_ics(ics_file):
    with open(ics_file, 'r') as f:
        gcal = Calendar.from_ical(f.read())
        for component in gcal.walk():
            if component.name == "VEVENT":
                event_details = {
                    'title': str(component.get('SUMMARY')),
                    'description': str(component.get('DESCRIPTION')),
                    'place_name': str(component.get('LOCATION')).split(",")[0],  # Asume que el nombre del lugar es la primera parte de la ubicación
                    'place_address': str(component.get('LOCATION')),
                    'start_datetime': int(component.get('DTSTART').dt.timestamp()),
                }
                return event_details
    return None

def save_to_file(data, file_path):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def send_event(config, event_details, base_filename):
    api_url = config["gancio_api"]["url"]
    api_token = config["gancio_api"].get("token")

    # Obtener la latitud y longitud usando la API de OpenCage
    lat, lng = get_geolocation(config, event_details['place_address'])
    if lat is not None and lng is not None:
        event_details['place_latitude'] = lat
        event_details['place_longitude'] = lng

    data = {
        'title': event_details['title'],
        'description': event_details['description'],
        'place_name': event_details['place_name'],
        'place_address': event_details['place_address'],
        'place_latitude': str(event_details.get('place_latitude', '')),
        'place_longitude': str(event_details.get('place_longitude', '')),
        'start_datetime': str(event_details['start_datetime']),
    }

    headers = {}
    if api_token:
        headers['Authorization'] = f'Bearer {api_token}'

    # Guardar datos en un archivo
    api_data_directory = Path("api_data")
    api_data_directory.mkdir(exist_ok=True)
    file_path = api_data_directory / f"{base_filename}.json"
    save_to_file(data, file_path)

    response = requests.post(api_url, data=data, headers=headers)
    logging.info(f'Status Code: {response.status_code}, Response: {response.text}')
    return response
