import json
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytz

from calendar_generator import EntityExtractor, ICSExporter, OCRReader
from ics_uploader import extract_event_details_from_ics, send_event
from sqlite_tracker import DatabaseManager
from telegram_bot import TelegramBot
from utils import (
    are_images_similar,
    clean_directories,
    get_image_hash,
    get_next_occurrence,
    is_recurrent_event,
    load_config,
    setup_logging,
    get_next_valid_date,
)


async def main():
    config = load_config()
    logger = setup_logging(config, "main")

    logger.info("Starting main process")

    db_manager = DatabaseManager(config["event_tracker_db_path"])

    if config["telegram_bot"]["use"]:
        # Convertir la lista de canales del config a un formato utilizable
        channels = [
            {"id": channel["id"], "name": channel["name"]} 
            for channel in config["telegram_bot"]["channels"]
        ]
        
        start_date = config["telegram_bot"]["start_date"]
        if start_date:
            try:
                start_date = datetime.strptime(start_date, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
                logger.info(f"Using provided start date: {start_date}")
            except ValueError:
                logger.error(
                    f"Invalid start_date format: {start_date}. Using last 24 hours."
                )
                start_date = datetime.now(timezone.utc) - timedelta(days=1)
        else:
            start_date = datetime.now(timezone.utc) - timedelta(days=1)
            logger.info(f"No start date provided. Using last 24 hours: {start_date}")

        bot = TelegramBot(
            config["telegram_bot"]["api_id"],
            config["telegram_bot"]["api_hash"],
            config["telegram_bot"]["phone"],
            config["telegram_bot"]["session_file"],
            db_manager,
            channels,  # Pasamos la lista de canales completa
            start_date.strftime("%Y-%m-%d") if start_date else None,
            config["telegram_bot"].get("max_posters_per_day", 50),
        )

        images_folder = Path(config["directories"]["images"])
        text_output_folder = Path(config["directories"]["plain_texts"])
        ics_output_folder = Path(config["directories"]["ics"])
        text_output_folder.mkdir(exist_ok=True)
        ics_output_folder.mkdir(exist_ok=True)

        logger.info("Checking for new images from Telegram")
        await bot.start()
        new_images = await bot.download_images(config["directories"]["images"])
        await bot.stop()
        logger.info(f"Downloaded {new_images} new images from Telegram")
    else:
        logger.info("Telegram bot is disabled in settings")
        new_images = 0

    images_folder = Path(config["directories"]["images"])
    new_image_files = [
        img_file
        for img_file in images_folder.iterdir()
        if img_file.suffix.lower() in OCRReader.SUPPORTED_FORMATS
        and not db_manager.is_image_processed(img_file.name)
    ]
    logger.info(f"Found {len(new_image_files)} new images to process")

    ocr_service = config["ocr_service"]
    google_config = config.get("google_document_ai")
    logger.info(f"Initializing OCR reader with service: {ocr_service}")
    reader = OCRReader(ocr_service, google_config)
    extractor = EntityExtractor(config)
    exporter = ICSExporter()

    processed_events = 0
    processed_hashes = {}

    for img_file in new_image_files:
        image_hash = get_image_hash(img_file)

        is_duplicate = False
        for processed_file, processed_hash in processed_hashes.items():
            similar, distance = are_images_similar(image_hash, processed_hash)
            if similar:
                logger.info(
                    f"Imagen {img_file.name} es similar a {processed_file}. Distancia: {distance}. Saltando..."
                )
                is_duplicate = True
                break

        if is_duplicate:
            logger.info(f"Duplicate image found: {img_file.name}. Skipping processing.")
            continue
        elif db_manager.is_hash_processed(image_hash):
            logger.info(f"Image hash already processed: {img_file.name}. Skipping processing.")
            continue

        logger.info(f"Processing new image: {img_file.name}")
        text_file_path = text_output_folder / (img_file.stem + ".txt")
        ics_file_path = ics_output_folder / (img_file.stem + ".ics")
        text = reader.read(img_file)

        # Cargar metadata del archivo JSON asociado
        json_file_path = img_file.with_suffix('.json')
        metadata = None
        if json_file_path.exists():
            try:
                with open(json_file_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                logger.info(f"Loaded metadata for {img_file.name}: {metadata}")
            except Exception as e:
                logger.error(f"Error loading metadata from {json_file_path}: {e}")

        combined_text = ""
        if metadata and metadata.get('text'):
            combined_text = metadata['text']
        if text:
            combined_text = f"{combined_text}\n{text}" if combined_text else text

        if combined_text:
            with open(text_file_path, "w", encoding="utf-8") as text_file:
                text_file.write(combined_text)
            logger.info(f"Extracting event info from: {combined_text[:100]}...")
        
            extracted_data_list = extractor.extract_event_info(combined_text, metadata)
            
            if extracted_data_list:
                for extracted_data in extracted_data_list:
                    if extracted_data and any(
                        [
                            extracted_data.get("SUMMARY"),
                            extracted_data.get("DTSTART"),
                            extracted_data.get("LOCATION"),
                        ]
                    ):
                        logger.info(f"Processing extracted data: {extracted_data}")
                        try:
                            start_date = extracted_data.get("DTSTART")
                            end_date = extracted_data.get("DTEND")

                            if start_date is None:
                                logger.error(f"Unable to determine start date for event: {extracted_data.get('SUMMARY')}")
                                continue

                            # Crear un ID único para el evento que incluya el canal
                            channel_prefix = f"{metadata['channel_name']}_" if metadata and metadata.get('channel_name') else ""
                            event_id = f"{channel_prefix}{extracted_data.get('SUMMARY')}_{start_date.isoformat()}_{extracted_data.get('LOCATION')}"

                            if not db_manager.is_event_sent(event_id):
                                # Preparar los datos del evento incluyendo tags y metadatos
                                event_data = {
                                    "summary": extracted_data.get("SUMMARY"),
                                    "dtstart": start_date,
                                    "location": extracted_data.get("LOCATION"),
                                    "description": extracted_data.get("DESCRIPTION", ""),
                                    "rrule": extracted_data.get("RRULE"),
                                }
                                
                                # Agregar tags si existen
                                if "tags" in extracted_data:
                                    event_data["tags"] = extracted_data["tags"]
                                
                                if end_date:
                                    event_data["dtend"] = end_date

                                logger.debug(f"Event data before export: {event_data}")
                                exporter.export(event_data, ics_file_path)
                                logger.info(f"ICS file successfully generated: {img_file.name}")
                                db_manager.add_event_title(extracted_data.get("SUMMARY"))
                                db_manager.add_event(extracted_data)
                                processed_events += 1
                            else:
                                logger.info(f"Skipping already processed event: {event_id}")
                        except Exception as e:
                            logger.error(f"Error processing event data: {str(e)}", exc_info=True)
                            logger.error(f"Problematic data: {extracted_data}")
                            for key, value in extracted_data.items():
                                logger.error(f"{key}: {value}")
            else:
                logger.warning(
                    f"Failed to extract complete data for image {img_file.name}"
                )
                logger.warning(f"Extracted data: {extracted_data_list}")
        else:
            logger.warning(f"No text extracted from image {img_file.name}")
        
        processed_hashes[img_file.name] = image_hash
        db_manager.add_image_hash(img_file.name, image_hash)
        db_manager.mark_image_as_processed(img_file.name)

    logger.info(f"Total new events processed from images: {processed_events}")

    ics_files = [
        ics_file
        for ics_file in ics_output_folder.iterdir()
        if ics_file.suffix.lower() == ".ics"
    ]
    logger.info(f"Found {len(ics_files)} ICS files to process")

    sent_events = 0
    for ics_file in ics_files:
        events = extract_event_details_from_ics(ics_file)
        for event_details in events:
            # Incluir el canal en el ID del evento si está disponible
            base_filename = ics_file.stem
            channel_id = base_filename.split('_')[0] if '_' in base_filename else None
            
            # Buscar el nombre del canal en la configuración
            channel_name = None
            if channel_id:
                for channel in channels:
                    if str(channel['id']) == channel_id:
                        channel_name = channel['name']
                        break
            
            channel_prefix = f"{channel_name}_" if channel_name else ""
            event_id = f"{channel_prefix}{event_details['title']}_{event_details['start_datetime']}_{event_details['place_name']}"

            if not db_manager.is_event_sent(event_id):
                logger.info(f"Attempting to send event: {event_details['title']}")
                
                # Agregar tags si existe información del canal
                if channel_name:
                    event_details['tags'] = [
                        channel_name,
                        "Generado automáticamente via CalGen Bot"
                    ]
                
                image_file = images_folder / f"{base_filename}.jpg"
                if image_file.exists():
                    success = send_event(
                        config, event_details, base_filename, str(image_file)
                    )
                else:
                    success = send_event(config, event_details, base_filename)

                if success:
                    db_manager.mark_event_as_sent(event_id)
                    logger.info(f"Event sent and marked as processed: {event_id}")
                    sent_events += 1
                else:
                    logger.warning(f"Failed to send event: {event_id}")
            else:
                logger.info(f"Skipping already sent event: {event_id}")

    logger.info(f"Total events sent in this execution: {sent_events}")
    logger.info("All processes completed successfully.")
    db_manager.close()

    directories_to_clean = [
        config["directories"]["images"],
        config["directories"]["download_tracker"],
        config["directories"]["plain_texts"],
        config["directories"]["ics"],
    ]
    clean_directories(directories_to_clean)

    logger.info("Main function completed.")


if __name__ == "__main__":
    asyncio.run(main())
