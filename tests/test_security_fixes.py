"""Audit fixes [MED]: clone-source transport-helper guard + transient-error
classification (these are the unit-testable parts of the C3 batch; the deploy
provenance-mismatch-always-blocks change is a logic simplification in
deploy_with_gate, and the rea-agents version pin is config)."""
import pytest

import area.engine.adapter as ADAPTER
import area.pipeline as P


# ---- clone source guard (git transport-helper RCE) ------------------------------

def test_safe_clone_source_allows_normal_sources():
    for s in ["https://github.com/u/r.git", "http://x.com/a", "git@github.com:u/r.git",
              "/local/path", "./rel/path", "ssh://host/r", "git://h/r"]:
        assert P._safe_clone_source(s) is True, s


def test_safe_clone_source_rejects_helpers_and_option_injection():
    for s in ["ext::sh -c 'id'", "fd::7", "foo::bar", "-oProxyCommand=x", "  ext::x  ", ""]:
        assert P._safe_clone_source(s) is False, s


def test_clone_pipeline_refuses_transport_helper_source(tmp_path):
    with pytest.raises(RuntimeError, match="transport helper"):
        P.clone_pipeline("ext::sh -c id", name="x", workspace=tmp_path)


# ---- transient-error classification (_run_retry) --------------------------------

def test_transient_tokens_do_not_match_common_words():
    for m in ["failed to generate output", "an accurate result", "separate modules",
              "invalid api key", "could not generate the spec"]:
        assert not any(k in m.lower() for k in ADAPTER._TRANSIENT), m


def test_transient_tokens_still_match_real_transients():
    for m in ["429 Too Many Requests", "Rate limit exceeded", "request timeout",
              "ECONNRESET", "service unavailable", "server error 529"]:
        assert any(k in m.lower() for k in ADAPTER._TRANSIENT), m
