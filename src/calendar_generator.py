import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

import pytz
from dateutil.rrule import rrulestr
from google.api_core.client_options import ClientOptions
from google.cloud import documentai_v1beta3 as documentai
from google.oauth2 import service_account
from groq import Groq
from ics.grammar.parse import ContentLine

from ics import Calendar, Event
from utils import get_next_valid_date, setup_logging, get_geolocation

logger = logging.getLogger(__name__)


class OCRReader:
    SUPPORTED_FORMATS = [
        ".jpg",
        ".jpeg",
        ".png",
        ".bmp",
        ".pdf",
        ".tiff",
        ".tif",
        ".gif",
    ]

    def __init__(self, service: str, google_config: Optional[Dict[str, str]] = None):
        self.service = service
        if service == "documentai":
            if not google_config:
                raise ValueError("Google Document AI configuration is missing.")
            self.project_id = google_config["project_id"]
            self.location = google_config["location"]
            self.processor_id = google_config["processor_id"]
            self.credentials = service_account.Credentials.from_service_account_file(
                google_config["credentials_path"]
            )
            self.client_options = ClientOptions(
                api_endpoint=f"{self.location}-documentai.googleapis.com"
            )
        else:
            raise ValueError(
                "Invalid OCR service. Only 'documentai' is supported."
            )

    def read(self, image_path: Path) -> Optional[str]:
        if image_path.suffix.lower() not in OCRReader.SUPPORTED_FORMATS:
            return None

        try:
            if self.service == "documentai":
                docai_client = documentai.DocumentProcessorServiceClient(
                    client_options=self.client_options, credentials=self.credentials
                )
                resource_name = docai_client.processor_path(
                    self.project_id, self.location, self.processor_id
                )

                with open(image_path, "rb") as image:
                    image_content = image.read()

                raw_document = documentai.RawDocument(
                    content=image_content, mime_type=self.get_mime_type(image_path)
                )
                request = documentai.ProcessRequest(
                    name=resource_name, raw_document=raw_document
                )
                result = docai_client.process_document(request=request)

                document_object = result.document
                combined_text = document_object.text
                
            logger.info(f"Raw extracted document: {combined_text}")
            return combined_text
        except Exception as e:
            logger.exception("Error during text extraction: %s", e)
            return None

    def get_mime_type(self, image_path: Path) -> str:
        suffix = image_path.suffix.lower()
        if suffix in [".jpg", ".jpeg"]:
            return "image/jpeg"
        elif suffix == ".png":
            return "image/png"
        elif suffix == ".bmp":
            return "image/bmp"
        elif suffix in [".tiff", ".tif"]:
            return "image/tiff"
        elif suffix == ".gif":
            return "image/gif"
        elif suffix == ".pdf":
            return "application/pdf"
        else:
            raise ValueError(f"Unsupported file extension: {suffix}")


