from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
from dataclasses import dataclass
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class UnsafeDestinationError(ValueError):
    pass


class PinnedHTTPRequestError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PinnedHTTPResponse:
    status_code: int
    reason: str
    headers: dict[str, str]
    body: bytes
    url: str
    resolved_addresses: tuple[str, ...]
    truncated: bool = False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise PinnedHTTPRequestError(f"HTTP {self.status_code} {self.reason}".strip())

    def decoded_body(self) -> str:
        content_type = self.headers.get("content-type", "")
        match = re.search(r"charset=([^;\s]+)", content_type, re.I)
        encoding = match.group(1).strip("\"'") if match else "utf-8"
        try:
            return self.body.decode(encoding, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


def _parse_destination(url: str, allowed_schemes: frozenset[str]):
    if not isinstance(url, str) or len(url) > 16_384 or any(ord(c) < 32 for c in url):
        raise UnsafeDestinationError("destination URL is invalid")
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in allowed_schemes or not parsed.hostname:
        schemes = " or ".join(sorted(allowed_schemes)).upper()
        raise UnsafeDestinationError(f"destination must be an absolute {schemes} URL")
    if parsed.username or parsed.password:
        raise UnsafeDestinationError("destination URLs cannot contain credentials")
    try:
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except ValueError as exc:
        raise UnsafeDestinationError("destination URL has an invalid port") from exc
    try:
        host = parsed.hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise UnsafeDestinationError("destination hostname is invalid") from exc
    return parsed, host, port


def _resolve_destination(host: str, port: int, *, allow_private: bool) -> tuple[str, ...]:
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise UnsafeDestinationError(f"destination cannot be resolved: {exc}") from exc
    if not addresses:
        raise UnsafeDestinationError("destination resolution returned no addresses")
    try:
        normalized = tuple(sorted({ipaddress.ip_address(item).compressed for item in addresses}))
    except ValueError as exc:
        raise UnsafeDestinationError("destination resolution returned an invalid address") from exc
    if not allow_private and any(not ipaddress.ip_address(item).is_global for item in normalized):
        raise UnsafeDestinationError("destination resolves to a non-public address")
    return normalized


def validate_https_destination(url: str, *, allow_private: bool = False) -> str:
    """Validate an operator-configured HTTPS endpoint before outbound use."""
    _parsed, host, port = _parse_destination(url, frozenset({"https"}))
    _resolve_destination(host, port, allow_private=allow_private)
    return url


def validate_https_url(url: str) -> str:
    """Validate HTTPS URL structure without making startup depend on DNS."""
    _parse_destination(url, frozenset({"https"}))
    return url


def _validated_headers(headers: dict[str, str] | None) -> dict[str, str]:
    safe: dict[str, str] = {}
    for name, value in (headers or {}).items():
        if not isinstance(name, str) or not _HEADER_NAME.fullmatch(name):
            raise PinnedHTTPRequestError("request contains an invalid header name")
        if not isinstance(value, str) or "\r" in value or "\n" in value:
            raise PinnedHTTPRequestError("request contains an invalid header value")
        try:
            name.encode("ascii")
            value.encode("latin-1")
        except UnicodeEncodeError as exc:
            raise PinnedHTTPRequestError("request headers must be HTTP encodable") from exc
        if name.lower() in {"host", "content-length", "connection", "accept-encoding"}:
            raise PinnedHTTPRequestError(f"request cannot override the {name} header")
        safe[name] = value
    return safe


def _request_once(
    url: str,
    *,
    method: str,
    headers: dict[str, str],
    content: bytes,
    timeout: float,
    max_response_bytes: int,
    allow_private: bool,
    allowed_schemes: frozenset[str],
    truncate_response: bool,
) -> PinnedHTTPResponse:
    parsed, host, port = _parse_destination(url, allowed_schemes)
    addresses = _resolve_destination(host, port, allow_private=allow_private)
    encoded_path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
    encoded_query = quote(parsed.query, safe="=&%/:@!$'()*+,;?-._~")
    path = urlunsplit(("", "", encoded_path, encoded_query, ""))
    display_host = f"[{host}]" if ":" in host else host
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    host_header = display_host if port == default_port else f"{display_host}:{port}"
    request_headers = {
        "Host": host_header,
        "Connection": "close",
        "Accept-Encoding": "identity",
        **headers,
    }
    if content or method == "POST":
        request_headers["Content-Length"] = str(len(content))
    request_lines = [f"{method} {path} HTTP/1.1"]
    request_lines.extend(f"{name}: {value}" for name, value in request_headers.items())
    wire_request = ("\r\n".join(request_lines) + "\r\n\r\n").encode("latin-1") + content

    failures: list[str] = []
    for address in addresses:
        raw_socket = None
        transport = None
        try:
            raw_socket = socket.create_connection((address, port), timeout=timeout)
            transport = raw_socket
            if parsed.scheme.lower() == "https":
                transport = ssl.create_default_context().wrap_socket(
                    raw_socket, server_hostname=host
                )
            transport.sendall(wire_request)
            response = http.client.HTTPResponse(transport)
            response.begin()
            body = response.read(max_response_bytes + 1)
            truncated = len(body) > max_response_bytes
            if truncated and not truncate_response:
                raise PinnedHTTPRequestError(f"response exceeded {max_response_bytes} bytes")
            body = body[:max_response_bytes]
            response_headers: dict[str, str] = {}
            for name, value in response.getheaders():
                lowered = name.lower()
                response_headers[lowered] = (
                    f"{response_headers[lowered]}, {value}"
                    if lowered in response_headers
                    else value
                )
            return PinnedHTTPResponse(
                status_code=response.status,
                reason=response.reason or "",
                headers=response_headers,
                body=body,
                url=url,
                resolved_addresses=addresses,
                truncated=truncated,
            )
        except PinnedHTTPRequestError:
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            failures.append(f"{address}: {type(exc).__name__}: {exc}")
        finally:
            if transport is not None:
                transport.close()
            elif raw_socket is not None:
                raw_socket.close()
    raise PinnedHTTPRequestError("; ".join(failures) or "request failed")


def pinned_http_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    content: bytes = b"",
    timeout: float = 10.0,
    max_response_bytes: int = 1_000_000,
    allow_private: bool = False,
    allowed_schemes: frozenset[str] = frozenset({"https"}),
    max_redirects: int = 0,
    truncate_response: bool = False,
) -> PinnedHTTPResponse:
    """Perform an HTTP request pinned to IPs that passed SSRF policy.

    DNS is resolved exactly once per hop and the socket connects to the
    validated address, closing the usual DNS-rebinding gap between checking a
    hostname and letting an HTTP client resolve it again.
    """
    method = method.upper()
    if method not in {"GET", "POST"}:
        raise PinnedHTTPRequestError("only GET and POST requests are supported")
    if not isinstance(content, bytes) or len(content) > 1_000_000:
        raise PinnedHTTPRequestError("request content must be bytes and at most 1 MB")
    if not 0 < timeout <= 300:
        raise PinnedHTTPRequestError("request timeout must be between 0 and 300 seconds")
    if not 0 <= max_response_bytes <= 100_000_000:
        raise PinnedHTTPRequestError("response limit is invalid")
    if not 0 <= max_redirects <= 10:
        raise PinnedHTTPRequestError("redirect limit is invalid")
    safe_headers = _validated_headers(headers)
    current = url
    for hop in range(max_redirects + 1):
        response = _request_once(
            current,
            method=method,
            headers=safe_headers,
            content=content,
            timeout=timeout,
            max_response_bytes=max_response_bytes,
            allow_private=allow_private,
            allowed_schemes=allowed_schemes,
            truncate_response=truncate_response,
        )
        location = response.headers.get("location")
        if response.status_code not in _REDIRECT_STATUSES or not location:
            return response
        if method != "GET":
            return response
        if hop >= max_redirects:
            if max_redirects == 0:
                return response
            raise PinnedHTTPRequestError("redirect limit exceeded")
        current = urljoin(current, location)
    raise PinnedHTTPRequestError("redirect limit exceeded")
