import io
import socket

import pytest

from app.core.network import (
    PinnedHTTPRequestError,
    UnsafeDestinationError,
    pinned_http_request,
    validate_https_destination,
)


def test_outbound_destination_requires_https(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))],
    )
    with pytest.raises(UnsafeDestinationError, match="HTTPS"):
        validate_https_destination("http://hooks.example.com/path")


def test_private_outbound_destination_is_blocked(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(UnsafeDestinationError, match="non-public"):
        validate_https_destination("https://hooks.example.com/path")


def test_public_outbound_destination_is_accepted(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))],
    )
    assert (
        validate_https_destination("https://hooks.example.com/path")
        == "https://hooks.example.com/path"
    )


def test_invalid_resolver_address_is_rejected(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("not-an-ip", 443))],
    )
    with pytest.raises(UnsafeDestinationError, match="invalid address"):
        validate_https_destination("https://hooks.example.com/path")


def test_safe_http_connects_to_the_validated_ip_not_the_hostname(monkeypatch):
    connections = []

    class FakeSocket:
        def __init__(self):
            self.sent = b""

        def sendall(self, payload):
            self.sent += payload

        def makefile(self, *_args, **_kwargs):
            return io.BytesIO(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")

        def close(self):
            pass

    fake_socket = FakeSocket()
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80))],
    )

    def connect(address, timeout):
        connections.append((address, timeout))
        return fake_socket

    monkeypatch.setattr(socket, "create_connection", connect)

    response = pinned_http_request(
        "http://public.example/path?q=1",
        allowed_schemes=frozenset({"http"}),
    )

    assert connections == [(("8.8.8.8", 80), 10.0)]
    assert b"GET /path?q=1 HTTP/1.1\r\n" in fake_socket.sent
    assert b"Host: public.example\r\n" in fake_socket.sent
    assert response.body == b"ok"
    assert response.resolved_addresses == ("8.8.8.8",)


def test_safe_http_rejects_header_injection_before_connecting():
    with pytest.raises(PinnedHTTPRequestError, match="header value"):
        pinned_http_request(
            "https://public.example/",
            headers={"X-Test": "safe\r\nHost: internal"},
        )
