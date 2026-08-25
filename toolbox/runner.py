from __future__ import annotations

import base64
import binascii
import contextlib
import ctypes
import hashlib
import hmac
import ipaddress
import json
import os
import re
import selectors
import shutil
import signal
import subprocess
import tempfile
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import BoundedSemaphore
from typing import Any
from urllib.parse import urlsplit, urlunsplit

MAX_REQUEST_BYTES = 2_000_000
MAX_STDOUT_BYTES = 2_000_000
MAX_STDERR_BYTES = 256_000
MAX_TIMEOUT_SECONDS = 300
DOMAIN_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
PRIVATE_NETWORKS = (
    "0.0.0.0/8,10.0.0.0/8,100.64.0.0/10,127.0.0.0/8,"
    "169.254.0.0/16,172.16.0.0/12,192.0.0.0/24,192.0.2.0/24,"
    "192.168.0.0/16,198.18.0.0/15,198.51.100.0/24,203.0.113.0/24,"
    "224.0.0.0/4,240.0.0.0/4,::/128,::1/128,fc00::/7,fe80::/10,"
    "ff00::/8,2001:db8::/32"
)
TOOL_VERSIONS = {
    "subfinder": "v2.16.0",
    "urlfinder": "v0.0.3",
    "httpx": "v1.10.0",
    "katana": "v1.7.0",
    "naabu": "v2.6.1",
    "jsluice": "0ddfab153e060a9eeaded4d8669233f7c071e7e4",
    "alterx": "v0.1.0",
    "cdncheck": "v1.2.50",
}


def _consume_shared_secret() -> str:
    secret = os.environ.pop("TOOLBOX_SHARED_SECRET", "")
    # unsetenv does not reliably erase the initial environment memory exposed
    # through /proc/<pid>/environ. Zero the original entry so an untrusted tool
    # subprocess running under the container UID cannot recover broker auth.
    try:
        environ = ctypes.POINTER(ctypes.c_void_p).in_dll(ctypes.CDLL(None), "environ")
        index = 0
        while environ[index]:
            pointer = environ[index]
            raw = ctypes.string_at(pointer)
            if raw.startswith(b"TOOLBOX_SHARED_SECRET="):
                ctypes.memset(pointer, 0, len(raw))
                break
            index += 1
    except (OSError, ValueError):
        pass
    return secret


def _verify_tool_installation() -> tuple[dict[str, dict[str, str]], str]:
    verified: dict[str, dict[str, str]] = {}
    aggregate = hashlib.sha256()
    for tool, version in TOOL_VERSIONS.items():
        path = shutil.which(tool)
        if path is None or not os.access(path, os.X_OK):
            raise RuntimeError(f"required tool is missing or not executable: {tool}")
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        aggregate.update(f"{tool}:{version}:{digest}\n".encode())
        verified[tool] = {"version": version, "sha256": digest}
    return verified, aggregate.hexdigest()


class RequestError(ValueError):
    pass


