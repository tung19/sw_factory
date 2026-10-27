"""`scripts/run-runner.sh` must invoke a command that exists.

`area/runner.py` arrived on this branch with the forward-port, but nothing wired it to
the CLI: no `runner` subparser, no `_HANDLERS` entry, no `__main__`. So
`scripts/run-runner.sh` and the hosted `runner.sh` bootstrap — the documented
one-command way to start the data plane — both `exec`'d `area runner`, which did not
exist. `area/runner.py` was imported by nothing but a test.

The valuable test here is the drift guard: the shell script and the parser have to agree
about the flags, because the gap between them was the whole bug.
"""
import argparse
import re

import pytest

import area.cli as C
from area.paths import REPO


def _parser() -> argparse.ArgumentParser:
    return C._build_parser()


def test_runner_is_a_real_subcommand_with_a_handler():
    args = _parser().parse_args(["runner", "--connect", "wss://c.example/ws/runner"])
    assert args.cmd == "runner"
    assert "runner" in C._HANDLERS, "parses but dispatches nowhere"


@pytest.mark.parametrize("flag", ["--connect", "--token"])
def test_the_shell_script_and_the_parser_agree_on_the_flags(flag):
    """The script `exec`s `area runner --connect <url> [--token <tok>]`. If the parser
    stops accepting one of those, the documented path breaks silently again."""
    script = (REPO / "scripts" / "run-runner.sh").read_text()
    assert "area runner" in script
    assert flag in script, f"{flag} is no longer passed by run-runner.sh"
    _parser().parse_args(["runner", flag, "x"])   # must not raise


def test_the_env_vars_the_script_reads_are_the_ones_the_handler_reads(monkeypatch):
    """run-runner.sh seeds URL/TOK from AREA_COORD_URL / AREA_PAIR_TOKEN before parsing
    its own flags, so the handler has to honour the same two names."""
    script = (REPO / "scripts" / "run-runner.sh").read_text()
    for var in ("AREA_COORD_URL", "AREA_PAIR_TOKEN"):
        assert var in script

    seen = {}
    monkeypatch.setattr("area.runner.run_runner",
                        lambda url, token=None: seen.update(url=url, token=token) or 0)
    monkeypatch.setenv("AREA_COORD_URL", "wss://from-env/ws/runner")
    monkeypatch.setenv("AREA_PAIR_TOKEN", "tok-from-env")
    args = _parser().parse_args(["runner"])
    assert C._HANDLERS["runner"](args, None) == 0
    assert seen == {"url": "wss://from-env/ws/runner", "token": "tok-from-env"}


def test_an_explicit_flag_beats_the_env_var(monkeypatch):
    seen = {}
    monkeypatch.setattr("area.runner.run_runner",
                        lambda url, token=None: seen.update(url=url, token=token) or 0)
    monkeypatch.setenv("AREA_COORD_URL", "wss://env/ws")
    args = _parser().parse_args(["runner", "--connect", "wss://flag/ws"])
    C._HANDLERS["runner"](args, None)
    assert seen["url"] == "wss://flag/ws"


def test_a_missing_or_wrong_scheme_is_refused_before_dialling(monkeypatch, capsys):
    """`https://` is the commonest paste error and websockets would fail with an opaque
    error much later. Nothing may be dialled in either case."""
    monkeypatch.delenv("AREA_COORD_URL", raising=False)
    monkeypatch.setattr("area.runner.run_runner",
                        lambda *a, **k: pytest.fail("dialled despite a bad URL"))

    assert C._HANDLERS["runner"](_parser().parse_args(["runner"]), None) == 2
    assert "need --connect" in capsys.readouterr().out

    bad = _parser().parse_args(["runner", "--connect", "https://c.example"])
    assert C._HANDLERS["runner"](bad, None) == 2
    assert "must be ws:// or wss://" in capsys.readouterr().out


def test_plain_ws_to_a_remote_host_warns_about_the_clear_text_token(monkeypatch, capsys):
    """Pairing is a single shared token; over `ws://` it crosses the network in clear."""
    monkeypatch.setattr("area.runner.run_runner", lambda *a, **k: 0)
    C._HANDLERS["runner"](_parser().parse_args(
        ["runner", "--connect", "ws://coord.example/ws/runner"]), None)
    assert "UNENCRYPTED" in capsys.readouterr().out

    C._HANDLERS["runner"](_parser().parse_args(
        ["runner", "--connect", "ws://127.0.0.1:8787/ws/runner"]), None)
    assert "UNENCRYPTED" not in capsys.readouterr().out   # localhost is fine


def test_the_docs_banner_does_not_claim_the_command_is_absent_here():
    """RUNNER.md's banner was written for a `main` reader ("Not on this branch"), which
    is the wrong statement on the branch where the runner actually lives."""
    doc = (REPO / "docs" / "RUNNER.md").read_text()
    assert not re.search(r"^> \*\*⚠ Not on this branch", doc, re.M)
    assert "This branch only" in doc
