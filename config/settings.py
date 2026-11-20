import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

APP_NAME = os.getenv("APP_NAME", "Digit-OCR")
APP_ENV = os.getenv("APP_ENV", "development")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

MONGODB_URI = os.getenv(
    "MONGODB_URI",
    "mongodb://localhost:27017",
)

MONGODB_DATABASE = os.getenv(
    "MONGODB_DATABASE",
    "digit_ocr7",
)

MONGODB_TIMEOUT_MS = int(os.getenv("MONGODB_TIMEOUT_MS", "5000"))

OCR_MAX_CONCURRENCY = int(
    os.getenv("OCR_MAX_CONCURRENCY", "4")
)
if OCR_MAX_CONCURRENCY < 1:
    raise ValueError("OCR_MAX_CONCURRENCY must be positive.")

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
if MAX_UPLOAD_BYTES < 1:
    raise ValueError("MAX_UPLOAD_BYTES must be positive.")


YOURCOMPANY_DB_HOST = os.getenv("YOURCOMPANY_DB_HOST")
YOURCOMPANY_DB_USER = os.getenv("YOURCOMPANY_DB_USER")
YOURCOMPANY_DB_PASSWORD = os.getenv("YOURCOMPANY_DB_PASSWORD")
YOURCOMPANY_DB_NAME = os.getenv("YOURCOMPANY_DB_NAME")

GHASEDAK_API_KEY = os.getenv("GHASEDAK_API_KEY")
GHASEDAK_LINE_NUMBER = os.getenv("GHASEDAK_LINE_NUMBER")

DAILY_REPORT_ENABLED = os.getenv("DAILY_REPORT_ENABLED", "false").strip().lower() in {
    "true", "1", "yes",
}

YOURCOMPANY_ERP_ENABLED_VALUE = os.getenv("YOURCOMPANY_ERP_ENABLED", "true").strip().lower()
if YOURCOMPANY_ERP_ENABLED_VALUE not in {"true", "false"}:
    raise ValueError("YOURCOMPANY_ERP_ENABLED must be true or false.")
YOURCOMPANY_ERP_ENABLED = YOURCOMPANY_ERP_ENABLED_VALUE == "true"
YOURCOMPANY_EXPORT_DIR = Path(os.getenv("YOURCOMPANY_EXPORT_DIR", str(PROJECT_ROOT / "infrastructure/storage/yourcompany_exports"))).expanduser()
if not YOURCOMPANY_EXPORT_DIR.is_absolute():
    YOURCOMPANY_EXPORT_DIR = PROJECT_ROOT / YOURCOMPANY_EXPORT_DIR
