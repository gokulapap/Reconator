import os

import pytest

from app.recon.modules.base import (
    ModuleContext,
    ModuleExecutionError,
    ModuleManifest,
    ModuleMode,
    ModuleResult,
)
from app.recon.modules.command import CommandModule, CommandSpec
from app.recon.normalization import normalize_asset


def _parser(stdout, _context):
    return ModuleResult(metadata={"captured": len(stdout)})


def _context():
    return ModuleContext(
        target_id=1,
        task_id=1,
        input_asset=normalize_asset("domain", "command.example.com"),
        config={},
        timeout_seconds=5,
    )


def _manifest(name="test.command"):
    return ModuleManifest(
        name=name,
        version="1",
        description="fixture",
        capability="test.command",
        consumes=frozenset({"domain"}),
        produces=frozenset({"technology"}),
        mode=ModuleMode.local,
    )


def test_command_output_is_streamed_and_bounded():
    module = CommandModule(
        _manifest(),
        CommandSpec(argv=("/usr/bin/printf", "%s", "x" * 4096), parser=_parser),
        max_output_bytes=64,
    )
    result = module.execute(_context())
    assert result.metadata["captured"] == 64
    assert result.metadata["stdout_truncated"] is True
    assert len(result.raw_output) == 64


def test_shell_interpreters_are_rejected():
    module = CommandModule(
        _manifest("test.shell"),
        CommandSpec(argv=("/bin/sh", "-c", "printf unsafe"), parser=_parser),
    )
    with pytest.raises(ModuleExecutionError, match="shell interpreters") as exc:
        module.execute(_context())
    assert exc.value.code == "unsafe_command"


@pytest.mark.skipif(not os.path.exists("/usr/bin/printf"), reason="POSIX printf unavailable")
def test_input_is_passed_as_one_argv_element():
    context = ModuleContext(
        target_id=1,
        task_id=1,
        input_asset=normalize_asset("custom.input", "literal;echo injected"),
        config={},
        timeout_seconds=5,
    )
    module = CommandModule(
        _manifest("test.argv"),
        CommandSpec(argv=("/usr/bin/printf", "%s", "{input}"), parser=_parser),
    )
    result = module.execute(context)
    assert result.raw_output == "literal;echo injected"