class EntityExtractor:
    def __init__(self, config):
        self.config = config
        self.max_retries = 3
        self.client = None

        # Verificar si se debe usar la API externa
        if config.get("external_api", {}).get("use"):
            if config["external_api"]["service"] == "groq":
                try:
                    api_key = config["external_api"]["api_key"]
                    # Inicializar el cliente Groq con solo la api_key
                    self.client = Groq(api_key=api_key)
                except Exception as e:
                    logger.error(f"Error initializing Groq client: {str(e)}")
                    self.client = None

    def process_event_date(self, date_str: str, reference_date: datetime) -> Optional[datetime]:
        if not date_str:
            return None

        try:
            # Caso 1: Si viene con año (YYYY-MM-DD[THH:MM:SS])
            if len(date_str.split('-')) == 3:
                return datetime.fromisoformat(date_str).replace(
                    tzinfo=pytz.timezone("Europe/Madrid")
                )
            
            # Caso 2: Solo hora (HH:MM)
            if ":" in date_str and "-" not in date_str:
                time_obj = datetime.strptime(date_str, "%H:%M").time()
                date_time = reference_date.replace(
                    hour=time_obj.hour,
                    minute=time_obj.minute,
                    second=0,
                    microsecond=0
                )
                # Si la hora ya pasó hoy, asumimos que es para mañana
                if date_time < reference_date:
                    date_time += timedelta(days=1)
                return date_time
            
            # Caso 3: Fecha sin año (MM-DD)
            if "-" in date_str:
                # Verificamos si contiene "T" (ej: 01-18T18:30:00)
                if "T" in date_str:
                    # dividir "MM" y el resto: "01", "18T18:30:00"
                    month_str, rest_str = date_str.split('-', maxsplit=1)
                    month = int(month_str)

                    # dividir "18T18:30:00" en "18" y "18:30:00"
                    day_str, time_str = rest_str.split('T')
                    day = int(day_str)
                    # dividir "18:30:00" en hora, minuto, segundo
                    hour, minute, second = map(int, time_str.split(':'))

                    date_time = reference_date.replace(
                        month=month,
                        day=day,
                        hour=hour,
                        minute=minute,
                        second=second,
                        microsecond=0
                    )
                else:
                    # solo "MM-DD"
                    month, day = map(int, date_str.split('-'))
                    date_time = reference_date.replace(
                        month=month,
                        day=day,
                        hour=0,
                        minute=0,
                        second=0,
                        microsecond=0
                    )

                # Si la fecha resultante ya pasó, asignar el siguiente año
                if date_time < reference_date:
                    date_time = date_time.replace(year=date_time.year + 1)

                return date_time

        except ValueError as e:
            logger.error(f"Error procesando fecha: {str(e)}")
            return None

        # Si ningún caso coincide
        return None

    def get_improved_prompt(self, text: str) -> str:
        return f"""Analiza el siguiente texto y extrae la información del evento principal en un formato JSON estructurado. Sigue estas reglas estrictamente:

1. Para fechas y horas, usa estos formatos:
   - Si se menciona un año específico: YYYY-MM-DDTHH:MM:SS
   - Si no se menciona año: MM-DD
   - Si solo hay hora: HH:MM
2. Todas las fechas y horas deben estar en la zona horaria de España (Europe/Madrid).
3. Para eventos recurrentes, proporciona una regla RRULE adecuada.
4. NO inventes ni infieras fechas que no estén explícitamente mencionadas en el texto.
5. NO incluyas el campo DTEND si no se menciona explícitamente una hora o fecha de finalización.
6. No inventes un año que no exista literalmente en el texto. 
7. Si en el texto no se lee claramente un año (por ejemplo, '2024', '2025', etc.), no asumas uno. 
8. Devuelve siempre MM-DD u HH:MM si el año no se menciona explícitamente.

Estructura JSON requerida:
[
    {{
    "SUMMARY": "Título del evento",
    "DTSTART": formatos según el caso:
        - Con año: "YYYY-MM-DDTHH:MM:SS"
        - Sin año: "MM-DD"
        - Solo hora: "HH:MM",
    "DTEND": mismo formato que DTSTART (omitir si no se especifica),
    "LOCATION": "Ubicación del evento",
    "RRULE": "Regla de recurrencia en formato ICS estándar",
    "ALL_DAY": true/false
    }}
]

Reglas para RRULE:
- Para eventos de un solo día: deja el campo vacío.
- Para eventos recurrentes: proporciona la regla completa (ej: "FREQ=WEEKLY;BYDAY=WE")
- NO incluyas fechas específicas en la RRULE a menos que estén explícitamente mencionadas en el texto.

Texto a analizar:

{text}

Proporciona solo la respuesta en formato JSON, sin explicaciones adicionales. Si algún campo no tiene información específica, omítelo del JSON."""

    def validate_and_fix_json(self, json_data: str) -> dict:
        """
        Llama a la API de Groq para validar y corregir el JSON, 
        o devuelve el JSON parseado si no hay cliente o hay algún error.
        """
        if not self.client:
            logger.warning(
                "El cliente Groq no está inicializado. No se puede validar el JSON."
            )
            return json.loads(json_data)

        prompt = f"""
        Valida el siguiente JSON para un evento y corrige cualquier problema:
        {json_data}

        Asegúrate de que siga esta estructura:
        [
            {{
                "SUMMARY": "Título del evento",
                "DTSTART": formatos válidos:
                    - "YYYY-MM-DDTHH:MM:SS" (si se menciona año)
                    - "MM-DD" (si hay fecha sin año)
                    - "HH:MM" (si solo hay hora),
                "DTEND": igual que DTSTART (opcional),
                "LOCATION": "Ubicación del evento",
                "RRULE": "Regla de recurrencia en formato ICS estándar" (opcional),
                "ALL_DAY": true/false
            }}
        ]

        Reglas:
        1. Si la fecha viene con año específico, usa formato completo: YYYY-MM-DDTHH:MM:SS
        2. Si la fecha viene sin año, usa formato: MM-DD
        3. Si solo hay hora, usa formato: HH:MM
        4. Omite DTEND si no se menciona explícitamente
        5. Asegúrate de que RRULE esté en el formato ICS correcto si está presente
        6. Elimina cualquier campo que no esté en la estructura especificada

        Importante: 
        - No inventes un año que no exista literalmente en el texto. 
        - Si en el texto no se lee claramente un año (por ejemplo, '2024', '2025', etc.), no asumas uno. 
        - Devuelve siempre MM-DD u HH:MM si el año no se menciona explícitamente.

        Devuelve solo el JSON corregido, sin explicaciones.
        """

        retries = 0
        while retries < self.max_retries:
            try:
                chat_completion = self.client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    model=self.config["external_api"]["model_name"],
                )
                corrected_json = chat_completion.choices[0].message.content
                return json.loads(corrected_json)
            except json.JSONDecodeError as e:
                logger.error(f"Error al analizar el JSON corregido: {e}")
                retries += 1
            except Exception as e:
                logger.error(
                    f"Error durante la validación del JSON: {e}", exc_info=True
                )
                retries += 1

        logger.error(
            "No se pudo validar y corregir el JSON después del número máximo de intentos."
        )
        # Devolver JSON original parseado si fallan todos los intentos
        return json.loads(json_data)

    def extract_event_info(self, text: str, metadata: dict = None):
        """
        Extrae la información del evento del texto proporcionado y agrega metadatos si están disponibles.
        
        Args:
            text (str): El texto del que extraer la información del evento
            metadata (dict, optional): Diccionario con metadatos adicionales (canal, fuente, etc.)
        
        Returns:
            list: Lista de diccionarios con la información de los eventos
        """
        model_type = (
            self.config["external_api"]["service"]
            if self.config["external_api"]["use"]
            else "local_model"
        )
        prompt = self.get_improved_prompt(text)

        retries = 0
        while retries < self.max_retries:
            try:
                if model_type == "groq" and self.client:
                    logger.debug(
                        f"Enviando solicitud a la API de Groq con el prompt: {prompt}"
                    )
                    chat_completion = self.client.chat.completions.create(
                        messages=[{"role": "user", "content": prompt}],
                        model=self.config["external_api"]["model_name"],
                    )
                    logger.info(
                        f"Respuesta recibida de la API de Groq: {chat_completion}"
                    )
                    content = chat_completion.choices[0].message.content
                elif model_type == "local_model" and self.config["local_model"]["use"]:
                    logger.warning("Local model is not implemented yet.")
                    return []

                logger.info(f"Contenido sin procesar: {content}")
                event_data_list = json.loads(content)
                logger.info(f"Contenido JSON parseado: {event_data_list}")

                # Validar y corregir JSON
                validated_event_data_list = self.validate_and_fix_json(json.dumps(event_data_list))

                # If the validated JSON is a single object, convert it to a list
                if isinstance(validated_event_data_list, dict):
                    validated_event_data_list = [validated_event_data_list]

                if metadata and metadata.get("telegram_timestamp"):
                    try:
                        reference_date = datetime.fromtimestamp(
                            metadata["telegram_timestamp"], pytz.timezone("Europe/Madrid")
                        )
                        logger.info(f"Usando la fecha de publicación del mensaje como referencia: {reference_date}")
                    except Exception as ex:
                        logger.warning(f"No se pudo parsear telegram_timestamp ({ex}). Usando fecha del sistema.")
                        reference_date = datetime.now(pytz.timezone("Europe/Madrid"))
                else:
                    reference_date = datetime.now(pytz.timezone("Europe/Madrid"))
                    logger.info(f"Usando fecha/hora del sistema como referencia: {reference_date}")

                # Process and return all valid events
                for event_data in validated_event_data_list:
                    start_str = event_data.get("DTSTART")
                    if start_str:
                        start_date_time = self.process_event_date(start_str, reference_date)
                    else:
                        logger.warning(
                            "No se proporcionó fecha/hora de inicio. Usando la fecha/hora actual."
                        )
                        start_date_time = reference_date

                    if "RRULE" in event_data:
                        rrule = event_data["RRULE"].strip()
                        start_date_time = get_next_valid_date(start_date_time, rrule)

                    event_data["DTSTART"] = start_date_time

                    # Procesar fecha de fin
                    end_str = event_data.get("DTEND")
                    if end_str:
                        end_date_time = self.process_event_date(end_str, reference_date)

                        if end_date_time and end_date_time <= start_date_time:
                            end_date_time += timedelta(days=1)

                        event_data["DTEND"] = end_date_time
                    else:
                        logger.warning(
                            "No se proporcionó fecha/hora de finalización. El evento no tendrá hora de finalización."
                        )

                    # Procesar ubicación y geolocalización
                    if event_data.get("LOCATION"):
                        logger.info(f"Processing location: {event_data['LOCATION']}")
                        location_info = get_geolocation(self.config, event_data["LOCATION"])
                        if location_info:
                            logger.info(f"Geolocation found: {location_info}")
                            
                            # Añadir coordenadas
                            if 'latitude' in location_info and 'longitude' in location_info:
                                event_data["place_latitude"] = location_info["latitude"]
                                event_data["place_longitude"] = location_info["longitude"]
                            
                            # Inicializar tags con las categorías base
                            base_tags = []
                            if metadata:
                                base_tags = [
                                    metadata.get("channel_name", "Canal Desconocido"),
                                    metadata.get("source", "Fuente Desconocido")
                                ]
                            
                            # Añadir categorías de ubicación a los tags
                            categories = location_info.get("categories", [])
                            logger.info(f"Location categories: {categories}")
                            
                            event_data["tags"] = base_tags + categories
                            logger.info(f"Final tags for event: {event_data['tags']}")
                        else:
                            logger.warning(f"No geolocation info found for: {event_data['LOCATION']}")
                            event_data["tags"] = []

                    # Añadir descripción del mensaje de Telegram
                    if metadata and metadata.get("text"):
                        event_data["DESCRIPTION"] = metadata["text"]

                logger.info(f"Datos del evento extraídos: {validated_event_data_list}")
                return validated_event_data_list

            except json.JSONDecodeError as e:
                logger.error(f"Error al analizar JSON: {e}")
                logger.debug(f"Contenido sin procesar: {content}")
                retries += 1
            except Exception as e:
                logger.error(
                    f"Error durante la extracción de información del evento: {e}",
                    exc_info=True,
                )
                retries += 1

        logger.error(
            "No se pudo extraer la información completa del evento después del número máximo de intentos."
        )
        return []



