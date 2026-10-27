"""The verifier runs the generated app, so it must not hold the deploy tokens.

`run_until` is the build loop: it runs the agent, then calls `verify()`. The scrub
covered only the agent exchange (`_send_and_run`), so `verify()` ran at top level with
the full environment — and `verify()` is what runs `npm install` on an AGENT-AUTHORED
`package.json`, which executes whatever `postinstall` script the agent wrote, then its
build and its tests. Cloudflare/Vercel/database tokens were in that environment.

Two mechanisms, because there are two shapes:
  * `command_verifier` launches the subprocess itself -> hand the child a filtered
    `env=`, which needs no global mutation (`scrubbed_env`).
  * a Verifier is an ARBITRARY callable and may launch its own subprocesses that
    inherit `os.environ` (the holdout oracle does exactly that) -> `run_until` wraps
    the call in `_scrubbed_agent_env()`.

Only the named keys are dropped, which is what makes this safe to apply to the build
itself: PATH, HOME and the npm/node configuration survive.
"""
import os
import subprocess

import pytest

from area.engine import adapter as A
from area.engine import VerifyResult, command_verifier, scrubbed_env

SECRETS = {"CLOUDFLARE_API_TOKEN": "cf-tok", "VERCEL_TOKEN": "vc-tok",
           "DATABASE_URL": "postgres://u:pw@h/db", "GITHUB_TOKEN": "gh-tok"}


@pytest.fixture
def with_secrets(monkeypatch):
    for k, v in SECRETS.items():
        monkeypatch.setenv(k, v)
    return SECRETS


def test_scrubbed_env_drops_the_secrets_and_keeps_what_a_build_needs(with_secrets):
    e = scrubbed_env()
    assert not (set(SECRETS) & set(e)), "a deploy token survived the filter"
    # the filter must be a filter, not a replacement: a build needs these
    for keep in ("PATH", "HOME"):
        if keep in os.environ:
            assert e[keep] == os.environ[keep]
    assert len(e) >= len(os.environ) - len(SECRETS)
    # and the PARENT keeps its own credentials — it is the thing that deploys
    assert all(k in os.environ for k in SECRETS)


def test_command_verifier_hands_the_child_no_tokens(tmp_path, with_secrets):
    """The real subprocess, not a fixture: every gate (audit tier-1, e2e, chaos, the
    build oracle) runs its command through this."""
    out = tmp_path / "seen.txt"
    v = command_verifier(
        ["bash", "-lc", f'env | grep -cE "^({"|".join(SECRETS)})=" > {out}; exit 0'],
        cwd=str(tmp_path))
    assert v().ok
    assert out.read_text().strip() == "0", "the child could read a deploy token"


def test_command_verifier_does_not_mutate_the_parent_environment(tmp_path, with_secrets):
    """`env=` instead of popping `os.environ` — so nothing else in this process ever
    observes the credentials missing, not even for the duration of a build."""
    probe = {}
    real = A.subprocess.Popen

    def spy(*a, **kw):
        probe["parent_had"] = all(k in os.environ for k in SECRETS)
        probe["child_env"] = kw.get("env")
        return real(*a, **kw)

    A.subprocess.Popen = spy
    try:
        command_verifier(["bash", "-lc", "exit 0"], cwd=str(tmp_path))()
    finally:
        A.subprocess.Popen = real
    assert probe["parent_had"] is True
    assert probe["child_env"] is not None
    assert not (set(SECRETS) & set(probe["child_env"]))


def test_run_until_scrubs_around_an_arbitrary_verifier(tmp_path, monkeypatch, with_secrets):
    """The holdout shape: a Verifier that launches its own subprocess inheriting
    os.environ. `command_verifier`'s `env=` cannot help here, so the loop itself has to
    scrub — this is the actual H2 regression."""
    monkeypatch.setattr(A, "_mk_conversation", lambda *a, **k: object())
    monkeypatch.setattr(A, "_send_and_run", lambda conv, msg: None)

    seen = {}

    def verifier():
        r = subprocess.run(  # NO env= : inherits whatever the parent has
            ["bash", "-lc", f'env | grep -cE "^({"|".join(SECRETS)})="'],
            capture_output=True, text=True)
        seen["count"] = r.stdout.strip()
        return VerifyResult(True, "ok")

    class _Agent:
        def close(self):
            pass

    passed, _ = A.run_until(_Agent(), tmp_path, "task", verifier, max_iters=1)
    assert passed is True
    assert seen["count"] == "0", "the verifier's own subprocess inherited a deploy token"
    assert all(k in os.environ for k in SECRETS)   # restored


def test_a_failing_verifier_is_also_scrubbed_on_the_retry_path(tmp_path, monkeypatch,
                                                               with_secrets):
    """Both call sites: the loop's `verify()` and the post-loop `verify().ok`."""
    monkeypatch.setattr(A, "_mk_conversation", lambda *a, **k: object())
    monkeypatch.setattr(A, "_send_and_run", lambda conv, msg: None)
    counts = []

    def verifier():
        counts.append(len(set(SECRETS) & set(os.environ)))
        return VerifyResult(False, "nope")

    class _Agent:
        def close(self):
            pass

    passed, _ = A.run_until(_Agent(), tmp_path, "task", verifier, max_iters=2)
    assert passed is False
    assert counts and set(counts) == {0}, f"secrets visible to verify(): {counts}"


