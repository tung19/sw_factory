"""area adapt P0 (audit #10): the agent runs with deploy/cloud secrets scrubbed
from its environment, so untrusted content it reads (cloned source, web research)
can't exfiltrate them via the terminal tool. LLM keys are kept; secrets are
restored after the run (even on error)."""
import os

import area.engine.adapter as A


def test_scrub_removes_cloud_secrets_keeps_llm_key(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-secret")
    monkeypatch.setenv("VERCEL_TOKEN", "vc-secret")
    monkeypatch.setenv("AREA_POSTGRES_URL", "postgres://secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "llm-key")      # the agent needs this
    monkeypatch.setenv("LLM_API_KEY", "llm-key2")
    with A._scrubbed_agent_env():
        assert "CLOUDFLARE_API_TOKEN" not in os.environ
        assert "VERCEL_TOKEN" not in os.environ
        assert "AREA_POSTGRES_URL" not in os.environ
        assert os.environ["ANTHROPIC_API_KEY"] == "llm-key"   # kept
        assert os.environ["LLM_API_KEY"] == "llm-key2"        # kept
    # restored after
    assert os.environ["CLOUDFLARE_API_TOKEN"] == "cf-secret"
    assert os.environ["VERCEL_TOKEN"] == "vc-secret"


def test_scrub_restores_on_error(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-secret")
    try:
        with A._scrubbed_agent_env():
            assert "CLOUDFLARE_API_TOKEN" not in os.environ
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert os.environ["CLOUDFLARE_API_TOKEN"] == "cf-secret"   # restored despite error


def test_scrub_noop_when_absent(monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    with A._scrubbed_agent_env():
        assert "CLOUDFLARE_API_TOKEN" not in os.environ        # nothing to strip
    assert "CLOUDFLARE_API_TOKEN" not in os.environ            # still absent after


def test_run_retry_scrubs_during_conv_run(monkeypatch):
    """The scrub is actually applied around conv.run() — the secret is absent
    while the agent executes, present again after."""
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-secret")
    seen = {}

    class _Conv:
        def run(self):
            seen["cf_during_run"] = os.environ.get("CLOUDFLARE_API_TOKEN")

    A._run_retry(_Conv())
    assert seen["cf_during_run"] is None                       # scrubbed during run
    assert os.environ["CLOUDFLARE_API_TOKEN"] == "cf-secret"   # restored after
