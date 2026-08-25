from __future__ import annotations

import json
import time
import tracemalloc

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Target
from app.recon.knowledge import KnowledgeStore
from app.recon.modules.base import AssetEmission
from app.recon.modules.toolbox import _json_lines
from app.recon.normalization import normalize_asset


def benchmark_normalization(count: int = 100_000) -> dict[str, float | int]:
    tracemalloc.start()
    started = time.perf_counter()
    for index in range(count):
        normalize_asset(
            "url",
            f"HTTPS://API-{index % 10_000}.Example.com:443/v1/../users?b={index}&a=1#x",
        )
    duration = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "items": count,
        "seconds": round(duration, 4),
        "items_per_second": round(count / duration, 2),
        "peak_memory_mib": round(peak / 1024 / 1024, 2),
    }


def benchmark_persistence(count: int = 10_000) -> dict[str, float | int]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    started = time.perf_counter()
    with Session(engine) as db:
        target = Target(url="benchmark.example.com", authorization_confirmed=True)
        db.add(target)
        db.flush()
        store = KnowledgeStore(db)
        for index in range(count):
            store.observe_asset(
                target_id=target.id,
                task_id=None,
                module_name="benchmark",
                emission=AssetEmission(
                    "domain",
                    f"host-{index % (count // 2)}.benchmark.example.com",
                    evidence={"batch": index // (count // 2)},
                ),
            )
        db.commit()
    duration = time.perf_counter() - started
    return {
        "observations": count,
        "unique_assets": count // 2,
        "seconds": round(duration, 4),
        "observations_per_second": round(count / duration, 2),
    }


def benchmark_toolbox_jsonl(count: int = 20_000) -> dict[str, float | int]:
    output = "\n".join(
        json.dumps(
            {
                "url": f"https://api-{index % 2_000}.example.com/v1/users?id={index}",
                "source": "benchmark",
                "status_code": 200,
            },
            separators=(",", ":"),
        )
        for index in range(count)
    )
    tracemalloc.start()
    started = time.perf_counter()
    records, rejected = _json_lines(output, limit=count)
    duration = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "records": len(records),
        "rejected": rejected,
        "seconds": round(duration, 4),
        "records_per_second": round(len(records) / duration, 2),
        "peak_memory_mib": round(peak / 1024 / 1024, 2),
    }


def main() -> None:
    print(
        json.dumps(
            {
                "normalization": benchmark_normalization(),
                "sqlite_persistence": benchmark_persistence(),
                "toolbox_jsonl": benchmark_toolbox_jsonl(),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
