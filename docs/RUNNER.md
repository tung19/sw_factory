# Run an AREA runner (on your own infra)

The **coordinator** only relays; the **runner** does the work. You run the runner
on a machine you control (your laptop, or a VM in your own cloud account), and it
uses **your** Claude and **your** Cloudflare/Vercel. Nothing but log lines leaves
your machine. (Architecture: [docs/adr/0002](adr/0002-coordinator-runner-saas.md).)

## What a runner needs

- Python 3.12+, Node 18+, git (run `area doctor` to check).
- A Claude path: **Claude Code logged in (keyless)**, or `ANTHROPIC_API_KEY`.
- (When you deploy) your own Cloudflare/Vercel login.
- The **coordinator URL** and a **pairing token** (your private channel — anyone
  who knows it can drive *your* runner, so keep it secret).

## Option A — on your machine (keyless, simplest)

```bash
git clone <this repo> && cd SW_Factory
bash scripts/run-runner.sh --connect wss://<coordinator-host> --token <your-token>
```

`run-runner.sh` installs AREA on first run, checks the environment, and starts the
runner. It uses your existing Claude Code login — no API key. Leave it running;
jobs you send from the coordinator UI execute here and stream back.

Open the coordinator at `https://<coordinator-host>/?token=<your-token>` — while no
runner is connected it shows the exact `area runner …` command to paste.

## Option B — on a cloud VM / container (headless)

A headless box usually has no interactive Claude Code login, so use an API key.
Build and run the container:

```bash
docker build -f Dockerfile.runner -t area-runner .
docker run --rm \
  -e AREA_COORD_URL=wss://<coordinator-host> \
  -e AREA_PAIR_TOKEN=<your-token> \
  -e ANTHROPIC_API_KEY=<your-key> \
  # -e CLOUDFLARE_API_TOKEN=… / VERCEL_TOKEN=…  (when you deploy)
  area-runner
```

> The container is a **starting template** for the headless path (API-key mode).
> The keyless Claude Code path (Option A) is the validated one; running Claude Code
> headless in a container needs its own auth (mount `~/.claude`) and is not covered
> here.

## Pairing & isolation

- The `--token` you pass is your **channel**. The coordinator routes your UI only
  to the runner with the same token — other users on the same coordinator can't
  see or reach your runner.
- No token = the shared local channel (fine for local dev only). For a coordinator
  exposed publicly, always use a unique secret token, and run the coordinator with
  `AREA_COORD_REQUIRE_TOKEN=1` so tokenless connections are refused.

## Stop

`Ctrl-C` in the runner terminal (or stop the container). Your jobs stop; your
machine and accounts are untouched otherwise.
