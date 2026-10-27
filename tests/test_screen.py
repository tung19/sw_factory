"""area.screen — keep credentials out of what the agent reads (group 3 / item 8).

Pure logic: regexes and file copies on a fake tree. No agent, no network, no npm.
"""
import re
import subprocess

import pytest

from area import screen as S
from area.verify.audit import _SECRET_EXCLUDE, _SECRET_RE

# ---- the shared corpus -----------------------------------------------------------
# One source of truth for "this is the assignment shape". Asserted against BOTH the
# Python screener and the grep pattern the audit gate uses, so the two cannot drift.
MUST_MATCH_ASSIGNMENT = (
    'const apiKey = "sk_live_aaaaaaaaaaaaaaaaaaaa";',
    "API_KEY=AbCdEf0123456789AbCdEf",
    'password: "hunter2hunter2hunter2"',
    "access_token = 'ya29.AAAAAAAAAAAAAAAAAAAAAAAA'",
    'client_secret: "0123456789abcdef0123456789abcdef"',
)
MUST_NOT_MATCH = (
    'const apiKey = process.env.API_KEY;',
    'const key = "short";',
    'password: "changeme"',
    'apiKey: "your_api_key_here_please_set"',
    'const token = "<YOUR_TOKEN_HERE_GOES_RIGHT>"',
    'NEXT_PUBLIC_API_KEY = "pk_public_0123456789abcdef"',
)


@pytest.mark.parametrize("line", MUST_MATCH_ASSIGNMENT)
def test_python_screener_catches_the_assignment_corpus(line):
    assert S.scan_text(line), f"missed: {line}"


@pytest.mark.parametrize("line", MUST_NOT_MATCH)
def test_python_screener_ignores_env_lookups_and_placeholders(line):
    assert S.scan_text(line) == [], f"false positive: {line}"


@pytest.mark.parametrize("line", MUST_MATCH_ASSIGNMENT)
def test_grep_pattern_agrees_on_the_same_corpus(line, tmp_path):
    """The audit gate's tier-1 scan must still catch what the screener catches, so a
    secret can't pass one and fail the other.

    Invoked exactly as area/verify/audit.py does it — `grep -nEi` piped through
    `grep -viE <exclude>`. The `-i` matters: without it `apiKey` and `API_KEY` both
    slip past, which is most of the real corpus."""
    f = tmp_path / "x.ts"
    f.write_text(line)
    hit = subprocess.run(["grep", "-nEi", _SECRET_RE, str(f)],
                         capture_output=True, text=True)
    assert hit.returncode == 0, f"audit grep pattern missed: {line}"
    kept = subprocess.run(["grep", "-viE", _SECRET_EXCLUDE],
                          input=hit.stdout, capture_output=True, text=True)
    assert kept.returncode == 0, f"audit exclude filter dropped a real hit: {line}"


def test_the_grep_pattern_is_not_reusable_as_a_python_regex():
    """THE TRAP this module exists to avoid. `_SECRET_RE` contains the POSIX class
    `[[:space:]]`, which Python's `re` accepts silently and reads as "one of the
    characters [ : s p a c e". It does not error — it just matches the wrong thing, so
    a screener built by reusing the string would look fine and protect nothing."""
    # Python itself warns about it — "possible nested set" is the interpreter telling
    # you `[[:space:]]` is being read as a character class of `[ : s p a c e`.
    with pytest.warns(FutureWarning, match="nested set"):
        py = re.compile(_SECRET_RE, re.IGNORECASE)
    # the spaced form the audit comment says was the whole point of `[[:space:]]`
    spaced = 'const apiKey = "AbCdEf0123456789AbCdEf";'
    assert py.search(spaced) is None, (
        "if this now matches, Python gained POSIX class support and area/screen.py's "
        "warning should be revisited")
    # and the screener does handle it
    assert S.scan_text(spaced)


