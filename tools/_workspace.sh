# Shared by the shell tools: resolve the workspace AREA actually uses, and find a python.
# Sourced, not executed.
#
# `area_workspace` mirrors `area.paths.workspace()`: $AREA_WORKSPACE when set, else
# <repo>/workspace. Two things it is careful about, each from a bug measured on the way:
#
#  * PURE SHELL. The first version asked `.venv/bin/python` for the answer and fell back
#    to the literal `workspace` when that was missing — so in any checkout without a venv
#    (CI, a fresh clone) the fix silently reverted to the bug it was fixing. CI caught it;
#    the local run could not, because the local checkout has a venv.
#  * ANCHORED ON THE SCRIPT, not on `$PWD`. `lock-holdout.sh` and
#    `verify-holdout-intact.sh` do not cd to the repo root, so a `$PWD`-relative default
#    would mean something different depending on where the operator stood.
#
# Tilde is expanded by hand rather than through `eval`, which would execute whatever the
# environment variable happened to contain.
_area_repo_root() { CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd; }

area_workspace() {
  _ws="${AREA_WORKSPACE:-}"
  if [ -z "$_ws" ]; then
    printf '%s/workspace\n' "$(_area_repo_root)"
    return 0
  fi
  case "$_ws" in
    "~") _ws="$HOME";;
    "~/"*) _ws="$HOME/${_ws#"~/"}";;
  esac
  # Absolutise when it exists; otherwise echo the intended path so errors can name it.
  if [ -d "$_ws" ]; then (CDPATH='' cd -- "$_ws" && pwd); else printf '%s\n' "$_ws"; fi
}

# First usable python. `.venv/bin/python` is preferred (it has `area` installed) but must
# not be assumed: hard-coding it made gate.sh exit 127 in CI. Absolute, so it does not
# depend on the caller's cwd either.
area_python() {
  _root="$(_area_repo_root)"
  if [ -x "$_root/.venv/bin/python" ]; then printf '%s\n' "$_root/.venv/bin/python"; return 0; fi
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then command -v "$c"; return 0; fi
  done
  return 1
}
