from typing import ClassVar

from app import cli


class FakeClient:
    instances: ClassVar[list["FakeClient"]] = []

    def __init__(self, base_url, api_key):
        self.base_url = base_url
        self.api_key = api_key
        self.requests = []
        self.client = self
        self.closed = False
        self.instances.append(self)

    def request(self, method, path, **kwargs):
        self.requests.append((method, path, kwargs))
        return {
            "assets_total": 2,
            "source_yield": [{"source_name": "fixture", "distinct_assets": 2}],
            "module_health": [],
        }

    def close(self):
        self.closed = True


def test_summary_command_exposes_discovery_quality(monkeypatch, capsys):
    FakeClient.instances.clear()
    monkeypatch.setattr(cli, "ReconatorClient", FakeClient)

    assert cli.main(["--json", "summary", "42"]) == 0

    client = FakeClient.instances[0]
    assert client.requests == [("GET", "/targets/42/knowledge-summary", {})]
    assert client.closed
    assert '"distinct_assets": 2' in capsys.readouterr().out


def test_scan_command_requires_an_explicit_authorization_flag(capsys):
    assert cli.main(["scan", "example.invalid"]) == 2
    assert "--authorized" in capsys.readouterr().err
