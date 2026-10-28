"""M12 + M13 — two defects found by one real build, both of which cost real money.

**M12.** `expenses` provenance was written at 09:13:39; AREA's own `npm run dev`
preview then regenerated `next-env.d.ts` at 09:13:40. The attested digest
(`75f7cd5e…`) no longer matched the app (`af97d656…`) one second after it was taken,
so `area deploy` would have refused a build nothing had tampered with — fail-closed
protecting the operator from the factory. The same would happen to ANY app that
persists data, the moment a human clicked through the preview and saved a row.

The fix is the rule, not the preview: **an attestation describes an artifact, not a
moment.** Files the toolchain generates and files the running app writes are not
authored source, so they are out of the digest. Every authored file is still in it.

**M13.** `assert_locked_files_ran` required every locked `.ts` file to appear in the
runner's report — including a holdout author's shared helper (`_source-scan.ts`) that
registers no tests. Satisfying that cost a real build an entire extra attempt. It was
the first lesson the experience store ever harvested, which is also the evidence that
F1b works: the memory mechanism found a defect in the factory.
"""
import json

from area.provenance import artifact_digest, write_provenance
from area.verify._runners import assert_locked_files_ran

_TEST = "import { it, expect } from 'vitest'\nit('AC-1', () => expect(1).toBe(1))\n"
_HELPER = "export const PROJECT_ROOT = process.cwd()\nexport function scan() { return [] }\n"


def _app(tmp_path):
    app = tmp_path / "apps" / "a"
    (app / "app").mkdir(parents=True)
    (app / "app" / "page.tsx").write_text("export default function P() { return null }\n")
    (app / "package.json").write_text('{"name":"a"}')
    return app


# ---- M12: the digest must survive the toolchain and the user ------------------

def test_a_regenerated_next_env_does_not_invalidate_the_attestation(tmp_path):
    """The exact file, from the exact incident."""
    app = _app(tmp_path)
    before = artifact_digest(app)
    (app / "next-env.d.ts").write_text(
        "/// <reference types=\"next\" />\n"
        "// see https://nextjs.org/docs/app/api-reference/config/typescript\n")
    assert artifact_digest(app) == before, \
        "a toolchain-generated file changed the artifact digest"


def test_using_the_app_does_not_invalidate_the_attestation(tmp_path):
    """`expenses` persists to ./data/expenses.db. Saving one row through the preview
    AREA itself opens must not make the build undeployable."""
    app = _app(tmp_path)
    before = artifact_digest(app)
    (app / "data").mkdir()
    (app / "data" / "expenses.db").write_bytes(b"SQLite format 3\x00rows...")
    (app / "data" / "expenses.db-wal").write_bytes(b"wal")
    assert artifact_digest(app) == before


def test_build_caches_and_logs_are_still_out(tmp_path):
    app = _app(tmp_path)
    before = artifact_digest(app)
    (app / "tsconfig.tsbuildinfo").write_text("{}")
    (app / "dev.log").write_text("listening on 3000\n")
    (app / ".eslintcache").write_text("[]")
    assert artifact_digest(app) == before


def test_authored_source_is_still_digested(tmp_path):
    """The exclusions must not become a hole: tampering with real code must show."""
    app = _app(tmp_path)
    before = artifact_digest(app)
    (app / "app" / "page.tsx").write_text("export default function P() { return 'evil' }\n")
    assert artifact_digest(app) != before

    d = artifact_digest(app)
    (app / "lib").mkdir()
    (app / "lib" / "db.ts").write_text("export const x = 1\n")
    assert artifact_digest(app) != d, "an ADDED source file must change the digest"


def test_a_d_ts_file_the_author_wrote_is_still_digested(tmp_path):
    """Only `next-env.d.ts` is excluded by name — not every declaration file, or a
    hand-written `types.d.ts` would become a blind spot."""
    app = _app(tmp_path)
    before = artifact_digest(app)
    (app / "types.d.ts").write_text("declare module 'x'\n")
    assert artifact_digest(app) != before


