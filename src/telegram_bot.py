import logging
from telegram import Bot, PhotoSize
from telegram.error import TelegramError
from pathlib import Path
import json

class TelegramBot:
    def __init__(self, token, chat_ids, download_tracker_path, offset_path):
        self.bot = Bot(token)
        self.chat_ids = [int(str(chat_id).strip()) for chat_id in chat_ids]
        self.download_tracker_path = Path(download_tracker_path)
        self.offset_path = Path(offset_path)

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

    async def download_images(self, image_folder):
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

                    if update_chat_id in self.chat_ids:
                        if update.message.photo:
                            # Get the highest resolution photo
                            photo: PhotoSize = update.message.photo[-1]

                            # Get the caption of the image if available
                            caption = update.message.caption or ""

                            if photo.file_id not in downloaded_ids:
                                try:
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
                                except TelegramError as e:
                                    logging.error(f"Error fetching file: {e}")

            self.update_offset(offset)

        except TelegramError as e:
            logging.error(f"Error fetching updates: {e}")
        except Exception as e:
            logging.error(f"An unexpected error occurred: {e}")
