import json
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import time
import pytz

os.environ['TZ'] = 'Europe/Madrid'
time.tzset()

from calendar_generator import EntityExtractor, ICSExporter, OCRReader
from ics_uploader import extract_event_details_from_ics, send_event, process_events_batch
from sqlite_tracker import DatabaseManager
from telegram_bot import TelegramBot
from utils import (
    clean_directories,
    get_next_occurrence,
    is_recurrent_event,
    load_config,
    setup_logging,
    get_next_valid_date,
    DuplicateDetector
)


async def main():
    config = load_config()
    logger = setup_logging(config, "main")

    # Initialize the duplicate detector
    duplicate_detector = DuplicateDetector(config)

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
            channels,
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
        channels = config["telegram_bot"]["channels"]

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
        # Get current image hashes
        current_hashes = duplicate_detector.calculate_image_hash(img_file)
        
        if current_hashes:
            # Check for duplicates
            is_duplicate, matching_file = duplicate_detector.check_duplicate(
                img_file,
                processed_hashes,
                new_image_files
            )

            if is_duplicate:
                matching_name = matching_file.name if isinstance(matching_file, Path) else str(matching_file)
                logger.info(f"Skipping duplicate image: {img_file.name} (duplicate of: {matching_name})")
                continue
            elif db_manager.is_hash_processed(current_hashes["phash"]):  # Use perceptual hash for DB check
                logger.info(f"Hash already processed: {img_file.name}")
                continue

            # Process new image
            logger.info(f"Processing new image: {img_file.name}")
            
            # Store hash information
            hash_info = {
                "processed_date": datetime.now().isoformat(),
                "hash_size": duplicate_detector.hash_size,
                "phash": current_hashes["phash"],
                "ahash": current_hashes["ahash"],
                "ghash": current_hashes["ghash"]
            }
            db_manager.add_image_hash_with_info(img_file.name, current_hashes["phash"], hash_info)
            processed_hashes[img_file.name] = current_hashes

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
        
        processed_hashes[img_file.name] = current_hashes
        db_manager.mark_image_as_processed(img_file.name)

    logger.info(f"Total new events processed from images: {processed_events}")

    # Nueva sección de procesamiento de ICS
    ics_files = [
        ics_file
        for ics_file in ics_output_folder.iterdir()
        if ics_file.suffix.lower() == ".ics"
    ]
    logger.info(f"Found {len(ics_files)} ICS files to process")
    
    all_events = []
    for ics_file in ics_files:
        events = extract_event_details_from_ics(ics_file)
        for event in events:
            # Incluir el nombre base del archivo en los detalles del evento
            event['base_filename'] = ics_file.stem
            
            # Buscar el nombre del canal en la configuración
            channel_id = ics_file.stem.split('_')[0] if '_' in ics_file.stem else None
            channel_name = None
            if channel_id:
                for channel in channels:
                    if str(channel['id']) == channel_id:
                        channel_name = channel['name']
                        break
            
            existing_tags = event.get('categories', [])
            event['tags'] = existing_tags + ["Generado automáticamente"]
            if channel_name:
                event['tags'].insert(0, channel_name)
            
            # Preparar ID del evento
            event_id = f"{channel_name+'_' if channel_name else ''}{event['title']}_{event['start_datetime']}_{event['place_name']}"
            
            # Añadir imagen si existe
            image_path = images_folder / f"{ics_file.stem}.jpg"
            if image_path.exists():
                event['image_path'] = str(image_path)
            
            # Solo añadir si no ha sido enviado
            if not db_manager.is_event_sent(event_id):
                all_events.append(event)
            else:
                logger.info(f"Skipping already sent event: {event_id}")

    # Procesar todos los eventos en lotes
    if all_events:
        logger.info(f"Processing {len(all_events)} events in batches")
        process_events_batch(config, all_events, db_manager)
        logger.info(f"Finished processing all events")
    else:
        logger.info("No new events to process")

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