import logging
import os
from config import settings
from infrastructure.yourcompany.erp_client import YourCompanyERPClient
from infrastructure.notification.sms import GhasedakSmsClient
from application.temperature_report_service import TemperatureReportService

logging.basicConfig(level=logging.INFO)

def main() -> None:
    erp_client = YourCompanyERPClient(
        host=settings.YOURCOMPANY_DB_HOST,
        user=settings.YOURCOMPANY_DB_USER,
        password=settings.YOURCOMPANY_DB_PASSWORD,
        database=settings.YOURCOMPANY_DB_NAME,
    )

    sms_client = GhasedakSmsClient(
        api_key=settings.GHASEDAK_API_KEY,
        line_number=settings.GHASEDAK_LINE_NUMBER,
    )

    report_service = TemperatureReportService(
        erp_client=erp_client,
        sms_client=sms_client,
        recipients=[value.strip() for value in os.getenv("DAILY_REPORT_RECIPIENTS", "").split(",") if value.strip()],
    )

    report = report_service.send_yesterday_report()

    print("\nDaily report sent:")
    print(report)


if __name__ == "__main__":
    main()
