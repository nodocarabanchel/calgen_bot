from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional
from PIL import Image
from dateutil import parser, rrule
from google.cloud import documentai_v1beta3 as documentai
from google.oauth2 import service_account
from google.api_core.client_options import ClientOptions
import easyocr
import pytesseract
from ics import Calendar, Event
from ics.grammar.parse import ContentLine
from groq import Groq
import re
import pytz
from utils import setup_logging
import logging

logger = logging.getLogger(__name__)

class OCRReader:
    SUPPORTED_FORMATS = ['.jpg', '.jpeg', '.png', '.bmp', '.pdf', '.tiff', '.tif', '.gif']

    def __init__(self, service: str, google_config: Optional[Dict[str, str]] = None):
        self.service = service
        if service == 'easyocr':
            logger.info("Using EasyOCR for text extraction.")
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
            logger.exception("Error during text extraction: %s", e)
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
        self.max_retries = 3
        self.client = None
        if config.get('external_api', {}).get('use') and config['external_api']['service'] == 'groq':
            self.client = Groq(api_key=config['external_api']['api_key'])

    def extract_event_info(self, text: str):
        model_type = self.config['external_api']['service'] if self.config['external_api']['use'] else 'local_model'
        prompt = (f"Extrae la siguiente información del texto en formato ICS: "
                    f"SUMMARY (título del evento), DTSTART (fecha y hora de inicio), DTEND (fecha y hora de finalización si está disponible), "
                    f"LOCATION (ubicación), y RRULE (si es un evento recurrente). Para eventos recurrentes, proporciona la regla de recurrencia "
                    f"(por ejemplo, FREQ=WEEKLY;BYDAY=MO,WE,FR). Asume que estamos en España, y si no se especifica el año, "
                    f"usa el año actual ({datetime.now().year}). Aquí está el texto: {text}")

        retries = 0
        while retries < self.max_retries:
            try:
                if model_type == 'groq' and self.client:
                    logger.debug(f"Sending request to Groq API with prompt: {prompt}")
                    chat_completion = self.client.chat.completions.create(
                        messages=[{"role": "user", "content": prompt}],
                        model=self.config['external_api']['model_name'],
                    )
                    logger.debug(f"Received response from Groq API: {chat_completion}")
                    content = chat_completion.choices[0].message.content
                elif model_type == 'local_model' and self.config['local_model']['use']:
                    response = ollama.chat(
                        model=self.config['local_model']['model_name'],
                        messages=[{'role': 'user', 'content': prompt}]
                    )
                    content = response['message']['content'].strip() if 'message' in response and 'content' in response['message'] else "Datos no encontrados"

                summary = self.extract_field("SUMMARY", content)
                dtstart = self.clean_date(self.extract_field("DTSTART", content))
                dtend = self.clean_date(self.extract_field("DTEND", content))
                location = self.extract_field("LOCATION", content)
                rrule = self.extract_field("RRULE", content)

                calendar_data = {
                    'summary': summary,
                    'dtstart': dtstart,
                    'dtend': dtend,
                    'location': location,
                    'rrule': rrule,
                }
                logger.info(f"Extracted calendar data: {calendar_data}")
                return calendar_data

            except Exception as e:
                logger.error(f"Error during event info extraction: {e}")
                retries += 1

        logger.error("Failed to extract complete event info after maximum retries.")
        return {
            'summary': None,
            'dtstart': None,
            'dtend': None,
            'location': None,
            'rrule': None,
        }

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
            # Remove all non-digit characters
            clean_date_str = re.sub(r'\D', '', date_str)
            
            # Check if the date string starts with a day (assuming it's in DD format)
            if len(clean_date_str) >= 2 and 1 <= int(clean_date_str[:2]) <= 31:
                # Rearrange to YYYYMMDD format
                clean_date_str = clean_date_str[4:8] + clean_date_str[2:4] + clean_date_str[:2] + clean_date_str[8:]
            
            # If the string is shorter than 14 characters, pad with zeros
            clean_date_str = clean_date_str.ljust(14, '0')
            # Take only the first 14 characters (YYYYMMDDThhmmss)
            clean_date_str = clean_date_str[:14]
            return f"{clean_date_str[:8]}T{clean_date_str[8:]}"
        return None

class ICSExporter:
    def export(self, entities: Dict[str, str], output_path: Path):
        logging.info(f"Attempting to export ICS with entities: {entities}")
        if not entities.get('dtstart'):
            logging.warning("No se proporcionó fecha de inicio para la exportación ICS. Ignorando este evento.")
            return

        try:
            cest = pytz.timezone("Europe/Madrid")
            current_date = datetime.now(cest)

            start_date = self.parse_date(entities['dtstart'], cest)
            end_date = self.parse_date(entities.get('dtend'), cest) if entities.get('dtend') else None

            if start_date is None:
                logging.error(f"No se pudo analizar la fecha de inicio: {entities['dtstart']}")
                return

            if start_date < current_date and not entities.get('rrule'):
                logging.warning(f"La fecha del evento {start_date} está en el pasado y no es recurrente. Ignorando este evento.")
                return

            calendar = Calendar()
            event = Event()

            event.name = entities.get("summary", "Evento Desconocido")
            event.begin = start_date
            if end_date:
                event.end = end_date
            else:
                # Si no hay fecha de fin, establecer la duración a 2 horas por defecto
                event.end = start_date + timedelta(hours=2)
            event.location = entities.get("location", "Ubicación Desconocida")
            event.description = entities.get('description', "")

            if entities.get('rrule'):
                rrule = entities['rrule']
                if isinstance(rrule, str):
                    # Convertir la cadena RRULE en un ContentLine
                    rrule = ContentLine.parse('RRULE:' + rrule)
                event.extra.append(rrule)

            calendar.events.add(event)

            calendar_data = calendar.serialize()
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(calendar_data)
            
            logging.info(f"Archivo ICS exportado exitosamente: {output_path}")
            logging.info(f"Evento exportado: {event.name}, Inicio: {event.begin}, Fin: {event.end}, Recurrencia: {entities.get('rrule')}")
        except ValueError as e:
            logging.error(f"Error al analizar la fecha para la exportación ICS: {e}")
            logging.error(f"Cadena de fecha problemática: {entities.get('dtstart')}")
        except Exception as e:
            logging.error(f"Ocurrió un error inesperado al exportar el ICS: {e}", exc_info=True)

    @staticmethod
    def parse_date(date_str, timezone):
        if not date_str:
            return None
        try:
            # First, try the original format
            date_obj = datetime.strptime(date_str, "%Y%m%dT%H%M%S")
            return timezone.localize(date_obj)
        except ValueError:
            try:
                # If that fails, try parsing just the date part
                date_obj = datetime.strptime(date_str[:8], "%Y%m%d")
                time_part = date_str[9:] if len(date_str) > 8 else "000000"
                time_obj = datetime.strptime(time_part, "%H%M%S").time()
                date_obj = date_obj.replace(hour=time_obj.hour, minute=time_obj.minute, second=time_obj.second)
                return timezone.localize(date_obj)
            except ValueError:
                try:
                    # If that also fails, try a more flexible parsing
                    date_obj = parser.parse(date_str)
                    if date_obj.tzinfo is None:
                        date_obj = timezone.localize(date_obj)
                    return date_obj
                except Exception as e:
                    logging.error(f"Failed to parse date: {date_str}. Error: {e}")
                    return None


