"""area.deploy.cloudflare — deploy a built app to Cloudflare Workers.

Keyless: uses the developer's `wrangler login` session (run `npx wrangler login`
once). Runs the app's own `deploy` script (vinext/@vinext/cloudflare). A human
gate guards production by default.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Callable, Optional

# matches *.workers.dev and *.pages.dev deploy URLs
_URL_RE = re.compile(r"https://[A-Za-z0-9.\-]+\.(?:workers|pages)\.dev\S*")


def _env() -> dict:
    """Env with the writable npm cache workaround (root-owned ~/.npm issue)."""
    e = dict(os.environ)
    e.setdefault("npm_config_cache", str(Path.home() / ".cache" / "npm-area"))
    return e


def deploy(app_dir: str | Path) -> tuple[bool, str, Optional[str]]:
    """Run the app's Cloudflare deploy. Returns (ok, output_tail, url).

    Requires a prior `npx wrangler login`. Prefers the app's `npm run deploy`
    script, falling back to `npx @vinext/cloudflare deploy`.
    """
    app = Path(app_dir)
    cmd = [
        "bash",
        "-lc",
        "npm run deploy 2>&1 || npx -y @vinext/cloudflare deploy 2>&1",
    ]
    proc = subprocess.run(
        cmd, cwd=str(app), capture_output=True, text=True, env=_env()
    )
    out = (proc.stdout + "\n" + proc.stderr).strip()
    m = _URL_RE.search(out)
    return proc.returncode == 0, out[-4000:], (m.group(0) if m else None)


def deploy_with_gate(
    app_dir: str | Path, *, confirm: Callable[[str], bool]
) -> tuple[bool, Optional[str]]:
    """Human gate, then deploy. `confirm(path)` must return True to proceed."""
    if not confirm(str(app_dir)):
        print("[area] deploy cancelled by human gate.")
        return False, None
    ok, out, url = deploy(app_dir)
    if ok:
        print(f"[area] ✅ deployed to Cloudflare: {url or '(URL not parsed — see output)'}")
    else:
        print(f"[area] ❌ deploy failed:\n{out}")
    return ok, url
