"""B6 (deep audit 2026-10-28): a connected Postgres store whose migration fails must
BLOCK the Vercel deploy, not ship an app against a half-migrated database.

provision_postgres returned (True, ...) on every path — including when some
migrations/*.sql failed to apply (it tallied applied N/len and still returned True). So
_provision's "a failed provision blocks the deploy" was unreachable for Vercel, asymmetric
with cloudflare.provision_d1 (which returns ok_all). The not-yet-connected (no-URL) case
stays non-fatal: that is the deploy-first-then-connect-Marketplace workflow.
"""
import area.deploy as D
import area.deploy.vercel as V


def _setup(monkeypatch, app, *, apply_ok):
    (app / "migrations").mkdir(parents=True)
    (app / "migrations" / "001_init.sql").write_text("create table t (id int);")
    (app / "migrations" / "002_more.sql").write_text("alter table t add col int;")
    monkeypatch.setattr(V, "needs_postgres", lambda a: True)
    monkeypatch.setattr(V, "_vercel", lambda *a, **k: None)
    monkeypatch.setattr(V, "_env_file_value", lambda a, k: "postgres://u:p@h/db")
    monkeypatch.setattr(V, "_apply_sql", lambda a, url, path: apply_ok)


def test_a_failed_migration_blocks(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, apply_ok=False)
    ok, log = V.provision_postgres(tmp_path)
    assert ok is False, f"a failed Postgres migration must block the deploy: {log}"


def test_all_migrations_applied_is_ok(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, apply_ok=True)
    ok, _ = V.provision_postgres(tmp_path)
    assert ok is True


def test_no_postgres_usage_skips_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(V, "needs_postgres", lambda a: False)
    ok, log = V.provision_postgres(tmp_path)
    assert ok is True and "skipped" in log


def test_provision_blocks_deploy_when_postgres_migration_fails(monkeypatch, tmp_path):
    """The decision must reach the measurement: _provision('vercel') must actually
    refuse when provision_postgres returns False (and allow_failure=False)."""
    monkeypatch.setattr(V, "needs_postgres", lambda a: True)
    monkeypatch.setattr(V, "needs_kv", lambda a: False)
    monkeypatch.setattr(V, "provision_postgres", lambda a: (False, "migrate failed"))
    assert D._provision("vercel", str(tmp_path), allow_failure=False) is False
    assert D._provision("vercel", str(tmp_path), allow_failure=True) is True
