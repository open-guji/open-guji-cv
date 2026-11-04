"""按需拉取与整文件表分批取（2026-11-02 中心库维护方案）。

不连库：数据源是内存里的假货，记下每次向库要了哪些文件。"""

from __future__ import annotations

import hashlib
import json

import pytest

from open_guji_cv.datastore import materialize as M
from open_guji_cv.datastore import workcopy as W


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class _Src:
    """files 表若干整文件；记录 files 表每次请求的路径（None = 整表）。"""

    def __init__(self, docs: dict[str, bytes]):
        self.docs = docs
        self.calls: list[list[str] | None] = []

    def rows(self, table, ws=None, cols=None, **filters):
        if table == "source_files":
            return [{"src_path": p, "tbl": "files", "sha256": _sha(b), "bytes": len(b), "n_lines": None,
                     "final_newline": True} for p, b in self.docs.items()]
        if table == "files":
            want = filters.get("src_path")
            self.calls.append(sorted(want) if want is not None else None)
            return [{"src_path": p, "raw": b.decode("utf-8")} for p, b in self.docs.items()
                    if want is None or p in want]
        return []


def _docs(n: int, size: int, prefix: str = "feedback/lists/proofing/b/") -> dict[str, bytes]:
    return {f"{prefix}{i:03d}.pending.json": (json.dumps({"i": i}) + "x" * size).encode() for i in range(n)}


def test_whole_table_fetched_by_path_in_byte_batches(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "WHOLE_BATCH_BYTES", 3000)
    docs = _docs(10, 1000)
    src = _Src(docs)
    st = M.materialize(src, "w", tmp_path / "out", prefixes=("feedback/",), with_images=False)
    assert st["files"] == 10
    assert None not in src.calls                          # 从不整表读
    assert all(len(c) <= 3 for c in src.calls) and sum(len(c) for c in src.calls) == 10
    for p, b in docs.items():
        assert (tmp_path / "out" / p).read_bytes() == b


def test_whole_table_many_files_still_by_path(tmp_path):
    docs = _docs(M.BY_PATH_MAX + 50, 10, prefix="config/x/")
    src = _Src(docs)
    M.materialize(src, "w", tmp_path / "out", prefixes=("config/",), with_images=False)
    assert None not in src.calls
    assert max(len(c) for c in src.calls) <= M.WHOLE_BATCH_FILES


def test_exclude_skips_prefix(tmp_path):
    docs = {**_docs(3, 10), "config/codepoints.yaml": b"a: 1\n"}
    src = _Src(docs)
    st = M.materialize(src, "w", tmp_path / "out", prefixes=("feedback/", "config/"), with_images=False,
                       exclude=("feedback/lists/proofing/",))
    assert st["files"] == 1
    assert (tmp_path / "out" / "config" / "codepoints.yaml").is_file()
    assert not (tmp_path / "out" / "feedback").exists()
    assert src.calls == [["config/codepoints.yaml"]]


def test_pull_exclude_parsing(monkeypatch):
    monkeypatch.delenv(W.PULL_EXCLUDE_ENV, raising=False)
    assert W.pull_exclude() == ()
    assert W.pull_exclude(["run"]) == W.RUN_EXCLUDE
    monkeypatch.setenv(W.PULL_EXCLUDE_ENV, "run, review/batches/")
    assert W.pull_exclude(["review/batches/"]) == W.RUN_EXCLUDE + ("review/batches/",)
    monkeypatch.setenv(W.PULL_EXCLUDE_ENV, "-")
    assert W.pull_exclude() == ()
    with pytest.raises(SystemExit):
        W.pull_exclude(["../x"])
    with pytest.raises(SystemExit):
        W.pull_exclude(["workspace.yaml"])


def test_partial_copy_refuses_push_and_sync(tmp_path, monkeypatch):
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home"))
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "workspace.yaml").write_text("id: tws\n")
    (ws / ".central.json").write_text('{"ws": "tws", "branch": "main"}')
    data = W.data_dir(ws)
    data.mkdir(parents=True)
    W.write_state(data, ws="tws", branch="main", rev=1, base={}, exclude=list(W.RUN_EXCLUDE))
    with pytest.raises(SystemExit, match="部分副本"):
        W.push(None, ws, actor="t")
    with pytest.raises(SystemExit, match="部分副本"):
        W.sync(None, None, ws, actor="t")
