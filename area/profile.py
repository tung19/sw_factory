"""area.profile — one versioned artifact per kind of agent AREA runs.

An agent run's configuration used to come from seven places (CLI flags, env, agent
construction, a prompt literal in whichever module owned the stage, the skills copy,
memory injection, ad-hoc MCP config). Nothing tied a RESULT to the configuration that
produced it, so the factory's own improvements were ungraded: edit a prompt and no
measurement told you whether it helped. That is the one thing AREA's spine forbids —
the same reasoning writing and grading — applied to AREA itself.

A profile is the reference architecture's unit of factory config: "a single versioned
artifact ... [that] gives the outer loop one thing to improve, evaluate, and roll back"
(The Secure Software Factory, p.20). Here it holds ONLY what it genuinely controls or
identifies, so it cannot drift into decoration:

  labels          the obs label globs this kind owns (how a run is attributed)
  prompt_sources  dotted names whose SOURCE is hashed into the digest
  defaults        agent_iters / budget_usd / max_iters — applied when the caller
                  passes nothing; a CLI flag always wins
  skills          whether the skills pack is installed for this kind

THE DIGEST is the point. It covers the YAML, the hashed source of every prompt symbol,
and (when skills are installed) the skills pack — so editing a prompt, a skill or a
knob produces a NEW version, and `area evals` can compare the new version's measured
runs against the previous one's. Prompts stay in Python: they are interpolated
f-strings with real branching, and rewriting them as templates would be a large,
lossy change for no measurement benefit — hashing their source gets the same
attribution.

NOT in scope here (deliberately, so the artifact stays honest about what it does):
per-kind model selection (model tiering, PLAN §10 P5), tools/MCP and memory injection.
Those still come from the call sites; see docs/secure-factory-gap-assessment.md.
"""
from __future__ import annotations

import fnmatch
import hashlib
import importlib
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from area.paths import REPO

PROFILES_DIR = REPO / "profiles"


@dataclass(frozen=True)
class Profile:
    kind: str
    description: str = ""
    labels: tuple[str, ...] = ()
    prompt_sources: tuple[str, ...] = ()
    skills: str = "none"              # "all" | "none"
    notes: str = ""
    agent_iters: Optional[int] = None
    budget_usd: Optional[float] = None
    max_iters: Optional[int] = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def digest(self) -> str:
        return profile_digest(self)

    def owns(self, label: str) -> bool:
        return any(fnmatch.fnmatchcase(label, pat) for pat in self.labels)


def _source_hash(dotted: str) -> str:
    """Hash the SOURCE of a prompt symbol — a function's text, or a constant's value.

    Best-effort by design: an unresolvable name hashes as "<missing>" rather than
    raising, so a renamed symbol changes the digest (correct: the prompt changed) and
    never breaks a build. `area evals --check` reports missing sources separately."""
    mod_name, _, attr = dotted.rpartition(".")
    if not mod_name:
        return f"{dotted}=<malformed>"
    try:
        obj = getattr(importlib.import_module(mod_name), attr)
    except Exception:  # noqa: BLE001
        return f"{dotted}=<missing>"
    try:
        text = inspect.getsource(obj)  # functions / classes
    except (TypeError, OSError):
        text = repr(obj)               # module-level string constants
    return f"{dotted}={hashlib.sha256(text.encode()).hexdigest()}"


def missing_prompt_sources(p: Profile) -> list[str]:
    """Prompt symbols the profile names but that no longer resolve — i.e. the profile
    has drifted from the code it claims to describe."""
    return [d for d in p.prompt_sources if _source_hash(d).endswith("=<missing>")]


def _skills_hash() -> str:
    try:
        from area.provenance import skills_digest

        return skills_digest() or "none"
    except Exception:  # noqa: BLE001
        return "unknown"


