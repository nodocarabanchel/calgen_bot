import asyncio
import logging
from pathlib import Path
from utils import load_config, setup_logging, clean_directories
from ics_uploader import extract_event_details_from_ics, send_event
from calendar_generator import OCRReader, EntityExtractor, ICSExporter
from telegram_bot import TelegramBot
from sqlite_tracker import SQLiteTracker

async def main():
    config = load_config()
    setup_logging(config)
    
    tracker = SQLiteTracker(config["sqlite_db_path"])
    
    if config["telegram_bot"]["use"]:
        bot = TelegramBot(
            config["telegram_bot"]["token"],
            config["telegram_bot"]["chat_ids"],
            config["telegram_bot"]["offset_path"],
            tracker
        )
        await bot.download_images(config["directories"]["images"])
    
    images_folder = Path(config["directories"]["images"])
    text_output_folder = Path(config["directories"]["plain_text"])
    ics_output_folder = Path(config["directories"]["ics"])
    text_output_folder.mkdir(exist_ok=True)
    ics_output_folder.mkdir(exist_ok=True)
    
    image_files = [img_file for img_file in images_folder.iterdir() if img_file.suffix.lower() in OCRReader.SUPPORTED_FORMATS]
    ocr_service = config["ocr_service"]
    google_config = config.get("google_document_ai")
    logging.info(f"Initializing OCR reader with service: {ocr_service}")
    reader = OCRReader(ocr_service, google_config)
    extractor = EntityExtractor(config)
    exporter = ICSExporter()
    
    for img_file in image_files:
        if not tracker.is_image_processed(img_file.name):
            text_file_path = text_output_folder / (img_file.stem + '.txt')
            ics_file_path = ics_output_folder / (img_file.stem + '.ics')
            text = reader.read(img_file)
            
            caption_file_path = img_file.with_suffix('.txt')
            caption = ""
            if caption_file_path.exists():
                with open(caption_file_path, 'r', encoding='utf-8') as caption_file:
                    caption = caption_file.read()
            
            combined_text = f"{caption} {text}" if text else caption
            if combined_text:
                with open(text_file_path, 'w', encoding='utf-8') as text_file:
                    text_file.write(combined_text)
                extracted_data = extractor.extract_event_info(combined_text)
                if extracted_data and all([extracted_data.get('summary'), extracted_data.get('dtstart'), extracted_data.get('location')]):
                    exporter.export({
                        'summary': extracted_data['summary'],
                        'date': extracted_data['dtstart'],
                        'location': extracted_data['location'],
                        'description': caption  # Use caption as description
                    }, ics_file_path)
                    logging.info(f"ICS file successfully generated: {img_file.name}")
                    tracker.mark_image_as_processed(img_file.name)
                else:
                    logging.warning(f"Failed to extract complete data for image {img_file.name}")
        else:
            logging.info(f"Skipping already processed image: {img_file.name}")
    
    ics_files = [ics_file for ics_file in ics_output_folder.iterdir() if ics_file.suffix.lower() == '.ics']
    for ics_file in ics_files:
        event_details = extract_event_details_from_ics(ics_file)
        if event_details:
            event_id = f"{event_details['title']}_{event_details['start_datetime']}_{event_details['place_name']}"
            if not tracker.is_event_sent(event_id):
                base_filename = ics_file.stem
                image_file = images_folder / f"{base_filename}.jpg"  # Asume que la imagen es jpg
                if image_file.exists():
                    response = send_event(config, event_details, base_filename, str(image_file))
                else:
                    response = send_event(config, event_details, base_filename)  # Sin imagen
                
                if response and response.status_code == 200:
                    tracker.mark_event_as_sent(event_id)
                    logging.info(f"Event sent and marked as processed: {event_id}")
                else:
                    logging.warning(f"Failed to send event: {event_id}")
            else:
                logging.info(f"Skipping already sent event: {event_id}")
        else:
            logging.warning(f'Failed to extract event details from {ics_file.name}')
    
    logging.info("All processes completed successfully.")
    tracker.close()

    # Clean up directories
    directories_to_clean = [
        config["directories"]["download_tracker"],
        config["directories"]["images"],
        config["directories"]["plain_text"],
        config["directories"]["ics"],
        'api_data'
    ]
    clean_directories(directories_to_clean)

if __name__ == "__main__":
    asyncio.run(main())