"""Timeouts and a kill switch (group 3 / item 10).

Before this, `command_verifier` — the call that runs `npm install && build && test` —
had NO timeout, a dashboard job could not be cancelled, and nothing was started in its
own process group, so a cancelled job's children kept running. The cost gate is
post-hoc: it blocks a deploy after the money is spent and cannot interrupt a thrash.

Real subprocesses, but tiny and fast: `sleep`/`bash`, no agent, no network, no npm.
"""
import os
import signal
import subprocess
import time

import pytest

import area.deploy.cloudflare as CF
import area.deploy.vercel as VC
import area.verify.holdout as H
import area.web.jobs as J
from area._util import CMD_TIMEOUT_DEFAULT, kill_process_group
from area import engine_util as EU
from area.engine import adapter as A


# ---- the shared teardown ------------------------------------------------------
def test_kill_process_group_takes_the_children_too():
    """A plain terminate() signals one pid; `npm run build` forks, so the group is
    what has to die."""
    proc = subprocess.Popen(
        ["bash", "-c", "sleep 60 & echo $! >&2; sleep 60"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True)
    time.sleep(0.4)
    kill_process_group(proc, grace=3.0)
    assert proc.poll() is not None


def test_kill_process_group_survives_an_already_dead_child():
    proc = subprocess.Popen(["true"], start_new_session=True)
    proc.wait()
    kill_process_group(proc)  # must not raise


# ---- command_verifier ---------------------------------------------------------
def test_command_verifier_times_out_and_reports_it_as_a_failure(monkeypatch):
    """Reported, not raised — `run_until` feeds the text back to the agent."""
    monkeypatch.setenv("AREA_CMD_TIMEOUT", "1")
    r = EU.command_verifier(["bash", "-c", "echo working; sleep 30"])()
    assert r.ok is False
    assert "TIMED OUT" in r.feedback and "AREA_CMD_TIMEOUT" in r.feedback
    assert "working" in r.feedback  # partial output is kept, so the agent sees context


def test_command_verifier_kills_the_whole_tree_on_timeout(monkeypatch):
    monkeypatch.setenv("AREA_CMD_TIMEOUT", "1")
    r = EU.command_verifier(["bash", "-c", "sleep 60 & echo PID=$!; sleep 60"])()
    pid = int(r.feedback.split("PID=")[1].split()[0])
    time.sleep(0.4)
    with pytest.raises(OSError):
        os.kill(pid, 0)  # ESRCH — the forked child went with the group


def test_command_verifier_still_passes_and_fails_normally(monkeypatch):
    monkeypatch.delenv("AREA_CMD_TIMEOUT", raising=False)
    assert EU.command_verifier(["true"])().ok is True
    bad = EU.command_verifier(["bash", "-c", "echo boom >&2; exit 3"])()
    assert bad.ok is False and "boom" in bad.feedback


def test_command_verifier_explicit_timeout_beats_the_env(monkeypatch):
    monkeypatch.setenv("AREA_CMD_TIMEOUT", "99")
    r = EU.command_verifier(["bash", "-c", "sleep 30"], timeout=1)()
    assert r.ok is False and "TIMED OUT after 1s" in r.feedback


def test_timeouts_are_read_at_call_time_not_import(monkeypatch):
    """AREA already hit the stale-oracle trap once: a value captured at import can't
    be changed for a running process."""
    monkeypatch.setenv("AREA_CMD_TIMEOUT", "7")
    assert EU._cmd_timeout() == 7.0
    monkeypatch.setenv("AREA_CMD_TIMEOUT", "9")
    assert EU._cmd_timeout() == 9.0
    monkeypatch.setenv("AREA_CMD_TIMEOUT", "not-a-number")
    assert EU._cmd_timeout() == CMD_TIMEOUT_DEFAULT
    monkeypatch.delenv("AREA_CMD_TIMEOUT")
    assert EU._cmd_timeout() == CMD_TIMEOUT_DEFAULT


def test_wall_timeout_parsing_and_opt_out(monkeypatch):
    monkeypatch.setenv("AREA_MAX_WALL_S", "120")
    assert A._wall_timeout() == 120.0
    monkeypatch.setenv("AREA_MAX_WALL_S", "0")
    assert A._wall_timeout() == 0.0  # 0 disables the cap
    monkeypatch.delenv("AREA_MAX_WALL_S")
    assert A._wall_timeout() == A._WALL_TIMEOUT_DEFAULT


# ---- the other previously-unbounded calls ------------------------------------
def test_every_provider_cli_call_is_capped():
    """Drift guard: a new uncapped subprocess.run in the deploy path would reopen the
    hang. Both modules route every call through a timeout."""
    import inspect

    for mod in (CF, VC):
        src = inspect.getsource(mod)
        runs = src.count("subprocess.run(")
        capped = src.count("_CLI_TIMEOUT_S")
        assert capped >= runs, (
            f"{mod.__name__}: {runs} subprocess.run but only {capped} timeout refs")


def test_holdout_runner_has_a_cap_and_handles_it():
    import inspect

    src = inspect.getsource(H)
    assert "_TEST_TIMEOUT_S" in src
    # TimeoutExpired is a SubprocessError, NOT an OSError — it needs its own branch
    assert "subprocess.TimeoutExpired" in src


def test_vercel_capped_runner_synthesises_a_failure(monkeypatch, tmp_path):
    """Callers only inspect returncode/stdout, so a timeout must come back as a failed
    CompletedProcess rather than an exception."""
    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="x", timeout=1)

    monkeypatch.setattr(VC.subprocess, "run", _boom)
    cp = VC._capped(["true"], cwd=tmp_path, env={}, what="vercel whoami")
    assert cp.returncode == 124 and "TIMED OUT" in cp.stdout


