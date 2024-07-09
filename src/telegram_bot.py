import logging
from telegram import Bot
from telegram.error import TelegramError
from pathlib import Path
import json

class TelegramBot:
    def __init__(self, token, offset_path, tracker):
        self.bot = Bot(token)
        self.offset_path = Path(offset_path)
        self.tracker = tracker
        self.offset = self.load_offset()

    def load_offset(self):
        if self.offset_path.exists():
            with open(self.offset_path, 'r') as file:
                data = json.load(file)
                return data.get("offset", 0)
        return 0

    def save_offset(self, new_offset):
        with open(self.offset_path, 'w') as file:
            json.dump({"offset": new_offset}, file)
        self.offset = new_offset

    async def get_all_chats_and_channels(self):
        chats_and_channels = []
        try:
            updates = await self.bot.get_updates(offset=self.offset, timeout=30)
            for update in updates:
                if update.message and update.message.chat.id not in chats_and_channels:
                    chats_and_channels.append(update.message.chat.id)
                elif update.channel_post and update.channel_post.chat.id not in chats_and_channels:
                    chats_and_channels.append(update.channel_post.chat.id)
        except Exception as e:
            logging.error(f"Error getting chats and channels: {e}")
        return chats_and_channels

    async def download_images(self, image_folder):
        image_folder_path = Path(image_folder)
        image_folder_path.mkdir(parents=True, exist_ok=True)
        try:
            chats_and_channels = await self.get_all_chats_and_channels()
            updates = await self.bot.get_updates(offset=self.offset)
            new_offset = self.offset
            new_images_downloaded = 0
            for update in updates:
                if update.update_id >= new_offset:
                    new_offset = update.update_id + 1
                    message = update.message or update.channel_post
                    if message and message.chat.id in chats_and_channels:
                        if message.photo:
                            photo = message.photo[-1]
                            caption = message.caption or ""
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
                                    new_images_downloaded += 1
                                except TelegramError as e:
                                    logging.error(f"Error fetching file: {e}")
                            else:
                                logging.info(f"Skipping already downloaded image: {photo.file_id}")
            if new_offset > self.offset:
                self.save_offset(new_offset)
                logging.info(f"Updated offset to: {new_offset}")
            logging.info(f"Final offset after processing updates: {new_offset}")
            logging.info(f"New images downloaded in this execution: {new_images_downloaded}")
        except Exception as e:
            logging.error(f"An error occurred while downloading images: {e}")