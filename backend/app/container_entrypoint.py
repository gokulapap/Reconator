from __future__ import annotations

import os


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise SystemExit(f"{name} must be between {minimum} and {maximum}")
    return value


def main() -> None:
    port = _bounded_int("PORT", 8000, 1, 65_535)
    workers = _bounded_int("WEB_CONCURRENCY", 2, 1, 64)
    os.execvp(
        "gunicorn",
        [
            "gunicorn",
            "app.main:app",
            "--worker-class",
            "uvicorn.workers.UvicornWorker",
            "--bind",
            f"0.0.0.0:{port}",
            "--workers",
            str(workers),
            "--timeout",
            "120",
            "--access-logfile",
            "-",
        ],
    )


if __name__ == "__main__":
    main()
