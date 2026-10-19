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
