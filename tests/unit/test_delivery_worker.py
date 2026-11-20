from application.delivery_worker import DeliveryWorker

class FakeOutboxRepository:

    def __init__(self, event=None):
        self.event = event
        self.sent_events = []
        self.failed_events = []

    def claim_next_event(self, *, lease_seconds=60, destination="erp"):
        event = self.event
        self.event = None
        return event

    def mark_as_sent(self, event_id):
        self.sent_events.append(event_id)
        return True

    def mark_as_failed(self, event_id, error):
        self.failed_events.append({
            "event_id": event_id,
            "error": error,
        })
        return True


class FakeERPClient:

    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.inserted_records = []

    def insert_temperature(self, data):
        if self.should_fail:
            raise ConnectionError("ERP connection failed.")

        self.inserted_records.append(data)


def test_delivery_worker_cases():

    outbox = FakeOutboxRepository(event=None)
    erp = FakeERPClient()

    worker = DeliveryWorker(outbox, erp)

    result = worker.run_once()

    assert result is False
    assert len(erp.inserted_records) == 0
    assert len(outbox.sent_events) == 0

    print("PASS: No pending event.")

    event = {
        "camera_code": "SRC-001",
        "event_id": "TEST-EVENT-001",
        "erp_data": {
            "Date": "1405/08/16",
            "Time": "08:00:00",
            "Temperature": 24,
            "CreateDateTime": "2026-11-07 08:00:00",
            "RecordType": 1,
        },
    }

    outbox = FakeOutboxRepository(event=event)
    erp = FakeERPClient()

    worker = DeliveryWorker(outbox, erp)

    result = worker.run_once()

    assert result is True
    assert len(erp.inserted_records) == 1
    assert erp.inserted_records[0]["Temperature"] == 24
    assert outbox.sent_events == ["TEST-EVENT-001"]
    assert len(outbox.failed_events) == 0

    print("PASS: Event delivered successfully.")

    event = {
        "camera_code": "SRC-001",
        "event_id": "TEST-EVENT-002",
        "erp_data": {
            "Date": "1405/08/16",
            "Time": "08:01:00",
            "Temperature": 25,
            "CreateDateTime": "2026-11-07 08:01:00",
            "RecordType": 1,
        },
    }

    outbox = FakeOutboxRepository(event=event)
    erp = FakeERPClient(should_fail=True)

    worker = DeliveryWorker(outbox, erp)

    result = worker.run_once()

    assert result is True
    assert len(erp.inserted_records) == 0
    assert len(outbox.sent_events) == 0
    assert len(outbox.failed_events) == 1
    assert outbox.failed_events[0]["event_id"] == "TEST-EVENT-002"
    assert outbox.failed_events[0]["error"] == "ERP connection failed."

    print("PASS: ERP failure scheduled for retry.")

    class FakeOutboxWithSentFailure(FakeOutboxRepository):

        def mark_as_sent(self, event_id):
            return False

    event = {
        "camera_code": "SRC-001",
        "event_id": "TEST-EVENT-003",
        "erp_data": {
            "Date": "1405/08/16",
            "Time": "08:02:00",
            "Temperature": 26,
            "CreateDateTime": "2026-11-07 08:02:00",
            "RecordType": 1,
        },
    }

    outbox = FakeOutboxWithSentFailure(event=event)
    erp = FakeERPClient()

    worker = DeliveryWorker(outbox, erp)

    result = worker.run_once()

    assert result is True
    assert len(erp.inserted_records) == 1
    assert len(outbox.failed_events) == 0

    print("PASS: ERP success with outbox update failure handled.")

    print("\nAll DeliveryWorker tests passed.")


if __name__ == "__main__":
    test_delivery_worker_cases()
