"""area deploy: auto-provision Cloudflare D1 (create DB + apply migrations)
before deploying a persistence app. Pure detection/parse + gate wiring (the
actual wrangler calls need a live CLI + login, so they are not run here)."""
import area.deploy as D
import area.deploy.cloudflare as C


def test_needs_d1_binding(tmp_path):
    (tmp_path / "cloudflare.config.ts").write_text("env: { DB: bindings.d1() }")
    assert C.needs_d1(tmp_path)


def test_needs_d1_migrations(tmp_path):
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "0001_init.sql").write_text("CREATE TABLE x(id TEXT);")
    assert C.needs_d1(tmp_path)


def test_needs_d1_false_for_plain(tmp_path):
    (tmp_path / "cloudflare.config.ts").write_text('worker: { name: "app" }')
    assert not C.needs_d1(tmp_path)


def test_db_names_uses_worker_name(tmp_path):
    (tmp_path / "cloudflare.config.ts").write_text(
        'defineWorker({ name: "gb-d1", env: { DB: bindings.d1() } })'
    )
    assert C.d1_db_names(tmp_path) == ["gb-d1"]


def test_db_names_prefers_database_name(tmp_path):
    (tmp_path / "wrangler.toml").write_text(
        'name = "w"\n[[d1_databases]]\nbinding = "DB"\ndatabase_name = "mydb"\n'
    )
    assert "mydb" in C.d1_db_names(tmp_path)


def test_db_names_fallback_to_app_dir(tmp_path):
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "0001.sql").write_text("x")
    assert C.d1_db_names(tmp_path) == [tmp_path.name]


def test_gate_provisions_d1_before_deploy(monkeypatch, tmp_path):
    # The attestation tripwire has its own tests (test_attest_what_ships.py);
    # stub it here so this stays a routing/provisioning test and does not copy
    # the braces template or shell out to `npm ls`.
    monkeypatch.setattr(D, "_settle_before_attesting", lambda a, p: True)
    (tmp_path / "cloudflare.config.ts").write_text("env: { DB: bindings.d1() }")
    order = []
    monkeypatch.setattr(C, "provision_d1",
                        lambda a: (order.append("provision"), (True, "d1 create ok"))[1])
    monkeypatch.setattr(C, "deploy",
                        lambda a: (order.append("deploy"), (True, "out", None))[1])
    # provisioning order, not the provenance policy → opt out of it explicitly
    ok, _ = D.deploy_with_gate(tmp_path, confirm=lambda p: True,
                               require_provenance=False)
    assert ok and order == ["provision", "deploy"]


def test_gate_skips_provision_for_plain_app(monkeypatch, tmp_path):
    # The attestation tripwire has its own tests (test_attest_what_ships.py);
    # stub it here so this stays a routing/provisioning test and does not copy
    # the braces template or shell out to `npm ls`.
    monkeypatch.setattr(D, "_settle_before_attesting", lambda a, p: True)
    (tmp_path / "cloudflare.config.ts").write_text('worker: { name: "app" }')
    order = []
    monkeypatch.setattr(C, "provision_d1",
                        lambda a: (order.append("provision"), (True, ""))[1])
    monkeypatch.setattr(C, "deploy",
                        lambda a: (order.append("deploy"), (True, "out", None))[1])
    D.deploy_with_gate(tmp_path, confirm=lambda p: True, require_provenance=False)
    assert order == ["deploy"]  # no D1 -> no provisioning


def test_gate_cancelled_runs_nothing(monkeypatch, tmp_path):
    (tmp_path / "cloudflare.config.ts").write_text("env: { DB: bindings.d1() }")
    order = []
    monkeypatch.setattr(C, "provision_d1", lambda a: (order.append("p"), (True, ""))[1])
    monkeypatch.setattr(C, "deploy", lambda a: (order.append("d"), (True, "", None))[1])
    # require_provenance=False so the refusal must come from the HUMAN gate
    ok, _ = D.deploy_with_gate(tmp_path, confirm=lambda p: False,
                               require_provenance=False)
    assert not ok and order == []


def test_provision_d1_shlex_quotes_migration_filename(monkeypatch, tmp_path):
    """Audit fix: an agent-authored migration filename must be shlex-quoted into
    the `bash -lc` string so a crafted name can't inject a command."""
    import shlex

    (tmp_path / "cloudflare.config.ts").write_text(
        'defineWorker({ name: "db", env: { DB: bindings.d1() } })')
    mig = tmp_path / "migrations"
    mig.mkdir()
    evil = "0001$(touch pwned).sql"
    (mig / evil).write_text("CREATE TABLE IF NOT EXISTS t(id TEXT);")

    cmds = []

    class _P:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(argv, **kw):
        cmds.append(argv[2] if argv and argv[0] == "bash" else " ".join(map(str, argv)))
        return _P()

    monkeypatch.setattr(C.subprocess, "run", fake_run)
    C.provision_d1(tmp_path)

    exec_cmds = [c for c in cmds if "d1 execute" in c]
    assert exec_cmds, "no `d1 execute` command was issued"
    assert f"--file={shlex.quote(f'migrations/{evil}')}" in exec_cmds[0]
    # the payload only appears inside the single-quoted (inert) filename
    assert "$(touch pwned)" not in exec_cmds[0].replace(shlex.quote(f"migrations/{evil}"), "")
