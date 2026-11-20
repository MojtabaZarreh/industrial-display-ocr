from datetime import timedelta
import logging
import jdatetime
from config import settings
from infrastructure.yourcompany.erp_client import YourCompanyERPClient


logging.basicConfig(level=logging.INFO)

RECORD_TYPES = [
    "Temperature point 01",
    "Temperature point 02",
    "Temperature point 03",
]


def main() -> None:
    yesterday = (
        jdatetime.date.today() - jdatetime.timedelta(days=1)
    )

    report_date = yesterday.strftime("%Y/%m/%d")

    print(f"\nReport date: {report_date}")

    erp_client = YourCompanyERPClient(
        host=settings.YOURCOMPANY_DB_HOST,
        user=settings.YOURCOMPANY_DB_USER,
        password=settings.YOURCOMPANY_DB_PASSWORD,
        database=settings.YOURCOMPANY_DB_NAME,
    )

    results = erp_client.get_daily_temperatures(
        report_date=report_date,
        record_types=RECORD_TYPES,
    )

    print("\nDaily temperature results:")
    print("-" * 50)

    for record_type, temperatures in results.items():
        print(f"\n{record_type}")

        if not temperatures:
            print("No temperature records found.")
            continue

        print(f"Count: {len(temperatures)}")
        print(f"Maximum: {max(temperatures)}")
        print(f"Minimum: {min(temperatures)}")
        print(f"Average: {sum(temperatures) / len(temperatures):.2f}")

    print("\nERP daily temperature test completed.")


if __name__ == "__main__":
    main()