def _domain(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 253:
        raise RequestError("input must be a valid fully qualified domain")
    if any(ord(char) < 33 for char in value):
        raise RequestError("domain contains invalid characters")
    candidate = value.rstrip(".").lower()
    try:
        candidate = candidate.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise RequestError("domain is not valid IDNA") from exc
    if "." not in candidate or any(
        not DOMAIN_LABEL.fullmatch(label) for label in candidate.split(".")
    ):
        raise RequestError("input must be a valid fully qualified domain")
    return candidate


def _ip(value: Any, *, allow_private: bool) -> str:
    if not isinstance(value, str):
        raise RequestError("input must be an IP address")
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise RequestError("input must be an IP address") from exc
    if not allow_private and not address.is_global:
        raise RequestError("non-public IP targets require explicit private-network authorization")
    return address.compressed


def _url(value: Any, *, require_url: bool = True) -> str:
    if not isinstance(value, str) or not value or len(value) > 16_384:
        raise RequestError("input URL is invalid")
    if any(ord(char) < 32 for char in value):
        raise RequestError("input URL contains control characters")
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        if not require_url:
            return _domain(value)
        raise RequestError("input must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise RequestError("input URLs cannot contain credentials")
    try:
        _port = parsed.port
    except ValueError as exc:
        raise RequestError("input URL contains an invalid port") from exc
    return value


def _url_prefix_regex(value: Any) -> tuple[str, str]:
    validated = _url(value)
    parsed = urlsplit(validated)
    prefix = urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", "", ""))
    expression = f"^{re.escape(prefix.rstrip('/'))}(/.*)?([?#].*)?$"
    return prefix, expression


def _bounded_int(
    config: dict[str, Any], name: str, default: int, minimum: int, maximum: int
) -> int:
    raw = config.get(name, default)
    if isinstance(raw, bool):
        raise RequestError(f"{name} must be an integer")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise RequestError(f"{name} must be an integer") from exc
    return min(max(value, minimum), maximum)


def _choice_int(config: dict[str, Any], name: str, default: int, choices: frozenset[int]) -> int:
    raw = config.get(name, default)
    if isinstance(raw, bool):
        raise RequestError(f"{name} must be an integer")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise RequestError(f"{name} must be an integer") from exc
    if value not in choices:
        expected = ", ".join(str(choice) for choice in sorted(choices))
        raise RequestError(f"{name} must be one of: {expected}")
    return value


def _minimal_environment() -> dict[str, str]:
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp/reconator-toolbox",
        "XDG_CONFIG_HOME": "/tmp/reconator-toolbox/config",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "NO_COLOR": "1",
    }


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    process.wait()


def run_bounded_command(
    argv: list[str], *, timeout: int, cwd: str
) -> tuple[int, bytes, bytes, bool, bool]:
    """Drain child pipes while retaining a bounded prefix of each stream."""
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=_minimal_environment(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        close_fds=True,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    limits = {"stdout": MAX_STDOUT_BYTES, "stderr": MAX_STDERR_BYTES}
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    truncated = {"stdout": False, "stderr": False}
    deadline = time.monotonic() + timeout
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_process_group(process)
                raise TimeoutError
            for key, _ in selector.select(timeout=min(remaining, 0.25)):
                chunk = os.read(key.fileobj.fileno(), 65_536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                name = key.data
                capacity = limits[name] - len(buffers[name])
                if capacity > 0:
                    buffers[name].extend(chunk[:capacity])
                if len(chunk) > max(capacity, 0):
                    truncated[name] = True
        returncode = process.wait(timeout=max(deadline - time.monotonic(), 0.01))
    except subprocess.TimeoutExpired as exc:
        _terminate_process_group(process)
        raise TimeoutError from exc
    except BaseException:
        _terminate_process_group(process)
        raise
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()
    return (
        returncode,
        bytes(buffers["stdout"]),
        bytes(buffers["stderr"]),
        truncated["stdout"],
        truncated["stderr"],
    )


def _provider_config(argv: list[str], tool: str, flag: str) -> None:
    candidate = Path("/config") / f"{tool}-provider.yaml"
    if candidate.is_file():
        argv.extend([flag, str(candidate)])


def build_command(request: dict[str, Any], *, workdir: str) -> tuple[str, list[str], int]:
    tool = request.get("tool")
    config = request.get("config") or {}
    if not isinstance(tool, str) or tool not in TOOL_VERSIONS:
        raise RequestError("unknown or unavailable tool")
    if not isinstance(config, dict) or len(config) > 64:
        raise RequestError("tool configuration must be a small object")
    timeout = _bounded_int(config, "execution_timeout", 120, 1, MAX_TIMEOUT_SECONDS)
    allow_private = config.get("allow_private_networks", False) is True

    if tool == "subfinder":
        target = _domain(request.get("input"))
        argv = [
            "subfinder",
            "-d",
            target,
            "-json",
            "-collect-sources",
            "-silent",
            "-disable-update-check",
            "-timeout",
            str(_bounded_int(config, "request_timeout", 30, 5, 120)),
            "-max-time",
            str(_bounded_int(config, "max_time_minutes", 3, 1, 10)),
            "-rate-limit",
            str(_bounded_int(config, "rate_limit", 20, 1, 100)),
        ]
        if config.get("all_sources", True) is not False:
            argv.append("-all")
        _provider_config(argv, "subfinder", "-provider-config")
        return tool, argv, timeout

    if tool == "urlfinder":
        target = _domain(request.get("input"))
        argv = [
            "urlfinder",
            "-d",
            target,
            "-jsonl",
            "-collect-sources",
            "-silent",
            "-no-color",
            "-disable-update-check",
            "-timeout",
            str(_bounded_int(config, "request_timeout", 30, 5, 120)),
            "-max-time",
            str(_bounded_int(config, "max_time_minutes", 3, 1, 10)),
        ]
        return tool, argv, timeout

    if tool == "httpx":
        target = _url(request.get("input"), require_url=False)
        argv = [
            "httpx",
            "-u",
            target,
            "-json",
            "-silent",
            "-no-color",
            "-disable-update-check",
            "-status-code",
            "-content-type",
            "-location",
            "-title",
            "-server",
            "-tech-detect",
            "-ip",
            "-cname",
            "-asn",
            "-cdn",
            "-tls-grab",
            "-no-stdin",
            "-threads",
            str(_bounded_int(config, "concurrency", 10, 1, 50)),
            "-rate-limit",
            str(_bounded_int(config, "rate_limit", 10, 1, 100)),
            "-timeout",
            str(_bounded_int(config, "request_timeout", 10, 1, 30)),
            "-retries",
            str(_bounded_int(config, "retries", 1, 0, 3)),
            "-response-size-to-read",
            str(_bounded_int(config, "max_response_bytes", 262_144, 1_024, 1_000_000)),
            "-response-size-to-save",
            "0",
        ]
        if not allow_private:
            argv.extend(["-deny", PRIVATE_NETWORKS])
        return tool, argv, timeout

    if tool == "katana":
        target = _url(request.get("input"))
        depth = _bounded_int(config, "depth", 3, 1, 5)
        authorized_prefix_value = config.get("_authorized_url_prefix")
        authorized_prefix: str | None = None
        crawl_scope: str | None = None
        if authorized_prefix_value is not None:
            authorized_prefix, crawl_scope = _url_prefix_regex(authorized_prefix_value)
            if not (
                target == authorized_prefix
                or target.startswith(authorized_prefix.rstrip("/") + "/")
            ):
                raise RequestError("crawl input is outside the authorized URL prefix")
        argv = [
            "katana",
            "-u",
            target,
            "-jsonl",
            "-silent",
            "-no-color",
            "-disable-update-check",
            "-depth",
            str(depth),
            "-concurrency",
            str(_bounded_int(config, "concurrency", 5, 1, 20)),
            "-parallelism",
            str(_bounded_int(config, "parallelism", 5, 1, 20)),
            "-rate-limit",
            str(_bounded_int(config, "rate_limit", 5, 1, 50)),
            "-timeout",
            str(_bounded_int(config, "request_timeout", 10, 1, 30)),
            "-crawl-duration",
            f"{_bounded_int(config, 'crawl_duration_seconds', 90, 10, 240)}s",
            "-max-response-size",
            str(_bounded_int(config, "max_response_bytes", 1_000_000, 1_024, 2_000_000)),
            "-max-domain-pages",
            str(_bounded_int(config, "max_domain_pages", 500, 10, 2_000)),
            "-js-crawl",
            "-filter-similar",
            "-form-extraction",
            "-tech-detect",
            "-omit-raw",
            "-omit-body",
        ]
        excluded_prefixes = config.get("_excluded_url_prefixes", [])
        if not isinstance(excluded_prefixes, list) or len(excluded_prefixes) > 100:
            raise RequestError("_excluded_url_prefixes must be a bounded list")
        if crawl_scope:
            argv.extend(["-crawl-scope", crawl_scope])
        else:
            argv.extend(["-field-scope", "fqdn"])
        for excluded_prefix in excluded_prefixes:
            _prefix, expression = _url_prefix_regex(excluded_prefix)
            argv.extend(["-crawl-out-scope", expression])
        authorized_path = urlsplit(authorized_prefix).path if authorized_prefix else "/"
        if depth >= 3 and authorized_path == "/" and not excluded_prefixes:
            argv.extend(["-known-files", "all"])
        if not allow_private:
            argv.extend(["-exclude", "private-ips"])
        return tool, argv, timeout

    if tool == "naabu":
        target = _ip(request.get("input"), allow_private=allow_private)
        argv = [
            "naabu",
            "-host",
            target,
            "-json",
            "-silent",
            "-no-color",
            "-disable-update-check",
            "-scan-type",
            "c",
            "-top-ports",
            str(_choice_int(config, "top_ports", 100, frozenset({100, 1000}))),
            "-rate",
            str(_bounded_int(config, "rate_limit", 100, 1, 1000)),
            "-c",
            str(_bounded_int(config, "concurrency", 25, 1, 100)),
            "-timeout",
            str(_bounded_int(config, "request_timeout_ms", 1000, 100, 5000)),
            "-retries",
            str(_bounded_int(config, "retries", 1, 0, 3)),
            "-no-stdin",
        ]
        return tool, argv, timeout

    if tool == "jsluice":
        target = _url(request.get("input"))
        payload = request.get("payload_b64")
        if not isinstance(payload, str) or len(payload) > 1_500_000:
            raise RequestError("jsluice requires a bounded base64 JavaScript payload")
        try:
            source = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise RequestError("JavaScript payload is not valid base64") from exc
        if not source or len(source) > 1_000_000:
            raise RequestError("JavaScript payload must be between 1 byte and 1 MB")
        source_path = Path(workdir) / "source.js"
        source_path.write_bytes(source)
        argv = [
            "jsluice",
            "urls",
            "-R",
            target,
            "-c",
            str(_bounded_int(config, "concurrency", 1, 1, 4)),
            str(source_path),
        ]
        return tool, argv, timeout

    if tool == "alterx":
        target = _domain(request.get("input"))
        argv = [
            "alterx",
            "-list",
            target,
            "-enrich",
            "-limit",
            str(_bounded_int(config, "max_mutations", 250, 1, 2_000)),
            "-silent",
            "-disable-update-check",
        ]
        return tool, argv, timeout

    target = _ip(request.get("input"), allow_private=allow_private)
    return (
        tool,
        [
            "cdncheck",
            "-input",
            target,
            "-jsonl",
            "-silent",
            "-no-color",
            "-disable-update-check",
        ],
        timeout,
    )


class ToolboxServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int]) -> None:
        super().__init__(address, ToolboxHandler)
        concurrency = max(1, min(int(os.environ.get("TOOLBOX_MAX_CONCURRENT", "4")), 32))
        self.capacity = BoundedSemaphore(concurrency)
        self.connection_capacity = BoundedSemaphore(concurrency + 8)
        self.shared_secret = _consume_shared_secret()
        if len(self.shared_secret) < 24:
            raise RuntimeError("TOOLBOX_SHARED_SECRET must contain at least 24 characters")
        self.verified_tools, self.implementation_digest = _verify_tool_installation()

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self.connection_capacity.acquire(blocking=False):
            try:
                request.sendall(
                    b"HTTP/1.1 503 Service Unavailable\r\n"
                    b"Content-Length: 0\r\nConnection: close\r\n\r\n"
                )
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.connection_capacity.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connection_capacity.release()


class ToolboxHandler(BaseHTTPRequestHandler):
    server: ToolboxServer
    protocol_version = "HTTP/1.1"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, message: str, *args: object) -> None:
        print(
            json.dumps(
                {
                    "event": "toolbox.http",
                    "client": self.client_address[0],
                    "message": message % args,
                },
                separators=(",", ":"),
            ),
            flush=True,
        )

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "tools": TOOL_VERSIONS,
                    "verified_tools": self.server.verified_tools,
                    "implementation_digest": self.server.implementation_digest,
                },
            )
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/v1/run":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {self.server.shared_secret}"
        if not hmac.compare_digest(supplied, expected):
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= MAX_REQUEST_BYTES:
            self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "invalid_size"})
            return
        try:
            request = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
            return
        if not isinstance(request, dict):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request"})
            return
        if not self.server.capacity.acquire(timeout=30):
            self._send_json(HTTPStatus.TOO_MANY_REQUESTS, {"error": "capacity_exhausted"})
            return
        try:
            with tempfile.TemporaryDirectory(prefix="reconator-tool-") as workdir:
                tool, argv, timeout = build_command(request, workdir=workdir)
                started = time.monotonic()
                try:
                    result = run_bounded_command(argv, timeout=timeout, cwd=workdir)
                except TimeoutError:
                    self._send_json(
                        HTTPStatus.GATEWAY_TIMEOUT,
                        {"error": "tool_timeout", "tool": tool, "timeout": timeout},
                    )
                    return
                except OSError as exc:
                    self._send_json(
                        HTTPStatus.SERVICE_UNAVAILABLE,
                        {
                            "error": "tool_unavailable",
                            "tool": tool,
                            "detail": str(exc)[:500],
                        },
                    )
                    return
                returncode, stdout, stderr, stdout_truncated, stderr_truncated = result
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "tool": tool,
                        "version": TOOL_VERSIONS[tool],
                        "implementation_digest": self.server.implementation_digest,
                        "exit_code": returncode,
                        "stdout": stdout.decode("utf-8", errors="replace"),
                        "stderr": stderr.decode("utf-8", errors="replace"),
                        "stdout_truncated": stdout_truncated,
                        "stderr_truncated": stderr_truncated,
                        "duration_ms": round((time.monotonic() - started) * 1000, 3),
                    },
                )
        except RequestError as exc:
            self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
        except Exception as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "internal_error", "detail": type(exc).__name__},
            )
        finally:
            self.server.capacity.release()


def main() -> None:
    Path("/tmp/reconator-toolbox/config").mkdir(parents=True, exist_ok=True)
    for tool in TOOL_VERSIONS:
        Path("/tmp/reconator-toolbox/.config", tool).mkdir(parents=True, exist_ok=True)
        Path("/tmp/reconator-toolbox/config", tool).mkdir(parents=True, exist_ok=True)
    host = os.environ.get("TOOLBOX_BIND", "0.0.0.0")
    port = int(os.environ.get("TOOLBOX_PORT", "7777"))
    server = ToolboxServer((host, port))
    print(
        json.dumps({"event": "toolbox.started", "host": host, "port": port}),
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
