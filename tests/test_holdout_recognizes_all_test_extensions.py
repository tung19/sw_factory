"""B8 + B10 (deep audit 2026-10-28): the authoring gate and the provenance
oracle-strength field must recognize the SAME test extensions the runner does.

The runner (`_runners.py`) accepts `.ts/.tsx/.mts/.cts/.js/.jsx/.mjs/.cjs`, but
`_has_tests`/`_test_text` used a narrower set (so a `.mjs` holdout was rejected at
authoring — the build cannot complete) and `provenance._oracle_strength` globbed `*.ts`
non-recursively (so a `.tsx`/`.mjs` holdout was never read and the oracle was attested as
clean without being measured). One shared definition (`area.paths.TEST_SUFFIXES`) now
backs all of them.
"""
import pytest

from area.verify import holdout as H


@pytest.mark.parametrize("ext", [".mjs", ".mts", ".tsx", ".cjs", ".cts", ".jsx"])
def test_has_tests_sees_every_runnable_extension(ext, tmp_path):
    (tmp_path / f"a.test{ext}").write_text("it('AC-1', () => expect(1).toBe(1))")
    assert H._has_tests(tmp_path), f"{ext} holdout invisible to the authoring gate"


def test_test_text_reads_mjs_and_tsx(tmp_path):
    (tmp_path / "a.test.mjs").write_text("// AC-9 expect(x).toBe(1)")
    (tmp_path / "b.test.tsx").write_text("// AC-10 expect(y).toBe(2)")
    txt = H._test_text(tmp_path)
    assert "AC-9" in txt and "AC-10" in txt


def test_expected_ac_count_counts_mts(tmp_path):
    (tmp_path / "a.test.mts").write_text("it('AC-1'); it('AC-2')")
    assert H._expected_ac_count(tmp_path) == 2


def test_authoring_oracle_accepts_an_mjs_suite(tmp_path):
    (tmp_path / "a.test.mjs").write_text(
        "describe('x', () => { it('AC-1', () => { expect(add(1)).toBe(1) }) })")
    acc = "criteria:\n- {id: AC-1, feature: f, given: g, when: w, then: t}\n"
    ok, feedback = H._authoring_oracle(tmp_path, acc, require_contract=False)
    assert ok, f"a valid .mjs holdout was rejected at authoring: {feedback}"


def test_provenance_reads_non_ts_holdouts(tmp_path, monkeypatch):
    import area.provenance as P
    import area.verify.strength as strength

    captured: dict = {}
    monkeypatch.setattr(strength, "classify",
                        lambda crit, text: (captured.update(text=text), [])[1])
    app = tmp_path / "apps" / "x"
    hold = app / "__tests__" / "_holdout"
    hold.mkdir(parents=True)
    (hold / "a.test.tsx").write_text("MARKER_TSX")
    (hold / "b.test.mjs").write_text("MARKER_MJS")
    sd = tmp_path / "specs" / "x"
    sd.mkdir(parents=True)
    (sd / "acceptance.yaml").write_text(
        "criteria:\n- {id: AC-1, feature: f, given: g, when: w, then: t}\n")
    P._oracle_strength(app, sd)
    assert "MARKER_TSX" in captured.get("text", ""), "provenance ignored a .tsx holdout"
    assert "MARKER_MJS" in captured.get("text", ""), "provenance ignored a .mjs holdout"
