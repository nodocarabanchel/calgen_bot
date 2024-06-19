import logging
from telegram import Bot, PhotoSize
from telegram.error import TelegramError
from pathlib import Path
import asyncio
import json
from datetime import datetime
import yaml

class TelegramBot:
    def __init__(self, token, download_tracker_path, offset_path, start_date=None, end_date=None):
        self.bot = Bot(token)
        self.download_tracker_path = Path(download_tracker_path)
        self.offset_path = Path(offset_path)
        self.start_date = start_date
        self.end_date = end_date

        # Create the tracker file if it does not exist
        if not self.download_tracker_path.exists():
            self.download_tracker_path.touch()

        # Create the offset file if it does not exist
        if not self.offset_path.exists():
            self.offset_path.write_text(json.dumps({"offset": 0}))

    def get_downloaded_ids(self):
        with open(self.download_tracker_path, 'r') as file:
            return set(file.read().splitlines())

    def add_downloaded_id(self, file_id):
        with open(self.download_tracker_path, 'a') as file:
            file.write(file_id + '\n')

    def get_offset(self):
        with open(self.offset_path, 'r') as file:
            data = json.load(file)
            return data.get("offset", 0)

    def update_offset(self, new_offset):
        with open(self.offset_path, 'w') as file:
            json.dump({"offset": new_offset}, file)

    def is_within_date_range(self, message_date):
        if self.start_date and message_date < self.start_date:
            return False
        if self.end_date and message_date > self.end_date:
            return False
        return True

    async def download_images(self, channel_id, image_folder):
        downloaded_ids = self.get_downloaded_ids()
        offset = self.get_offset()
    
        # Ensure the image folder exists
        image_folder_path = Path(image_folder)
        if not image_folder_path.exists():
            logging.info(f"Creating image folder at {image_folder}")
            image_folder_path.mkdir(parents=True, exist_ok=True)
    
        try:
            updates = await self.bot.get_updates(offset=offset)
    
            for update in updates:
                if update.update_id >= offset:
                    offset = update.update_id + 1  # Prepare for the next update
    
                if update.message:
                    update_chat_id = int(str(update.message.chat.id).strip())
                    expected_channel_id = int(str(channel_id).strip())
    
                    if update_chat_id == expected_channel_id:
                        await self.process_update(update, downloaded_ids, image_folder_path)
    
            self.update_offset(offset)
    
        except TelegramError as e:
            logging.error(f"Error fetching updates: {e}")
        except Exception as e:
            logging.error(f"An unexpected error occurred: {e}")
    
    async def process_update(self, update, downloaded_ids, image_folder_path):
        if update.message.photo:
            # Get the highest resolution photo
            photo: PhotoSize = update.message.photo[-1]
    
            # Get the caption of the image if available
            caption = update.message.caption or ""
    
            message_date = update.message.date
    
            # Check if the message date is within the specified range if dates are provided
            if self.start_date or self.end_date:
                if not self.is_within_date_range(message_date):
                    return
    
            if photo.file_id not in downloaded_ids:
                try:
                    await self.download_and_save_image(photo, downloaded_ids, image_folder_path, caption)
                except TelegramError as e:
                    logging.error(f"Error fetching file: {e}")
    
    async def download_and_save_image(self, photo, downloaded_ids, image_folder_path, caption):
        file = await self.bot.get_file(photo.file_id)
        file_path = image_folder_path / f"{photo.file_id}.jpg"
    
        # Download the file
        await file.download_to_drive(str(file_path))
        logging.info(f"Image saved to {file_path}")
    
        # Save the caption to a text file
        caption_file_path = image_folder_path / f"{photo.file_id}.txt"
        with open(caption_file_path, 'w', encoding='utf-8') as caption_file:
            caption_file.write(caption)
    
        self.add_downloaded_id(photo.file_id)

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

async def main():
    config = load_config()
    setup_logging(config)

    if config["telegram_bot"]["use"]:
        bot = TelegramBot(
            config["telegram_bot"]["token"],
            config["telegram_bot"]["download_tracker_path"],
            config["telegram_bot"]["offset_path"],
            start_date=datetime.fromisoformat(config["telegram_bot"]["start_date"]) if config["telegram_bot"]["start_date"] else None,
            end_date=datetime.fromisoformat(config["telegram_bot"]["end_date"]) if config["telegram_bot"]["end_date"] else None
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
