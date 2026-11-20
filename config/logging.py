import json
import logging
import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ServiceFormatter(logging.Formatter):
    COLORS = {"DEBUG": "36", "INFO": "32", "WARNING": "33", "ERROR": "31", "CRITICAL": "35"}
    URL_CREDENTIALS = re.compile(r"(?i)\b((?:mongodb(?:\+srv)?|rtsps?|https?)://)[^/\s]+@")

    def __init__(self, service: str, *, json_output: bool = False, color: bool = False):
        super().__init__()
        self.service = service
        self.json_output = json_output
        self.color = color and not json_output
        try:
            self.timezone = ZoneInfo(os.getenv("LOG_TIMEZONE", "Asia/Tehran"))
        except ZoneInfoNotFoundError:
            self.timezone = ZoneInfo("UTC")

    def _redact(self, message: str) -> str:
        message = self.URL_CREDENTIALS.sub(r"\1***@", message)
        for key in ("DETECTION_API_KEY", "GHASEDAK_API_KEY", "YOURCOMPANY_DB_PASSWORD", "MONGO_INITDB_ROOT_PASSWORD"):
            secret = os.getenv(key, "")
            if len(secret) >= 4:
                message = message.replace(secret, "***")
        return message

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, self.timezone).isoformat(timespec="milliseconds")
        message = self._redact(record.getMessage())
        exception = self._redact(self.formatException(record.exc_info)) if record.exc_info else None

        if self.json_output:
            entry = {"timestamp": timestamp, "level": record.levelname, "service": self.service,
                     "logger": record.name, "message": message}
            if exception:
                entry["exception"] = exception
            return json.dumps(entry, ensure_ascii=False)

        level = f"{record.levelname:<8}"
        if self.color:
            level = f"\033[{self.COLORS.get(record.levelname, '0')}m{level}\033[0m"
        output = f"{timestamp} | {level} | {self.service:<9} | {record.name} | {message}"
        return f"{output}\n{exception}" if exception else output


def configure_logging(service: str) -> None:
    color_mode = os.getenv("LOG_COLOR", "auto").lower()
    color = color_mode == "always" or (color_mode == "auto" and sys.stdout.isatty())
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ServiceFormatter(
        service, json_output=os.getenv("LOG_FORMAT", "text").lower() == "json", color=color,
    ))
    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(level=level, handlers=[handler], force=True)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    for name in ("httpx", "httpcore", "urllib3", "pymongo", "apscheduler"):
        logging.getLogger(name).setLevel(logging.WARNING)
