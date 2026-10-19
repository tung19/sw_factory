"""area deploy (Vercel): auto-provision connected storage before deploying a
persistence app — detect Postgres/KV usage, pull the connection string, apply
SQL migrations, and wire it non-fatally into the gate. Pure detection/parse +
gate wiring; the actual `vercel`/`psql` calls need live auth, so they are not
run here (same posture as test_deploy_d1.py)."""
import area.deploy as D
import area.deploy.vercel as V


# ---- needs_postgres / needs_kv (source sniffing) --------------------------------

def test_needs_postgres_by_dependency(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies":{"@vercel/postgres":"^0.9.0"}}')
    assert V.needs_postgres(tmp_path)


def test_needs_postgres_by_env_reference_in_code(tmp_path):
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "db.ts").write_text("export const url = process.env.POSTGRES_URL!;")
    assert V.needs_postgres(tmp_path)


def test_needs_postgres_by_migrations(tmp_path):
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "0001_init.sql").write_text("CREATE TABLE x(id TEXT);")
    assert V.needs_postgres(tmp_path)


def test_needs_postgres_false_for_stateless(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies":{"next":"15"}}')
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "page.tsx").write_text("export default () => <div>tip</div>;")
    assert not V.needs_postgres(tmp_path)


def test_needs_postgres_ignores_node_modules(tmp_path):
    # a dep's own source mentioning pg must NOT trip detection
    nm = tmp_path / "node_modules" / "something" / "lib"
    nm.mkdir(parents=True)
    (nm / "x.js").write_text("const pg = require('pg');")
    (tmp_path / "package.json").write_text('{"dependencies":{"next":"15"}}')
    assert not V.needs_postgres(tmp_path)


