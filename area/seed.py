"""area.seed — P4 of `area adapt`: OPT-IN seeding of the clone with data from the
reference app, behind an explicit authorization attestation + the safeguards agreed
in the feature spec (public-only, robots.txt, rate-limit, no-PII by default,
provenance). DEFAULT OFF.

AREA does NOT rule on legality — it surfaces the checklist and refuses to seed
unless the operator attests they have the right (their own app / public + permitted
data). This module owns the deterministic SAFEGUARDS: the attestation gate, a
minimal robots.txt check, PII stripping, the record cap, and the provenance record.
Fetching the candidate records is upstream (agent/http, untrusted) and passed in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Field names treated as PII and dropped unless the operator opts into including it.
_PII_FIELDS = {
    "email", "e_mail", "phone", "phone_number", "mobile", "ssn", "password",
    "pwd", "name", "full_name", "first_name", "last_name", "dob", "birthdate",
    "address", "street", "credit_card", "card_number", "cvv", "ip", "ip_address",
}


@dataclass
class SeedPolicy:
    attested: bool = False          # operator confirmed they have the right to seed
    max_records: int = 100
    include_pii: bool = False
    user_agent: str = "area-adapt-seed"
    rate_limit_s: float = 1.0


@dataclass
class SeedResult:
    source: str
    attested: bool
    seeded: int = 0
    skipped_pii_fields: int = 0
    records: list[dict[str, Any]] = field(default_factory=list)
    blocked_reason: str = ""

    @property
    def ok(self) -> bool:
        return not self.blocked_reason


def seed_allowed(policy: SeedPolicy) -> tuple[bool, str]:
    """Seeding is opt-in: it runs ONLY with an explicit authorization attestation."""
    if not policy.attested:
        return False, ("seed-from-reference is opt-in and requires an explicit "
                       "authorization attestation (you confirm you have the right "
                       "to copy this data)")
    return True, ""


def robots_allows(robots_txt: str, path: str, *, user_agent: str = "*") -> bool:
    """Minimal robots.txt check: honor the matching User-agent group (specific name
    else `*`), longest-matching Allow/Disallow wins. No matching rule → allowed; an
    empty `Disallow:` → allowed."""
    groups: dict[str, list[tuple[str, str]]] = {}
    cur: list[tuple[str, str]] | None = None
    for raw in robots_txt.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip().lower(), v.strip()
        if k == "user-agent":
            cur = groups.setdefault(v.lower(), [])
        elif k in ("disallow", "allow") and cur is not None:
            cur.append((k, v))
    rules = groups.get(user_agent.lower()) or groups.get("*") or []
    best: tuple[int, bool] | None = None   # (match length, allowed)
    for typ, val in rules:
        if val and path.startswith(val) and (best is None or len(val) > best[0]):
            best = (len(val), typ == "allow")
    return True if best is None else best[1]


def is_pii_field(name: str) -> bool:
    return name.strip().lower() in _PII_FIELDS


def strip_pii(record: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Drop PII fields; return (clean record, #dropped)."""
    clean = {k: v for k, v in record.items() if not is_pii_field(k)}
    return clean, len(record) - len(clean)


def seed_from_reference(
    reference: str, candidate_records: list[dict[str, Any]], policy: SeedPolicy, *,
    robots_txt: str | None = None, path: str = "/",
) -> SeedResult:
    """Apply the safeguards to already-fetched candidate records. BLOCKS (seeds
    nothing) unless attested; honors robots.txt when given; strips PII unless
    `include_pii`; caps at `max_records`. The caller writes `result.records` into
    the clone and records provenance."""
    ok, why = seed_allowed(policy)
    if not ok:
        return SeedResult(source=reference, attested=False, blocked_reason=why)
    if robots_txt is not None and not robots_allows(robots_txt, path,
                                                    user_agent=policy.user_agent):
        return SeedResult(source=reference, attested=True,
                          blocked_reason=f"robots.txt disallows {path}")
    out: list[dict[str, Any]] = []
    skipped = 0
    for rec in candidate_records[:policy.max_records]:
        if policy.include_pii:
            out.append(rec)
        else:
            clean, dropped = strip_pii(rec)
            skipped += dropped
            out.append(clean)
    return SeedResult(source=reference, attested=True, seeded=len(out),
                      skipped_pii_fields=skipped, records=out)
