"""area.trace — optional Langfuse tracing of a whole pipeline run.

Deep process-visualization: one Langfuse TRACE per `area run/clone/intake`, with
one SPAN per agent run (spec, holdout author, build loop, each gate, deploy) —
cost + latency + outcome on every span. We already have that data in `area.obs`,
so we emit it directly instead of relying on OpenTelemetry from the ACP server
(the keyless Claude Code path does not reliably surface token usage to OTel).

Entirely OPTIONAL and best-effort: a no-op unless the `langfuse` SDK is importable
AND LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY are set (LANGFUSE_HOST for self-host).
Every SDK call is guarded so a version mismatch degrades to no-op, never a crash —
AREA's keyless path keeps working with no Langfuse at all. Written against the
Langfuse v2 client API (`client.trace(...).span(...)`); pin `langfuse>=2,<3`.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

_sink: Any = None          # active sink (a _LangfuseSink, a test fake, or None)
_resolved = False     # have we tried to build the default sink yet?
_current: Any = None       # the trace for the pipeline currently running


class _LangfuseSink:
    def __init__(self, client: Any) -> None:
        self._c = client

    def trace(self, **kw: Any) -> Any:
        return self._c.trace(**kw)

    def flush(self) -> None:
        try:
            self._c.flush()
        except Exception:
            pass


def set_sink(sink: Any) -> None:
    """Inject a sink (tests) or force-disable with None. Marks resolution done."""
    global _sink, _resolved, _current
    _sink = sink
    _resolved = True
    _current = None


def _default_sink() -> Optional["_LangfuseSink"]:
    pk, sk = os.getenv("LANGFUSE_PUBLIC_KEY"), os.getenv("LANGFUSE_SECRET_KEY")
    if not (pk and sk):
        return None
    try:
        from langfuse import Langfuse

        return _LangfuseSink(
            Langfuse(public_key=pk, secret_key=sk, host=os.getenv("LANGFUSE_HOST") or None)
        )
    except Exception:
        return None


def _get_sink() -> Any:
    global _sink, _resolved
    if not _resolved:
        _sink = _default_sink()
        _resolved = True
    return _sink


def enabled() -> bool:
    return _get_sink() is not None


def _dt(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, timezone.utc)


def start_pipeline(name: str, kind: str, inputs: Optional[dict[str, Any]] = None) -> None:
    """Open a trace for a pipeline run and print its Langfuse URL (if any)."""
    global _current
    sink = _get_sink()
    _current = None
    if not sink:
        return
    try:
        _current = sink.trace(
            name=f"{kind}:{name}", input=inputs,
            metadata={"kind": kind, "name": name},
        )
        url = None
        for attr in ("get_trace_url",):
            fn = getattr(_current, attr, None)
            if callable(fn):
                try:
                    url = fn()
                except Exception:
                    url = None
        url = url or getattr(_current, "url", None)
        if url:
            print(f"[area] trace : {url}")
    except Exception:
        _current = None


def log_span(
    label: str,
    *,
    duration: float = 0.0,
    cost: Optional[float] = None,
    passed: Optional[bool] = None,
    backend: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    """Record one agent run as a span under the current pipeline trace."""
    import time as _t

    if _current is None:
        return
    end = _t.time()
    start = end - max(duration, 0.0)
    md = {"cost_usd": cost, "duration_s": round(duration, 2),
          "passed": passed, "backend": backend}
    if metadata:
        md.update(metadata)
    try:
        _current.span(
            name=label, start_time=_dt(start), end_time=_dt(end),
            metadata=md, level=("ERROR" if passed is False else "DEFAULT"),
        )
    except Exception:
        pass


def end_pipeline(passed: Optional[bool] = None, output: Optional[dict[str, Any]] = None) -> None:
    """Close + flush the current pipeline trace."""
    global _current
    if _current is not None:
        try:
            _current.update(output=output, metadata={"passed": passed})
        except Exception:
            pass
    sink = _get_sink()
    if sink is not None and hasattr(sink, "flush"):
        sink.flush()
    _current = None
