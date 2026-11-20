import json
import logging

from config.logging import ServiceFormatter


def test_text_logs_are_readable_without_terminal_escape_codes(monkeypatch):
    monkeypatch.setenv("LOG_TIMEZONE", "Asia/Tehran")
    record = logging.LogRecord("application.readings", logging.INFO, "", 1, "camera=%s value=%s", ("AMP-001", 0), None)
    record.created = 0
    output = ServiceFormatter("worker").format(record)
    assert "1970-01-01T03:30:00.000+03:30" in output
    assert "| INFO     | worker" in output
    assert "camera=AMP-001 value=0" in output
    assert "\033[" not in output


def test_json_logs_redact_credentials_and_configured_secrets(monkeypatch):
    monkeypatch.setenv("DETECTION_API_KEY", "secret-api-value")
    record = logging.LogRecord("api", logging.ERROR, "", 1,
        "Failed rtsp://user:pass@word@camera/stream key=secret-api-value", (), None)
    payload = json.loads(ServiceFormatter("model-api", json_output=True, color=True).format(record))
    assert payload["service"] == "model-api"
    assert payload["level"] == "ERROR"
    assert "rtsp://***@camera/stream" in payload["message"]
    assert "pass@word" not in payload["message"]
    assert "secret-api-value" not in payload["message"]


def test_exception_logs_are_redacted(monkeypatch):
    import sys
    monkeypatch.setenv("YOURCOMPANY_DB_PASSWORD", "private-password")
    try:
        raise ValueError("connection failed: private-password")
    except ValueError:
        record = logging.LogRecord("worker", logging.ERROR, "", 1, "Delivery failed", (), sys.exc_info())
    payload = json.loads(ServiceFormatter("worker", json_output=True).format(record))
    assert "ValueError" in payload["exception"]
    assert "private-password" not in payload["exception"]
