"""area.export — hand a generated app off as its own git repository.

A generated app lives in workspace/apps/<name> (gitignored from AREA — the
factory's OUTPUT is kept separate from the factory's CODE). `area export` turns
one into a standalone, user-owned git repo: it writes an app-level .gitignore,
git-inits + commits the source, and optionally copies it out of the workspace
and/or pushes to a GitHub remote. Each app becomes its OWN repo, never folded
into AREA's.

Flow for a real user: describe → AREA builds (local) → review → `area export
<app> --repo <url> --push` → the user owns + versions it like any other repo.
"""
from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from area._util import safe_name
from area.pipeline import WORKSPACE

# Dirs that are build output / deps / tooling — never copied or committed.
_IGNORE_DIRS = {
    "node_modules", ".next", ".vinext", ".open-next", ".cloudflare", ".wrangler",
    ".openhands", ".vercel", "dist", "build", "out", "test-results",
    "playwright-report", ".area", ".git", ".claude",
}

_GITIGNORE = """# dependencies & build output
node_modules/
.next/
.vinext/
.open-next/
.cloudflare/
.wrangler/
.vercel/
dist/
build/
out/
# test & tooling artifacts
test-results/
playwright-report/
.openhands/
# env & secrets
.env
.env.*
!.env.example
# OS
.DS_Store
"""


def _run(cmd: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-lc", cmd], cwd=str(cwd), capture_output=True, text=True)


def ensure_gitignore(app_dir: str | Path) -> bool:
    """Write an app-level .gitignore if absent. Returns True if it wrote one."""
    p = Path(app_dir) / ".gitignore"
    if p.exists():
        return False
    p.write_text(_GITIGNORE)
    return True


def copy_source(src: str | Path, dest: str | Path) -> Path:
    """Copy the app's OWN source to dest, excluding deps/build/tooling dirs."""
    src, dest = Path(src), Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    def _ignore(_dir, names):
        return [n for n in names if n in _IGNORE_DIRS]

    for item in src.iterdir():
        if item.name in _IGNORE_DIRS:
            continue
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=_ignore, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)
    return dest


def export_app(
    name: str,
    *,
    out: Optional[str | Path] = None,
    repo: Optional[str] = None,
    push: bool = False,
    create: bool = False,
    message: Optional[str] = None,
    visibility: str = "private",
    workspace: Optional[str | Path] = None,
) -> tuple[bool, str]:
    """Export a generated app as its own git repo. Returns (ok, log).

    out=<dir>  -> copy the app into <dir>/<name> first (default: in place).
    repo=<url> -> set as `origin`. create=True -> `gh repo create` (needs gh).
    push=True  -> push to origin after the initial commit.
    """
    name = safe_name(name)
    root = Path(workspace) if workspace else WORKSPACE
    app = root / "apps" / name
    if not app.exists():
        raise RuntimeError(f"no app at {app}")

    log: list[str] = []
    dest = app
    if out:
        dest = Path(out).expanduser() / name
        copy_source(app, dest)
        log.append(f"copied source → {dest}")

    log.append(".gitignore " + ("written" if ensure_gitignore(dest) else "present"))

    if not (dest / ".git").exists():
        _run("git init -q", dest)
        log.append("git init")
    _run("git add -A", dest)
    msg = message or f"AREA: initial generated app ({name})"
    c = _run(f'git -c user.name=AREA -c user.email=area@local commit -q -m {shlex.quote(msg)}', dest)
    log.append("git commit: " + ("ok" if c.returncode == 0 else (c.stdout + c.stderr).strip()[-200:]))

    if create and not repo:
        vis = "--public" if visibility == "public" else "--private"
        g = _run(f"gh repo create {shlex.quote(name)} {vis} --source=. --remote=origin", dest)
        log.append("gh repo create: " + ("ok" if g.returncode == 0 else (g.stdout + g.stderr).strip()[-200:]))
    elif repo:
        _run(f"git remote remove origin 2>/dev/null; git remote add origin {shlex.quote(repo)}", dest)
        log.append(f"remote origin = {repo}")

    if push:
        p = _run("git push -u origin HEAD", dest)
        log.append("git push: " + ("ok" if p.returncode == 0 else (p.stdout + p.stderr).strip()[-300:]))

    log.append(f"→ exported at {dest}")
    return True, "\n".join(log)