# ---- the dashboard kill switch ------------------------------------------------
@pytest.fixture
def jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(J, "JOBS_JSON", tmp_path / "jobs.json")
    (tmp_path / "logs").mkdir()
    return J.JobManager()


def test_cancel_stops_the_job_and_its_children(jobs, monkeypatch):
    monkeypatch.setattr(jobs, "_cmd",
                        lambda kind, p: ["bash", "-c",
                                         "sleep 60 & echo PID=$!; sleep 60"])
    jid = jobs.start("run", {"name": "x", "requirement": "r"})
    time.sleep(1.0)
    assert jobs.get(jid)["status"] == "running"
    pid = int(jobs.log_path(jid).read_text().split("PID=")[1].split()[0])

    assert jobs.cancel(jid) is True
    entry = jobs.get(jid)
    assert entry["status"] == "cancelled" and entry["ended"]
    time.sleep(0.4)
    with pytest.raises(OSError):
        os.kill(pid, 0)  # the forked child died with the group


def test_cancel_is_false_when_there_is_nothing_to_stop(jobs, monkeypatch):
    assert jobs.cancel("nope") is False
    monkeypatch.setattr(jobs, "_cmd", lambda kind, p: ["true"])
    jid = jobs.start("run", {"name": "x", "requirement": "r"})
    time.sleep(0.5)
    jobs.list()  # finalises the finished job
    assert jobs.cancel(jid) is False  # already done -> not "cancelled"
    assert jobs.get(jid)["status"] != "cancelled"


def test_jobs_start_their_own_process_group(jobs, monkeypatch):
    """Without start_new_session, killpg would signal the dashboard's own group."""
    monkeypatch.setattr(jobs, "_cmd", lambda kind, p: ["bash", "-c", "sleep 30"])
    jid = jobs.start("run", {"name": "x", "requirement": "r"})
    proc = jobs._procs[jid][0]
    assert os.getpgid(proc.pid) != os.getpgid(os.getpid())
    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)


def test_cancelled_status_survives_a_restart(jobs, monkeypatch):
    """A cancelled job must not be relabelled "interrupted" by the restart sweep."""
    monkeypatch.setattr(jobs, "_cmd", lambda kind, p: ["bash", "-c", "sleep 30"])
    jid = jobs.start("run", {"name": "x", "requirement": "r"})
    time.sleep(0.3)
    jobs.cancel(jid)
    fresh = J.JobManager()  # re-reads jobs.json
    assert fresh.get(jid)["status"] == "cancelled"
