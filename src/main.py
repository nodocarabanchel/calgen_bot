import os
import yaml
import logging
from pathlib import Path
from telegram_bot import TelegramBot
from calendar_generator import OCRReader, EntityExtractor, ICSExporter
import asyncio

def load_config():
    with open("settings.yaml", "r") as file:
        return yaml.safe_load(file)

def setup_logging(config):
    log_file = config.get("logging", {}).get("log_file", "default.log")
    log_level = config.get("logging", {}).get("log_level", "INFO").upper()

    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )

def process_images(config, image_files, text_output_folder, ics_output_folder):
    ocr_service = config["ocr_service"]
    google_config = config.get("google_document_ai")
    
    logging.info(f"Initializing OCR reader with service: {ocr_service}")
    reader = OCRReader(ocr_service, google_config)
    extractor = EntityExtractor(config)
    exporter = ICSExporter()

    for img_file in image_files:
        text_file_path = text_output_folder / (img_file.stem + '.txt')
        ics_file_path = ics_output_folder / (img_file.stem + '.ics')

        text = reader.read(img_file)
        
        # Read the caption
        caption_file_path = img_file.with_suffix('.txt')
        if caption_file_path.exists():
            with open(caption_file_path, 'r', encoding='utf-8') as caption_file:
                caption = caption_file.read()
        else:
            caption = ""

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
            else:
                logging.warning(f"Failed to extract complete data for image {img_file.name}")

async def main():
    config = load_config()
    setup_logging(config)

    if config["telegram_bot"]["use"]:
        bot = TelegramBot(
            config["telegram_bot"]["token"],
            config["telegram_bot"]["download_tracker_path"],
            config["telegram_bot"]["offset_path"]
        )
        await bot.download_images(config["telegram_bot"]["chat_id"], "./images")

    images_folder = Path("images")
    text_output_folder = Path("plain_texts")
    ics_output_folder = Path("ics")

    text_output_folder.mkdir(exist_ok=True)
    ics_output_folder.mkdir(exist_ok=True)

    image_files = [img_file for img_file in images_folder.iterdir() if img_file.suffix.lower() in OCRReader.SUPPORTED_FORMATS]
    
    process_images(config, image_files, text_output_folder, ics_output_folder)
    logging.info("All processes completed successfully.")

if __name__ == "__main__":
    asyncio.run(main())