def test_needs_kv_by_dependency(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies":{"@upstash/redis":"^1"}}')
    assert V.needs_kv(tmp_path)


def test_needs_kv_false(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies":{"next":"15"}}')
    assert not V.needs_kv(tmp_path)


# ---- env-file parsing -----------------------------------------------------------

def test_env_file_value_plain(tmp_path):
    (tmp_path / ".env.local").write_text("POSTGRES_URL=postgres://u:p@h/db\nOTHER=1\n")
    assert V._env_file_value(tmp_path, "POSTGRES_URL") == "postgres://u:p@h/db"


def test_env_file_value_export_and_quotes(tmp_path):
    (tmp_path / ".env.local").write_text('export KV_REST_API_URL="https://x.upstash.io"\n')
    assert V._env_file_value(tmp_path, "KV_REST_API_URL") == "https://x.upstash.io"


def test_env_file_value_missing(tmp_path):
    (tmp_path / ".env.local").write_text("A=1\n")
    assert V._env_file_value(tmp_path, "POSTGRES_URL") is None


# ---- provision_postgres (CLI stubbed) -------------------------------------------

def test_provision_postgres_skips_stateless(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies":{"next":"15"}}')
    ok, log = V.provision_postgres(tmp_path)
    assert ok and "skipped" in log


def test_provision_postgres_missing_url_is_nonfatal(monkeypatch, tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies":{"@vercel/postgres":"^0.9"}}')
    monkeypatch.delenv("AREA_POSTGRES_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    monkeypatch.setattr(V, "_vercel", lambda app, args: None)  # link + env pull are no-ops
    ok, log = V.provision_postgres(tmp_path)
    assert ok  # NON-FATAL
    assert "POSTGRES_URL not found" in log and "Marketplace" in log


def test_provision_postgres_applies_migrations(monkeypatch, tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies":{"@vercel/postgres":"^0.9"}}')
    mig = tmp_path / "migrations"
    mig.mkdir()
    (mig / "0001_init.sql").write_text("CREATE TABLE IF NOT EXISTS u(id TEXT);")
    (mig / "0002_more.sql").write_text("CREATE TABLE IF NOT EXISTS n(id TEXT);")

    # `env pull` surfaces the connection string
    def fake_vercel(app, args):
        if args.startswith("env pull"):
            (tmp_path / ".env.local").write_text("POSTGRES_URL=postgres://u:p@h/db\n")
        return None

    applied = []
    monkeypatch.setattr(V, "_vercel", fake_vercel)
    monkeypatch.setattr(V, "_apply_sql", lambda app, url, rel: (applied.append(rel), True)[1])
    ok, log = V.provision_postgres(tmp_path)
    assert ok
    assert applied == ["migrations/0001_init.sql", "migrations/0002_more.sql"]
    assert "applied 2/2" in log


def test_vercel_env_add_value_via_stdin_not_argv(monkeypatch, tmp_path):
    """Security: a wired connection string must go through stdin/env, never argv."""
    SECRET = "postgres://user:p@ss@host/db?sslmode=require"
    seen = []

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(V.subprocess, "run",
                        lambda cmd, **kw: (seen.append((cmd, kw.get("env") or {})), _Proc())[1])
    V._vercel_env_add(tmp_path, "POSTGRES_URL", SECRET, "production")

    (cmd, env) = seen[0]
    joined = " ".join(cmd)
    assert SECRET not in joined, "connection string leaked onto argv"
    assert env.get("AREA_ENV_VAL") == SECRET, "value must travel via the env/stdin"
    assert "printf" in joined and "vercel env add" in joined and "POSTGRES_URL" in joined


def test_provision_postgres_wires_provided_url(monkeypatch, tmp_path):
    """With no store connected but AREA_POSTGRES_URL exported, provisioning wires
    the URL into the project and migrates against it."""
    (tmp_path / "package.json").write_text('{"dependencies":{"@vercel/postgres":"^0.9"}}')
    mig = tmp_path / "migrations"; mig.mkdir()
    (mig / "0001_init.sql").write_text("CREATE TABLE IF NOT EXISTS u(id TEXT);")
    PG = "postgres://u:p@h/db"
    monkeypatch.setenv("AREA_POSTGRES_URL", PG)
    monkeypatch.setattr(V, "_vercel", lambda app, args: None)  # link + pull surface nothing

    added, applied = [], []
    monkeypatch.setattr(V, "_vercel_env_add",
                        lambda app, k, v, t="production": added.append((k, v, t)))
    monkeypatch.setattr(V, "_apply_sql",
                        lambda app, url, rel: (applied.append((url, rel)), True)[1])

    ok, log = V.provision_postgres(tmp_path)
    assert ok
    assert added == [("POSTGRES_URL", PG, "production")]
    assert applied == [(PG, "migrations/0001_init.sql")]
    assert "wired" in log


def test_provision_postgres_no_url_no_provided_is_actionable(monkeypatch, tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies":{"@vercel/postgres":"^0.9"}}')
    monkeypatch.delenv("AREA_POSTGRES_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    monkeypatch.setattr(V, "_vercel", lambda app, args: None)
    ok, log = V.provision_postgres(tmp_path)
    assert ok and "export AREA_POSTGRES_URL" in log and "NON-FATAL" in log


def test_provision_kv_present_env(monkeypatch, tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies":{"@vercel/kv":"^3"}}')

    def fake_vercel(app, args):
        if args.startswith("env pull"):
            (tmp_path / ".env.local").write_text("KV_REST_API_URL=https://x.upstash.io\n")
        return None

    monkeypatch.setattr(V, "_vercel", fake_vercel)
    ok, log = V.provision_kv(tmp_path)
    assert ok and "KV/Redis env present" in log


# ---- gate wiring (order + skips), mirroring test_deploy_d1 ----------------------

def test_gate_vercel_provisions_postgres_before_deploy(monkeypatch, tmp_path):
    (tmp_path / "package.json").write_text(
        '{"scripts":{"build":"next build"},"dependencies":{"@vercel/postgres":"^0.9"}}'
    )
    order = []
    monkeypatch.setattr(V, "provision_postgres",
                        lambda a: (order.append("provision-pg"), (True, "ok"))[1])
    monkeypatch.setattr(V, "deploy",
                        lambda a: (order.append("deploy"), (True, "", "https://x.vercel.app"))[1])
    ok, url = D.deploy_with_gate(tmp_path, confirm=lambda p: True)
    assert ok and order == ["provision-pg", "deploy"] and url == "https://x.vercel.app"


def test_vercel_token_never_on_command_line(monkeypatch, tmp_path):
    """Security: the VERCEL_TOKEN must reach the CLI via the env, never as a
    --token flag (which leaks the secret into the process table / captured logs)."""
    SECRET = "vcp_SECRET_SHOULD_NOT_APPEAR_ON_ARGV"
    monkeypatch.setenv("VERCEL_TOKEN", SECRET)
    seen = []

    class _Proc:
        returncode = 0
        stdout = "https://x.vercel.app"
        stderr = ""

    def fake_run(cmd, **kw):
        seen.append((cmd, kw.get("env") or {}))
        return _Proc()

    monkeypatch.setattr(V.subprocess, "run", fake_run)

    V._vercel(tmp_path, "link --yes")
    V.deploy(tmp_path)

    assert seen, "subprocess.run was not invoked"
    for cmd, env in seen:
        joined = " ".join(cmd)
        assert "--token" not in joined, f"--token leaked onto argv: {joined}"
        assert SECRET not in joined, "token value leaked onto argv"
        assert env.get("VERCEL_TOKEN") == SECRET, "token must be passed via the env"


def test_gate_vercel_skips_provision_for_stateless(monkeypatch, tmp_path):
    (tmp_path / "package.json").write_text('{"scripts":{"build":"next build"}}')
    order = []
    monkeypatch.setattr(V, "provision_postgres",
                        lambda a: (order.append("provision-pg"), (True, ""))[1])
    monkeypatch.setattr(V, "provision_kv",
                        lambda a: (order.append("provision-kv"), (True, ""))[1])
    monkeypatch.setattr(V, "deploy",
                        lambda a: (order.append("deploy"), (True, "", None))[1])
    D.deploy_with_gate(tmp_path, confirm=lambda p: True)
    assert order == ["deploy"]  # stateless -> no provisioning
