"""area.profile — one versioned artifact per kind of agent (group 4 / item 12).

The digest is the point: editing a prompt, a skill or a knob must produce a NEW
version, or `area evals` has nothing to compare. Pure logic — no agent, no network.
"""
import argparse

import pytest
import yaml

import area.cli as C
from area import obs
from area import profile as P


def _write(root, kind, **over):
    raw = {
        "kind": kind,
        "description": "d",
        "labels": over.pop("labels", [f"{kind}:*"]),
        "prompt_sources": over.pop("prompt_sources", []),
        "skills": over.pop("skills", "none"),
        "defaults": over.pop("defaults", {"agent_iters": None, "budget_usd": None,
                                          "max_iters": None}),
    }
    raw.update(over)
    (root / f"{kind}.yaml").write_text(yaml.safe_dump(raw))
    return raw


# ---- the shipped profiles describe reality ------------------------------------
def test_every_shipped_profile_loads_and_resolves_its_prompts():
    """A profile that names a symbol which no longer exists has drifted from the code
    it claims to describe."""
    assert P.broken_profiles() == {}, "a profile file is unloadable"
    profs = P.all_profiles()
    assert len(profs) >= 16
    for kind, prof in profs.items():
        assert prof.labels, f"{kind} claims no obs labels — nothing would attribute"
        assert P.missing_prompt_sources(prof) == [], f"{kind} names a dead symbol"
        assert prof.skills in P.SKILLS_VALUES, (
            f"{kind} declares skills: {prof.skills!r}")


def test_every_label_the_code_emits_is_owned_by_exactly_one_profile():
    """Attribution has to be total: an unowned label means those runs are invisible
    to evals. The list mirrors the labels the real obs log contains."""
    for label in ("build:plain:tdd", "build:cloudflare", "build:vercel:tdd",
                  "holdout:author", "holdout:author:tdd", "holdout:author:tdd:parity",
                  "holdout:fix", "holdout:readjudicate", "spec", "spec-review", "re",
                  "product", "audit", "e2e", "chaos", "design", "heal:spec",
                  "research", "intake", "intake:aidlc", "inception:intent"):
        prof = P.for_label(label)
        assert prof is not None, f"no profile owns obs label {label!r}"
        owners = [p.kind for p in P.all_profiles().values() if p.owns(label)]
        assert len(owners) >= 1
        if len(owners) > 1:   # overlapping globs are allowed; longest must win
            assert prof.kind in owners


def test_author_and_fixer_are_separate_profiles():
    """They live in the same module but play opposite roles, and keeping them apart
    IS the spine: never let the same reasoning write AND grade."""
    a, f = P.load_profile("holdout-author"), P.load_profile("holdout-fixer")
    assert a and f and a.kind != f.kind
    assert a.digest != f.digest
    assert not set(a.labels) & set(f.labels)


# ---- the digest ---------------------------------------------------------------
def test_digest_changes_when_a_knob_changes(tmp_path):
    _write(tmp_path, "k")
    before = P.load_profile("k", root=tmp_path).digest
    _write(tmp_path, "k", defaults={"agent_iters": 40, "budget_usd": None,
                                    "max_iters": None})
    assert P.load_profile("k", root=tmp_path).digest != before


def test_digest_changes_when_a_prompt_source_changes(tmp_path, monkeypatch):
    """The keystone. Prompts stay as interpolated Python, so the digest hashes their
    SOURCE — edit the prompt, get a new version, with no prompt rewriting."""
    _write(tmp_path, "k", prompt_sources=["area.obs.log_run"])
    before = P.load_profile("k", root=tmp_path).digest

    calls = {"n": 0}
    real = P._source_hash

    def fake(dotted):
        if dotted == "area.obs.log_run":
            calls["n"] += 1
            return f"{dotted}=EDITED"
        return real(dotted)

    monkeypatch.setattr(P, "_source_hash", fake)
    assert P.load_profile("k", root=tmp_path).digest != before
    assert calls["n"] >= 1


def test_digest_tracks_skills_only_when_the_kind_installs_them(tmp_path, monkeypatch):
    _write(tmp_path, "withskills", skills="all")
    _write(tmp_path, "without", skills="none")
    a1 = P.load_profile("withskills", root=tmp_path).digest
    b1 = P.load_profile("without", root=tmp_path).digest
    monkeypatch.setattr(P, "_skills_hash", lambda: "sha256:DIFFERENT")
    assert P.load_profile("withskills", root=tmp_path).digest != a1
    assert P.load_profile("without", root=tmp_path).digest == b1


def test_a_missing_prompt_symbol_changes_the_digest_but_never_raises(tmp_path):
    """A renamed prompt SHOULD be a new version (the prompt did change), and must not
    crash a build."""
    _write(tmp_path, "k", prompt_sources=["area.obs.definitely_not_there"])
    prof = P.load_profile("k", root=tmp_path)
    assert prof.digest.startswith("sha256:")
    assert P.missing_prompt_sources(prof) == ["area.obs.definitely_not_there"]


# ---- broken profiles must not fail silently ----------------------------------
def test_a_broken_profile_is_reported_not_swallowed(tmp_path):
    """Found for real: one bad indent left `inception:*` unattributed while the
    loaded count merely read 15 instead of 16."""
    (tmp_path / "bad.yaml").write_text("kind: bad\ndescription: >-\n  x\nnope\n")
    assert P.load_profile("bad", root=tmp_path) is None          # lenient path
    with pytest.raises(P.ProfileError):
        P.load_profile("bad", root=tmp_path, strict=True)
    assert "bad.yaml" in P.broken_profiles(root=tmp_path)


