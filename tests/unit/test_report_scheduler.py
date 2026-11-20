from unittest.mock import Mock

import main
from infrastructure.database.mongodb.repositories import MeasurementPointRepository


def test_scheduler_factory_wires_unit_aware_report(database, monkeypatch):
    database.measurement_points.insert_many([
        {"camera_code": "SRC-001", "unit": "celsius", "description": "Temperature", "is_active": True},
        {"camera_code": "AMP-001", "unit": "ampere", "description": "Current", "is_active": True},
    ])
    for key in ("GHASEDAK_API_KEY", "GHASEDAK_LINE_NUMBER", "DAILY_REPORT_RECIPIENTS"):
        monkeypatch.setenv(key, "test-only")
    erp, sms = Mock(), Mock()
    erp.get_daily_temperatures.return_value = {"Temperature": [217]}
    monkeypatch.setattr(main, "GhasedakSmsClient", Mock(return_value=sms))
    scheduler = main.create_daily_report_scheduler(erp, MeasurementPointRepository(database))
    scheduler._execute_report()
    assert erp.get_daily_temperatures.call_args.kwargs["record_types"] == ["Temperature"]
    assert "21.70" in sms.send.call_args.kwargs["message"]


def test_missing_report_settings_disable_factory(monkeypatch):
    for key in ("GHASEDAK_API_KEY", "GHASEDAK_LINE_NUMBER", "DAILY_REPORT_RECIPIENTS"):
        monkeypatch.delenv(key, raising=False)
    assert main.create_daily_report_scheduler(Mock()) is None
