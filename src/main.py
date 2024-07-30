import io
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone
from utils import load_config, setup_logging, clean_directories, get_image_hash, are_images_similar
from ics_uploader import extract_event_details_from_ics, send_event
from calendar_generator import OCRReader, EntityExtractor, ICSExporter
from telegram_bot import TelegramBot
from sqlite_tracker import DatabaseManager
from event_fingerprint import EventFingerprint

async def main():
    config = load_config()
    logger = setup_logging(config, 'main')

    logger.info("Starting main process")
        
    db_manager = DatabaseManager(config["event_tracker_db_path"])
    
    if config["telegram_bot"]["use"]:
        start_date = config["telegram_bot"]["start_date"]
        if start_date:
            try:
                start_date = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                logger.info(f"Using provided start date: {start_date}")
            except ValueError:
                logger.error(f"Invalid start_date format: {start_date}. Using last 24 hours.")
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
            config["telegram_bot"]["channel_ids"],
            start_date.strftime("%Y-%m-%d") if start_date else None,
            config["telegram_bot"].get("max_posters_per_day", 50)
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
    
    new_image_files = [img_file for img_file in images_folder.iterdir() 
                    if img_file.suffix.lower() in OCRReader.SUPPORTED_FORMATS 
                    and not db_manager.is_image_processed(img_file.name)]
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
                logger.info(f"Imagen {img_file.name} es similar a {processed_file}. Distancia: {distance}. Saltando...")
                is_duplicate = True
                break
        
        if is_duplicate or db_manager.is_hash_processed(image_hash):
            continue
        
        logger.info(f"Processing new image: {img_file.name}")
        text_file_path = text_output_folder / (img_file.stem + '.txt')
        ics_file_path = ics_output_folder / (img_file.stem + '.ics')
        text = reader.read(img_file)
        
        caption_file_path = img_file.with_suffix('.txt')
        caption = ""
        if caption_file_path.exists():
            with open(caption_file_path, 'r', encoding='utf-8') as caption_file:
                caption = caption_file.read()
        
        combined_text = f"{caption} {text}" if caption else text
        if combined_text:
            with open(text_file_path, 'w', encoding='utf-8') as text_file:
                text_file.write(combined_text)
            logger.info(f"Extracting event info from: {combined_text[:100]}...")
            extracted_data = extractor.extract_event_info(combined_text)
            if extracted_data and all([extracted_data.get('summary'), extracted_data.get('dtstart'), extracted_data.get('location')]):
                logger.info(f"Extracted data: {extracted_data}")
                
                try:
                    start_date = exporter.parse_date(extracted_data['dtstart'], pytz.timezone("Europe/Madrid"))
                    end_date = exporter.parse_date(extracted_data.get('dtend'), pytz.timezone("Europe/Madrid")) if extracted_data.get('dtend') else None
                    
                    if start_date is None:
                        logger.error(f"Invalid start date: {extracted_data['dtstart']}")
                        continue
                    
                    if db_manager.is_duplicate_event(extracted_data):
                        logger.info(f"Skipping duplicate event: {extracted_data['summary']}")
                    else:
                        event_id = f"{extracted_data['summary']}_{start_date.isoformat()}_{extracted_data['location']}"
                        if not db_manager.is_event_sent(event_id):
                            exporter.export({
                                'summary': extracted_data['summary'],
                                'dtstart': start_date,
                                'dtend': end_date,
                                'location': extracted_data['location'],
                                'description': caption
                            }, ics_file_path)
                            logger.info(f"ICS file successfully generated: {img_file.name}")
                            db_manager.add_event_title(extracted_data['summary'])
                            db_manager.add_event(extracted_data)
                            processed_events += 1
                        else:
                            logger.info(f"Skipping already processed event: {event_id}")
                except Exception as e:
                    logger.error(f"Error processing event data: {str(e)}")
                    logger.error(f"Problematic data: {extracted_data}")
                    for key, value in extracted_data.items():
                        logger.error(f"{key}: {value}")
            else:
                logger.warning(f"Failed to extract complete data for image {img_file.name}")
                logger.warning(f"Extracted data: {extracted_data}")
        else:
            logger.warning(f"No text extracted from image {img_file.name}")
        processed_hashes[img_file.name] = image_hash
        db_manager.add_image_hash(img_file.name, image_hash)
        db_manager.mark_image_as_processed(img_file.name)

    logger.info(f"Total new events processed from images: {processed_events}")
    
    ics_files = [ics_file for ics_file in ics_output_folder.iterdir() if ics_file.suffix.lower() == '.ics']
    logger.info(f"Found {len(ics_files)} ICS files to process")
    
    sent_events = 0
    for ics_file in ics_files:
        events = extract_event_details_from_ics(ics_file)
        for event_details in events:
            event_id = f"{event_details['title']}_{event_details['start_datetime']}_{event_details['place_name']}"
            if not db_manager.is_event_sent(event_id):
                logger.info(f"Attempting to send event: {event_details['title']}")
                base_filename = ics_file.stem
                image_file = images_folder / f"{base_filename}.jpg"
                if image_file.exists():
                    response = send_event(config, event_details, base_filename, str(image_file))
                else:   
                    response = send_event(config, event_details, base_filename)
                
                if response and response.status_code == 200:
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
        'api_data'
    ]
    clean_directories(directories_to_clean)

    logger.info("Main function completed.")

if __name__ == "__main__":
    asyncio.run(main())