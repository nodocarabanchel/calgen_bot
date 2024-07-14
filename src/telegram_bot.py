import logging
from telethon import TelegramClient
from telethon.tl.types import InputPeerChannel
from pathlib import Path
import asyncio
from datetime import datetime, timedelta, timezone
from collections import defaultdict

class TelegramBot:
    def __init__(self, api_id, api_hash, phone, session_file, tracker, channel_ids, start_date=None, max_posters_per_day=50):
        self.client = TelegramClient(session_file, api_id, api_hash)
        self.phone = phone
        self.tracker = tracker
        self.channel_ids = channel_ids
        self.max_posters_per_day = max_posters_per_day
        
        if start_date:
            try:
                self.start_date = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                logging.error(f"Invalid start_date format: {start_date}. Using last 24 hours.")
                self.start_date = datetime.now(timezone.utc) - timedelta(days=1)
        else:
            self.start_date = datetime.now(timezone.utc) - timedelta(days=1)
        
        logging.info(f"Initialized TelegramClient with start date: {self.start_date}")

    async def start(self):
        await self.client.start(phone=self.phone)
        logging.info("TelegramClient started")

    async def stop(self):
        await self.client.disconnect()
        logging.info("TelegramClient stopped")

    async def download_images(self, image_folder):
        image_folder_path = Path(image_folder)
        image_folder_path.mkdir(parents=True, exist_ok=True)
        new_images_downloaded = 0
        daily_counts = defaultdict(int)

        for channel_id in self.channel_ids:
            try:
                entity = await self.client.get_entity(int(channel_id))
                logging.info(f"Processing channel/group with ID: {channel_id}")

                async for message in self.client.iter_messages(entity, reverse=True, offset_date=self.start_date):
                    message_date = message.date.replace(tzinfo=timezone.utc)
                    if message_date < self.start_date:
                        break

                    message_date_str = message_date.strftime("%Y-%m-%d")
                    if daily_counts[message_date_str] >= self.max_posters_per_day:
                        logging.info(f"Reached max posters limit for {message_date_str}")
                        continue

                    if message.photo:
                        if not self.tracker.is_image_downloaded(str(message.id)):
                            try:
                                file_path = image_folder_path / f"{message.id}.jpg"
                                await message.download_media(file=str(file_path))
                                logging.info(f"New image saved to {file_path}")

                                caption = message.text or ""
                                caption_file_path = image_folder_path / f"{message.id}.txt"
                                with open(caption_file_path, 'w', encoding='utf-8') as caption_file:
                                    caption_file.write(caption)

                                self.tracker.mark_image_as_downloaded(str(message.id))
                                new_images_downloaded += 1
                                daily_counts[message_date_str] += 1

                                if daily_counts[message_date_str] >= self.max_posters_per_day:
                                    logging.info(f"Reached max posters limit for {message_date_str}")
                            except Exception as e:
                                logging.error(f"Error downloading image: {e}")
                        else:
                            logging.info(f"Skipping already downloaded image: {message.id}")

            except Exception as e:
                logging.error(f"Error processing channel/group with ID {channel_id}: {e}")

        logging.info(f"Total new images downloaded: {new_images_downloaded}")
        return new_images_downloaded