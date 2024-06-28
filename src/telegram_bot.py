import logging
from telegram import Bot
from telegram.error import TelegramError
from pathlib import Path
import json

class TelegramBot:
    def __init__(self, token, chat_ids, offset_path, tracker):
        self.bot = Bot(token)
        self.chat_ids = [int(str(chat_id).strip()) for chat_id in chat_ids]
        self.offset_path = Path(offset_path)
        self.tracker = tracker

        # Create the offset file if it does not exist
        if not self.offset_path.exists():
            self.offset_path.write_text(json.dumps({"offset": 0}))

    def get_offset(self):
        try:
            with open(self.offset_path, 'r') as file:
                data = json.load(file)
            offset = data.get("offset", 0)
            logging.info(f"Retrieved offset: {offset}")
            return offset
        except Exception as e:
            logging.error(f"Error reading offset: {e}")
            return 0

    def update_offset(self, new_offset):
        try:
            with open(self.offset_path, 'w') as file:
                json.dump({"offset": new_offset}, file)
            logging.info(f"Updated offset to: {new_offset}")
        except Exception as e:
            logging.error(f"Error updating offset: {e}")

    async def download_images(self, image_folder):
        offset = self.get_offset()
        image_folder_path = Path(image_folder)
        image_folder_path.mkdir(parents=True, exist_ok=True)

        try:
            updates = await self.bot.get_updates(offset=offset)
            for update in updates:
                if update.update_id >= offset:
                    offset = update.update_id + 1  # Prepare for the next update
                
                if update.message and int(str(update.message.chat.id).strip()) in self.chat_ids:
                    if update.message.photo:
                        photo = update.message.photo[-1]
                        caption = update.message.caption or ""
                        
                        if not self.tracker.is_image_downloaded(photo.file_id):
                            try:
                                file = await self.bot.get_file(photo.file_id)
                                file_path = image_folder_path / f"{photo.file_id}.jpg"
                                await file.download_to_drive(str(file_path))
                                logging.info(f"New image saved to {file_path}")
                                
                                caption_file_path = image_folder_path / f"{photo.file_id}.txt"
                                with open(caption_file_path, 'w', encoding='utf-8') as caption_file:
                                    caption_file.write(caption)
                                
                                self.tracker.mark_image_as_downloaded(photo.file_id)
                            except TelegramError as e:
                                logging.error(f"Error fetching file: {e}")
                        else:
                            logging.info(f"Skipping already downloaded image: {photo.file_id}")
            
            self.update_offset(offset)
            logging.info(f"Final offset after processing updates: {offset}")
        except TelegramError as e:
            logging.error(f"Error fetching updates: {e}")
        except Exception as e:
            logging.error(f"An unexpected error occurred: {e}")