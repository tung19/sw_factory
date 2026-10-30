"""area.verify — independent (holdout) acceptance verification.

Lazy on purpose (ADR 0004 Stage 0): importing a single leaf gate (e.g. `area.verify.nfr` or
`area.verify.perf`, which are deterministic and OpenHands-free) must not eager-load the
agent-driving gates (audit/chaos/e2e/holdout/product) that import the engine and so the 30M
vendored OpenHands SDK. The nine `*_verify` names are still importable from here — resolved on
first access via PEP 562 `__getattr__` — and keep their types for mypy through the
TYPE_CHECKING block. tests/test_engine_util_leaf.py pins the leaf gates as OpenHands-free.
"""
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from area.verify.audit import static_audit as static_audit
    from area.verify.chaos import chaos_verify as chaos_verify
    from area.verify.cost import cost_verify as cost_verify
    from area.verify.e2e import e2e_verify as e2e_verify
    from area.verify.holdout import holdout_verify as holdout_verify
    from area.verify.nfr import nfr_verify as nfr_verify
    from area.verify.perf import perf_verify as perf_verify
    from area.verify.product import product_verify as product_verify
    from area.verify.visual import visual_verify as visual_verify

_EXPORTS = {
    "static_audit": "area.verify.audit",
    "chaos_verify": "area.verify.chaos",
    "cost_verify": "area.verify.cost",
    "e2e_verify": "area.verify.e2e",
    "holdout_verify": "area.verify.holdout",
    "nfr_verify": "area.verify.nfr",
    "perf_verify": "area.verify.perf",
    "product_verify": "area.verify.product",
    "visual_verify": "area.verify.visual",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module 'area.verify' has no attribute {name!r}") from None
    import importlib

    return getattr(importlib.import_module(module), name)