def test_the_attestation_still_verifies_after_a_preview_regenerates_files(tmp_path):
    """End to end, in the order the incident happened: attest, then let the preview
    write what it writes, then check."""
    from area.provenance import verify_provenance

    app = _app(tmp_path)
    write_provenance(app, name="a", target="plain", gates={})
    (app / "next-env.d.ts").write_text("/// <reference types=\"next\" />\n")
    (app / "data").mkdir()
    (app / "data" / "app.db").write_bytes(b"rows")

    status, why = verify_provenance(app)
    assert status != "mismatch", f"the preview invalidated the attestation: {why}"


def test_the_recorded_digest_matches_what_a_later_reader_computes(tmp_path):
    app = _app(tmp_path)
    rec = write_provenance(app, name="a", target="plain", gates={})
    assert rec["product"]["artifactDigest"] == artifact_digest(app)
    on_disk = json.loads((app / ".area" / "provenance.json").read_text())
    assert on_disk["product"]["artifactDigest"] == artifact_digest(app)


# ---- M13: a helper that registers no tests cannot be required to run ----------

def _report(tmp_path, names):
    r = tmp_path / "report.json"
    r.write_text(json.dumps({"testResults": [
        {"name": str(tmp_path / "hold" / n), "status": "passed"} for n in names]}))
    return r


def _holdout(tmp_path, files):
    h = tmp_path / "hold"
    h.mkdir(exist_ok=True)
    for n, body in files.items():
        (h / n).write_text(body)
    return h


def test_a_locked_helper_with_no_tests_need_not_appear_in_the_report(tmp_path):
    """The real shape: the author locked `_source-scan.ts` as a shared helper."""
    h = _holdout(tmp_path, {"ac1.test.ts": _TEST, "_source-scan.ts": _HELPER})
    ok, why = assert_locked_files_ran(
        _report(tmp_path, ["ac1.test.ts"]), h, ["ac1.test.ts", "_source-scan.ts"])
    assert ok is True, why


def test_a_locked_test_file_that_did_not_run_still_blocks(tmp_path):
    """The guard this exists for: the builder excludes a locked suite and exits 0."""
    h = _holdout(tmp_path, {"ac1.test.ts": _TEST, "ac2.test.ts": _TEST})
    ok, why = assert_locked_files_ran(
        _report(tmp_path, ["ac1.test.ts"]), h, ["ac1.test.ts", "ac2.test.ts"])
    assert ok is False and "ac2.test.ts" in why


def test_a_helper_that_does_register_tests_is_still_required(tmp_path):
    """Registration is read from the file's checksum-locked bytes, so tests cannot be
    hidden in an underscore-prefixed module to escape the requirement."""
    h = _holdout(tmp_path, {"ac1.test.ts": _TEST, "_sneaky.ts": _TEST})
    ok, why = assert_locked_files_ran(
        _report(tmp_path, ["ac1.test.ts"]), h, ["ac1.test.ts", "_sneaky.ts"])
    assert ok is False and "_sneaky.ts" in why


def test_an_unreadable_locked_file_is_still_required_to_run(tmp_path):
    """Unreadable must read as "has tests" — the safe direction."""
    h = _holdout(tmp_path, {"ac1.test.ts": _TEST})
    ok, why = assert_locked_files_ran(
        _report(tmp_path, ["ac1.test.ts"]), h, ["ac1.test.ts", "gone.test.ts"])
    assert ok is False and "gone.test.ts" in why


def test_non_runnable_locked_files_are_untouched_by_this(tmp_path):
    h = _holdout(tmp_path, {"ac1.test.ts": _TEST, "CONTRACT.md": "lib/x: f()\n"})
    ok, _ = assert_locked_files_ran(
        _report(tmp_path, ["ac1.test.ts"]), h, ["ac1.test.ts", "CONTRACT.md"])
    assert ok is True


