from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

import httpx


class ReconatorClient:
    def __init__(self, base_url: str, api_key: str | None, timeout: float = 30.0) -> None:
        headers = {"X-API-Key": api_key} if api_key else {}
        self.client = httpx.Client(
            base_url=base_url.rstrip("/") + "/api/v1",
            headers=headers,
            timeout=timeout,
        )

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.client.request(method, path, **kwargs)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise RuntimeError(f"API returned HTTP {response.status_code}: {detail}") from exc
        return response.json() if response.content else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reconator",
        description="Reconator authorized reconnaissance CLI",
    )
    parser.add_argument(
        "--api-url",
        default=os.getenv("RECONATOR_API_URL", "http://127.0.0.1:8000"),
    )
    parser.add_argument("--api-key", default=os.getenv("RECONATOR_API_KEY"))
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    commands = parser.add_subparsers(dest="command", required=True)

    scan = commands.add_parser("scan", help="create an authorized reconnaissance scan")
    scan.add_argument("target")
    scan.add_argument(
        "--kind",
        choices=["domain", "url", "ip_address", "cidr"],
        default="domain",
    )
    scan.add_argument("--profile", choices=["passive", "balanced", "active"], default="balanced")
    scan.add_argument("--module", action="append", dest="modules")
    scan.add_argument("--tag", action="append", dest="tags", default=[])
    scan.add_argument(
        "--authorized",
        action="store_true",
        help="confirm you own the target or have explicit permission to assess it",
    )
    scan.add_argument("--wait", action="store_true", help="wait for the scan to finish")
    scan.add_argument("--poll-interval", type=float, default=2.0)

    status = commands.add_parser("status", help="show one scan and its task state")
    status.add_argument("scan_id", type=int)

    assets = commands.add_parser("assets", help="list canonical assets from a scan")
    assets.add_argument("scan_id", type=int)
    assets.add_argument("--kind")
    assets.add_argument("--min-priority", type=float, default=0)

    events = commands.add_parser("events", help="show a scan's execution timeline")
    events.add_argument("scan_id", type=int)

    commands.add_parser("modules", help="list registered recon modules")
    return parser


def _print(data: Any, machine_readable: bool) -> None:
    if machine_readable:
        print(json.dumps(data, indent=2, sort_keys=True))
        return
    if isinstance(data, list):
        for item in data:
            print(json.dumps(item, sort_keys=True))
    elif isinstance(data, dict):
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        print(data)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "scan" and not args.authorized:
        print(
            "Refusing to start: pass --authorized only when you have explicit permission.",
            file=sys.stderr,
        )
        return 2
    client = ReconatorClient(args.api_url, args.api_key)
    try:
        if args.command == "scan":
            data = client.request(
                "POST",
                "/targets",
                json={
                    "url": args.target,
                    "target_kind": args.kind,
                    "profile": args.profile,
                    "selected_modules": args.modules,
                    "tags": args.tags,
                    "authorization_confirmed": True,
                },
            )
            if args.wait:
                if not 0.2 <= args.poll_interval <= 300:
                    raise RuntimeError("--poll-interval must be between 0.2 and 300 seconds")
                scan_id = data["id"]
                while data["status"] in {"queued", "running"}:
                    time.sleep(args.poll_interval)
                    data = client.request("GET", f"/targets/{scan_id}")
        elif args.command == "status":
            scan = client.request("GET", f"/targets/{args.scan_id}")
            tasks = client.request("GET", f"/targets/{args.scan_id}/tasks?page_size=500")
            data = {"scan": scan, "tasks": tasks}
        elif args.command == "assets":
            params = {"page_size": 500, "min_priority": args.min_priority}
            if args.kind:
                params["kind"] = args.kind
            data = client.request("GET", f"/targets/{args.scan_id}/assets", params=params)
        elif args.command == "events":
            data = client.request("GET", f"/targets/{args.scan_id}/events?limit=1000")
        else:
            data = client.request("GET", "/modules")
    except (httpx.HTTPError, RuntimeError) as exc:
        print(f"reconator: {exc}", file=sys.stderr)
        return 1
    finally:
        client.client.close()
    _print(data, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