class ICSExporter:
    def export(self, entities: Dict[str, str], output_path: Path):
        logger.info(f"Attempting to export ICS with entities: {entities}")

        cest = pytz.timezone("Europe/Madrid")
        current_date = datetime.now(cest)

        start_date = entities.get("dtstart")
        end_date = entities.get("dtend")
        rrule = entities.get("rrule")

        if not start_date and rrule:
            start_date = self.get_next_occurrence(rrule, current_date)
            if not start_date:
                logger.warning(
                    "No se pudo determinar la próxima ocurrencia del evento recurrente. Ignorando este evento."
                )
                return

        if not start_date:
            logger.warning(
                "No se proporcionó fecha de inicio para la exportación ICS. Ignorando este evento."
            )
            return

        # Add this check
        if end_date and end_date <= start_date:
            logger.warning(
                f"End date ({end_date}) is not after start date ({start_date}). Adjusting end date."
            )
            # Set end date to 1 hour after start date
            end_date = start_date + timedelta(hours=1)

        try:
            calendar = Calendar()
            event = Event()

            event.name = entities.get("summary", "Evento Desconocido")
            event.begin = start_date
            if end_date:
                event.end = end_date
            event.location = entities.get("location", "Ubicación Desconocida")
            event.description = entities.get("description", "")

            if rrule:
                if isinstance(rrule, str):
                    # Convertir la cadena RRULE en un ContentLine
                    rrule = ContentLine.parse("RRULE:" + rrule)
                event.extra.append(rrule)

                # Add this check for recurring events
                if end_date and end_date <= start_date:
                    logger.warning(
                        f"For recurring event, end date ({end_date}) is not after start date ({start_date}). Adjusting end date."
                    )
                    end_date = start_date + timedelta(hours=1)
                    event.end = end_date

            calendar.events.add(event)

            calendar_data = calendar.serialize()
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(calendar_data)

            logger.info(f"Archivo ICS exportado exitosamente: {output_path}")
            logger.info(
                f"Evento exportado: {event.name}, Inicio: {event.begin}, Fin: {event.end}, Recurrencia: {rrule}"
            )
        except Exception as e:
            logger.error(f"Error al exportar el ICS: {e}", exc_info=True)

    def get_next_occurrence(self, rrule_str: str, current_date: datetime) -> datetime:
        try:
            rrule = rrulestr(rrule_str, dtstart=current_date)
            next_occurrence = rrule.after(current_date, inc=True)
            return next_occurrence
        except Exception as e:
            logger.error(f"Error al calcular la próxima ocurrencia: {e}")
            return None
