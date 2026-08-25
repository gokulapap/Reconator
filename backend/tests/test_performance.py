import json
import time

import pytest

from app.recon.modules.toolbox import _json_lines
from app.recon.normalization import normalize_asset


@pytest.mark.performance
def test_normalization_throughput_regression():
    count = 10_000
    started = time.perf_counter()
    identities = {
        normalize_asset(
            "url", f"HTTPS://Host-{index}.Example.com:443/a/../api?b=2&a=1#fragment"
        ).identity_hash
        for index in range(count)
    }
    duration = time.perf_counter() - started
    assert len(identities) == count
    assert duration < 3.0, f"normalization took {duration:.2f}s for {count} assets"


@pytest.mark.performance
def test_toolbox_jsonl_parser_throughput_regression():
    count = 20_000
    output = "\n".join(
        json.dumps({"host": f"host-{index}.example.com", "source": "fixture"})
        for index in range(count)
    )
    started = time.perf_counter()
    records, rejected = _json_lines(output, limit=count)
    duration = time.perf_counter() - started
    assert len(records) == count
    assert rejected == 0
    assert duration < 3.0, f"JSONL parsing took {duration:.2f}s for {count} records"
