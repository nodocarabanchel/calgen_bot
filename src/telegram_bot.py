import logging
from telegram import Bot
from pathlib import Path
import json
import asyncio

class TelegramBot:
    def __init__(self, token, offset_path, tracker):
        self.bot = Bot(token)
        self.offset_path = Path(offset_path)
        self.tracker = tracker
        self.offset = self.load_offset()
        logging.info(f"Initialized with offset: {self.offset}")

    def load_offset(self):
        if self.offset_path.exists():
            with open(self.offset_path, 'r') as file:
                data = json.load(file)
                offset = data.get("offset", 0)
                logging.info(f"Loaded offset: {offset}")
                return offset
        logging.info("No offset file found, starting from 0")
        return 0

    def save_offset(self, new_offset):
        with open(self.offset_path, 'w') as file:
            json.dump({"offset": new_offset}, file)
        logging.info(f"Saved offset: {new_offset}")

    async def download_images(self, image_folder):
        image_folder_path = Path(image_folder)
        image_folder_path.mkdir(parents=True, exist_ok=True)
        new_images_downloaded = 0

        while True:
            updates = await self.bot.get_updates(offset=self.offset, limit=100, timeout=60)
            if not updates:
                logging.info("No new updates available.")
                break

            for update in updates:
                self.offset = update.update_id + 1
                message = update.message or update.channel_post
                if message and message.photo:
                    photo = message.photo[-1]
                    if not self.tracker.is_image_downloaded(photo.file_id):
                        try:
                            file = await self.bot.get_file(photo.file_id)
                            file_path = image_folder_path / f"{photo.file_id}.jpg"
                            await file.download_to_drive(str(file_path))
                            logging.info(f"New image saved to {file_path}")
                            caption = message.caption or ""
                            caption_file_path = image_folder_path / f"{photo.file_id}.txt"
                            with open(caption_file_path, 'w', encoding='utf-8') as caption_file:
                                caption_file.write(caption)
                            self.tracker.mark_image_as_downloaded(photo.file_id)
                            new_images_downloaded += 1
                        except Exception as e:
                            logging.error(f"Error downloading image: {e}")
                    else:
                        logging.info(f"Skipping already downloaded image: {photo.file_id}")
            
            self.save_offset(self.offset)
            logging.info(f"Processed batch of updates. New offset: {self.offset}")

            if len(updates) < 100:
                break

            await asyncio.sleep(1)  # Small delay to avoid hitting rate limits

        logging.info(f"Final offset after processing all updates: {self.offset}")
        logging.info(f"Total new images downloaded: {new_images_downloaded}")
        return new_images_downloaded