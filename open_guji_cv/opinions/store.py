"""意见池的五个文件（设计 2.1）：本地数据目录，或经 Worker ``/v1/files`` 读写中心库（``base_sha`` 乐观锁）。

| 文件 | 写法 |
|---|---|
| ``opinions.jsonl`` | 只追加；同 id 重复追加被拒 |
| ``log.jsonl`` | 只追加 |
| ``raw-feedback.jsonl`` | 按 id 去重合并 |
| ``text_versions.json`` | 整文件替换 |
| ``cv_events_todo.jsonl`` | 只追加 |

本地路径缺省是数据目录 ``$GUJI_DATA_HOME/<分支>/<工作区>/feedback/lists/opinions/<书>/``（``guji db sync`` 会把它推进中心库）；
``root`` 给了就是 ``<root>/<书>/``（试跑、测试、不想进中心库的判定）。远端是中心库同一路径 ``feedback/lists/opinions/<书>/…``。

只追加的文件保存时把新行接在**读到的原文**后面，原有字节不动；读后别人改过（sha 对不上）就报冲突、不覆盖。
"""
from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path

from .schema import LogEvent, Opinion, SchemaError, derive_status, now_iso

FILES = {
    "opinions": "opinions.jsonl",
    "log": "log.jsonl",
    "raw": "raw-feedback.jsonl",
    "versions": "text_versions.json",
    "cv_todo": "cv_events_todo.jsonl",
    # 自动化（doc/design 修订流程自动化设计）：发布批、格谱系、度量，都只追加
    "releases": "releases.jsonl",
    "lineage": "lineage.jsonl",
    "metrics": "metrics.jsonl",
}
APPEND_ONLY = ("opinions", "log", "cv_todo", "releases", "lineage", "metrics")
REMOTE_DIR = "feedback/lists/opinions/{book}"


class StoreConflict(RuntimeError):
    """读后文件被别人改过（base_sha 对不上）。"""


