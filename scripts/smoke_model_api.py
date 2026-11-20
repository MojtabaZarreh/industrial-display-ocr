import json
import os
import struct
import urllib.request
import uuid
import zlib


def sample_png():
    def chunk(name, data):
        return struct.pack("!I", len(data)) + name + data + struct.pack("!I", zlib.crc32(name + data) & 0xFFFFFFFF)

    width, height = 160, 48
    pixels = (b"\x00" + b"\xff\xff\xff" * width) * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!2I5B", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


def main():
    base_url = os.getenv("SMOKE_API_URL", "http://127.0.0.1:18000").rstrip("/")
    key = os.environ["DETECTION_API_KEY"]
    for camera_code, expected_model in (("AMP-SMOKE", "paddle"), ("SRC-SMOKE", "yolo")):
        boundary = uuid.uuid4().hex
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="image.png"\r\nContent-Type: image/png\r\n\r\n'.encode()
            + sample_png() + f"\r\n--{boundary}--\r\n".encode()
        )
        request = urllib.request.Request(
            f"{base_url}/predict/{camera_code}", data=body,
            headers={"X-API-Key": key, "Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.load(response)
        assert result["model"] == expected_model, result
        assert result["image"] == {"width": 160, "height": 48}, result
        assert isinstance(result["predictions"], list), result
        print(f"PASS: {camera_code} -> {expected_model}")


if __name__ == "__main__":
    main()
