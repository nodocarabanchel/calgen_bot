import logging
from pathlib import Path
import requests
import json
from icalendar import Calendar
from utils import get_geolocation, save_to_file

def extract_event_details_from_ics(ics_file):
    logging.info(f"Extracting event details from ICS file: {ics_file}")
    try:
        with open(ics_file, 'r') as f:
            gcal = Calendar.from_ical(f.read())
            for component in gcal.walk():
                if component.name == "VEVENT":
                    event_details = {
                        'title': str(component.get('SUMMARY')),
                        'description': str(component.get('DESCRIPTION')),
                        'place_name': str(component.get('LOCATION')).split(",")[0],
                        'place_address': str(component.get('LOCATION')),
                        'start_datetime': int(component.get('DTSTART').dt.timestamp()),
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
        logging.info(f"Data successfully saved to file: {file_path}")
    except Exception as e:
        logging.error(f"Failed to save data to file: {e}")

def send_event(config, event_details, base_filename):
    api_url = config["gancio_api"]["url"]
    api_token = config["gancio_api"].get("token")

    logging.info(f"Sending event: {event_details['title']}")

    lat, lng = get_geolocation(config, event_details['place_address'])
    if lat is not None and lng is not None:
        event_details['place_latitude'] = lat
        event_details['place_longitude'] = lng
        logging.info(f"Geolocation obtained: Latitude {lat}, Longitude {lng}")
    else:
        logging.warning("Geolocation could not be obtained.")

    data = {
        'title': event_details['title'],
        'description': event_details['description'],
        'place_name': event_details['place_name'],
        'place_address': event_details['place_address'],
        'place_latitude': str(event_details.get('place_latitude', '')),
        'place_longitude': str(event_details.get('place_longitude', '')),
        'start_datetime': str(event_details['start_datetime']),
        'tags[]': 'test tag',  # Assuming a test tag for this example
        'multidate': 'false',  # Assuming this field for this example
    }

    headers = {
        'Authorization': f'Bearer {api_token}' if api_token else '',
        'Content-Type': 'multipart/form-data'
    }

    # Save data to a file
    api_data_directory = Path("api_data")
    api_data_directory.mkdir(exist_ok=True)
    file_path = api_data_directory / f"{base_filename}.json"
    save_to_file(data, file_path)

    # Format the payload for multipart/form-data
    files = {
        'title': (None, data['title']),
        'description': (None, data['description']),
        'place_name': (None, data['place_name']),
        'place_address': (None, data['place_address']),
        'place_latitude': (None, data['place_latitude']),
        'place_longitude': (None, data['place_longitude']),
        'start_datetime': (None, data['start_datetime']),
        'tags[]': (None, data['tags[]']),
        'multidate': (None, data['multidate']),
    }

    try:
        logging.info(f"Headers: {headers}")
        logging.info(f"Files: {files}")

        response = requests.post(api_url, files=files, headers=headers)
        logging.info(f'Event sent. Status Code: {response.status_code}, Response: {response.text}')
    except Exception as e:
        logging.error(f"Failed to send event: {e}")

    if response.status_code == 404:
        logging.error(f"404 Not Found: The endpoint {api_url} does not exist.")
    elif response.status_code != 200:
        logging.error(f"Error {response.status_code}: {response.text}")

    return response

