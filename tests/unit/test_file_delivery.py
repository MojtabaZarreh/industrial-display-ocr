import importlib
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from PIL import Image

import main
from config import settings
from application.camera_worker import CapturedFrame
from application.delivery_worker import DeliveryWorker
from application.reading_result_handler import ReadingResultHandler
from infrastructure.database.mongodb.indexes import create_indexes
from infrastructure.database.mongodb.repositories import DeliveryOutboxRepository, ReadingRepository, MeasurementPointRepository
from infrastructure.yourcompany.file_sink import LocalDeliveryFile

OBSERVED = datetime(2026, 11, 19, 13, 30, 12, 345000, tzinfo=timezone.utc)


def event(identifier="test", code="AMP-001", value=120, at=OBSERVED):
    return {"event_id": identifier, "camera_code": code, "scheduled_at": at,
            "source": {"name": "Test", "unit": "celsius" if code.startswith("SRC") else "ampere"},
            "erp_data": {"Temperature": value, "RecordType": "منبع <script>alert(1)</script>"}}


def test_file_is_idempotent_after_restart_and_html_has_counts_and_actual_time(tmp_path):
    sink = LocalDeliveryFile(tmp_path, refresh_seconds=0, sources=[{"camera_code": "AMP-EMPTY", "name": "Empty"}])
    for row in [event("a", value=0), event("b", value=-2), event("c", "SRC-001", 217)]:
        sink.record(row)
    restarted = LocalDeliveryFile(tmp_path, refresh_seconds=0)
    restarted.record(event("a", value=0))
    with sqlite3.connect(sink.database_path) as database:
        assert database.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 3
        captured, recorded = database.execute("SELECT captured_at, recorded_at FROM records WHERE event_id='a'").fetchone()
    assert captured == "2026-11-19T17:00:12.345+03:30"
    assert datetime.fromisoformat(recorded).utcoffset() == timedelta(hours=3, minutes=30)
    html = (tmp_path / 'readings-2026-11-19.html').read_text(encoding='utf-8')
    assert 'تعداد کل رکوردها: 3' in html
    assert '<td>AMP-001</td><td>Test</td><td>2</td><td>1</td><td>1</td>' in html
    assert '<td>21.7</td>' in html and '<td>217</td>' in html
    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;' in html
    assert captured in html


def test_reports_show_zero_count_sources_and_roll_over_by_tehran_day(tmp_path):
    sink = LocalDeliveryFile(tmp_path, refresh_seconds=0, sources=[{"camera_code": "AMP-EMPTY", "name": "Empty"}])
    sink.record(event("before", at=datetime(2026, 11, 19, 20, 29, 59, tzinfo=timezone.utc)))
    sink.record(event("after", at=datetime(2026, 11, 19, 20, 30, tzinfo=timezone.utc)))
    for day in ['2026-11-19', '2026-11-20']:
        html = (tmp_path / f'readings-{day}.html').read_text(encoding='utf-8')
        assert 'تعداد کل رکوردها: 1' in html
        assert '<td>AMP-EMPTY</td><td>Empty</td><td>0</td>' in html


def test_failed_atomic_export_preserves_previous_report_and_recovers_without_duplicate(tmp_path, monkeypatch):
    sink = LocalDeliveryFile(tmp_path, refresh_seconds=0)
    sink.record(event("a"))
    path = tmp_path / 'readings-2026-11-19.html'
    before = path.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr('infrastructure.yourcompany.file_sink.os.replace', Mock(side_effect=PermissionError('read-only')))
        with pytest.raises(PermissionError):
            sink.record(event("b"))
    assert path.read_bytes() == before
    assert not list(tmp_path.glob('*.tmp'))
    sink.record(event("b"))
    assert 'تعداد کل رکوردها: 2' in path.read_text(encoding='utf-8')
    assert LocalDeliveryFile(tmp_path).database_path == sink.database_path


def test_report_refresh_is_throttled_but_force_flush_and_restart_rebuild_it(tmp_path, monkeypatch):
    sink = LocalDeliveryFile(tmp_path, refresh_seconds=60)
    monkeypatch.setattr('infrastructure.yourcompany.file_sink.time.monotonic', lambda: 100)
    sink.record(event("a"))
    sink.record(event("b"))
    path = tmp_path / 'readings-2026-11-19.html'
    assert 'تعداد کل رکوردها: 1' in path.read_text(encoding='utf-8')
    sink.flush(force=True)
    assert 'تعداد کل رکوردها: 2' in path.read_text(encoding='utf-8')
    path.unlink()
    LocalDeliveryFile(tmp_path).flush(force=True)
    assert path.exists()


def test_destination_is_fixed_and_legacy_sql_events_are_not_claimed_by_file_worker(database, tmp_path):
    create_indexes(database)
    outbox = DeliveryOutboxRepository(database)
    for identifier, destination in [('local', 'file'), ('sql', 'erp'), ('legacy', 'erp')]:
        row = event(identifier)
        outbox.create_event(event_id=identifier, camera_code=row['camera_code'], scheduled_at=OBSERVED,
                            erp_data=row['erp_data'], destination=destination, source=row['source'])
    database.delivery_outbox.update_one({'event_id': 'legacy'}, {'$unset': {'destination': ''}})
    sink = LocalDeliveryFile(tmp_path, refresh_seconds=0)
    worker = DeliveryWorker(outbox, file_sink=sink)
    assert worker.run_once()
    assert not worker.run_once()
    assert database.delivery_outbox.find_one({'event_id': 'local'})['status'] == 'sent'
    erp = Mock()
    sql_worker = DeliveryWorker(outbox, erp)
    assert sql_worker.run_once() and sql_worker.run_once()
    assert not sql_worker.run_once()
    assert erp.insert_temperature.call_count == 2
    assert database.delivery_outbox.count_documents({'destination': 'file', 'status': 'sent'}) == 1


