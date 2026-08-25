from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from app.recon.modules.base import (
    ModuleContext,
    ModuleExecutionError,
    ModuleManifest,
    ModuleResult,
)

Parser = Callable[[str, ModuleContext], ModuleResult]


@dataclass(frozen=True, slots=True)
class CommandSpec:
    argv: tuple[str, ...]
    parser: Parser
    cwd: str | None = None
    allowed_exit_codes: frozenset[int] = frozenset({0})


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    process.wait()


def run_bounded_command(
    argv: list[str],
    *,
    cwd: str | None,
    env: dict[str, str],
    timeout: int,
    max_output_bytes: int,
) -> tuple[int, bytes, bytes, bool, bool]:
    """Drain both process pipes while retaining only a fixed number of bytes."""
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        close_fds=True,
    )
    selector = selectors.DefaultSelector()
    assert process.stdout is not None
    assert process.stderr is not None
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
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
                capacity = max_output_bytes - len(buffers[name])
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


class CommandModule:
    """Safe subprocess adapter: static argv, no shell, bounded output and timeout."""

    def __init__(
        self,
        manifest: ModuleManifest,
        command: CommandSpec,
        *,
        max_output_bytes: int = 2_000_000,
    ) -> None:
        self.manifest = manifest
        self.command = command
        self.max_output_bytes = max_output_bytes

    def execute(self, context: ModuleContext) -> ModuleResult:
        argv = [
            part.replace("{input}", context.input_asset.canonical_value)
            for part in self.command.argv
        ]
        executable = Path(argv[0])
        if executable.name.lower() in {
            "sh",
            "bash",
            "zsh",
            "fish",
            "cmd",
            "cmd.exe",
            "powershell",
            "pwsh",
        }:
            raise ModuleExecutionError(
                "shell interpreters are not permitted by the command adapter",
                retryable=False,
                code="unsafe_command",
            )
        if executable.is_absolute() and not executable.is_file():
            raise ModuleExecutionError(
                f"module executable is unavailable: {executable}",
                retryable=False,
                code="tool_unavailable",
            )
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "NO_COLOR": "1",
        }
        try:
            returncode, stdout_bytes, stderr_bytes, stdout_truncated, stderr_truncated = (
                run_bounded_command(
                    argv,
                    cwd=self.command.cwd,
                    env=env,
                    timeout=context.timeout_seconds,
                    max_output_bytes=self.max_output_bytes,
                )
            )
        except TimeoutError as exc:
            raise ModuleExecutionError(
                f"module timed out after {context.timeout_seconds}s",
                code="timeout",
            ) from exc
        except OSError as exc:
            raise ModuleExecutionError(str(exc), code="spawn_failed") from exc

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        if returncode not in self.command.allowed_exit_codes:
            detail = stderr.strip() or stdout.strip() or "no diagnostic output"
            raise ModuleExecutionError(
                f"tool exited with {returncode}: {detail[:1000]}",
                code="tool_exit",
            )
        parsed = self.command.parser(stdout, context)
        parsed.raw_output = stdout + (f"\n[stderr]\n{stderr}" if stderr.strip() else "")
        parsed.metadata.update(
            {
                "exit_code": returncode,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
            }
        )
        return parsed
