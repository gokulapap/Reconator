import base64
import importlib.util
import tempfile
from pathlib import Path

import pytest

RUNNER_PATH = Path(__file__).parents[2] / "toolbox" / "runner.py"
SPEC = importlib.util.spec_from_file_location("reconator_toolbox_runner", RUNNER_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_runner_rejects_command_injection_as_an_invalid_domain():
    with tempfile.TemporaryDirectory() as workdir, pytest.raises(runner.RequestError):
        runner.build_command(
            {"tool": "subfinder", "input": "example.com;id", "config": {}},
            workdir=workdir,
        )


def test_httpx_runner_applies_private_network_denylist_and_bounds():
    with tempfile.TemporaryDirectory() as workdir:
        tool, argv, timeout = runner.build_command(
            {
                "tool": "httpx",
                "input": "example.com",
                "config": {"concurrency": 9999, "rate_limit": 9999, "execution_timeout": 9999},
            },
            workdir=workdir,
        )

    assert tool == "httpx"
    assert timeout == runner.MAX_TIMEOUT_SECONDS
    assert argv[argv.index("-threads") + 1] == "50"
    assert argv[argv.index("-rate-limit") + 1] == "100"
    assert runner.PRIVATE_NETWORKS in argv
    assert "-favicon" not in argv


def test_katana_runner_blocks_private_addresses_and_bounds_response_work():
    with tempfile.TemporaryDirectory() as workdir:
        _, argv, _ = runner.build_command(
            {
                "tool": "katana",
                "input": "https://app.example.com/",
                "config": {"max_domain_pages": 99_999, "max_response_bytes": 99_999_999},
            },
            workdir=workdir,
        )

    assert argv[argv.index("-exclude") + 1] == "private-ips"
    assert argv[argv.index("-max-domain-pages") + 1] == "2000"
    assert argv[argv.index("-max-response-size") + 1] == "2000000"
    assert "-omit-body" in argv


def test_katana_runner_enforces_authorized_url_prefix_and_exclusions():
    with tempfile.TemporaryDirectory() as workdir:
        _, argv, _ = runner.build_command(
            {
                "tool": "katana",
                "input": "https://app.example.com/app/",
                "config": {
                    "_authorized_url_prefix": "https://app.example.com/app/",
                    "_excluded_url_prefixes": ["https://app.example.com/app/admin/"],
                },
            },
            workdir=workdir,
        )
        with pytest.raises(runner.RequestError, match="outside the authorized"):
            runner.build_command(
                {
                    "tool": "katana",
                    "input": "https://app.example.com/",
                    "config": {"_authorized_url_prefix": "https://app.example.com/app/"},
                },
                workdir=workdir,
            )

    assert "-crawl-scope" in argv
    assert "-crawl-out-scope" in argv
    assert "-field-scope" not in argv
    assert "-known-files" not in argv


def test_passive_and_local_tools_preserve_sources_without_update_checks():
    with tempfile.TemporaryDirectory() as workdir:
        _, subfinder_argv, _ = runner.build_command(
            {"tool": "subfinder", "input": "example.com", "config": {}},
            workdir=workdir,
        )
        _, urlfinder_argv, _ = runner.build_command(
            {"tool": "urlfinder", "input": "example.com", "config": {}},
            workdir=workdir,
        )
        _, cdncheck_argv, _ = runner.build_command(
            {"tool": "cdncheck", "input": "93.184.216.34", "config": {}},
            workdir=workdir,
        )
    assert "-all" in subfinder_argv
    assert "-collect-sources" in subfinder_argv
    assert "-collect-sources" in urlfinder_argv
    assert "-disable-update-check" in cdncheck_argv


def test_subfinder_all_sources_can_be_disabled_for_low_cost_runs():
    with tempfile.TemporaryDirectory() as workdir:
        _, argv, _ = runner.build_command(
            {
                "tool": "subfinder",
                "input": "example.com",
                "config": {"all_sources": False},
            },
            workdir=workdir,
        )

    assert "-all" not in argv


def test_dnsx_runner_is_file_bounded_wildcard_aware_and_noninteractive():
    with tempfile.TemporaryDirectory() as workdir:
        _, argv, timeout = runner.build_command(
            {
                "tool": "dnsx",
                "input": "candidate.authorized.invalid",
                "config": {
                    "concurrency": 99_999,
                    "rate_limit": 99_999,
                    "request_timeout_seconds": 99,
                    "retries": 99,
                    "wildcard_threshold": 99,
                    "execution_timeout": 99_999,
                },
            },
            workdir=workdir,
        )
        input_path = Path(argv[argv.index("-list") + 1])
        assert input_path.parent == Path(workdir)
        assert input_path.read_text() == "candidate.authorized.invalid\n"

    assert timeout == runner.MAX_TIMEOUT_SECONDS
    assert argv[argv.index("-threads") + 1] == "100"
    assert argv[argv.index("-rate-limit") + 1] == "500"
    assert argv[argv.index("-timeout") + 1] == "15s"
    assert argv[argv.index("-retry") + 1] == "4"
    assert argv[argv.index("-wildcard-threshold") + 1] == "20"
    assert {"-a", "-aaaa", "-cname", "-ns", "-mx", "-txt", "-caa"} <= set(argv)
    assert "-auto-wildcard" in argv
    assert "-json" in argv
    assert "-omit-raw" in argv
    assert "-disable-update-check" in argv


def test_dnsx_runner_rejects_injected_or_non_domain_input():
    with (
        tempfile.TemporaryDirectory() as workdir,
        pytest.raises(runner.RequestError),
    ):
        runner.build_command(
            {"tool": "dnsx", "input": "authorized.invalid;id", "config": {}},
            workdir=workdir,
        )


def test_naabu_runner_requires_explicit_private_network_authorization():
    with tempfile.TemporaryDirectory() as workdir:
        with pytest.raises(runner.RequestError):
            runner.build_command(
                {"tool": "naabu", "input": "127.0.0.1", "config": {}},
                workdir=workdir,
            )
        _, argv, _ = runner.build_command(
            {
                "tool": "naabu",
                "input": "127.0.0.1",
                "config": {"allow_private_networks": True},
            },
            workdir=workdir,
        )
    assert argv[argv.index("-host") + 1] == "127.0.0.1"
    assert argv[argv.index("-scan-type") + 1] == "c"


def test_naabu_runner_accepts_only_supported_top_port_sets():
    with (
        tempfile.TemporaryDirectory() as workdir,
        pytest.raises(runner.RequestError, match="top_ports must be one of"),
    ):
        runner.build_command(
            {
                "tool": "naabu",
                "input": "127.0.0.1",
                "config": {"allow_private_networks": True, "top_ports": 10},
            },
            workdir=workdir,
        )


def test_jsluice_runner_writes_only_a_bounded_local_payload():
    source = b"fetch('/api/v1/users')"
    with tempfile.TemporaryDirectory() as workdir:
        _, argv, _ = runner.build_command(
            {
                "tool": "jsluice",
                "input": "https://app.example.com/app.js",
                "payload_b64": base64.b64encode(source).decode(),
                "config": {},
            },
            workdir=workdir,
        )
        local_source = Path(argv[-1])
        assert local_source.parent == Path(workdir)
        assert local_source.read_bytes() == source
        assert "https://app.example.com/app.js" not in argv[-1]


def test_runner_rejects_unknown_tools_and_oversized_javascript():
    with tempfile.TemporaryDirectory() as workdir:
        with pytest.raises(runner.RequestError):
            runner.build_command(
                {"tool": "shell", "input": "example.com", "config": {}},
                workdir=workdir,
            )
        with pytest.raises(runner.RequestError):
            runner.build_command(
                {
                    "tool": "jsluice",
                    "input": "https://app.example.com/app.js",
                    "payload_b64": base64.b64encode(b"x" * 1_000_001).decode(),
                    "config": {},
                },
                workdir=workdir,
            )
