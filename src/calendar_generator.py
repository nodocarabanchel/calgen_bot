import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
from PIL import Image
from dateutil import parser
from google.cloud import documentai_v1beta3 as documentai
from google.oauth2 import service_account
from google.api_core.client_options import ClientOptions
import easyocr
import pytesseract
from ics import Calendar, Event
from groq import Groq
import re
import pytz


class OCRReader:
    SUPPORTED_FORMATS = ['.jpg', '.jpeg', '.png', '.bmp', '.pdf', '.tiff', '.tif', '.gif']

    def __init__(self, service: str, google_config: Optional[Dict[str, str]] = None):
        self.service = service
        if service == 'easyocr':
            logging.info("Using EasyOCR for text extraction.")
            self.reader = easyocr.Reader(['es'])
        elif service == 'documentai':
            if not google_config:
                raise ValueError("Google Document AI configuration is missing.")
            self.project_id = google_config['project_id']
            self.location = google_config['location']
            self.processor_id = google_config['processor_id']
            self.credentials = service_account.Credentials.from_service_account_file(
                google_config['credentials_path']
            )
            self.client_options = ClientOptions(api_endpoint=f"{self.location}-documentai.googleapis.com")
        else:
            raise ValueError("Invalid OCR service. Choose either 'easyocr' or 'documentai'.")

    def read(self, image_path: Path) -> Optional[str]:
        if image_path.suffix.lower() not in OCRReader.SUPPORTED_FORMATS:
            return None
        
        try:
            if self.service == 'easyocr':
                easy_ocr_result = self.reader.readtext(str(image_path))
                easy_ocr_text = ' '.join([item[1] for item in easy_ocr_result])
                tesseract_text = pytesseract.image_to_string(Image.open(image_path))
                combined_text = f"{easy_ocr_text} {tesseract_text}"
            elif self.service == 'documentai':
                docai_client = documentai.DocumentProcessorServiceClient(
                    client_options=self.client_options,
                    credentials=self.credentials
                )
                resource_name = docai_client.processor_path(self.project_id, self.location, self.processor_id)
                
                with open(image_path, "rb") as image:
                    image_content = image.read()

                raw_document = documentai.RawDocument(content=image_content, mime_type=self.get_mime_type(image_path))
                request = documentai.ProcessRequest(name=resource_name, raw_document=raw_document)
                result = docai_client.process_document(request=request)

                document_object = result.document
                combined_text = document_object.text

            return combined_text
        except Exception as e:
            logging.exception("Error during text extraction: %s", e)
            return None

    def get_mime_type(self, image_path: Path) -> str:
        suffix = image_path.suffix.lower()
        if suffix in ['.jpg', '.jpeg']:
            return 'image/jpeg'
        elif suffix == '.png':
            return 'image/png'
        elif suffix == '.bmp':
            return 'image/bmp'
        elif suffix in ['.tiff', '.tif']:
            return 'image/tiff'
        elif suffix == '.gif':
            return 'image/gif'
        elif suffix == '.pdf':
            return 'application/pdf'
        else:
            raise ValueError(f"Unsupported file extension: {suffix}")

class EntityExtractor:
    def __init__(self, config):
        self.config = config
        self.max_retries = 3  # Maximum number of retries per image
        self.client = None
        if config.get('external_api', {}).get('use') and config['external_api']['service'] == 'groq':
            self.client = Groq(api_key=config['external_api']['api_key'])

    def extract_event_info(self, text: str):
        model_type = self.config['external_api']['service'] if self.config['external_api']['use'] else 'local_model'
        prompt = (f"¿Cuál es el título, la fecha, hora de inicio y final (si lo tiene), el lugar del evento y si es recurrente en formato ICS "
                  f"(SUMMARY, DTSTART, LOCATION) y sin comentarios asumiendo que estamos en España y que si no "
                  f"se especifica el año, es el actual ({datetime.now().year})?: {text}")

        retries = 0
        while retries < self.max_retries:
            try:
                if model_type == 'groq' and self.client:
                    logging.debug(f"Sending request to Groq API with prompt: {prompt}")
                    chat_completion = self.client.chat.completions.create(
                        messages=[{"role": "user", "content": prompt}],
                        model=self.config['external_api']['model_name'],
                    )
                    logging.debug(f"Received response from Groq API: {chat_completion}")
                    content = chat_completion.choices[0].message.content
                elif model_type == 'local_model' and self.config['local_model']['use']:
                    response = ollama.chat(
                        model=self.config['local_model']['model_name'],
                        messages=[{'role': 'user', 'content': prompt}]
                    )
                    content = response['message']['content'].strip() if 'message' in response and 'content' in response['message'] else "Datos no encontrados"

                summary = self.extract_field("SUMMARY", content)
                dtstart = self.clean_date(self.extract_field("DTSTART", content))
                location = self.extract_field("LOCATION", content)
                description = text  # Use the extracted text as the description

                if all([summary, dtstart, location]):
                    return {'summary': summary, 'dtstart': dtstart, 'location': location, 'description': description}

                retries += 1
            except Exception as e:
                logging.error(f"Error during event info extraction: {e}")
                retries += 1

        logging.error("Failed to extract complete event info after maximum retries.")
        return None

    @staticmethod
    def extract_field(field, text):
        pattern = rf"{field}:([^\n\r]+)"
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def clean_date(date_str):
        if date_str:
            # Remove any unwanted characters from the date string
            clean_date_str = re.sub(r'[^\dT]', '', date_str)
            if re.match(r'\d{8}T\d{6}', clean_date_str):
                return clean_date_str
        return None
    
class ICSExporter:
    def export(self, entities: Dict[str, str], output_path: Path):
        if not entities.get('date'):
            logging.error("No date provided for ICS export.")
            return

        try:
            date_str = entities['date']
            logging.info(f"Attempting to parse date: {date_str}")
            
            # Intentar diferentes formatos de fecha
            try:
                date_obj = parser.parse(date_str)
            except parser.ParserError:
                # Si falla, intentar con un formato específico
                date_obj = datetime.strptime(date_str, "%Y%m%dT%H%M%S")
            
            cest = pytz.timezone("Europe/Madrid")
            if date_obj.tzinfo is None:
                date_obj = cest.localize(date_obj)
            else:
                date_obj = date_obj.astimezone(cest)
            
            calendar = Calendar()
            event = Event()
            
            event.begin = date_obj
            event.name = entities.get("summary", "Evento Desconocido")
            event.location = entities.get("location", "Ubicación Desconocida")
            event.description = entities.get("description", "No description provided")

            calendar.events.add(event)

            calendar_data = calendar.serialize()
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(calendar_data)
            
            logging.info(f"ICS file exported successfully preserving CEST timezone: {output_path}")
            logging.info(f"Exported date: {date_obj}, Timezone: {date_obj.tzinfo}")
        except ValueError as e:
            logging.error(f"Error parsing date for ICS export: {e}")
            logging.error(f"Problematic date string: {entities.get('date')}")
        except Exception as e:
            logging.error(f"An unexpected error occurred while exporting the ICS: {e}", exc_info=True)  

