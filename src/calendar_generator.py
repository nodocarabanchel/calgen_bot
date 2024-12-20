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

    def get_improved_prompt(self, text: str) -> str:
        current_year = datetime.now().year
        return f"""Analiza el siguiente texto y extrae la información del evento principal en un formato JSON estructurado. Sigue estas reglas estrictamente:

1. Utiliza el formato ISO 8601 para las fechas y horas (YYYY-MM-DDTHH:MM:SS) si se proporciona una fecha específica en el texto.
2. Si no se especifica una fecha exacta pero hay una hora de inicio, utiliza el formato HH:MM para el campo DTSTART.
3. Si no se proporciona un año específico, asume que el evento es para el año actual ({current_year}).
4. Todas las fechas y horas deben estar en la zona horaria de España (Europe/Madrid).
5. Para eventos recurrentes, proporciona una regla RRULE adecuada.
6. NO inventes ni infieras fechas que no estén explícitamente mencionadas en el texto, excepto para el año actual cuando no se especifique.
7. NO incluyas el campo DTEND si no se menciona explícitamente una hora o fecha de finalización.

Estructura JSON requerida:
[
    {{
    "SUMMARY": "Título del evento",
    "DTSTART": "YYYY-MM-DDTHH:MM:SS" o "HH:MM", // Usar HH:MM si solo se proporciona la hora
    "DTEND": "YYYY-MM-DDTHH:MM:SS", // Omitir si no hay fecha/hora de fin específica
    "LOCATION": "Ubicación del evento",
    "RRULE": "Regla de recurrencia en formato ICS estándar",
    "ALL_DAY": true/false
    }}
]

Reglas para RRULE:
- Para eventos de un solo día: deja el campo vacío.
- Para eventos recurrentes: proporciona la regla completa (ej: "FREQ=WEEKLY;BYDAY=WE")
- NO incluyas fechas específicas en la RRULE a menos que estén explícitamente mencionadas en el texto.

Asegúrate de que la RRULE sea coherente con la información proporcionada en el texto.

Texto a analizar:

{text}

Proporciona solo la respuesta en formato JSON, sin explicaciones adicionales. Si algún campo no tiene información específica, omítelo del JSON."""

    def validate_and_fix_json(self, json_data: str) -> dict:
        if not self.client:
            logger.warning(
                "El cliente Groq no está inicializado. No se puede validar el JSON."
            )
            # Devolver JSON parseado sin validación
            return json.loads(json_data)

        prompt = f"""
        Valida el siguiente JSON para un evento y corrige cualquier problema:
        {json_data}

        Asegúrate de que siga esta estructura:
        [
            {{
                "SUMMARY": "Título del evento",
                "DTSTART": "YYYY-MM-DDTHH:MM:SS" o "HH:MM",
                "DTEND": "YYYY-MM-DDTHH:MM:SS" (opcional),
                "LOCATION": "Ubicación del evento",
                "RRULE": "Regla de recurrencia en formato ICS estándar" (opcional),
                "ALL_DAY": true/false
            }}
        ]

        Reglas:
        1. Usa ISO 8601 para fechas y horas (YYYY-MM-DDTHH:MM:SS).
        2. Usa HH:MM para DTSTART si solo se proporciona la hora.
        3. Omite DTEND si no se menciona explícitamente.
        4. Asegúrate de que RRULE esté en el formato ICS correcto si está presente.
        5. Elimina cualquier campo que no esté en la estructura especificada.

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

                # Process and return all valid events
                for event_data in validated_event_data_list:
                    # Procesar fechas
                    current_date = datetime.now(pytz.timezone("Europe/Madrid"))
                    start_str = event_data.get("DTSTART")
                    if start_str:
                        if "T" in start_str:
                            start_date_time = datetime.fromisoformat(start_str).replace(
                                tzinfo=pytz.timezone("Europe/Madrid")
                            )
                        else:
                            start_time = datetime.strptime(start_str, "%H:%M").time()
                            start_date_time = current_date.replace(
                                hour=start_time.hour,
                                minute=start_time.minute,
                                second=0,
                                microsecond=0,
                            )
                    else:
                        logger.warning(
                            "No se proporcionó fecha/hora de inicio. Usando la fecha/hora actual."
                        )
                        start_date_time = current_date

                    if "RRULE" in event_data:
                        rrule = event_data["RRULE"].strip()
                        start_date_time = get_next_valid_date(start_date_time, rrule)

                    event_data["DTSTART"] = start_date_time

                    # Procesar fecha de fin
                    end_str = event_data.get("DTEND")
                    if end_str:
                        if "T" in end_str:
                            end_date_time = datetime.fromisoformat(end_str).replace(
                                tzinfo=pytz.timezone("Europe/Madrid")
                            )
                        else:
                            end_time = datetime.strptime(end_str, "%H:%M").time()
                            end_date_time = start_date_time.replace(
                                hour=end_time.hour, minute=end_time.minute
                            )

                        if end_date_time <= start_date_time:
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
                            event_data["tags"] = base_tags if 'base_tags' in locals() else []

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

    def parse_datetime_or_time(self, date_str):
        if not date_str:
            return None

        try:
            # Intentar analizar como datetime completo
            return datetime.fromisoformat(date_str).replace(
                tzinfo=pytz.timezone("Europe/Madrid")
            )
        except ValueError:
            try:
                # Intentar analizar como solo hora
                time_obj = datetime.strptime(date_str, "%H:%M").time()
                # Usar la fecha actual con la hora dada
                current_date = datetime.now(pytz.timezone("Europe/Madrid"))
                return current_date.replace(
                    hour=time_obj.hour, minute=time_obj.minute, second=0, microsecond=0
                )
            except ValueError:
                # Si ambos intentos de análisis fallan, devolver None
                logger.error(f"No se pudo analizar la fecha/hora: {date_str}")
                return None


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
