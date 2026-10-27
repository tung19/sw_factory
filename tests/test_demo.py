"""area.demo — keyless run of a committed example (no Claude, no cost). The
install/build/serve path isn't exercised here (it needs npm); the discovery +
error path + the committed example's presence are."""
import area.cli as CLI
import area.demo as D


def test_committed_taskboard_example_is_discoverable():
    # the examples/taskboard app is committed, so the factory's output is visible
    assert "taskboard" in D.list_examples()


def test_run_demo_unknown_name_fails_cleanly(capsys):
    assert D.run_demo("does-not-exist") == 1
    assert "no example" in capsys.readouterr().out


def test_free_port_is_an_int_in_range():
    p = D._free_port()
    assert isinstance(p, int) and 1024 < p < 65536


def test_cli_demo_without_name_lists_examples(capsys):
    assert CLI.main(["demo"]) == 0
    out = capsys.readouterr().out
    assert "taskboard" in out
