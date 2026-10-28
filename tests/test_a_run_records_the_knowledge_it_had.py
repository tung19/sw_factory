"""M9's residual: the profile digest says which CONFIG, not which KNOWLEDGE.

M9 option 1b scoped the skills term so a Cloudflare skill stops re-versioning the kinds
a Cloudflare build never involves — 7 of 16 kinds down to 1. That left a residual, named
in the audit at the time rather than buried: the digest is derived from the **profile**,
so an `inherited` kind running in a Cloudflare app and the same kind running in a plain
app now carry the **same version** while seeing **different packs**.

Measured on this machine, which is what makes it concrete rather than theoretical:

    apps/taskboard/.claude/skills/  -> area-oracle-loop, vinext-cf-build
    apps/expenses/.claude/skills/   -> area-oracle-loop

Two different packs, and nothing in the ledger distinguished runs against them. `area
evals` would have compared runs that had different domain knowledge as if the only
difference were the thing under test — so closing this is a prerequisite for F4 being
worth its ~$40-50 of builds, not a tidy-up.
"""
import json

import pytest

from area import evals as E
from area import obs


@pytest.fixture(autouse=True)
def _fresh(monkeypatch, tmp_path):
    """`installed_skills` memoises per process, and the real workspace is elsewhere."""
    monkeypatch.setattr(obs, "WORKSPACE", tmp_path)
    monkeypatch.setattr(obs, "_skills_cache", {})
    return tmp_path


def _install(root, name, *skills):
    d = root / "apps" / name / ".claude" / "skills"
    for s in skills:
        (d / s).mkdir(parents=True)
        (d / s / "SKILL.md").write_text(f"---\nname: {s}\n---\n# {s}\n")
    return d


# ---- what a run had ----------------------------------------------------------

def test_the_installed_pack_is_read_from_the_app(_fresh):
    _install(_fresh, "a", "area-oracle-loop", "vinext-cf-build")
    digest, names = obs.installed_skills("a")
    assert names == ("area-oracle-loop", "vinext-cf-build")
    assert digest and digest.startswith("sha256:")


def test_two_apps_with_different_packs_are_distinguishable(_fresh):
    """The exact shape on this machine: taskboard has both, expenses has one."""
    _install(_fresh, "taskboard", "area-oracle-loop", "vinext-cf-build")
    _install(_fresh, "expenses", "area-oracle-loop")
    assert obs.installed_skills("taskboard")[0] != obs.installed_skills("expenses")[0]


def test_editing_a_skill_changes_what_the_run_records(_fresh):
    d = _install(_fresh, "a", "area-oracle-loop")
    before = obs.installed_skills("a")[0]
    (d / "area-oracle-loop" / "SKILL.md").write_text("---\nname: x\n---\n# changed\n")
    obs._skills_cache.clear()
    assert obs.installed_skills("a")[0] != before


def test_no_app_yet_is_recorded_as_nothing_not_guessed(_fresh):
    """A `spec` run happens before the app exists. That is information, not a gap."""
    assert obs.installed_skills("never-built") == (None, ())
    assert obs.installed_skills(None) == (None, ())


def test_log_run_stamps_it(_fresh, monkeypatch):
    monkeypatch.setattr(obs, "RUNS", _fresh / ".area" / "runs.jsonl")
    _install(_fresh, "a", "area-oracle-loop")
    obs.set_app("a")
    obs.log_run("build:plain:tdd", duration=1.0, passed=True, backend="ACPAgent")
    rec = json.loads(obs.RUNS.read_text().splitlines()[-1])
    assert rec["skills"] == ["area-oracle-loop"]
    assert rec["skills_digest"]


# ---- and evals refuses to compare across them --------------------------------

def _runs(digest, skills_digest, n, task="taskboard"):
    return [{"label": "build:plain:tdd", "profile": "builder", "ts": 1000 + i,
             "profile_digest": digest, "skills_digest": skills_digest, "name": task,
             "outer_iters": 1, "passed": True, "cost_usd": 1.0} for i in range(n)]


def _compare(cur_sk, prev_sk, n=6):
    runs = _runs("sha256:OLD", prev_sk, n) + _runs("sha256:NEW", cur_sk, n)

    class _P:
        digest = "sha256:NEW"
        raw: dict = {}
        prompt_sources: tuple = ()
        skills = "all"

        def owns(self, label):
            return True

    # `compare` imports load_profile INSIDE the function, so the patch goes on the
    # owning module, not on area.evals.
    import area.profile as _P_mod
    orig = _P_mod.load_profile
    _P_mod.load_profile = lambda kind, root=None, **k: _P()  # type: ignore[assignment]
    try:
        return E.compare("builder", runs=runs, min_runs=3)
    finally:
        _P_mod.load_profile = orig                            # type: ignore[assignment]


def test_different_packs_are_refused_not_compared():
    res = _compare("sha256:PACK_A", "sha256:PACK_B")
    assert res["verdict"] == "confounded-skills", res
    assert "DIFFERENT installed skill packs" in res["reason"]
    assert "cannot separate them" in res["reason"]


def test_the_same_pack_still_compares():
    res = _compare("sha256:PACK_A", "sha256:PACK_A")
    assert res["verdict"] in ("ok", "improved", "regressed"), res


def test_runs_with_no_pack_recorded_do_not_fabricate_a_confound():
    """Legacy and pre-build runs carry no skills_digest. Absence must not read as
    disagreement, or every old ledger becomes permanently unusable."""
    res = _compare(None, None)
    assert res["verdict"] != "confounded-skills", res


def test_a_confound_never_counts_as_a_pass_even_without_strict(monkeypatch):
    """Unlike "not enough data", this is a comparison that cannot be made — so it is
    not strict-only. Asserted on `check`'s posture with `compare` stubbed, because
    `check` otherwise reads the repo's real profiles and task set."""
    monkeypatch.setattr(E, "compare", lambda kind, **k: {
        "kind": kind, "verdict": "confounded-skills", "reason": "different packs"})
    ok, results = E.check(["builder"])
    assert ok is False, results
    assert results[0]["verdict"] == "confounded-skills"