def test_the_holdout_oracle_passes_a_scrubbed_env(tmp_path, monkeypatch, with_secrets):
    """The locked suite — and in TDD mode the production build and its `npm install` —
    runs through holdout.py's own `subprocess.run`, not a `command_verifier`. Asserted
    by running the oracle and inspecting the env it actually handed the child, rather
    than by grepping the source for the right-looking line."""
    from area.verify import holdout as H

    hd = tmp_path / "__tests__" / "_holdout"
    hd.mkdir(parents=True)
    (hd / "ac1.test.ts").write_text("it('AC-1', () => {})\n")

    captured = {}

    class _Done:
        returncode = 0
        stdout = "\n Test Files  1 passed (1)\n      Tests  1 passed (1)\n"
        stderr = ""

    def spy(cmd, **kw):
        captured["env"] = kw.get("env")
        captured["parent_still_has"] = all(k in os.environ for k in SECRETS)
        # the oracle also checks WHICH files ran, so produce the report it asked for
        out = next(a for a in cmd[-1].split() if a.startswith("--outputFile.json="))
        import json as _j
        with open(out.split("=", 1)[1].strip("'\""), "w", encoding="utf-8") as fh:
            _j.dump({"testResults": [{"name": str(hd / "ac1.test.ts"),
                                      "status": "passed"}]}, fh)
        return _Done()

    monkeypatch.setattr(H.subprocess, "run", spy)
    assert H._holdout_oracle(tmp_path, hd, H._lock(hd))().ok is True

    assert captured["env"] is not None, "the oracle inherited the parent environment"
    assert not (set(SECRETS) & set(captured["env"]))
    assert "PATH" not in os.environ or captured["env"].get("PATH") == os.environ["PATH"]
    assert captured["parent_still_has"] is True


# ---- every module that launches the generated app -----------------------------

@pytest.mark.parametrize("mod", ["area.verify.nfr", "area.verify.perf",
                                 "area.build.cf_scaffold"])
def test_each_module_env_helper_scrubs(mod, with_secrets):
    """These three build their own `env=` for `npm run build` / `npm run <script>` /
    the app server. All three were `dict(os.environ)`, so the generated app's scripts
    ran with the deploy tokens in their environment."""
    import importlib

    e = importlib.import_module(mod)._env()
    assert not (set(SECRETS) & set(e)), f"{mod}._env() leaks a deploy token"
    assert "npm_config_cache" in e, f"{mod}._env() lost the npm cache setting"
    if "PATH" in os.environ:
        assert e["PATH"] == os.environ["PATH"], f"{mod}._env() broke PATH"


# ---- the fail-open that scrubbing perf would otherwise have hidden ------------

def _perf_app(tmp_path, name="a", committed=None):
    (tmp_path / "apps" / name).mkdir(parents=True)
    if committed is not None:
        d = tmp_path / "specs" / name
        d.mkdir(parents=True)
        (d / "perf.yaml").write_text(committed)
    return name


def test_perf_fails_when_a_committed_budget_cannot_be_measured(tmp_path, monkeypatch):
    """`perf` returned True before it ever consulted `blocking`. The commonest reason
    it cannot measure is that the app's server never came up — exactly what a perf gate
    exists to notice. Scrubbing perf's environment makes an unstartable server more
    likely, so this had to be fixed in the same change, or the scrub would have
    converted a failure into a silent pass."""
    from area.verify import perf as P

    name = _perf_app(tmp_path, committed="p95_ms: 500\n")
    monkeypatch.setattr(P, "measure", lambda *a, **k: ({}, "server never started"))
    assert P.perf_verify(name, root=tmp_path) is False


def test_perf_still_skips_when_the_budget_is_only_the_lenient_default(tmp_path,
                                                                     monkeypatch):
    """No committed perf.yaml and no --strict: advisory, so an unmeasurable run skips
    rather than blocking a build on a default nobody asked for."""
    from area.verify import perf as P

    name = _perf_app(tmp_path)
    monkeypatch.setattr(P, "measure", lambda *a, **k: ({}, "no server script"))
    assert P.perf_verify(name, root=tmp_path) is True
    # ... and --strict makes the same situation blocking
    assert P.perf_verify(name, root=tmp_path, strict=True) is False


def test_perf_fails_when_no_budgeted_metric_was_measured(tmp_path, monkeypatch):
    """The second fail-open on the same path: metrics came back, but none of them is a
    metric the committed budget names."""
    from area.verify import perf as P

    name = _perf_app(tmp_path, committed="p95_ms: 500\n")
    monkeypatch.setattr(P, "measure",
                        lambda *a, **k: ({"_server": "start", "unrelated": 1.0}, ""))
    assert P.perf_verify(name, root=tmp_path) is False


def test_ask_cli_does_not_hand_an_agent_session_the_deploy_tokens(monkeypatch,
                                                                  with_secrets):
    """`ask_cli` spawns `claude -p`: an agent session with tool access, prompted with
    content AREA did not write. It ran with no `env=`, so it inherited everything. It
    authenticates from the Claude Code login in HOME, not from any key in the list, so
    the scrub costs it nothing."""
    captured = {}

    class _Done:
        returncode = 0
        stdout = "answer"
        stderr = ""

    def spy(cmd, **kw):
        captured["env"] = kw.get("env")
        return _Done()

    monkeypatch.setattr(A.subprocess, "run", spy)
    assert A.ask_cli("what is 2+2?") == "answer"
    assert captured["env"] is not None, "ask_cli inherited the parent environment"
    assert not (set(SECRETS) & set(captured["env"]))
    if "HOME" in os.environ:   # the login it actually needs must survive
        assert captured["env"]["HOME"] == os.environ["HOME"]
