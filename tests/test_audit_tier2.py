"""Two-tier `area audit`: tier-1 deterministic severity threshold + tier-2
advisory risky-pattern scan. Pure helpers — the live tsc/npm-audit/agent path
needs a built app, so it is not run here."""
import area.verify.audit as A


def test_advisory_scan_flags_risky_patterns(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "page.tsx").write_text(
        "const html = userInput;\n"
        "export default () => <div dangerouslySetInnerHTML={{__html: html}} />;\n"
    )
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "danger.ts").write_text(
        "export function run(s: string){ return eval(s); }\n"
        "import { exec } from 'child_process';\n"
        "const token = Math.random();\n"
        "const q = `SELECT * FROM users WHERE id = ${id}`;\n"
    )
    found = A.advisory_scan(tmp_path)
    msgs = " | ".join(m for _, _, m in found)
    assert "dangerouslySetInnerHTML" in msgs
    assert "eval()" in msgs
    assert "command-injection" in msgs
    assert "cryptographically" in msgs
    assert "injection risk" in msgs  # SQL interpolation
    # each finding carries (relpath, line, message)
    assert all(isinstance(r, str) and isinstance(ln, int) for r, ln, _ in found)


def test_advisory_scan_clean_app_has_no_findings(tmp_path):
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "tip.ts").write_text(
        "export const calc = (b: number, p: number) => Math.round(b*p)/100;\n"
    )
    assert A.advisory_scan(tmp_path) == []


def test_advisory_scan_ignores_node_modules_and_nonsource(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "page.tsx").write_text("export default () => null;")
    (tmp_path / "app" / "notes.md").write_text("we use eval() in docs")  # non-source ext
    nm = tmp_path / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / "i.js").write_text("eval(x)")  # dependency source — not ours
    assert A.advisory_scan(tmp_path) == []


def test_check_embeds_severity_level():
    assert "--audit-level=critical" in A._check("critical")
    assert "--audit-level=moderate" in A._check("moderate")


def test_check_clamps_invalid_level_to_high():
    assert "--audit-level=high" in A._check("bogus")
