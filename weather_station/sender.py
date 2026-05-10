import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


class ImageSender(ABC):
    """Abstract sender — swap TelegramSender for BluetoothSender to change transport."""

    @abstractmethod
    def send(self, images: list[Path], satellite: str, capture_time: datetime) -> bool:
        pass


class TelegramSender(ImageSender):
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id

    def _url(self, method: str) -> str:
        return _TELEGRAM_API.format(token=self.bot_token, method=method)

    def send_text(self, text: str) -> bool:
        try:
            resp = requests.post(
                self._url("sendMessage"),
                data={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                timeout=30,
            )
            if resp.ok:
                logger.info("Text message sent via Telegram")
                return True
            logger.error("Telegram API error %s: %s", resp.status_code, resp.text)
            return False
        except requests.RequestException as e:
            logger.error("Telegram send_text failed: %s", e)
            return False

    def send(self, images: list[Path], satellite: str, capture_time: datetime) -> bool:
        caption_base = (
            f"Satélite: {satellite}\n"
            f"Captura: {capture_time.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        labels = ["B&N", "Realce térmico"]
        success = True

        for i, image in enumerate(images):
            if not image.exists():
                logger.warning("Image not found, skipping: %s", image)
                continue

            caption = caption_base
            if len(images) > 1 and i < len(labels):
                caption += f"\nTipo: {labels[i]}"

            try:
                with open(image, "rb") as fh:
                    resp = requests.post(
                        self._url("sendPhoto"),
                        data={"chat_id": self.chat_id, "caption": caption},
                        files={"photo": fh},
                        timeout=60,
                    )
                if resp.ok:
                    logger.info("Sent via Telegram: %s", image.name)
                else:
                    logger.error("Telegram API error %s: %s", resp.status_code, resp.text)
                    success = False
            except requests.RequestException as e:
                logger.error("Telegram send failed: %s", e)
                success = False

        return success


class BluetoothSender(ImageSender):
    """Bluetooth OBEX transport — replace TelegramSender with this class when ready.

    Implementation requires pybluez and obexftp (or similar OBEX library).
    """

    def __init__(self, device_address: str):
        self.device_address = device_address

    def send(self, images: list[Path], satellite: str, capture_time: datetime) -> bool:
        # TODO: implement using pybluez / obexftp
        raise NotImplementedError(
            "Bluetooth OBEX sender is not yet implemented. "
            "Implement this method using pybluez and obexftp."
        )
