from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional
from PIL import Image
from dateutil.rrule import rrulestr
from dateutil.parser import parse
from google.cloud import documentai_v1beta3 as documentai
from google.oauth2 import service_account
from google.api_core.client_options import ClientOptions
import easyocr
import pytesseract
from ics import Calendar, Event
from ics.grammar.parse import ContentLine
from groq import Groq
import re
import json
from utils import setup_logging
import logging
import pytz


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

    def get_improved_prompt(self, text: str) -> str:
        return f"""Analiza el siguiente texto y extrae la información del evento en un formato JSON estructurado. Sigue estas reglas estrictamente:

1. Utiliza el formato ISO 8601 para las fechas y horas (YYYY-MM-DDTHH:MM:SS) SOLO si se proporciona una fecha específica en el texto.
2. Si no se especifica una fecha exacta, deja el campo DTSTART vacío.
3. Todas las fechas y horas deben estar en la zona horaria de España (Europe/Madrid).
4. Para eventos recurrentes o de varios días, proporciona una regla RRULE adecuada.
5. NO inventes ni infieras fechas que no estén explícitamente mencionadas en el texto.

Estructura JSON requerida:
{{
    "SUMMARY": "Título del evento",
    "DTSTART": "YYYY-MM-DDTHH:MM:SS", // Dejar vacío si no hay fecha específica
    "DTEND": "YYYY-MM-DDTHH:MM:SS", // Dejar vacío si no hay fecha de fin específica
    "LOCATION": "Ubicación del evento",
    "RRULE": "Regla de recurrencia en formato ICS estándar",
    "ALL_DAY": true/false
}}

Reglas para RRULE:
- Para eventos de un solo día: deja el campo vacío.
- Para eventos recurrentes: proporciona la regla completa (ej: "FREQ=WEEKLY;BYDAY=FR")
- NO incluyas fechas específicas en la RRULE a menos que estén explícitamente mencionadas en el texto.

Asegúrate de que la RRULE sea coherente con la información proporcionada en el texto.

Texto a analizar:

{text}

Proporciona solo la respuesta en formato JSON, sin explicaciones adicionales. Si algún campo no tiene información específica, déjalo vacío o null."""

    def extract_event_info(self, text: str):
        model_type = self.config['external_api']['service'] if self.config['external_api']['use'] else 'local_model'
        prompt = self.get_improved_prompt(text)

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
                    content = response['message']['content'].strip() if 'message' in response and 'content' in response['message'] else "{}"

                event_data = json.loads(content)
                
                # Convertir las fechas al formato requerido por ICSExporter
                event_data['DTSTART'] = self.convert_date_format(event_data['DTSTART'])
                event_data['DTEND'] = self.convert_date_format(event_data['DTEND'])
                
                logger.info(f"Extracted calendar data: {event_data}")
                return event_data

            except Exception as e:
                logger.error(f"Error during event info extraction: {e}")
                retries += 1

        logger.error("Failed to extract complete event info after maximum retries.")
        return {
            'SUMMARY': None,
            'DTSTART': None,
            'DTEND': None,
            'LOCATION': None,
            'RRULE': None,
            'ALL_DAY': False
        }

    @staticmethod
    def convert_date_format(date_str):
        if date_str:
            date_obj = datetime.fromisoformat(date_str)
            return date_obj.strftime("%Y%m%dT%H%M%S")
        return None

class ICSExporter:
    def export(self, entities: Dict[str, str], output_path: Path):
        logger.info(f"Attempting to export ICS with entities: {entities}")
        
        cest = pytz.timezone("Europe/Madrid")
        current_date = datetime.now(cest)

        start_date = entities.get('dtstart')
        end_date = entities.get('dtend')
        rrule = entities.get('rrule')

        if not start_date and rrule:
            start_date = self.get_next_occurrence(rrule, current_date)
            if not start_date:
                logger.warning("No se pudo determinar la próxima ocurrencia del evento recurrente. Ignorando este evento.")
                return

        if not start_date:
            logger.warning("No se proporcionó fecha de inicio para la exportación ICS. Ignorando este evento.")
            return

        try:
            calendar = Calendar()
            event = Event()

            event.name = entities.get("summary", "Evento Desconocido")
            event.begin = start_date
            if end_date:
                event.end = end_date
            event.location = entities.get("location", "Ubicación Desconocida")
            event.description = entities.get('description', "")

            if rrule:
                if isinstance(rrule, str):
                    # Convertir la cadena RRULE en un ContentLine
                    rrule = ContentLine.parse('RRULE:' + rrule)
                event.extra.append(rrule)

            calendar.events.add(event)

            calendar_data = calendar.serialize()
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(calendar_data)
            
            logger.info(f"Archivo ICS exportado exitosamente: {output_path}")
            logger.info(f"Evento exportado: {event.name}, Inicio: {event.begin}, Fin: {event.end}, Recurrencia: {rrule}")
        except Exception as e:
            logger.error(f"Error al exportar el ICS: {e}", exc_info=True)

    def get_next_occurrence(self, rrule_str: str, current_date: datetime) -> Optional[datetime]:
        try:
            # Asumimos que el rrule_str está en formato correcto, por ejemplo:
            # "FREQ=WEEKLY;BYDAY=WE"
            rrule = rrulestr(rrule_str, dtstart=current_date)
            next_occurrence = rrule.after(current_date, inc=True)
            return next_occurrence
        except Exception as e:
            logger.error(f"Error al calcular la próxima ocurrencia: {e}")
            return None