"""area.screen — keep credentials out of what the agent reads.

AREA's audit gate scans the app it BUILT for hardcoded secrets. Nothing scanned what
came IN. Flow B copies an untrusted reference repo into `_ui/` and then into the app,
uploads land as text the agent reads, and research output is fed forward — so a token
sitting in an unrelated file travels straight into the agent's context. That is the
PocketOS shape: an agent found a Railway token in a file created for something else and
deleted the production database with it. The reference architecture asks for exactly
this control: "source code, task data, and responses are screened for embedded
credentials and removing them before they cross" (Secure Software Factory, p.7).

POSTURE: redact the COPY, never the evidence. `workspace/specs/<name>/_sample/` stays
byte-exact (it is what the clone was reverse-engineered from, and provenance depends on
it); the derived copies that reach the agent get the secret VALUE replaced. Every
redaction is reported, because a false positive quietly corrupting a clone is worse than
a loud one — callers print the report.

Leaf module on purpose: stdlib only, imports nothing from `area`, so the capture and
upload paths can use it without pulling in the engine (same reasoning as
`area.ui_tokens`).

!! DO NOT reuse `area.verify.audit._SECRET_RE` here. That pattern is written for **grep**
and contains the POSIX class `[[:space:]]`. Python's `re` accepts it silently and reads
it as "one of the characters [ : s p a c e", so a screener built on it would compile,
run, and match the wrong thing without ever erroring. `tests/test_screen.py` pins that
trap so nobody "simplifies" by sharing the string.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

# Files bigger than this are copied unscanned — a screener must not read a 200MB blob
# into memory. Recorded as a finding of kind "unscanned-large" so the skip is visible.
MAX_SCAN_BYTES = 2 * 1024 * 1024

REDACTION = "AREA-REDACTED"


@dataclass(frozen=True)
class Finding:
    """One credential-shaped hit. `hint` is the key name or pattern label — NEVER the
    matched value, so a report can be printed and logged safely."""

    kind: str
    line: int
    hint: str


# --- patterns ------------------------------------------------------------------------
# Group 1 of each pattern (when present) is the part to redact; patterns without a
# group are redacted whole.

_ASSIGNMENT = re.compile(
    r"""(?P<key>api[_-]?key|secret[_a-z]*|password|passwd|access[_-]?token|auth[_-]?token
        |client[_-]?secret|private[_-]?key|token)
        \s*["']?\s*[:=]\s*
        (?:
            (?P<q>["'])(?P<val>[^"'\n]{8,})["']?       # quoted literal: punctuation allowed (B2)
          | (?P<val2>[A-Za-z0-9/+_.=~-]{16,})           # unquoted: strict class (JS-code guarded)
        )""",
    re.IGNORECASE | re.VERBOSE,
)

# High-signal vendor tokens: these need no key name, which is exactly the PocketOS case
# (a bare token sitting in a file).
_VENDOR: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws-access-key-id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("stripe-secret-key", re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("anthropic-api-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai-api-key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("private-key-block", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL)),
    # a connection string carrying a password
    ("db-url-password", re.compile(
        r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://"
        r"[^:/\s]+:(?P<val>[^@/\s]{6,})@")),
)

# Exclusions come in TWO scopes on purpose. Lumping them together (as
# area.verify.audit._SECRET_EXCLUDE does, where it only has to avoid a noisy gate
# finding) makes the screener miss real secrets: `example` anywhere on the line kills
# `postgres://admin:<real password>@db.example.com`, and `example.com` is the single
# most common host in a config file.

# STATEMENT scope — this assignment reads its value from the environment rather than
# containing one, so it is not a credential.
#
# This was once LINE scope, which was wrong in two ways that each silently disabled
# the screener, both reproduced in tests/test_screen_corpus.py:
#   · A BUNDLED file is frequently ONE line. A single `process.env` anywhere in it
#     excluded every secret in the whole file — and a bundled reference app is exactly
#     the input this module exists to screen.
#   · The marker `AREA-REDACTED` was on this list, to make screening idempotent. But
#     the marker is attacker-supplied text: planting it in a file turned screening off
#     for that file. It also meant redacting the FIRST secret on a line excluded the
#     second. Idempotence now comes from `_EXCLUDE_VALUE` ("redacted"), which looks at
#     the value we ourselves wrote, not at text an input can choose.
#
# Applied ONLY to `_ASSIGNMENT`, where "it came from the environment" is a real
# alternative reading. A vendor pattern matches a literal credential (`ghp_…`,
# `postgres://u:pw@…`); no env lookup can produce one, so nothing nearby excuses it.
_EXCLUDE_STATEMENT = re.compile(
    r"process\.env|import\.meta\.env|os\.environ|getenv|NEXT_PUBLIC",
    re.IGNORECASE,
)
# How far back a "statement" reaches. Bounded by the nearest separator so a minified
# bundle is split into statements instead of being treated as one line.
_STMT_BREAK = re.compile(r"[\n;,{}()\[\]]")
_STMT_MAX = 120
# VALUE scope — the matched value is itself a placeholder, not a credential.
_EXCLUDE_VALUE = re.compile(
    r"example|placeholder|dummy|changeme|your[_-]|sample|fixture|xxxx|redacted|todo",
    re.IGNORECASE,
)


# An UNQUOTED value that is obviously JavaScript rather than a literal. Measured, not
# guessed: screening 100 real files from a built app produced 15 findings and every one
# was this shape — `token = creditTokenParam`, `privateKey: r.ECPrivateKey.decode`,
# `Secret = sessionsTokenFromSecret`. Redaction REWRITES the copy the agent reads, so a
# false positive here silently corrupts third-party source; that is the harm this module
# is supposed to avoid. A credential literal is never a member expression, and never
# camelCase (a random secret does not have a lowercase→uppercase hump at a word break).
# A QUOTED value is a literal and is never excused by this.
_CODE_VALUE = re.compile(
    r"^[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)+$"   # member expression
    r"|^[a-z][a-zA-Z0-9_$]*[a-z][A-Z][a-zA-Z0-9_$]*$"               # camelCase identifier
)


# A value that is obviously a filesystem path, not a credential. Without this,
# `const privateKeyPath = "./certs/server.key"` reads as an assigned secret and the
# redaction would quietly break a clone's path.
_PATHISH = re.compile(r"^\.{0,2}/|^[A-Za-z]:[\\/]|/[^/\s]*\.[A-Za-z0-9]{1,5}$")


def _statement_at(s: str, pos: int) -> str:
    """The text just before `pos`, back to the nearest statement separator (newline,
    `;`, `,`, bracket) and at most `_STMT_MAX` chars. This is the neighbourhood that
    can legitimately explain a value — NOT the whole line, which in a bundled file is
    the whole file."""
    start = max(0, pos - _STMT_MAX)
    window = s[start:pos]
    m = None
    for m in _STMT_BREAK.finditer(window):
        pass  # keep the LAST separator before the match
    return window[m.end():] if m else window


def _env_sourced(s: str, pos: int, value: str) -> bool:
    """True when this assignment takes its value from the environment. Checked on the
    value itself (`x = process.env.API_KEY` captures the lookup AS the value) and on
    the statement the match sits in (`NEXT_PUBLIC_…` keys, `getenv("KEY")` forms)."""
    return (bool(_EXCLUDE_STATEMENT.search(value))
            or bool(_EXCLUDE_STATEMENT.search(_statement_at(s, pos))))


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _assigned_value(m: re.Match[str]) -> str:
    """The matched secret value: the quoted-literal group or the unquoted-strict group."""
    return m.group("val") or m.group("val2")


def _skip_assignment(s: str, m: re.Match[str]) -> bool:
    """Shared by scan and redact so the two can never disagree about a hit."""
    value = _assigned_value(m)
    return (_env_sourced(s, m.start(), value)
            or bool(_EXCLUDE_VALUE.search(value))
            or bool(_PATHISH.search(value))
            or (not m.group("q") and bool(_CODE_VALUE.match(value))))


_BARE_PLACEHOLDER = frozenset({
    "example", "placeholder", "dummy", "changeme", "sample", "fixture",
    "redacted", "todo", "xxxx",
})


def _skip_vendor(m: re.Match[str], kind: str = "") -> bool:
    """VALUE scope only — so the canonical doc placeholder `AKIAIOSFODNN7EXAMPLE` isn't
    flagged, while a real literal token is never excused by its surroundings.

    A connection-string password is HUMAN-CHOSEN, so a substring match would excuse a
    real secret that merely CONTAINS a placeholder word (`postgres://u:Todo1234pass@…`,
    finding B3). There we exclude only a value that IS a bare placeholder (`:changeme@`)."""
    val = m.groupdict().get("val") or m.group(0)
    if kind == "db-url-password":
        return val.lower() in _BARE_PLACEHOLDER
    return bool(_EXCLUDE_VALUE.search(val))


def scan_text(text: str) -> list[Finding]:
    """Credential-shaped hits in `text`. Never returns the matched value."""
    out: list[Finding] = []
    for m in _ASSIGNMENT.finditer(text):
        if _skip_assignment(text, m):
            continue
        out.append(Finding("assigned-secret", _line_of(text, m.start()),
                           m.group("key").lower()))
    for kind, pat in _VENDOR:
        for m in pat.finditer(text):
            if _skip_vendor(m, kind):
                continue
            out.append(Finding(kind, _line_of(text, m.start()), kind))
    return sorted(out, key=lambda f: (f.line, f.kind))


def redact_text(text: str) -> tuple[str, list[Finding]]:
    """Replace credential VALUES with a marker, keeping keys and structure so the file
    stays readable (and parseable) for the agent. Idempotent: the marker itself is an
    exclusion, so re-screening a redacted file finds nothing."""
    findings = scan_text(text)
    if not findings:
        return text, []

    def _sub_assignment(m: re.Match[str]) -> str:
        if _skip_assignment(m.string, m):
            return m.group(0)  # scan_text skipped it too — stay consistent
        val = _assigned_value(m)
        return m.group(0).replace(val, f"{REDACTION}:{m.group('key').lower()}")

    new = _ASSIGNMENT.sub(_sub_assignment, text)

    for kind, pat in _VENDOR:
        def _sub_vendor(m: re.Match[str], _kind: str = kind) -> str:
            if _skip_vendor(m, _kind):
                return m.group(0)
            val = m.groupdict().get("val")
            if val:  # only part of the match is the secret (e.g. a db URL password)
                return m.group(0).replace(val, f"{REDACTION}:{_kind}")
            return f"{REDACTION}:{_kind}"

        new = pat.sub(_sub_vendor, new)
    return new, findings


def redact_bytes(data: bytes) -> tuple[bytes, list[Finding]]:
    """Redact credentials in bytes already in hand (the live-URL capture path fetches
    into memory). Undecodable bytes are returned unchanged — there is nothing to redact
    textually in a PNG, and the sandbox/network boundaries are what limit a binary."""
    if len(data) > MAX_SCAN_BYTES:
        return data, [Finding("unscanned-large", 0, f"{len(data)} bytes")]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data, []
    new, findings = redact_text(text)
    return (new.encode("utf-8") if findings else data), findings


def redact_file(src: Path, dst: Path) -> list[Finding]:
    """Copy `src` to `dst`, redacting credentials on the way. Binary or oversized files
    are copied verbatim (nothing to redact textually) and reported as unscanned."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        size = src.stat().st_size
    except OSError:
        size = 0
    if size > MAX_SCAN_BYTES:
        shutil.copy2(src, dst)
        return [Finding("unscanned-large", 0, f"{size} bytes")]
    try:
        text = src.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        shutil.copy2(src, dst)
        return []
    new, findings = redact_text(text)
    dst.write_text(new, encoding="utf-8")
    return findings


def redact_tree(src: Path, dst: Path, *, skip_dirs: Optional[Iterable[str]] = None,
                ) -> list[tuple[str, Finding]]:
    """Copy the tree under `src` to `dst`, redacting credential VALUES on the way, so an
    untrusted reference can be read by the agent without handing it the secrets. `src` is
    left byte-exact (it is the evidence `_sample/` that provenance attests). Symlinks are
    skipped. Returns (relative-path, Finding) for every hit."""
    skip = set(skip_dirs or ("node_modules", ".git", ".next", "dist", "build"))
    out: list[tuple[str, Finding]] = []
    for p in sorted(src.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        rel = p.relative_to(src)
        if any(part in skip for part in rel.parts):
            continue
        for f in redact_file(p, dst / rel):
            out.append((str(rel), f))
    return out


def scan_tree(root: Path, *, skip_dirs: Optional[Iterable[str]] = None,
              ) -> list[tuple[str, Finding]]:
    """Report credential hits under `root` WITHOUT modifying anything — for evidence
    trees like `_sample/` that must stay byte-exact."""
    skip = set(skip_dirs or ("node_modules", ".git", ".next", "dist", "build"))
    out: list[tuple[str, Finding]] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in skip for part in rel.parts):
            continue
        try:
            if p.stat().st_size > MAX_SCAN_BYTES:
                continue
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for f in scan_text(text):
            out.append((rel.as_posix(), f))
    return out


def format_report(hits: list[tuple[str, Finding]], *, what: str) -> str:
    """A loud, value-free summary. Printed by callers so a false positive is visible
    instead of silently corrupting a clone."""
    if not hits:
        return f"[area] 🔎 credential screen: clean — {what}"
    lines = [f"[area] ⚠ credential screen: {len(hits)} hit(s) in {what} —"]
    for path, f in hits[:20]:
        lines.append(f"        {path}:{f.line}  {f.kind} ({f.hint})")
    if len(hits) > 20:
        lines.append(f"        … and {len(hits) - 20} more")
    return "\n".join(lines)