def test_file_retry_after_lost_acknowledgement_does_not_duplicate(database, tmp_path, monkeypatch):
    create_indexes(database)
    outbox = DeliveryOutboxRepository(database)
    row = event()
    outbox.create_event(event_id='test', camera_code='AMP-001', scheduled_at=OBSERVED,
                        erp_data=row['erp_data'], destination='file', source=row['source'])
    sink = LocalDeliveryFile(tmp_path, refresh_seconds=0)
    worker = DeliveryWorker(outbox, file_sink=sink)
    with monkeypatch.context() as patch:
        patch.setattr(outbox, 'mark_as_sent', lambda identifier: False)
        assert worker.run_once()
    database.delivery_outbox.update_one({'event_id': 'test'}, {'$set': {'lease_until': datetime.now(timezone.utc)-timedelta(seconds=1)}})
    assert worker.run_once()
    with sqlite3.connect(sink.database_path) as connection:
        assert connection.execute('SELECT COUNT(*) FROM records').fetchone()[0] == 1


def test_file_mode_main_never_constructs_erp_even_with_credentials(database, tmp_path, monkeypatch):
    create_indexes(database)
    database.measurement_points.insert_one({'camera_code': 'AMP-001', 'name': 'Test', 'description': 'Line', 'is_active': True})
    monkeypatch.setattr(settings, 'YOURCOMPANY_ERP_ENABLED', False)
    monkeypatch.setattr(settings, 'YOURCOMPANY_EXPORT_DIR', tmp_path)
    monkeypatch.setattr(settings, 'DAILY_REPORT_ENABLED', True)
    for key in ['HOST', 'USER', 'PASSWORD', 'NAME']:
        monkeypatch.setenv('YOURCOMPANY_DB_' + key, 'configured')
    erp = Mock()
    monkeypatch.setattr(main, 'YourCompanyERPClient', erp)
    monkeypatch.setattr(main, 'MongoDB', lambda: Mock(database=database))
    monkeypatch.setattr(main, 'configure_logging', Mock())
    monkeypatch.setattr(main, 'DetectionAPIClient', Mock())
    monkeypatch.setattr(main.threading, 'Thread', lambda **kwargs: Mock())
    def factory(**kwargs):
        def run(cameras):
            kwargs['camera_failure_handler']('AMP-001', OBSERVED)
        return Mock(run_forever=run)
    monkeypatch.setattr(main, 'ProcessingService', factory)
    main.main()
    erp.assert_not_called()
    queued = database.delivery_outbox.find_one()
    assert queued['destination'] == 'file'
    assert queued['erp_data']['Temperature'] == -2
    sink = LocalDeliveryFile(tmp_path, refresh_seconds=0)
    assert DeliveryWorker(DeliveryOutboxRepository(database), file_sink=sink).run_once()


def test_invalid_flag_is_rejected_without_silently_enabling_sql(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setenv('YOURCOMPANY_ERP_ENABLED', 'flase')
        with pytest.raises(ValueError, match='YOURCOMPANY_ERP_ENABLED'):
            importlib.reload(settings)
    importlib.reload(settings)


def test_file_destination_preserves_zero_anomaly_and_capture_failure_policy(database, tmp_path):
    create_indexes(database)
    database.measurement_points.insert_one({'camera_code': 'AMP-001', 'name': 'Test', 'description': 'Line'})
    outbox = DeliveryOutboxRepository(database)
    handler = ReadingResultHandler(ReadingRepository(database), MeasurementPointRepository(database), outbox, destination='file')
    sink = LocalDeliveryFile(tmp_path, refresh_seconds=0)
    delivery = DeliveryWorker(outbox, file_sink=sink)
    for index, value in enumerate([120, 124, 119, 819, 0, 121]):
        handler(CapturedFrame('AMP-001', Image.new('RGB', (10, 10)), OBSERVED + timedelta(minutes=index)), {
            'camera_code': 'AMP-001', 'inference_id': f'reading-{index}', 'model': 'paddle',
            'predictions': [{'text': str(value), 'confidence': 0.99}],
        })
        assert delivery.run_once()
    handler.handle_camera_failure('AMP-001', OBSERVED + timedelta(minutes=6))
    assert delivery.run_once()
    with sqlite3.connect(sink.database_path) as connection:
        assert [row[0] for row in connection.execute('SELECT raw_value FROM records ORDER BY captured_at')] == [120, 124, 119, 119, 0, 121, -2]
    assert database.measurement_states.find_one()['latest_value'] == 121
    assert database.delivery_outbox.count_documents({'destination': 'file', 'status': 'sent'}) == 7


def test_file_write_failure_retries_without_any_sql_fallback(database, tmp_path):
    create_indexes(database)
    outbox = DeliveryOutboxRepository(database)
    row = event()
    outbox.create_event(event_id='test', camera_code='AMP-001', scheduled_at=OBSERVED,
                        erp_data=row['erp_data'], destination='file')
    sink = Mock()
    sink.record.side_effect = OSError('disk full')
    worker = DeliveryWorker(outbox, file_sink=sink)
    assert worker.run_once()
    queued = database.delivery_outbox.find_one()
    assert queued['status'] == 'pending'
    assert queued['destination'] == 'file'
    assert 'disk full' in queued['last_error']
    assert DeliveryWorker(outbox, Mock()).run_once() is False
