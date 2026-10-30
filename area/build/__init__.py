"""area.build — spec artifact -> working app (Bước 2).

Lazy on purpose (ADR 0004 Stage 0): importing the leaf `area.build.cf_scaffold` (deterministic
Cloudflare fixes, OpenHands-free) must not eager-load `area.build.nextjs`, which drives an agent
and so pulls the vendored OpenHands SDK. `build_app` stays importable here via PEP 562
`__getattr__`.
"""
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from area.build.nextjs import build_app as build_app

__all__ = ["build_app"]


def __getattr__(name: str) -> Any:
    if name == "build_app":
        from area.build.nextjs import build_app

        return build_app
    raise AttributeError(f"module 'area.build' has no attribute {name!r}")