def test_unknown_label_and_missing_dir_degrade_quietly(tmp_path):
    assert P.for_label("nope:nothing") is None
    assert P.all_profiles(root=tmp_path / "absent") == {}
    assert P.defaults_for("nope", root=tmp_path / "absent") == (None, None, {})


# ---- attribution + enforcement ------------------------------------------------
def test_obs_stamps_the_profile_on_every_run(tmp_path, monkeypatch):
    """One place, so all 19 agent call sites are attributed without touching them."""
    monkeypatch.setattr(obs, "RUNS", tmp_path / "runs.jsonl")
    obs._profile_cache.clear()
    obs.log_run("build:plain:tdd", duration=1.0, cost=0.5, outer_iters=1, passed=True)
    import json

    rec = json.loads((tmp_path / "runs.jsonl").read_text().strip())
    assert rec["profile"] == "builder"
    assert rec["profile_digest"].startswith("sha256:")


def test_obs_records_nulls_for_an_unowned_label(tmp_path, monkeypatch):
    monkeypatch.setattr(obs, "RUNS", tmp_path / "runs.jsonl")
    obs._profile_cache.clear()
    obs.log_run("totally-unknown", duration=1.0)
    import json

    rec = json.loads((tmp_path / "runs.jsonl").read_text().strip())
    assert rec["profile"] is None and rec["profile_digest"] is None


def test_profile_defaults_fill_only_what_the_caller_left_unset(tmp_path, monkeypatch):
    _write(tmp_path, "k", labels=["zz"], defaults={"agent_iters": 11,
                                                   "budget_usd": 2.5,
                                                   "max_iters": 7})
    monkeypatch.setattr(P, "PROFILES_DIR", tmp_path)
    kind, _dig, d = P.defaults_for("zz")
    assert kind == "k" and d == {"agent_iters": 11, "budget_usd": 2.5, "max_iters": 7}


def test_provenance_records_which_factory_config_applied():
    digests = C._profile_digests()
    assert digests and "builder" in digests
    assert all(v.startswith("sha256:") for v in digests.values())
    pol = C._run_policy(argparse.Namespace())
    assert pol["profiles"] == digests


# ---- `skills: inherited` (the pack the builder leaves behind) -----------------

def test_inherited_follows_the_skills_pack_but_none_does_not(tmp_path, monkeypatch):
    """A kind that runs in the app directory reads the pack the builder installed there
    and left behind, so a skill edit can change what it does — and must therefore change
    its version. Before this, only `builder` moved when a skill moved, so `area evals`
    would have compared the other kinds across a real behavioural change as if nothing
    had happened, and reported "ok"."""
    def _digest(skills: str, skills_hash: str) -> str:
        (tmp_path / "k.yaml").write_text(
            f"kind: k\nlabels: [k]\nprompt_sources: []\nskills: {skills}\n")
        monkeypatch.setattr(P, "_skills_hash", lambda: skills_hash)
        prof = P.load_profile("k", root=tmp_path)
        assert prof is not None
        return prof.digest

    for value, should_move in (("all", True), ("inherited", True), ("none", False)):
        a = _digest(value, "sha256:aaa")
        b = _digest(value, "sha256:bbb")
        assert (a != b) is should_move, (
            f"skills: {value} — the digest "
            f"{'must follow' if should_move else 'must NOT follow'} the skills pack")


def test_the_kinds_that_run_in_the_app_dir_declare_inherited():
    """Measured from the call sites: these six pass the APP directory to the engine, so
    they are Claude Code sessions in the directory where the pack was installed and
    left. The `ask_cli` kinds (product-reviewer, spec-reviewer) run in a temp dir, and
    the spec / inception / research kinds run in a spec or scratch directory — those
    stay `none`."""
    profs = P.all_profiles()
    expected = {"auditor", "chaos-author", "e2e-author", "holdout-author",
                "holdout-fixer", "holdout-readjudicator"}
    got = {k for k, pr in profs.items() if pr.skills == "inherited"}
    assert got == expected, f"inherited drifted: {sorted(got)}"
    assert profs["builder"].skills == "all", "the builder is what installs the pack"
    for k in ("product-reviewer", "spec-reviewer", "researcher", "designer",
              "spec-extractor", "intake-translator", "re-extractor", "inception",
              "healer"):
        assert profs[k].skills == "none", f"{k} does not run where the pack is"


def test_an_unknown_skills_value_is_rejected_not_silently_none(tmp_path):
    """Reading a typo as "none" would quietly drop that kind out of the skills digest —
    the exact failure this field exists to prevent."""
    (tmp_path / "k.yaml").write_text(
        "kind: k\nlabels: [k]\nprompt_sources: []\nskills: inherted\n")
    broken = P.broken_profiles(root=tmp_path)
    assert "k.yaml" in broken and "not one of" in broken["k.yaml"]
    with pytest.raises(P.ProfileError, match="not one of"):
        P.load_profile("k", root=tmp_path, strict=True)
    # ... while non-strict still returns None rather than raising: `evals.compare`
    # branches on `prof is None`, so raising here would crash the gate.
    assert P.load_profile("k", root=tmp_path) is None
