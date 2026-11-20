import os

import uvicorn
from config import settings
from config.logging import configure_logging


def main():
    configure_logging("model-api")
    uvicorn.run(
        "services.detection.app:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        workers=1,
        access_log=False,
        log_config=None,
    )


if __name__ == "__main__":
    main()
