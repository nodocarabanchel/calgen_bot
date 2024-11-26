import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from telethon import TelegramClient

logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(
        self,
        api_id,
        api_hash,
        phone,
        session_file,
        db_manager,
        channels,  # Lista de diccionarios {id, name}
        start_date=None,
        max_posters_per_day=50,
    ):
        self.client = TelegramClient(session_file, api_id, api_hash)
        self.phone = phone
        self.db_manager = db_manager
        self.channels = channels
        self.start_date = (
            datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if start_date
            else None
        )
        self.max_posters_per_day = max_posters_per_day
        self._is_started = False

    async def start(self):
        """Iniciar el cliente de Telegram."""
        if not self._is_started:
            try:
                await self.client.start(phone=self.phone)
                self._is_started = True
                logger.info("TelegramClient started successfully")
            except Exception as e:
                logger.error(f"Error starting TelegramClient: {e}")
                raise

    async def stop(self):
        """Detener el cliente de Telegram."""
        if self._is_started:
            try:
                await self.client.disconnect()
                self._is_started = False
                logger.info("TelegramClient stopped")
            except Exception as e:
                logger.error(f"Error stopping TelegramClient: {e}")
                raise

    async def download_images(self, image_folder):
        """Descargar imágenes de los canales configurados."""
        if not self._is_started:
            await self.start()

        image_folder_path = Path(image_folder)
        image_folder_path.mkdir(parents=True, exist_ok=True)
        new_images_downloaded = 0
        daily_counts = {}

        for channel in self.channels:
            channel_id = channel['id']
            channel_name = channel['name']
            try:
                entity = await self.client.get_entity(int(channel_id))
                logger.info(f"Processing channel: {channel_name} (ID: {channel_id})")

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
                        message_id = str(message.id)
                        if not self.db_manager.is_image_downloaded(message_id):
                            try:
                                file_path = image_folder_path / f"{channel_id}_{message_id}.jpg"
                                await message.download_media(file=str(file_path))
                                logger.info(f"New image saved to {file_path}")

                                # Guardar metadata y caption
                                metadata = {
                                    "text": message.text or "",
                                    "channel_name": channel_name,
                                    "channel_id": channel_id,
                                    "source": "Generado automáticamente via CalGen Bot",
                                    "date": message.date.isoformat()
                                }
                                
                                metadata_file_path = (
                                    image_folder_path / f"{channel_id}_{message_id}.json"
                                )
                                with open(
                                    metadata_file_path, "w", encoding="utf-8"
                                ) as metadata_file:
                                    json.dump(metadata, metadata_file, ensure_ascii=False, indent=2)

                                self.db_manager.mark_image_as_downloaded(message_id)
                                new_images_downloaded += 1
                                daily_counts[date_key] += 1

                                logger.debug(f"Saved metadata for image {message_id} from channel {channel_name}")

                            except Exception as e:
                                logger.error(f"Error downloading image from {channel_name}: {e}")
                        else:
                            logger.debug(f"Image {message_id} from {channel_name} already downloaded")

            except Exception as e:
                logger.error(f"Error processing channel {channel_name}: {e}")

        logger.info(f"Total new images downloaded: {new_images_downloaded}")
        return new_images_downloaded

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()