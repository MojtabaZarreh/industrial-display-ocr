from domain.models import determine_erp_value

def test_valid_reading():
    assert determine_erp_value(
        camera_connected=True,
        reading_valid=True,
        current_value=25,
        previous_valid_value=24,
    ) == 25


def test_camera_disconnected():
    assert determine_erp_value(
        camera_connected=False,
        reading_valid=False,
        current_value=None,
        previous_valid_value=24,
    ) == -2


def test_invalid_reading_uses_previous_value():
    assert determine_erp_value(
        camera_connected=True,
        reading_valid=False,
        current_value=None,
        previous_valid_value=24,
    ) == 24


def test_invalid_reading_without_history():
    assert determine_erp_value(
        camera_connected=True,
        reading_valid=False,
        current_value=None,
        previous_valid_value=None,
    ) == -2


if __name__ == "__main__":
    test_valid_reading()
    test_camera_disconnected()
    test_invalid_reading_uses_previous_value()
    test_invalid_reading_without_history()

    print("All ERP value tests passed.")
