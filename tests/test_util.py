"""safe_name must reduce any input to a single safe path segment (path-traversal
guard — this is a security boundary for everything written under workspace/)."""
from area._util import safe_name


def test_strips_path_traversal():
    assert safe_name("../../etc/passwd") == "etc-passwd"
    assert "/" not in safe_name("a/b/c")
    assert ".." not in safe_name("..")


def test_keeps_safe_chars():
    assert safe_name("my-app_01") == "my-app_01"


def test_empty_falls_back_to_default():
    assert safe_name("") == "app"
    assert safe_name("   ") == "app"
    assert safe_name("///") == "app"
    assert safe_name("", default="x") == "x"


def test_trims_edge_separators():
    assert safe_name("-weird-") == "weird"
    assert safe_name("__a__") == "a"
