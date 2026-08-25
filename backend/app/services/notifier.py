import json
import logging
from typing import Protocol

from app.core.config import settings
from app.core.network import (
    UnsafeDestinationError,
    pinned_http_request,
    validate_https_url,
)

log = logging.getLogger(__name__)


class Notifier(Protocol):
    enabled: bool

    def send(self, message: str) -> None: ...


class TelegramNotifier:
    def __init__(self, api_key: str | None, chat_id: str | None) -> None:
        self.api_key = api_key
        self.chat_id = chat_id
        self._bot = None
        if api_key and chat_id:
            try:
                import telebot

                self._bot = telebot.TeleBot(api_key)
            except Exception as exc:
                log.warning("telegram init failed: %s", exc)
                self._bot = None
        self.enabled: bool = self._bot is not None

    def send(self, message: str) -> None:
        if not self.enabled:
            return
        try:
            self._bot.send_message(self.chat_id, message)  # type: ignore[union-attr]
        except Exception as exc:
            log.warning("telegram send failed: %s", exc)


class WebhookNotifier:
    def __init__(self, url: str | None, kind: str = "generic") -> None:
        self.url = None
        self.kind = kind.lower()
        if self.kind not in {"generic", "slack", "discord"}:
            log.warning("unsupported webhook kind; notifications disabled")
        elif url:
            try:
                self.url = validate_https_url(url)
            except UnsafeDestinationError as exc:
                log.warning("unsafe webhook configuration; notifications disabled: %s", exc)
        self.enabled: bool = self.url is not None

    def _payload(self, message: str) -> dict:
        if self.kind == "slack":
            return {"text": message}
        if self.kind == "discord":
            return {"content": message}
        return {"message": message, "source": "reconator"}

    def send(self, message: str) -> None:
        if not self.enabled:
            return
        try:
            body = json.dumps(
                self._payload(message),
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
            response = pinned_http_request(
                self.url or "",
                method="POST",
                headers={"Content-Type": "application/json"},
                content=body,
                timeout=10.0,
                max_response_bytes=64_000,
                allow_private=settings.allow_private_webhooks,
            )
            response.raise_for_status()
        except Exception as exc:
            log.warning("webhook send failed kind=%s: %s", self.kind, exc)


class CompositeNotifier:
    def __init__(self, *notifiers: Notifier) -> None:
        self._notifiers = notifiers
        self.enabled: bool = any(n.enabled for n in notifiers)

    def send(self, message: str) -> None:
        for n in self._notifiers:
            if n.enabled:
                n.send(message)


telegram = TelegramNotifier(settings.telegram_api_key, settings.telegram_chat_id)
webhook = WebhookNotifier(settings.webhook_url, settings.webhook_kind)
notifier = CompositeNotifier(telegram, webhook)
