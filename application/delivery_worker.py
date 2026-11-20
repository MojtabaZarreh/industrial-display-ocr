from __future__ import annotations
import logging
import threading
import time
from typing import Any
from infrastructure.database.mongodb.repositories import DeliveryOutboxRepository
from infrastructure.yourcompany.erp_client import YourCompanyERPClient

logger = logging.getLogger(__name__)


class DeliveryWorker:
    def __init__(
        self,
        outbox_repository: DeliveryOutboxRepository,
        erp_client: YourCompanyERPClient | None = None,
        *,
        file_sink=None,
        poll_interval: float = 2.0,
        lease_seconds: int = 60,
    ) -> None:
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive.")

        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive.")

        if (erp_client is None) == (file_sink is None):
            raise ValueError("Provide exactly one delivery destination.")
        self._file_sink = file_sink
        self._destination = "file" if file_sink is not None else "erp"
        self._outbox = outbox_repository
        self._erp_client = erp_client
        self._poll_interval = poll_interval
        self._lease_seconds = lease_seconds
        self._stop_event = threading.Event()

    def run_once(self) -> bool:

        event = self._outbox.claim_next_event(
            lease_seconds=self._lease_seconds, destination=self._destination,
        )

        if event is None:
            if self._file_sink is not None:
                self._file_sink.flush()
            return False

        event_id = event["event_id"]
        camera_code = event["camera_code"]
        erp_data: dict[str, Any] = event["erp_data"]

        logger.debug(
            "Processing delivery: event_id=%s camera_code=%s",
            event_id,
            camera_code,
        )

        try:
            if self._file_sink is not None:
                self._file_sink.record(event)
            else:
                self._erp_client.insert_temperature(erp_data)

            marked = self._outbox.mark_as_sent(event_id)

            if not marked:
                logger.error(
                    "Delivery succeeded but event status "
                    "could not be updated: event_id=%s",
                    event_id,
                )
                return True

            logger.info(
                "Delivery completed successfully: destination=%s "
                "event_id=%s camera_code=%s value=%s attempts=%s",
                self._destination,
                event_id,
                camera_code,
                erp_data.get("Temperature"),
                event.get("attempts", 1),
            )

        except Exception as exc:
            logger.exception(
                "Delivery failed: event_id=%s camera_code=%s",
                event_id,
                camera_code,
            )

            try:
                marked = self._outbox.mark_as_failed(
                    event_id,
                    str(exc),
                )

                if not marked:
                    logger.error(
                        "Could not update failed event: event_id=%s",
                        event_id,
                    )

            except Exception:
                logger.exception(
                    "Failed to schedule delivery retry: "
                    "event_id=%s",
                    event_id,
                )

        return True

    def run_forever(self) -> None:
        """
        Continuously process pending ERP delivery events.
        """

        logger.info("DeliveryWorker started.")

        try:
            while not self._stop_event.is_set():
                try:
                    processed = self.run_once()

                    if not processed:
                        self._stop_event.wait(
                            self._poll_interval
                        )

                except Exception:
                    logger.exception(
                        "Unexpected error in DeliveryWorker."
                    )

                    self._stop_event.wait(
                        self._poll_interval
                    )

        finally:
            if self._file_sink is not None:
                self._file_sink.flush(force=True)
            logger.info("DeliveryWorker stopped.")

    def stop(self) -> None:
        self._stop_event.set()
