"""The agent env scrub must cover the WHOLE exchange, not just conv.run().

Group 3 / item 11 of docs/secure-factory-gap-assessment.md. `send_message` can itself
initialize the agent (true for a non-ACP backend), and an initialized agent spawns a
long-lived terminal that inherits the parent env at spawn time — so a scrub that only
wrapped `run()` could be bypassed depending on which backend was in use.

Pure logic: a fake conversation records os.environ at each step. No agent, no network.
"""
import os
from pathlib import Path

from area.engine import adapter as A


class _FakeConv:
    """Records the environment as the adapter hands control to the agent."""

    def __init__(self) -> None:
        self.env_at_send: dict[str, str] | None = None
        self.env_at_run: dict[str, str] | None = None
        self.messages: list[str] = []

    def send_message(self, m: str) -> None:
        self.messages.append(m)
        self.env_at_send = dict(os.environ)

    def run(self) -> None:
        self.env_at_run = dict(os.environ)


def test_deploy_secrets_are_gone_at_send_message_not_only_at_run(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "gh-secret")
    monkeypatch.setenv("POSTGRES_URL", "postgres://u:p@h/db")
    # LLM/provider keys must SURVIVE — the agent needs them to think
    monkeypatch.setenv("ANTHROPIC_API_KEY", "model-key")

    conv = _FakeConv()
    A._send_and_run(conv, "do x")

    assert conv.messages == ["do x"]
    for leaked in ("CLOUDFLARE_API_TOKEN", "GITHUB_TOKEN", "POSTGRES_URL"):
        assert leaked not in (conv.env_at_send or {}), f"{leaked} reached send_message"
        assert leaked not in (conv.env_at_run or {}), f"{leaked} reached run"
    assert (conv.env_at_send or {})["ANTHROPIC_API_KEY"] == "model-key"
    # restored afterwards — deploy runs in a separate, non-agent phase and needs them
    assert os.environ["CLOUDFLARE_API_TOKEN"] == "cf-secret"


def test_scrub_nests_without_restoring_early(monkeypatch):
    """`_send_and_run` wraps a `_run_retry` that still guards itself, so the context
    manager nests. The inner exit must NOT put the secret back while the outer scope
    is still handing control to the agent."""
    monkeypatch.setenv("VERCEL_TOKEN", "v1")
    with A._scrubbed_agent_env():
        assert "VERCEL_TOKEN" not in os.environ
        with A._scrubbed_agent_env():
            assert "VERCEL_TOKEN" not in os.environ
        assert "VERCEL_TOKEN" not in os.environ  # inner exit restored nothing
    assert os.environ["VERCEL_TOKEN"] == "v1"


def test_scrub_restores_even_when_the_agent_raises(monkeypatch):
    monkeypatch.setenv("CF_API_TOKEN", "t")

    class _Boom(_FakeConv):
        def run(self) -> None:
            raise RuntimeError("agent died")

    try:
        A._send_and_run(_Boom(), "x")
    except RuntimeError:
        pass
    assert os.environ["CF_API_TOKEN"] == "t"


def test_every_send_message_goes_through_the_helper():
    """Drift guard: a new `conv.send_message(...)` call site added outside
    `_send_and_run` would silently fall outside the scrub again."""
    src = Path(A.__file__).read_text()
    assert src.count(".send_message(") == 1, (
        "send_message must be called only inside _send_and_run — a new call site "
        "would bypass the env scrub"
    )