def test_a_lock_of_only_helpers_confirms_nothing_rather_than_passing_blindly(tmp_path):
    """If NOTHING in the lock registers a test there is no oracle to confirm ran, and
    the message must say that instead of implying a suite executed."""
    h = _holdout(tmp_path, {"_only-helper.ts": _HELPER})
    ok, why = assert_locked_files_ran(
        _report(tmp_path, []), h, ["_only-helper.ts"])
    assert ok is True
    assert "no runnable locked test files" in why


# ---- changing the digest DEFINITION must not read as tampering ----------------

def test_an_older_digest_definition_is_reported_as_stale_not_as_drift(tmp_path):
    """Widening the exclusions above re-answers the question the digest asks, so every
    attestation recorded under the old rules stops comparing. Saying "the artifact
    digest CHANGED since it was gated" there accuses the operator of drift for an
    upgrade AREA performed. Measured for real: of the four apps in the workspace, only
    `fb_incept` was validly attested, and this change alone invalidated it."""
    from area.provenance import DIGEST_VERSION, verify_provenance

    app = _app(tmp_path)
    write_provenance(app, name="a", target="plain", gates={})
    rec = json.loads((app / ".area" / "provenance.json").read_text())
    assert rec["product"]["digestVersion"] == DIGEST_VERSION, "version not recorded"

    rec["product"]["digestVersion"] = DIGEST_VERSION - 1
    rec["product"]["artifactDigest"] = "sha256:" + "0" * 64
    (app / ".area" / "provenance.json").write_text(json.dumps(rec))

    status, why = verify_provenance(app)
    assert status == "stale-digest", status
    assert "not comparable" in why and "Re-gate" in why
    assert "CHANGED since it was gated" not in why, "still reads as tampering"


def test_a_real_mismatch_under_the_current_definition_still_reads_as_drift(tmp_path):
    """The tamper signal must survive: same version, different bytes."""
    from area.provenance import verify_provenance

    app = _app(tmp_path)
    write_provenance(app, name="a", target="plain", gates={})
    (app / "app" / "page.tsx").write_text("export default () => 'tampered'\n")
    status, why = verify_provenance(app)
    assert status == "mismatch" and "CHANGED since it was gated" in why


def test_a_stale_digest_still_refuses_to_deploy_by_default(tmp_path, capsys):
    """Unverifiable is not a pass. Driven through the real `deploy_with_gate`, which
    is where the branch has to exist — leaning on its `else` for a status nobody
    anticipated is how fail-open creeps back in. The human gate would be asked AFTER
    attestation, so a refusal here must happen without `confirm` ever being called."""
    from area.deploy import deploy_with_gate

    app = _app(tmp_path)
    write_provenance(app, name="a", target="plain", gates={})
    rec = json.loads((app / ".area" / "provenance.json").read_text())
    rec["product"]["digestVersion"] = 1
    # The digest must differ too. A v1 record whose number still MATCHES is genuinely
    # ok — the bytes are provably unchanged whatever the definition — so only the
    # differing case is unverifiable.
    rec["product"]["artifactDigest"] = "sha256:" + "0" * 64
    (app / ".area" / "provenance.json").write_text(json.dumps(rec))

    asked = []
    ok, url = deploy_with_gate(app, confirm=lambda w: asked.append(w) or True,
                               provider="plain", require_provenance=True)
    out = capsys.readouterr().out
    assert ok is False and url is None
    assert asked == [], "a human was asked to approve a build that cannot ship"
    assert "NOT evidence of tampering" in out
    assert "UNVERIFIABLE" in out


def test_an_old_version_whose_digest_still_matches_is_genuinely_ok(tmp_path):
    """Learned from a failing test of my own: the version only matters when the
    numbers disagree. If a v1 record's digest equals what this AREA computes, the
    bytes are provably unchanged and refusing would be a false alarm."""
    from area.provenance import verify_provenance

    app = _app(tmp_path)
    write_provenance(app, name="a", target="plain", gates={})
    rec = json.loads((app / ".area" / "provenance.json").read_text())
    rec["product"]["digestVersion"] = 1          # digest left intact
    (app / ".area" / "provenance.json").write_text(json.dumps(rec))

    status, _ = verify_provenance(app)
    assert status == "ok"
