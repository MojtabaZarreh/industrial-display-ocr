import logging
from application.daily_report_scheduler import DailyReportScheduler

logging.basicConfig(level=logging.INFO)


def test_report():
    print("Daily report job executed successfully!")


def main():
    scheduler = DailyReportScheduler(report_job=test_report)
    scheduler.start()
    try:
        input("Scheduler is running. Press Enter to stop...\n")
    finally:
        scheduler.stop()


if __name__ == "__main__":
    main()
