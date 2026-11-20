from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any
import httpx

logger = logging.getLogger(__name__)

class GhasedakSmsClient:
    BASE_URL = "https://gateway.ghasedak.me/rest/api/v1/webservice"
    SEND_SINGLE_SMS_PATH = "/sendsinglesms"

    def __init__(
        self,
        *,
        api_key: str,
        line_number: str,
        timeout: float = 15.0,
    ) -> None:
        if not api_key:
            raise ValueError("Ghasedak API key cannot be empty.")

        if not line_number:
            raise ValueError("Ghasedak line number cannot be empty.")

        self._api_key = api_key
        self._line_number = line_number
        self._timeout = timeout

    def send(
        self,
        *,
        receptor: str,
        message: str,
        client_reference_id: str = "",
        send_date: datetime | None = None,
    ) -> dict[str, Any]:

        if not receptor:
            raise ValueError("SMS receptor cannot be empty.")

        if not message:
            raise ValueError("SMS message cannot be empty.")

        scheduled_at = send_date or datetime.now(timezone.utc)

        if scheduled_at.tzinfo is None:
            raise ValueError("send_date must be timezone-aware.")

        payload = {
            "send_date": scheduled_at.isoformat(),
            "line_number": self._line_number,
            "message": message,
            "receptor": receptor,
            "client_reference_id": client_reference_id,
        }

        try:
            response = httpx.post(
                f"{self.BASE_URL}{self.SEND_SINGLE_SMS_PATH}",
                headers={
                    "apiKey": self._api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._timeout,
            )

            response.raise_for_status()

            response_data = response.json()

        except httpx.HTTPError as exc:
            logger.exception("Ghasedak SMS request failed.")
            raise RuntimeError(
                "Failed to send SMS request."
            ) from exc

        except ValueError as exc:
            logger.exception("Invalid response received from Ghasedak.")
            raise RuntimeError(
                "Invalid response received from Ghasedak."
            ) from exc

        if not isinstance(response_data, dict):
            raise RuntimeError("Unexpected Ghasedak response format.")

        if response_data.get("isSuccess") is not True:
            error_message = response_data.get(
                "message",
                "SMS sending failed.",
            )

            raise RuntimeError(str(error_message))

        logger.info(
            "SMS successfully submitted to Ghasedak. Receptor: %s",
            receptor,
        )

        return response_data
