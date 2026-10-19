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
    (tmp_path / "cloudflare.config.ts").write_text("env: { DB: bindings.d1() }")
    order = []
    monkeypatch.setattr(C, "provision_d1",
                        lambda a: (order.append("provision"), (True, "d1 create ok"))[1])
    monkeypatch.setattr(C, "deploy",
                        lambda a: (order.append("deploy"), (True, "out", None))[1])
    ok, _ = D.deploy_with_gate(tmp_path, confirm=lambda p: True)
    assert ok and order == ["provision", "deploy"]


def test_gate_skips_provision_for_plain_app(monkeypatch, tmp_path):
    (tmp_path / "cloudflare.config.ts").write_text('worker: { name: "app" }')
    order = []
    monkeypatch.setattr(C, "provision_d1",
                        lambda a: (order.append("provision"), (True, ""))[1])
    monkeypatch.setattr(C, "deploy",
                        lambda a: (order.append("deploy"), (True, "out", None))[1])
    D.deploy_with_gate(tmp_path, confirm=lambda p: True)
    assert order == ["deploy"]  # no D1 -> no provisioning


def test_gate_cancelled_runs_nothing(monkeypatch, tmp_path):
    (tmp_path / "cloudflare.config.ts").write_text("env: { DB: bindings.d1() }")
    order = []
    monkeypatch.setattr(C, "provision_d1", lambda a: (order.append("p"), (True, ""))[1])
    monkeypatch.setattr(C, "deploy", lambda a: (order.append("d"), (True, "", None))[1])
    ok, _ = D.deploy_with_gate(tmp_path, confirm=lambda p: False)
    assert not ok and order == []
