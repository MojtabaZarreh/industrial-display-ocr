import logging
from config import settings
from infrastructure.notification.sms import GhasedakSmsClient


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def main() -> None:
    sms_client = GhasedakSmsClient(
        api_key=settings.GHASEDAK_API_KEY,
        line_number=settings.GHASEDAK_LINE_NUMBER,
    )

    receptor = input("Enter destination mobile number: ").strip()

    message = (
        "گزارش آزمایشی سیستم Digit OCR v2\n"
        "اتصال به پنل پیامکی با موفقیت برقرار شد."
    )

    response = sms_client.send(
        receptor=receptor,
        message=message,
        client_reference_id="digit-ocr-v2-test",
    )

    print("\nSMS submitted successfully.")
    print("Ghasedak response:", response)


if __name__ == "__main__":
    main()
