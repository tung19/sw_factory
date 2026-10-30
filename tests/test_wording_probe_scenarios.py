"""P10 — the wording-probe scenario library must stay machine-gradeable: every scenario
forces an A/B/C choice, combines 3+ pressures, and marks which option(s) game the
measurement. A malformed scenario would make the probe ungradeable, so the schema is a test.
"""
from __future__ import annotations

import yaml

from area.paths import REPO

LIB = REPO / "docs" / "templates" / "wording-probe-scenarios.yaml"


def _scenarios() -> list[dict]:
    data = yaml.safe_load(LIB.read_text(encoding="utf-8"))
    return data["scenarios"]


def test_library_has_several_scenarios() -> None:
    assert len(_scenarios()) >= 4


def test_each_scenario_is_machine_gradeable() -> None:
    seen_ids = set()
    for s in _scenarios():
        sid = s["id"]
        assert sid not in seen_ids, f"duplicate scenario id {sid}"
        seen_ids.add(sid)
        assert len(s.get("pressures", [])) >= 3, f"{sid}: needs 3+ combined pressures"
        opts = s.get("options", {})
        assert set(opts) == {"A", "B", "C"}, f"{sid}: must force an A/B/C choice"
        sp = s.get("symptom_patch", [])
        assert sp, f"{sid}: must mark the symptom-patch option(s)"
        assert set(sp) <= {"A", "B", "C"}, f"{sid}: symptom_patch letters must be A/B/C"
        # there must be an honest option too, or the forced choice is rigged
        assert set(opts) - set(sp), f"{sid}: every option is a symptom-patch — no honest choice"
        assert s.get("prompt"), f"{sid}: needs a prompt"
