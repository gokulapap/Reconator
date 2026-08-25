import logging
import sys

from pythonjsonlogger import jsonlogger

from app.core.config import settings
from app.core.middleware import RequestIDLogFilter

_REDACT_KEYS = {
    "password",
    "telegram_api_key",
    "admin_api_key",
    "api_key",
    "x-api-key",
    "secret",
    "token",
    "authorization",
}


class _RedactingFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        for key in list(log_record.keys()):
            if key.lower() in _REDACT_KEYS and log_record[key]:
                log_record[key] = "***"


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        _RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(request_id)s %(message)s")
    )
    handler.addFilter(RequestIDLogFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())

    for noisy in ("uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
