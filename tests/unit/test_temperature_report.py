from datetime import datetime, timezone
from unittest.mock import Mock

import jdatetime

from application import temperature_report_service as reports
from infrastructure.database.mongodb.repositories import MeasurementPointRepository


def test_report_converts_tenths_before_statistics_and_excludes_failure_sentinel():
    name = reports.RECORD_TYPES[0]
    temperatures = {name: [217, 223, 0, -2, float("nan"), float("inf"), True, None]}
    report = reports.TemperatureReportService._build_report(
        report_date="1405/08/26", temperatures=temperatures,
    )
    assert "بالاترین: 22.30" in report
    assert "کمترین: 0.00" in report
    assert "میانگین: 14.67" in report
    assert "تعداد رکورد: 3" in report
    assert "درجه سانتی‌گراد" in report
    assert temperatures[name][0] == 217


def test_single_temperature_217_is_21_point_7():
    report = reports.TemperatureReportService._build_report(
        report_date="1405/08/26", temperatures={reports.RECORD_TYPES[0]: [217]},
    )
    assert "بالاترین: 21.70" in report
    assert "کمترین: 21.70" in report
    assert "میانگین: 21.70" in report


def test_only_missing_or_invalid_values_show_no_data():
    report = reports.TemperatureReportService._build_report(
        report_date="1405/08/26", temperatures={reports.RECORD_TYPES[0]: [-2, None]},
    )
    assert report.count("داده‌ای برای این محل ثبت نشده است.") == len(reports.RECORD_TYPES)


def test_unit_controls_report_selection(database):
    database.measurement_points.insert_many([
        {"camera_code": "SRC-001", "description": "Legacy temperature", "is_active": True},
        {"camera_code": "AMP-001", "unit": "ampere", "description": "Current", "is_active": True},
        {"camera_code": "SRC-002", "unit": "ampere", "description": "Override", "is_active": True},
        {"camera_code": "TEMP-001", "unit": "celsius", "description": "Extra temperature", "is_active": True},
        {"camera_code": "WEIGHT-001", "unit": "kilogram", "description": "Weight", "is_active": True},
        {"camera_code": "TEMP-002", "unit": "celsius", "description": "Inactive", "is_active": False},
    ])
    erp = Mock()
    erp.get_daily_temperatures.return_value = {
        "Legacy temperature": [217], "Extra temperature": [225], "Current": [100],
    }
    service = reports.TemperatureReportService(
        erp, Mock(), ["test-recipient"],
        measurement_repository=MeasurementPointRepository(database),
    )
    report = service.generate_yesterday_report()
    assert erp.get_daily_temperatures.call_args.kwargs["record_types"] == [
        "Legacy temperature", "Extra temperature",
    ]
    assert "21.70" in report and "22.50" in report
    assert "Current" not in report and "Weight" not in report


def test_yesterday_uses_tehran_date(monkeypatch):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 17, 21, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(reports, "datetime", FrozenDateTime)
    erp = Mock()
    erp.get_daily_temperatures.return_value = {}
    service = reports.TemperatureReportService(erp, Mock(), ["test-recipient"])
    service.generate_yesterday_report()
    expected = jdatetime.date.fromgregorian(date=datetime(2026, 11, 17).date()).strftime("%Y/%m/%d")
    assert erp.get_daily_temperatures.call_args.kwargs["report_date"] == expected


def test_sms_contains_converted_report():
    erp, sms = Mock(), Mock()
    erp.get_daily_temperatures.return_value = {reports.RECORD_TYPES[0]: [217]}
    service = reports.TemperatureReportService(erp, sms, ["first", "second"])
    report = service.send_yesterday_report()
    assert sms.send.call_count == 2
    assert all(call.kwargs["message"] == report for call in sms.send.call_args_list)
    assert "21.70" in report


def test_no_temperature_sources_do_not_query_erp(database):
    erp = Mock()
    service = reports.TemperatureReportService(
        erp, Mock(), ["test"], measurement_repository=MeasurementPointRepository(database),
    )
    service.generate_yesterday_report()
    erp.get_daily_temperatures.assert_not_called()
