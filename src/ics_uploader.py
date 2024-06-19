import requests
import os
from pathlib import Path
import logging


def upload_ics_file(api_url, file_path, headers):
    with open(file_path, 'rb') as file:
        files = {'file': (file_path.name, file, 'text/calendar')}
        response = requests.post(api_url, files=files, headers=headers)
    return response

def delete_file(file_path):
    os.remove(file_path)
    logging.info(f"Deleted {file_path}")

# Example usage
api_url = 'https://example.com/calendar/api/upload'  # Replace with actual API endpoint
headers = {'Authorization': 'Bearer YOUR_ACCESS_TOKEN'}  # Replace with actual headers/authorization if needed

ics_folder = Path("path/to/ics_files")
for ics_file in ics_folder.glob("*.ics"):
    response = upload_ics_file(api_url, ics_file, headers)
    if response.status_code == 200:
        logging.info(f"Successfully uploaded {ics_file}")
        delete_file(ics_file)
    else:
        logging.error(f"Failed to upload {ics_file}: {response.text}")
