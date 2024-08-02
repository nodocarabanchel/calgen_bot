import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from telethon import TelegramClient
from telethon.tl.types import InputPeerChannel

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(
        self,
        api_id,
        api_hash,
        phone,
        session_file,
        db_manager,
        channel_ids,
        start_date=None,
        max_posters_per_day=50,
    ):
        self.client = TelegramClient(session_file, api_id, api_hash)
        self.phone = phone
        self.db_manager = db_manager
        self.channel_ids = channel_ids
        self.start_date = (
            datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if start_date
            else None
        )
        self.max_posters_per_day = max_posters_per_day

    async def start(self):
        await self.client.start(phone=self.phone)
        logger.info("TelegramClient started")

    async def stop(self):
        await self.client.disconnect()
        logger.info("TelegramClient stopped")

    async def download_images(self, image_folder):
        image_folder_path = Path(image_folder)
        image_folder_path.mkdir(parents=True, exist_ok=True)
        new_images_downloaded = 0
        daily_counts = {}

        for channel_id in self.channel_ids:
            try:
                entity = await self.client.get_entity(int(channel_id))
                logger.info(f"Processing channel/group with ID: {channel_id}")

                async for message in self.client.iter_messages(
                    entity, reverse=True, offset_date=self.start_date
                ):
                    if self.start_date and message.date < self.start_date:
                        break

                    date_key = message.date.strftime("%Y-%m-%d")
                    if date_key not in daily_counts:
                        daily_counts[date_key] = 0

                    if daily_counts[date_key] >= self.max_posters_per_day:
                        logger.info(f"Reached max posters limit for {date_key}")
                        continue

                    if message.photo:
                        if not self.db_manager.is_image_downloaded(str(message.id)):
                            try:
                                file_path = image_folder_path / f"{message.id}.jpg"
                                await message.download_media(file=str(file_path))
                                logger.info(f"New image saved to {file_path}")

                                caption = message.text or ""
                                caption_file_path = (
                                    image_folder_path / f"{message.id}.txt"
                                )
                                with open(
                                    caption_file_path, "w", encoding="utf-8"
                                ) as caption_file:
                                    caption_file.write(caption)

                                self.db_manager.mark_image_as_downloaded(
                                    str(message.id)
                                )
                                new_images_downloaded += 1
                                daily_counts[date_key] += 1

                                if daily_counts[date_key] >= self.max_posters_per_day:
                                    logger.info(
                                        f"Reached max posters limit for {date_key}"
                                    )
                            except Exception as e:
                                logger.error(f"Error downloading image: {e}")

            except Exception as e:
                logger.error(
                    f"Error processing channel/group with ID {channel_id}: {e}"
                )

        logger.info(f"Total new images downloaded: {new_images_downloaded}")
        return new_images_downloaded