# ---- vendor tokens (no key name needed — the PocketOS shape) ---------------------
@pytest.mark.parametrize("kind,sample", [
    ("aws-access-key-id", "AKIAJ7QZ2WB3KLMNOPQR"),
    ("github-token", "ghp_" + "a" * 36),
    ("slack-token", "xoxb-123456789012-abcdefghijkl"),
    ("stripe-secret-key", "sk_live_" + "a" * 24),
    ("google-api-key", "AIza" + "b" * 35),
    ("anthropic-api-key", "sk-ant-" + "c" * 30),
    ("jwt", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27u"),
])
def test_vendor_tokens_are_found_without_a_key_name(kind, sample):
    found = S.scan_text(f"// leftover\n{sample}\n")
    assert any(f.kind == kind for f in found), f"{kind} missed in {found}"


def test_private_key_block_and_db_url_password():
    pem = ("-----BEGIN RSA PRIVATE KEY-----\nAAAABBBBCCCC\n"
           "-----END RSA PRIVATE KEY-----")
    assert any(f.kind == "private-key-block" for f in S.scan_text(pem))
    url = 'DB="postgres://admin:s3cr3tp4ss@db.example.com:5432/app"'
    assert any(f.kind == "db-url-password" for f in S.scan_text(url))
    redacted, _ = S.redact_text(url)
    assert "s3cr3tp4ss" not in redacted
    # structure survives: host, port, db and the user are all still there
    assert "postgres://admin:" in redacted and "db.example.com:5432/app" in redacted


# ---- redaction behaviour ---------------------------------------------------------
def test_redaction_keeps_structure_and_never_leaks_the_value():
    src = 'export const config = {\n  apiKey: "AbCdEf0123456789AbCdEf",\n  port: 3000,\n};'
    out, findings = S.redact_text(src)
    assert findings and "AbCdEf0123456789AbCdEf" not in out
    assert "apiKey:" in out and "port: 3000" in out  # shape preserved
    assert S.REDACTION in out
    assert out.count("\n") == src.count("\n")  # line numbers stay valid


def test_redaction_is_idempotent():
    once, _ = S.redact_text('apiKey = "AbCdEf0123456789AbCdEf"')
    twice, findings = S.redact_text(once)
    assert twice == once and findings == []


def test_findings_never_carry_the_secret_value():
    """A report is printed and logged, so it must be safe by construction."""
    secret = "AbCdEf0123456789AbCdEf"
    for f in S.scan_text(f'apiKey = "{secret}"'):
        assert secret not in f.kind and secret not in f.hint


def test_a_path_value_is_not_mistaken_for_a_secret():
    """Regression guard for the false positive that would silently break a clone:
    `privateKeyPath` + a long path matches the assignment shape."""
    for line in ('const privateKeyPath = "./certs/server.key";',
                 'private_key_file = "/etc/ssl/private/app.pem"',
                 'secretsDir: "../config/secrets/local.json"'):
        assert S.scan_text(line) == [], f"false positive: {line}"


# ---- file + tree level -----------------------------------------------------------
def test_redact_file_writes_a_clean_copy(tmp_path):
    src = tmp_path / "in.ts"
    dst = tmp_path / "out" / "in.ts"
    src.write_text('const t = "ghp_' + "z" * 36 + '";')
    findings = S.redact_file(src, dst)
    assert findings and S.REDACTION in dst.read_text()
    assert "ghp_" not in dst.read_text()
    assert "ghp_" in src.read_text()  # the source is untouched


def test_redact_file_copies_binary_and_oversized_verbatim(tmp_path):
    binf = tmp_path / "logo.png"
    binf.write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe" + b"\x00" * 32)
    out = tmp_path / "o" / "logo.png"
    assert S.redact_file(binf, out) == []
    assert out.read_bytes() == binf.read_bytes()

    big = tmp_path / "big.txt"
    big.write_text("x" * (S.MAX_SCAN_BYTES + 1))
    obig = tmp_path / "o" / "big.txt"
    assert [f.kind for f in S.redact_file(big, obig)] == ["unscanned-large"]
    assert obig.read_text() == big.read_text()


def test_scan_tree_reports_without_modifying(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    leak = tmp_path / "app" / "cfg.ts"
    leak.write_text('// note\nconst secret = "AbCdEf0123456789AbCdEf";')
    (tmp_path / "node_modules" / "pkg" / "junk.ts").write_text(
        'const secret = "AbCdEf0123456789AbCdEf";')
    before = leak.read_bytes()

    hits = S.scan_tree(tmp_path)
    assert [p for p, _ in hits] == ["app/cfg.ts"]  # node_modules skipped
    assert hits[0][1].line == 2
    assert leak.read_bytes() == before  # evidence stays byte-exact


def test_format_report_is_loud_and_value_free():
    hits = S.scan_tree_result = [("a/b.ts", S.Finding("assigned-secret", 3, "api_key"))]
    txt = S.format_report(hits, what="_sample/")
    assert "1 hit" in txt and "a/b.ts:3" in txt and "api_key" in txt
    assert "clean" in S.format_report([], what="_sample/")