class DuplicateId(SchemaError):
    pass


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _jsonl(text: str) -> list[dict]:
    out = []
    for i, line in enumerate((text or "").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError as e:
            raise SchemaError(f"第 {i} 行不是 JSON：{e}") from None
    return out


def _line(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"))


class LocalBackend:
    def __init__(self, root: Path):
        self.root = Path(root)

    def describe(self) -> str:
        return str(self.root)

    def read(self, name: str) -> tuple[str | None, str | None]:
        p = self.root / name
        if not p.is_file():
            return None, None
        t = p.read_text(encoding="utf-8")
        return t, sha256_text(t)

    def write(self, name: str, text: str, base_sha: str | None) -> dict:
        _cur, sha = self.read(name)
        if sha != base_sha:
            raise StoreConflict(f"{self.root / name} 读后被改过（{base_sha} → {sha}），重读再写")
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / (name + ".tmp")
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, self.root / name)
        return {"sha256": sha256_text(text)}


class RemoteBackend:
    """中心库 Worker ``/v1/files``：``GET ?ws=&src_path=`` 取整文件，``PUT`` 整文件替换（带 ``base_sha``）。"""

    def __init__(self, worker, ws: str, book: str, branch: str | None = None):
        self.w, self.ws = worker, ws
        self.branch = branch or getattr(worker, "branch", "main")
        self.dir = REMOTE_DIR.format(book=book)

    def describe(self) -> str:
        return f"中心库 {self.ws}@{self.branch}:{self.dir}/"

    def _q(self, **kw) -> dict:
        return {"branch": self.branch, "ws": self.ws, **kw}

    def read(self, name: str) -> tuple[str | None, str | None]:
        from ..datastore.client import CentralError
        try:
            r = self.w._call("GET", "/v1/files", query=self._q(src_path=f"{self.dir}/{name}"))
        except CentralError as e:
            if e.status == 404:
                return None, None
            raise
        if not r:
            return None, None
        return r.get("text"), r.get("sha256")

    def list(self) -> list[dict]:
        return self.w._call("GET", "/v1/files", query=self._q(prefix=self.dir + "/")).get("files") or []

    def write(self, name: str, text: str, base_sha: str | None) -> dict:
        body = {"text": text}
        if base_sha:
            body["base_sha"] = base_sha
        return self.w._call("PUT", "/v1/files", query=self._q(src_path=f"{self.dir}/{name}"), body=body, tries=2)


class OpinionStore:
    """一本书的意见池。``load()`` 读五个文件进内存，改动先记在内存里，``save()`` 才写回。"""

    def __init__(self, book: str, backend, by: str = "tool"):
        self.book, self.backend, self.by = book, backend, by
        self._text: dict[str, str | None] = {}
        self._sha: dict[str, str | None] = {}
        self.opinions: dict[str, Opinion] = {}
        self.events: list[LogEvent] = []
        self.raw: dict[str, dict] = {}
        self.text_versions: dict = {}
        self.cv_todo: list[dict] = []
        self.releases: list[dict] = []
        self.lineage: list[dict] = []
        self.metrics: list[dict] = []
        self._new_rows: dict[str, list[dict]] = {"releases": [], "lineage": [], "metrics": []}
        self._new_ops: list[Opinion] = []
        self._new_events: list[LogEvent] = []
        self._new_todo: list[dict] = []
        self._raw_dirty = False
        self._versions_dirty = False

    # ---- 读 ----
    def load(self) -> OpinionStore:
        for key, name in FILES.items():
            self._text[key], self._sha[key] = self.backend.read(name)
        for d in _jsonl(self._text["opinions"] or ""):
            op = Opinion.from_dict(d)
            if op.id in self.opinions:
                raise DuplicateId(f"opinions.jsonl 里 id 重复：{op.id}")
            self.opinions[op.id] = op
        self.events = [LogEvent.from_dict(d) for d in _jsonl(self._text["log"] or "")]
        self.raw = {d["id"]: d for d in _jsonl(self._text["raw"] or "") if d.get("id")}
        self.text_versions = json.loads(self._text["versions"]) if self._text["versions"] else {}
        self.cv_todo = _jsonl(self._text["cv_todo"] or "")
        self.releases = _jsonl(self._text["releases"] or "")
        self.lineage = _jsonl(self._text["lineage"] or "")
        self.metrics = _jsonl(self._text["metrics"] or "")
        return self

    def release_latest(self) -> dict[str, dict]:
        """发布批按 id 取最后一行（状态变更是追加同 id 新行，最后一行为准）。"""
        out: dict[str, dict] = {}
        for r in self.releases:
            out[r["id"]] = r
        return out

    def add_row(self, kind: str, row: dict) -> None:
        """追加一行发布批（releases）、格谱系（lineage）或度量（metrics）。"""
        if kind not in self._new_rows:
            raise KeyError(kind)
        getattr(self, kind).append(row)
        self._new_rows[kind].append(row)

    def events_of(self, op_id: str) -> list[LogEvent]:
        return [e for e in self.events if e.opinion == op_id]

    def status(self, op_id: str) -> str:
        return derive_status(self.events_of(op_id))

    def statuses(self) -> dict[str, str]:
        by = defaultdict(list)
        for e in self.events:
            by[e.opinion].append(e)
        return {i: derive_status(by.get(i, [])) for i in self.opinions}

    def last(self, op_id: str, kind: str) -> LogEvent | None:
        evs = [e for e in self.events_of(op_id) if e.kind == kind]
        return evs[-1] if evs else None

    def get(self, op_id: str) -> Opinion:
        if op_id in self.opinions:
            return self.opinions[op_id]
        hits = [i for i in self.opinions if i.startswith(op_id)]
        if len(hits) == 1:
            return self.opinions[hits[0]]
        raise KeyError(f"意见池里没有 {op_id}" + (f"（前缀对上 {len(hits)} 条）" if hits else ""))

    # ---- 改（只在内存里，save 才写）----
    def add(self, op: Opinion, *, log: bool = True, log_data: dict | None = None) -> Opinion:
        op.validate()
        if op.book != self.book:
            raise SchemaError(f"{op.id} 的 book={op.book}，不是本池 {self.book}")
        if op.id in self.opinions:
            raise DuplicateId(f"{op.id} 已在池里（同 id 不重写；要改就记 superseded 再追加新 id）")
        if not op.created_at:
            op.created_at = now_iso()
        self.opinions[op.id] = op
        self._new_ops.append(op)
        if log:
            self.log(op.id, "ingested", log_data or {})
        return op

    def log(self, op_id: str, kind: str, data: dict | None = None, by: str | None = None,
            ts: str | None = None) -> LogEvent:
        if op_id not in self.opinions:
            raise KeyError(f"意见池里没有 {op_id}")
        ev = LogEvent(ts=ts or now_iso(), opinion=op_id, kind=kind, by=by or self.by, data=data or {}).validate()
        self.events.append(ev)
        self._new_events.append(ev)
        return ev

    def merge_raw(self, rec: dict) -> bool:
        """通用反馈 ``fb_`` 原样存档：按 id 去重，同 id 内容变了（站方改了状态、回复）就以新的为准。"""
        rid = rec.get("id")
        if not rid:
            raise SchemaError("raw-feedback 记录缺 id")
        if self.raw.get(rid) == rec:
            return False
        self.raw[rid] = rec
        self._raw_dirty = True
        return True

    def set_text_versions(self, tv: dict) -> bool:
        if tv == self.text_versions:
            return False
        self.text_versions = tv
        self._versions_dirty = True
        return True

    def add_cv_todo(self, draft: dict) -> None:
        self.cv_todo.append(draft)
        self._new_todo.append(draft)

    # ---- 写 ----
    def pending(self) -> dict[str, int]:
        return {"opinions": len(self._new_ops), "log": len(self._new_events),
                "raw": int(self._raw_dirty), "versions": int(self._versions_dirty), "cv_todo": len(self._new_todo),
                **{k: len(v) for k, v in self._new_rows.items()}}

    def _rendered(self) -> dict[str, str]:
        """要写的文件 → 新全文。只追加的文件 = 读到的原文（补齐末尾换行）+ 新行。"""
        out = {}

        def appended(key: str, rows: list[dict]) -> str:
            old = self._text[key] or ""
            if old and not old.endswith("\n"):
                old += "\n"
            return old + "".join(_line(r) + "\n" for r in rows)

        if self._new_ops:
            out["opinions"] = appended("opinions", [o.to_dict() for o in self._new_ops])
        if self._new_events:
            out["log"] = appended("log", [e.to_dict() for e in self._new_events])
        if self._new_todo:
            out["cv_todo"] = appended("cv_todo", self._new_todo)
        for k, rows in self._new_rows.items():
            if rows:
                out[k] = appended(k, rows)
        if self._raw_dirty:
            out["raw"] = "".join(_line(self.raw[k]) + "\n" for k in sorted(self.raw))
        if self._versions_dirty:
            out["versions"] = json.dumps(self.text_versions, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
        return out

    def save(self, *, only: list[str] | None = None) -> dict[str, dict]:
        """写回有改动的文件（``only`` 只写这几个 key）。返回 {文件名: 后端回执}。"""
        res = {}
        for key, text in self._rendered().items():
            if only is not None and key not in only:
                continue
            res[FILES[key]] = self.backend.write(FILES[key], text, self._sha[key])
            self._text[key], self._sha[key] = text, sha256_text(text)
        self._new_ops, self._new_events, self._new_todo = [], [], []
        self._new_rows = {k: [] for k in self._new_rows}
        self._raw_dirty = self._versions_dirty = False
        return res

    def touch(self, key: str) -> None:
        """把还不存在的文件建成空文件（第一次入池时把五个文件都建出来）。"""
        if self._text.get(key) is None:
            if key == "versions":
                self._versions_dirty = True
            elif key == "raw":
                self._raw_dirty = True


def default_root(ws_id: str, branch: str = "main") -> Path:
    from ..core.workspace import central_data_dir
    return central_data_dir(ws_id, branch) / "feedback" / "lists" / "opinions"


def open_store(book: str, *, ws: str | None = None, root: str | Path | None = None, remote: bool = False,
               token_env: str = "GUJI_DATA_TOKEN", branch: str = "main", by: str = "tool") -> OpinionStore:
    """按参数选后端并读入。``remote`` 经 Worker（令牌只从环境变量 ``token_env`` 读，不打印）；
    否则本地：``root`` 给了用 ``<root>/<书>/``，不给用数据目录。"""
    if remote:
        from ..datastore.client import WorkerSource
        tok = os.environ.get(token_env)
        if not tok:
            raise SystemExit(f"缺环境变量 {token_env}（中心库令牌）")
        if not ws:
            raise SystemExit("--remote 要给工作区 id（--ws）")
        backend = RemoteBackend(WorkerSource(token=tok, branch=branch), ws, book, branch)
    else:
        if root is None:
            if not ws:
                raise SystemExit("本地意见池要给 --root，或给 --ws 用数据目录")
            root = default_root(ws, branch)
        backend = LocalBackend(Path(root) / book)
    return OpinionStore(book, backend, by=by).load()
