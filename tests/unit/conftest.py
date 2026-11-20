import socket
import sys

import mongomock
import pytest


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    original_connect = socket.socket.connect

    def blocked_connect(sock, address, *args, **kwargs):
        if (
            sys.platform == "win32"
            and sys._getframe(1).f_code is getattr(socket.socketpair, "__code__", None)
            and address[0] in {"127.0.0.1", "::1"}
        ):
            return original_connect(sock, address, *args, **kwargs)
        raise AssertionError("Network access is disabled in unit tests.")

    def blocked(*args, **kwargs):
        raise AssertionError("Network access is disabled in unit tests.")

    monkeypatch.setattr(socket.socket, "connect", blocked_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)


@pytest.fixture
def database():
    client = mongomock.MongoClient(tz_aware=True)
    yield client["unit_tests"]
    client.close()
