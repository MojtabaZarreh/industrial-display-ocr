import logging
from config import settings
from infrastructure.notification.sms import GhasedakSmsClient
from infrastructure.yourcompany.erp_client import YourCompanyERPClient
from application.temperature_report_service import (
    TemperatureReportService,
)

logging.basicConfig(level=logging.INFO)


def main() -> None:
    erp_client = YourCompanyERPClient(
        host=settings.YOURCOMPANY_DB_HOST,
        user=settings.YOURCOMPANY_DB_USER,
        password=settings.YOURCOMPANY_DB_PASSWORD,
        database=settings.YOURCOMPANY_DB_NAME,
    )

    report_service = TemperatureReportService(
        erp_client=erp_client,
        sms_client=GhasedakSmsClient(
            api_key=settings.GHASEDAK_API_KEY,
            line_number=settings.GHASEDAK_LINE_NUMBER,
        ),
        recipients=["preview-only"],
    )

    report = report_service.generate_yesterday_report()

    print("\n" + "=" * 50)
    print(report)
    print("=" * 50)


if __name__ == "__main__":
    main()