def profile_digest(p: Profile) -> str:
    """sha256 over the declared config + the hashed source of each prompt + the skills
    pack. Editing any of them is a new version."""
    h = hashlib.sha256()
    h.update(yaml.safe_dump(p.raw, sort_keys=True).encode())
    for dotted in sorted(p.prompt_sources):
        h.update(_source_hash(dotted).encode())
        h.update(b"\0")
    if p.skills == "all":
        h.update(_skills_hash().encode())
    return "sha256:" + h.hexdigest()[:32]


def _from_raw(kind: str, raw: dict[str, Any]) -> Profile:
    d = raw.get("defaults") or {}
    return Profile(
        kind=kind,
        description=str(raw.get("description") or "").strip(),
        labels=tuple(raw.get("labels") or ()),
        prompt_sources=tuple(raw.get("prompt_sources") or ()),
        skills=str(raw.get("skills") or "none"),
        notes=str(raw.get("notes") or "").strip(),
        agent_iters=d.get("agent_iters"),
        budget_usd=d.get("budget_usd"),
        max_iters=d.get("max_iters"),
        raw=raw,
    )


class ProfileError(Exception):
    """A profile file exists but is unusable. Raised by `load_profile(strict=True)`
    and surfaced by `area evals --check`, because a silently-unloadable profile stops
    attributing runs with no signal at all — found exactly that way, when one bad
    indent left `inception:*` runs unattributed and the count simply read 15 of 16."""


def load_profile(kind: str, *, root: Optional[Path] = None,
                 strict: bool = False) -> Optional[Profile]:
    p = (root or PROFILES_DIR) / f"{kind}.yaml"
    if not p.is_file():
        if strict:
            raise ProfileError(f"{p}: no such profile")
        return None
    try:
        raw = yaml.safe_load(p.read_text()) or {}
    except (OSError, yaml.YAMLError) as e:
        if strict:
            raise ProfileError(f"{p}: {type(e).__name__}: {e}") from e
        return None
    if not isinstance(raw, dict):
        if strict:
            raise ProfileError(f"{p}: top level must be a mapping")
        return None
    return _from_raw(raw.get("kind") or kind, raw)


def broken_profiles(*, root: Optional[Path] = None) -> dict[str, str]:
    """{filename: why} for every profile file that cannot be loaded."""
    base = root or PROFILES_DIR
    out: dict[str, str] = {}
    if not base.is_dir():
        return out
    for f in sorted(base.glob("*.yaml")):
        try:
            load_profile(f.stem, root=base, strict=True)
        except ProfileError as e:
            out[f.name] = str(e)
    return out


def all_profiles(*, root: Optional[Path] = None) -> dict[str, Profile]:
    base = root or PROFILES_DIR
    out: dict[str, Profile] = {}
    if not base.is_dir():
        return out
    for f in sorted(base.glob("*.yaml")):
        p = load_profile(f.stem, root=base)
        if p is not None:
            out[p.kind] = p
    return out


def for_label(label: str, *, root: Optional[Path] = None) -> Optional[Profile]:
    """The profile that owns this obs label. Longest matching glob wins, so
    `holdout:author*` beats a broader `holdout:*`."""
    best: Optional[Profile] = None
    best_len = -1
    for p in all_profiles(root=root).values():
        for pat in p.labels:
            if fnmatch.fnmatchcase(label, pat) and len(pat) > best_len:
                best, best_len = p, len(pat)
    return best


def defaults_for(label: str, *, root: Optional[Path] = None,
                 ) -> tuple[Optional[str], Optional[str], dict[str, Any]]:
    """(kind, digest, defaults) for a label — what the adapter needs to stamp a run
    and fill in unspecified knobs. Never raises: no profile just means no attribution."""
    try:
        p = for_label(label, root=root)
    except Exception:  # noqa: BLE001
        return None, None, {}
    if p is None:
        return None, None, {}
    try:
        dig = p.digest
    except Exception:  # noqa: BLE001
        dig = None
    return p.kind, dig, {
        "agent_iters": p.agent_iters,
        "budget_usd": p.budget_usd,
        "max_iters": p.max_iters,
    }
