from __future__ import annotations
import logging
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import jdatetime
from domain.measurements import MeasurementUnit, resolve_unit
from infrastructure.database.mongodb.repositories import MeasurementPointRepository
from infrastructure.yourcompany.erp_client import YourCompanyERPClient
from infrastructure.notification.sms import GhasedakSmsClient

logger = logging.getLogger(__name__)

RECORD_TYPES = [
    "Temperature point 01",
    "Temperature point 02",
    "Temperature point 03",
]

class TemperatureReportService:
    def __init__(self, erp_client: YourCompanyERPClient, sms_client: GhasedakSmsClient, recipients: list[str], *, measurement_repository: MeasurementPointRepository | None = None) -> None:
        if not recipients:
            raise ValueError("At least one SMS recipient is required.")

        self._erp_client = erp_client
        self._sms_client = sms_client
        self._recipients = recipients
        self._measurement_repository = measurement_repository

    def generate_yesterday_report(self) -> str:
        yesterday = datetime.now(ZoneInfo("Asia/Tehran")).date() - timedelta(days=1)
        report_date = jdatetime.date.fromgregorian(date=yesterday).strftime("%Y/%m/%d")
        record_types = self._get_record_types()

        temperatures = self._erp_client.get_daily_temperatures(
            report_date=report_date,
            record_types=record_types,
        ) if record_types else {}

        report = self._build_report(
            report_date=report_date,
            temperatures=temperatures,
            record_types=record_types,
        )

        logger.info(
            "Daily temperature report generated. Date: %s",
            report_date,
        )

        return report

    def _get_record_types(self) -> list[str]:
        if self._measurement_repository is None:
            return list(RECORD_TYPES)

        record_types = []
        for camera in self._measurement_repository.list_active():
            unit = resolve_unit(camera["camera_code"], camera.get("unit"))
            description = camera.get("description")
            if unit == MeasurementUnit.CELSIUS.value and isinstance(description, str) and description.strip():
                record_types.append(description.strip())

        return list(dict.fromkeys(record_types))

    @staticmethod
    def _temperature_values(raw_values: list[float]) -> list[float]:
        return [
            float(value) / 10
            for value in raw_values
            if not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            and value != -2
        ]

    @staticmethod
    def _build_report(
        *,
        report_date: str,
        temperatures: dict[str, list[float]],
        record_types: list[str] | None = None,
    ) -> str:
        report_sections = [
            f"📡 گزارش روزانه دما - {report_date}",
        ]

        for record_type in RECORD_TYPES if record_types is None else record_types:
            values = TemperatureReportService._temperature_values(
                temperatures.get(record_type, [])
            )

            if not values:
                section = (
                    f"\n⚠️ {record_type}\n"
                    "داده‌ای برای این محل ثبت نشده است."
                )
            else:
                maximum = max(values)
                minimum = min(values)
                average = sum(values) / len(values)

                section = (
                    f"\n📍 {record_type}\n"
                    f"🔺 بالاترین: {maximum:.2f} درجه سانتی‌گراد\n"
                    f"🔻 کمترین: {minimum:.2f} درجه سانتی‌گراد\n"
                    f"📊 میانگین: {average:.2f} درجه سانتی‌گراد\n"
                    f"📝 تعداد رکورد: {len(values)}"
                )

            report_sections.append(section)

        return "\n".join(report_sections)


    def send_yesterday_report(self) -> str:
        report = self.generate_yesterday_report()

        for recipient in self._recipients:
            self._sms_client.send(
                receptor=recipient,
                message=report,
                client_reference_id=(
                    f"daily-temperature-report-{recipient}"
                ),
            )

            logger.info(
                "Daily temperature report sent to recipient: %s",
                recipient,
            )

        return report
