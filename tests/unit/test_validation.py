
from application.validation.result_validator import ResultValidator
from application.validation.anomaly_detector import AnomalyDetector


def test_result_validator():
    validator = ResultValidator(min_confidence=0.5)

    valid_result = {
        "camera_code": "AMP-001",
        "model": "paddle",
        "predictions": [
            {"text": "1234", "confidence": 0.98}
        ],
    }

    validation = validator.validate("AMP-001", valid_result)
    assert validation.is_valid
    assert validation.status == "valid"

    empty_result = {
        "camera_code": "AMP-001",
        "model": "paddle",
        "predictions": [],
    }

    validation = validator.validate("AMP-001", empty_result)
    assert not validation.is_valid
    assert "empty_predictions" in validation.reasons

    mismatch_result = {
        "camera_code": "AMP-002",
        "model": "paddle",
        "predictions": [
            {"text": "1234", "confidence": 0.98}
        ],
    }

    validation = validator.validate("AMP-001", mismatch_result)
    assert not validation.is_valid
    assert "camera_code_mismatch" in validation.reasons

    low_confidence_result = {
        "camera_code": "AMP-001",
        "model": "paddle",
        "predictions": [
            {"text": "1234", "confidence": 0.2}
        ],
    }

    validation = validator.validate(
        "AMP-001",
        low_confidence_result,
    )
    assert not validation.is_valid
    assert "prediction_0_low_confidence" in validation.reasons

    yolo_result = {
        "camera_code": "TMP-001",
        "model": "yolo",
        "predictions": [
            {"class": 3, "confidence": 0.95}
        ],
    }

    validation = validator.validate("TMP-001", yolo_result)
    assert validation.is_valid

    print("ResultValidator tests passed.")


def test_anomaly_detector():
    detector = AnomalyDetector(
        min_history=3,
        max_relative_change=0.2,
    )

    normal_result = detector.detect(
        current_value=103,
        history=[100, 101, 102],
    )

    assert not normal_result.is_anomaly
    assert normal_result.reason is None

    anomaly_result = detector.detect(
        current_value=1800,
        history=[1000, 1010, 990],
    )

    assert anomaly_result.is_anomaly
    assert anomaly_result.reason == "unusual_change_from_history"

    insufficient_history = detector.detect(
        current_value=5000,
        history=[1000, 1010],
    )

    assert not insufficient_history.is_anomaly
    assert insufficient_history.reason == "insufficient_history"

    outlier_history = detector.detect(
        current_value=103,
        history=[100, 101, 10000, 102, 104],
    )

    assert not outlier_history.is_anomaly

    print("AnomalyDetector tests passed.")


def main():
    tests = [
        ("ResultValidator", test_result_validator),
        ("AnomalyDetector", test_anomaly_detector),
    ]

    passed = 0
    failed = 0

    for name, test_function in tests:
        try:
            test_function()
            passed += 1
        except Exception as exc:
            failed += 1
            print(f"{name} test failed: {exc!r}")

    print(f"\nTest summary: {passed} passed, {failed} failed.")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
