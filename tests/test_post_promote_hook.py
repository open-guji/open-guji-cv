from open_guji_cv import cli_products as CP


class _EP:
    def __init__(self, name, fn):
        self.name, self._fn = name, fn

    def load(self):
        return self._fn


def test_plugins_called_with_book_label_ws(monkeypatch):
    seen = []
    monkeypatch.setattr("importlib.metadata.entry_points", lambda group: [_EP("ok", lambda b, l, w: seen.append((b, l, w)))])
    CP._run_post_promote("vol13", "lbl", "/ws")
    assert seen == [("vol13", "lbl", "/ws")]


def test_plugin_error_does_not_block_promote(monkeypatch, capsys):
    def boom(*a):
        raise RuntimeError("x")
    ran = []
    monkeypatch.setattr("importlib.metadata.entry_points",
                        lambda group: [_EP("bad", boom), _EP("good", lambda b, l, w: ran.append(1))])
    CP._run_post_promote("vol13", "lbl", None)
    assert ran == [1] and "bad" in capsys.readouterr().err


def test_entry_points_lookup_failure_is_ignored(monkeypatch):
    def fail(group):
        raise OSError("no metadata")
    monkeypatch.setattr("importlib.metadata.entry_points", fail)
    CP._run_post_promote("vol13", "lbl", None)
