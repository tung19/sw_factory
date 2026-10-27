"""area.verify.audit — the tier-1 (BLOCKING) hardcoded-secret scan. Exercises the
exact `_SECRET_RE` / `_SECRET_EXCLUDE` regexes the audit script uses (single source)
through the same grep pipeline, so the fix for the spaced-`=` miss + the
over-broad import/from exclusion is pinned."""
import subprocess

from area.verify.audit import _SECRET_EXCLUDE, _SECRET_RE

_SECRET = "sk_live_abcdef0123456789XYZ"  # 24 chars, matches the {16,} value tail


def _scan(tmp_path, line: str) -> bool:
    """Run the audit's secrets pipeline over one line in app/x.ts; True if flagged."""
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / "x.ts").write_text(line + "\n")
    cmd = (f'grep -rnEi "{_SECRET_RE}" app 2>/dev/null '
           f'| grep -viE "{_SECRET_EXCLUDE}"')
    p = subprocess.run(["bash", "-lc", cmd], cwd=str(tmp_path),
                       capture_output=True, text=True)
    return bool(p.stdout.strip())


def test_detects_spaced_equals(tmp_path):
    # the regression: a space before `=` (Prettier/standard style) used to slip past
    assert _scan(tmp_path, f'const apiKey = "{_SECRET}"') is True


def test_detects_tight_equals_and_colon(tmp_path):
    assert _scan(tmp_path, f'const apiKey="{_SECRET}"') is True
    assert _scan(tmp_path, f'api_key: "{_SECRET}"') is True


def test_does_not_drop_line_mentioning_from(tmp_path):
    # the other regression: the old `from `/`import ` substring exclusion dropped
    # real hits on any line merely containing those words
    assert _scan(tmp_path, f'const apiKey = "{_SECRET}"; // rotated from vault') is True


def test_excludes_env_lookup_and_public(tmp_path):
    assert _scan(tmp_path, 'const k = process.env.API_KEY') is False
    assert _scan(tmp_path, f'const k = "{_SECRET}" // NEXT_PUBLIC_SAFE') is False


def test_excludes_obvious_placeholders(tmp_path):
    assert _scan(tmp_path, 'const apiKey = "your-api-key-goes-here-xxxx"') is False
    assert _scan(tmp_path, 'password = "changeme-please-rotate-now"') is False


def test_import_statement_not_flagged(tmp_path):
    # an import/from statement can't match the keyword<sep>16+value shape anyway
    assert _scan(tmp_path, 'import { apiKey } from "./config/secrets-helper-long"') is False
