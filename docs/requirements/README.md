# Requirements inbox

Drop a requirement here as **`<name>.md`**, `.txt`, or `.pdf`, then tell Claude Code:

> "Build the app in `docs/requirements/<name>.md` following `CLAUDE.md`."

Claude Code runs the oracle-loop (intake → lock holdout → build to green → gates →
deploy) natively — see the root `CLAUDE.md`. Each requirement becomes an app under
`workspace/apps/<name>/`.

Keep one requirement per file. For a change to an existing app, say "iterate `<name>`:
<change>" and Claude re-locks a fresh holdout before rebuilding.
