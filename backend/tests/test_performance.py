import time

import pytest

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
