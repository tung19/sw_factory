"""The four shapes `area/screen.py` shipped broken — now its corpus.

Each case was reproduced against the shipped module during the 2026-10-27 self-audit:
all four returned findings and/or output that left the credential live. They are the
NORMAL shapes in a bundled reference app, i.e. exactly the Flow B input this module
exists to screen, so they belong in the test suite and not in a report.

Rule for every case: `redact_text` must both REPORT the hit and leave no copy of the
secret in the returned text.
"""
import area.screen as S

GH = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
SLACK = "xoxb-" + "123456789012-" + "abcdefghijKLMNOPqrstuvwx"
PW = "Pr0dPassw0rd"


def _redacted(text: str):
    new, findings = S.redact_text(text)
    return new, findings


def test_bundled_one_liner_is_not_excused_by_a_distant_env_lookup():
    """A bundled file is frequently ONE line. Line-scope exclusion meant a single
    `process.env` anywhere in it disabled screening for the entire file."""
    src = ('var a=1;const cfg={base:process.env.NEXT_PUBLIC_API_URL};'
           f'var t="{GH}";var s="{SLACK}";export{{a}};')
    new, findings = _redacted(src)
    assert len(findings) >= 2, findings
    assert GH not in new and SLACK not in new
    assert S.REDACTION in new


def test_the_marker_is_attacker_supplied_text_and_cannot_switch_screening_off():
    """`AREA-REDACTED` used to be an exclusion, so planting it in an input turned the
    screener off for that file."""
    src = f'// {S.REDACTION}\nconst token = "{GH}"\n'
    new, findings = _redacted(src)
    assert findings and GH not in new


def test_redacting_the_first_secret_does_not_excuse_the_second():
    """Same root cause: after the first substitution the line contained the marker,
    which then excluded every later hit on it."""
    src = f'const a = "{GH}", b = "{SLACK}"\n'
    new, findings = _redacted(src)
    assert len(findings) >= 2, findings
    assert GH not in new and SLACK not in new


def test_a_literal_fallback_credential_beside_an_env_lookup_is_still_a_credential():
    """`process.env.X || "<literal>"` — the env lookup explains the FIRST operand, not
    the hardcoded fallback."""
    src = f'const url = process.env.DATABASE_URL || "postgres://admin:{PW}@db.internal:5432/app"\n'
    new, findings = _redacted(src)
    assert findings, "the fallback connection string must be reported"
    assert PW not in new
    assert "postgres://admin:" in new  # structure kept, only the value replaced


# --- the exclusions that must SURVIVE the fix ---------------------------------

def test_env_sourced_assignment_is_still_not_a_finding():
    assert not S.scan_text('const apiKey = process.env.ANTHROPIC_API_KEY\n')
    assert not S.scan_text('api_key: os.environ["SOME_LONG_VAR_NAME"]\n')


def test_public_keys_and_placeholders_are_still_not_findings():
    assert not S.scan_text('const k = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY\n')
    assert not S.scan_text('password = "changeme-please-now-1234"\n')
    assert not S.scan_text('AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n')
    assert not S.scan_text('const privateKeyPath = "./certs/server.key"\n')


def test_redaction_is_still_idempotent():
    """Idempotence now comes from the value WE wrote ("redacted"), not from the input
    mentioning a marker."""
    once, f1 = _redacted(f'const token = "{GH}"\napi_key = "{SLACK}"\n')
    twice, f2 = _redacted(once)
    assert f1 and not f2
    assert twice == once


def test_the_grep_pattern_trap_is_still_pinned():
    """area.verify.audit._SECRET_RE is written for grep (POSIX `[[:space:]]`); Python
    re accepts it and means something else. screen.py must not share it."""
    from area.verify import audit

    assert "[[:space:]]" in audit._SECRET_RE
    assert "[[:space:]]" not in S._ASSIGNMENT.pattern


# --- the false-positive calibration (measured, not guessed) -------------------

def test_js_identifiers_are_not_credentials():
    """Screening 100 real files from a built app produced 15 findings and every single
    one was an unquoted JS expression. Redaction REWRITES the copy the agent reads, so
    each of those would have silently corrupted third-party source. The same 100 files
    now produce 1 (a PascalCase schema name), and `scan_tree` skips `node_modules`
    anyway, where it lives."""
    for src in ('const token = creditTokenParam\n',
                'privateKey: r.ECPrivateKey.decode\n',
                'Secret = sessionsTokenFromSecret\n',
                'token: details.fallback_credit_token\n',
                'PrivateKey=T.subjectPublicKey\n'):
        assert not S.scan_text(src), src


def test_a_quoted_literal_is_never_excused_as_code():
    """The exclusion is for UNQUOTED values only — quoting makes it a literal."""
    assert S.scan_text('const token = "creditTokenParam"\n')
    # and these real-secret shapes must survive the exclusion unquoted
    assert S.scan_text('password=hunter2hunter2hunter\n')
    assert S.scan_text(f'PASSWORD={PW}aaaaaaaa\n')
    assert S.scan_text('API_KEY=sk_live_abc123def456ghi\n')


def test_b2_quoted_values_with_punctuation_are_caught():
    """B2 (deep audit 2026-10-28): the assignment value class excluded punctuation, so a
    quoted password with special chars after a recognized key was never matched."""
    assert S.scan_text('password = "Str0ng!P@ss#2024"\n')
    assert S.scan_text('api_key="abc:defghijklmnop1234"\n')
    new, finds = S.redact_text('password = "Str0ng!P@ss#2024"\n')
    assert finds and "Str0ng!P@ss#2024" not in new and "password" in new


def test_b3_db_url_password_not_excused_by_a_contained_placeholder():
    """B3 (deep audit 2026-10-28): a connection password is human-chosen, so merely
    CONTAINING a placeholder word must not excuse it; only a bare placeholder is docs."""
    assert S.scan_text('DB="postgres://u:Todo1234passxyz@host:5432/app"\n')
    assert S.scan_text('DB="postgres://u:sampleRealPassword9@host/app"\n')
    assert not S.scan_text('DB="postgres://u:changeme@host/app"\n')
