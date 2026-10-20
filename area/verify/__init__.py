"""area.verify — independent (holdout) acceptance verification."""
from area.verify.audit import static_audit
from area.verify.chaos import chaos_verify
from area.verify.e2e import e2e_verify
from area.verify.holdout import holdout_verify
from area.verify.nfr import nfr_verify
from area.verify.perf import perf_verify
from area.verify.product import product_verify

__all__ = ["holdout_verify", "e2e_verify", "static_audit", "chaos_verify",
           "nfr_verify", "perf_verify", "product_verify"]
