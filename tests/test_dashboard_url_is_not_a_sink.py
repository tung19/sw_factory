"""A build-log line must not be able to inject HTML into the dashboard.

`jobs.py` scrapes the deploy URL out of a job's log with a regex whose trailing path
was `\\S*` — unbounded except for whitespace. The dashboard then interpolated that value
straight into `href="${j.url}"` inside `innerHTML`, with no escaping (the adjacent app
NAME was escaped, the URL was not). A log line containing

    https://x.workers.dev"><img src=x onerror=alert(1)>

was therefore captured whole and rendered as markup — on a page that can trigger
deploys. In Flow B a build log carries output from an UNTRUSTED reference app, which is
what makes the source reachable rather than theoretical.

Three layers now, and this file measures all three rather than grepping for them:
  1. the regex is bounded to URL-safe characters at the source;
  2. `escAttr()` escapes quotes — `esc()` does not, so it was never sufficient in an
     attribute context;
  3. `safeUrl()` renders nothing at all unless the value is an https URL, so a
     different scheme (`javascript:`) cannot reach an `href` either.
"""
import json
import re
import shutil
import subprocess

import pytest

from area.paths import REPO

PAYLOADS = [
    'https://x.workers.dev"><img src=x onerror=alert(1)>',
    "https://x.workers.dev'><script>alert(1)</script>",
    "https://x.workers.dev</a><b>oops",
    "javascript:alert(1)",
    "http://x.workers.dev",                      # not https
    'https://x.workers.dev?a=1"onmouseover="alert(1)',
]
REAL = [
    "https://my-app.workers.dev",
    "https://my-app.pages.dev/",
    "https://my-app.workers.dev/health?x=1",
]


# ---- layer 1: the regex at the source ----------------------------------------

@pytest.mark.parametrize("mod", ["area.web.jobs", "area.deploy.cloudflare",
                                 "area.deploy.vercel"])
def test_the_url_regex_cannot_swallow_an_html_payload(mod):
    """Three copies of the same pattern; all three fed a URL somewhere."""
    import importlib

    rx = importlib.import_module(mod)._URL_RE
    host = "vercel.app" if mod.endswith("vercel") else "workers.dev"
    line = f'[area] deployed https://x.{host}"><img src=x onerror=alert(1)> done'
    m = rx.search(line)
    assert m, "the regex must still find the URL"
    assert not (set(m.group(0)) & set("\"'<>`")), f"captured markup: {m.group(0)!r}"
    assert m.group(0) == f"https://x.{host}"


def test_the_url_regex_still_matches_a_real_deploy_url():
    """Bounding the path must not break the thing it exists to extract."""
    from area.web.jobs import _URL_RE

    for url in REAL:
        line = f"Deployed to {url} (version abc)"
        m = _URL_RE.search(line)
        assert m and line[m.start():].startswith(m.group(0))
        assert m.group(0).startswith("https://")


# ---- layers 2 and 3: run the page's OWN functions, in node -------------------

def _js_fn(name: str) -> str:
    src = (REPO / "area" / "web" / "static" / "index.html").read_text()
    m = re.search(rf"^function {name}\(.*$", src, re.M)
    assert m, f"{name}() is missing from the dashboard"
    return m.group(0)


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_safe_url_and_esc_attr_as_the_browser_would_run_them(tmp_path):
    """Not a source grep: the real functions, evaluated by a real JS engine."""
    script = tmp_path / "t.mjs"
    script.write_text(
        _js_fn("escAttr") + "\n" + _js_fn("safeUrl") + "\n"
        "const payloads = " + json.dumps(PAYLOADS) + ";\n"
        "const real = " + json.dumps(REAL) + ";\n"
        "console.log(JSON.stringify({\n"
        "  rejected: payloads.map(safeUrl),\n"
        "  accepted: real.map(safeUrl),\n"
        "  quoted: escAttr('a\"b\\'c<d>e&f'),\n"
        "}));\n")
    out = subprocess.run(["node", str(script)], capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)

    # every payload must render as NO link at all
    assert got["rejected"] == [""] * len(PAYLOADS), got["rejected"]
    # ... while real deploy URLs still link
    assert got["accepted"] == REAL
    # ... and escAttr closes the attribute-context hole esc() leaves open
    assert got["quoted"] == "a&quot;b&#39;c&lt;d&gt;e&amp;f"


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_esc_alone_would_not_have_been_enough(tmp_path):
    """Why `escAttr` had to exist: the page's `esc()` leaves `"` untouched, so
    `href="${esc(url)}"` is still escapable. Pinned so nobody "simplifies" it back."""
    script = tmp_path / "t.mjs"
    script.write_text(_js_fn("esc") + "\nconsole.log(esc('a\"b'));\n")
    out = subprocess.run(["node", str(script)], capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == 'a"b'


def test_every_href_in_the_dashboard_is_escaped_or_static():
    """A guard for the NEXT link somebody adds: any `href="${...}"` built inside a
    template string must run through escAttr/safeUrl."""
    src = (REPO / "area" / "web" / "static" / "index.html").read_text()
    bad = [h for h in re.findall(r'href="\$\{[^}]*\}"', src)
           if "escAttr" not in h and "safeUrl" not in h]
    assert not bad, f"unescaped interpolated href(s): {bad}"
