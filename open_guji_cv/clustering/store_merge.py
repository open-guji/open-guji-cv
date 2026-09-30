# -*- coding: utf-8 -*-
"""字形库 store 的三方合并与删除护栏（2026-09-28，overview#234）。

## 事故
`scripts/glyph_store_sync.py` 原来每轮先 `export_store`（拿服务器 db 整份覆盖工作区的
`output/glyph_store/`），提交之后才 `pull --rebase`。09-28 H 往 ws main 进了 14 例「聞」；服务器
pull 下来之后 db 并不知道，下一轮导出就把这 14 行和 patch 当成「db 里没有」删掉、提交、推了上去
（ws `7a1863a3`）。反过来，别人在 main 上撤的刻例 db 里还有，下一轮会被写回去。

## 做法：以 git 里的 store 为公共祖先，做三方合并，增量套进 db
- **base** = 上一次 db 与 store 对齐时的 store 树（同步脚本在推送成功 / 合并完成后记下它的 tree sha；
  没记过就取最近一条「定时同步」提交里的树）；
- **theirs** = pull 之后 HEAD 里的 store 树；
- **ours** = 本机 db。

逐个实例比「记录」（实例行 + 图块 blob sha + exemplar 行 + 准入行）：
- base 与 theirs 相同 → 别人没动，不管；
- db == theirs → 已经一致；
- db == base（db 没动过）→ 照 theirs 办：theirs 有就把那一例原样装进 db，theirs 没有就撤库（记撤例审计）；
- 两边都动过 → 取时间戳新的一边（准入 `admitted_at` / 实例 `updated_at` / exemplar `added_at`
  与撤例审计的 `at`）；分不出先后时**保留有数据的一边**（宁可多留，不删）。

**不整库重建**：服务器 db 里还有字体域（不导出、重建后要 `import-font` 约 10 分钟）、未导出的人裁
（重建后按水位线补放，但别人进的新刻例会把水位线推后，服务器那段就补不回来）。增量套用只动别人
改过的那些实例，db 自己的改动原封不动。

## 删除护栏
`export_store` 是整份覆盖。导出前算「这次会从 store 删掉哪些实例」，只有 db 的 `evictions` 撤例审计
（`evict_instance` 写）或体检台账 `glyph_selfcheck/decisions.jsonl` 的撤库裁决能解释的才放行，
其余一律拒绝导出（宁可不同步，也不删数据）。

## 近似字侧表（2026-09-29，overview#276）
`approx_labels` 一行挂在一个实例上，算进这个实例的「记录」（`Rec.apx`）：别人标了近似、db 没动
→ 照 theirs 装；别人撤了近似 → 照 theirs 删；两边都动过 → 同样按时间戳（`created_at` 与撤销审计
`approx_clears.at`）。删除护栏同样管它：实例留着、近似标记却要从 store 消失的，必须有 db 的
`approx_clears`（或撤例审计）能解释，否则整本拒绝导出（`unexplained_approx_deletions`）。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


# ── git 读树 ─────────────────────────────────────────────

def _git(repo: Path, *args: str, text: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=text)


def tree_sha(repo: Path, rev: str, rel: str) -> str | None:
    """`rev` 里 `rel` 目录的 tree sha；不存在返回 None。"""
    r = _git(repo, "rev-parse", "--verify", "--quiet", f"{rev}:./{rel}")
    return r.stdout.strip() or None if r.returncode == 0 else None


def tree_exists(repo: Path, sha: str | None) -> bool:
    return bool(sha) and _git(repo, "cat-file", "-e", f"{sha}^{{tree}}").returncode == 0


def last_sync_tree(repo: Path, rel: str) -> str | None:
    """最近一条碰过 `rel` 的「定时同步」提交里 `rel` 的树（同步脚本第一次跑新逻辑时当 base）。"""
    r = _git(repo, "log", "-1", "--format=%H", "--grep=^定时同步", "--", rel)
    sha = r.stdout.strip()
    return tree_sha(repo, sha, rel) if sha else None


def blob_sha(data: bytes) -> str:
    """git 的 blob sha1（与 `git ls-tree` 给的一致），用来不读 PNG 就比图块。"""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


class TreeStore:
    """git 树里的一份 store（只读）。"""

    def __init__(self, repo: Path, tree: str):
        self.repo, self.tree = Path(repo), tree
        self.files: dict[str, str] = {}
        r = _git(self.repo, "ls-tree", "-r", "-z", tree)
        for ent in r.stdout.split("\0"):
            if not ent:
                continue
            meta, path = ent.split("\t", 1)
            self.files[path] = meta.split()[2]

    def blob(self, sha: str) -> bytes:
        return subprocess.run(["git", "cat-file", "blob", sha], cwd=self.repo,
                              capture_output=True, check=True).stdout

    def jsonl(self, path: str) -> list[dict]:
        sha = self.files.get(path)
        if not sha:
            return []
        return [json.loads(l) for l in self.blob(sha).decode("utf-8").splitlines() if l.strip()]

    def patch_sha(self, iid: str) -> str | None:
        return self.files.get(f"patches/{iid.replace(':', '_')}.png")


class DirStore(TreeStore):
    """工作区里的一份 store（单测和护栏用）。"""

    def __init__(self, root: Path):                     # noqa: D401 —— 不调 super：不走 git
        self.root = Path(root)
        self.files = {p.relative_to(self.root).as_posix(): str(p)
                      for p in self.root.rglob("*") if p.is_file()} if self.root.exists() else {}

    def blob(self, sha: str) -> bytes:                  # 这里的 "sha" 就是文件路径
        return Path(sha).read_bytes()

    def patch_sha(self, iid: str) -> str | None:
        p = self.files.get(f"patches/{iid.replace(':', '_')}.png")
        return blob_sha(Path(p).read_bytes()) if p else None


# ── 记录 ────────────────────────────────────────────────

@dataclass
class Rec:
    """一个实例在 store 里的全部痕迹。`__eq__` 就是「这一例有没有被改过」。"""
    inst: dict | None = None
    patch: str | None = None
    ex: tuple = ()
    adm: dict | None = None
    apx: dict | None = None             # 近似字侧表那一行（overview#276）
    apx_cleared: str | None = None      # 最近一次撤近似标记的时间（只参与 stamp，不算内容）

    def key(self) -> tuple:
        return (json.dumps(self.inst, sort_keys=True, ensure_ascii=False),
                self.patch, self.ex,
                json.dumps(self.adm, sort_keys=True, ensure_ascii=False),
                json.dumps(self.apx, sort_keys=True, ensure_ascii=False))

    def __eq__(self, other) -> bool:
        return isinstance(other, Rec) and self.key() == other.key()

    @property
    def present(self) -> bool:
        return bool(self.inst or self.ex or self.adm)

    def stamp(self) -> datetime | None:
        ts = [(self.adm or {}).get("admitted_at"), (self.inst or {}).get("updated_at")]
        ts += [e[3] for e in self.ex]
        ts += [(self.apx or {}).get("created_at"), self.apx_cleared]
        ds = [d for d in map(parse_ts, ts) if d]
        return max(ds) if ds else None


def parse_ts(ts) -> datetime | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _norm_inst(d: dict) -> dict:
    """实例行按导出口径规范化（导出时去掉 patch_png、未评的可信度两列不写）。"""
    d = {k: v for k, v in d.items() if k != "patch_png"}
    for k in ("fidelity", "fidelity_by"):
        if d.get(k) is None:
            d.pop(k, None)
    return d


def store_records(st: TreeStore, with_patch: bool = True) -> dict[str, Rec]:
    recs: dict[str, Rec] = {}
    for path in sorted(p for p in st.files if p.startswith("instances/") and p.endswith(".jsonl")):
        for r in st.jsonl(path):
            recs.setdefault(r["instance_id"], Rec()).inst = _norm_inst(r)
    ex: dict[str, list] = {}
    for r in st.jsonl("exemplars.jsonl"):
        ex.setdefault(r["instance_id"], []).append(
            (r["edition_tag"], r["char"], r["role"], r["added_at"]))
    for iid, rows in ex.items():
        recs.setdefault(iid, Rec()).ex = tuple(sorted(rows))
    for r in st.jsonl("admissions.jsonl"):
        recs.setdefault(r["instance_id"], Rec()).adm = r
    for r in st.jsonl("approx_labels.jsonl"):
        recs.setdefault(r["instance_id"], Rec()).apx = r
    for r in st.jsonl("approx_clears.jsonl"):
        rec = recs.get(r["instance_id"])
        if rec is not None and (rec.apx_cleared or "") < (r.get("at") or ""):
            rec.apx_cleared = r.get("at")
    if with_patch:
        for iid, rec in recs.items():
            if rec.inst is not None:
                rec.patch = st.patch_sha(iid)
    return recs


def _font_editions(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT edition_tag FROM sources WHERE kind='font'")}


def db_record(conn: sqlite3.Connection, iid: str) -> Rec:
    """db 里一个实例、按导出口径（只含会导出的部分）。"""
    conn.row_factory = sqlite3.Row
    try:
        rec = Rec()
        row = conn.execute("SELECT * FROM instances WHERE instance_id=?", (iid,)).fetchone()
        ex = conn.execute(
            "SELECT g.edition_tag, g.char, e.role, e.added_at FROM exemplars e "
            "JOIN glyphs g ON g.glyph_id=e.glyph_id WHERE e.instance_id=?", (iid,)).fetchall()
        rec.ex = tuple(sorted(tuple(r) for r in ex))
        # 与 export_store 同口径：没定字、又不是刻例的实例不导出
        if row is not None and (row["label"] is not None or rec.ex):
            d = dict(row)
            rec.patch = blob_sha(bytes(d["patch_png"]))
            rec.inst = _norm_inst(d)
        adm = conn.execute("SELECT * FROM admissions WHERE instance_id=?", (iid,)).fetchone()
        rec.adm = dict(adm) if adm else None
        try:
            apx = conn.execute("SELECT * FROM approx_labels WHERE instance_id=?", (iid,)).fetchone()
            rec.apx = dict(apx) if apx else None
            clr = conn.execute("SELECT max(at) FROM approx_clears WHERE instance_id=?", (iid,)).fetchone()
            rec.apx_cleared = clr[0] if clr else None
        except sqlite3.OperationalError:
            pass                                        # 老库没有近似字侧表
        return rec
    finally:
        conn.row_factory = None


def db_evicted_at(conn: sqlite3.Connection, iid: str) -> datetime | None:
    try:
        ts = [r[0] for r in conn.execute("SELECT at FROM evictions WHERE instance_id=?", (iid,))]
    except sqlite3.OperationalError:
        return None
    ds = [d for d in map(parse_ts, ts) if d]
    return max(ds) if ds else None


# ── 合并 ────────────────────────────────────────────────

@dataclass
class MergeReport:
    changed_upstream: int = 0
    added: list = field(default_factory=list)
    updated: list = field(default_factory=list)
    evicted: list = field(default_factory=list)
    already: int = 0
    kept_ours: list = field(default_factory=list)     # 两边都改、留了 db 的
    took_theirs: list = field(default_factory=list)   # 两边都改、取了上游的
    evictions_merged: int = 0
    approx_clears_merged: int = 0

    def summary(self) -> dict:
        return {"changed_upstream": self.changed_upstream, "added": len(self.added),
                "updated": len(self.updated), "evicted": len(self.evicted),
                "already": self.already, "conflict_kept_ours": self.kept_ours[:20],
                "conflict_took_theirs": self.took_theirs[:20],
                "evictions_merged": self.evictions_merged,
                "approx_clears_merged": self.approx_clears_merged}

    @property
    def touched(self) -> bool:
        return bool(self.added or self.updated or self.evicted or self.took_theirs
                    or self.evictions_merged or self.approx_clears_merged)


def _recount(cur, gids) -> None:
    from .glyph_db import K_MIN, _now
    for gid in gids:
        n = cur.execute("SELECT count(*) FROM exemplars WHERE glyph_id=?", (gid,)).fetchone()[0]
        if n:
            cur.execute(f"UPDATE glyphs SET n_confirmed=?, status=CASE WHEN ? >= {K_MIN} "
                        "THEN 'stable' ELSE status END, updated_at=? WHERE glyph_id=?",
                        (n, n, _now(), gid))
        else:
            cur.execute("DELETE FROM glyphs WHERE glyph_id=?", (gid,))


def _install(db, st: TreeStore, iid: str, rec: Rec, glyph_rows: dict, source_rows: dict) -> None:
    """把 store 里的一例原样装进 db（先清掉 db 里同 id 的旧行，不记撤例：这是替换不是撤）。"""
    import cv2
    import numpy as np

    from .normalize import normalize_patch
    cur = db.conn.cursor()
    old_gids = [r[0] for r in cur.execute("SELECT glyph_id FROM exemplars WHERE instance_id=?",
                                          (iid,))]
    for t in ("approx_labels", "admissions", "exemplars", "derived", "instances"):
        cur.execute(f"DELETE FROM {t} WHERE instance_id=?", (iid,))
    patch = st.files.get(f"patches/{iid.replace(':', '_')}.png")
    if rec.inst is not None and patch:                  # 没图块的实例行不装（同 rebuild_from_store）
        src = rec.inst.get("source_id")
        if src and src in source_rows:
            r = source_rows[src]
            cur.execute(f"INSERT OR IGNORE INTO sources ({','.join(r)}) "
                        f"VALUES ({','.join('?' * len(r))})", tuple(r.values()))
        raw = st.blob(patch)
        d = {**rec.inst, "patch_png": raw}
        cur.execute(f"INSERT INTO instances ({','.join(d)}) VALUES ({','.join('?' * len(d))})",
                    tuple(d.values()))
        gray = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
        db._write_derived(cur, iid, normalize_patch(gray))
    new_gids = []
    for ed, ch, role, added_at in rec.ex:
        row = cur.execute("SELECT glyph_id FROM glyphs WHERE edition_tag=? AND char=?",
                          (ed, ch)).fetchone()
        if row is None:
            g = {k: v for k, v in (glyph_rows.get((ed, ch)) or {
                "edition_tag": ed, "char": ch, "semantic": ch,
                "unicode_cp": ord(ch) if len(ch) == 1 else None,
                "status": "sparse", "n_confirmed": 0,
                "updated_at": added_at}).items()}
            cur.execute(f"INSERT INTO glyphs ({','.join(g)}) VALUES ({','.join('?' * len(g))})",
                        tuple(g.values()))
            row = (cur.lastrowid,)
        cur.execute("INSERT OR REPLACE INTO exemplars VALUES (?,?,?,?)",
                    (row[0], iid, role, added_at))
        new_gids.append(row[0])
    if rec.adm is not None:
        a = rec.adm
        cur.execute(f"INSERT OR REPLACE INTO admissions ({','.join(a)}) "
                    f"VALUES ({','.join('?' * len(a))})", tuple(a.values()))
    if rec.apx is not None and rec.inst is not None and patch:
        x = rec.apx
        cur.execute(f"INSERT OR REPLACE INTO approx_labels ({','.join(x)}) "
                    f"VALUES ({','.join('?' * len(x))})", tuple(x.values()))
    _recount(cur, set(old_gids) | set(new_gids))


def merge_upstream(db, repo: Path, base_tree: str, cur_tree: str) -> MergeReport:
    """把 base→cur 这段上游改动套进 db（规则见模块头）。db 自己的改动不动。"""
    from .audit import evict_instance
    from .glyph_db import _borrowed
    rep = MergeReport()
    base, cur = TreeStore(repo, base_tree), TreeStore(repo, cur_tree)
    rb, rc = store_records(base), store_records(cur)
    borrowed = _borrowed(db)[0]
    glyph_rows = {(r["edition_tag"], r["char"]): r for r in cur.jsonl("glyphs.jsonl")}
    source_rows = {r["source_id"]: r for r in cur.jsonl("sources.jsonl")}
    ev_cur: dict[str, datetime] = {}
    for r in cur.jsonl("evictions.jsonl"):
        d = parse_ts(r.get("at"))
        if d and (r["instance_id"] not in ev_cur or d > ev_cur[r["instance_id"]]):
            ev_cur[r["instance_id"]] = d
    empty = Rec()
    for iid in sorted(set(rb) | set(rc)):
        b, t = rb.get(iid, empty), rc.get(iid, empty)
        if b == t or iid in borrowed:
            continue
        rep.changed_upstream += 1
        o = db_record(db.conn, iid)
        if o == t:
            rep.already += 1
            continue
        if o == b:
            take = True
        else:
            # 两边都改过：新的赢；拿不准就留有数据的一边
            to = o.stamp() if o.present else db_evicted_at(db.conn, iid)
            tt = t.stamp() if t.present else ev_cur.get(iid)
            if to and tt and to != tt:
                take = tt > to
            else:
                take = t.present and not o.present
            (rep.took_theirs if take else rep.kept_ours).append(iid)
            if not take:
                continue
        if t.present:
            (rep.updated if o.present else rep.added).append(iid)
            _install(db, cur, iid, t, glyph_rows, source_rows)
        else:
            evict_instance(db, iid, reason="glyph_store_sync: 上游已撤")
            rep.evicted.append(iid)
    # 上游的撤例审计也并进来，删除护栏与下一次合并都认它
    c = db.conn.cursor()
    for r in cur.jsonl("evictions.jsonl"):
        c.execute("INSERT OR IGNORE INTO evictions (instance_id, char, reason, at) VALUES (?,?,?,?)",
                  (r["instance_id"], r.get("char"), r.get("reason"), r["at"]))
        rep.evictions_merged += c.rowcount
    for r in cur.jsonl("approx_clears.jsonl"):
        c.execute("INSERT OR IGNORE INTO approx_clears (instance_id, label, at) VALUES (?,?,?)",
                  (r["instance_id"], r.get("label"), r["at"]))
        rep.approx_clears_merged += c.rowcount
    db.conn.commit()
    return rep


# ── 删除护栏 ────────────────────────────────────────────

def db_export_ids(conn: sqlite3.Connection) -> set[str]:
    """db 导出后 store 里会有的实例 id（与 export_store 同口径：非字体、非借来）。"""
    fe = _font_editions(conn)
    ids = set()
    for iid, ed in conn.execute(
            "SELECT e.instance_id, g.edition_tag FROM exemplars e JOIN glyphs g USING(glyph_id)"):
        if ed not in fe:
            ids.add(iid)
    for iid, kind in conn.execute(
            "SELECT i.instance_id, COALESCE(s.kind,'woodblock') FROM instances i "
            "LEFT JOIN sources s ON s.source_id=i.source_id WHERE i.label IS NOT NULL"):
        if kind != "font":
            ids.add(iid)
    for iid, in conn.execute("SELECT instance_id FROM admissions"):
        ids.add(iid)
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='borrowed'"
                    ).fetchone():
        ids -= {r[0] for r in conn.execute("SELECT instance_id FROM borrowed")}
    return ids


def _selfcheck_evictions(db_path: Path) -> dict[str, datetime | None]:
    """体检台账里的撤库裁决：{实例 id: 裁决时间}。"""
    out: dict[str, datetime | None] = {}
    f = Path(db_path).parent / "glyph_selfcheck" / "decisions.jsonl"
    if not f.exists():
        return out
    for line in f.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("v") == "evict":
            out[d.get("target") or d.get("instance_id")] = parse_ts(d.get("ts"))
    return out


def planned_deletions(conn: sqlite3.Connection, store_dir: Path) -> dict[str, Rec]:
    """这次导出会从 store 删掉的实例：{id: store 里的记录}。"""
    recs = store_records(DirStore(store_dir), with_patch=False)     # 护栏只看 id 与准入时间，不读图
    keep = db_export_ids(conn)
    return {iid: r for iid, r in recs.items() if iid not in keep}


def unexplained_deletions(db_path: Path, conn: sqlite3.Connection, store_dir: Path) -> dict:
    """删除护栏：{"planned": n, "explained": n, "unexplained": [id, ...]}。

    一例准删 = db 的撤例审计（或体检台账撤库裁决）里有它，且时间不早于 store 里那一例的准入时间
    （防「撤了又进、之后又被别的路径静默删掉」拿旧审计蒙混过关）。
    """
    planned = planned_deletions(conn, store_dir)
    sc = _selfcheck_evictions(db_path)
    bad = []
    for iid, rec in planned.items():
        admitted = parse_ts((rec.adm or {}).get("admitted_at"))
        ts = [db_evicted_at(conn, iid)]
        if iid in sc:
            ts.append(sc[iid] or datetime.max.replace(tzinfo=timezone.utc))
        ts = [t for t in ts if t]
        if not ts or (admitted and max(ts) < admitted):
            bad.append(iid)
    return {"planned": len(planned), "explained": len(planned) - len(bad),
            "unexplained": sorted(bad)}


def unexplained_approx_deletions(conn: sqlite3.Connection, store_dir: Path) -> dict:
    """近似字的删除护栏（overview#276）：{"planned": n, "explained": n, "unexplained": [id, ...]}。

    只管「实例还会导出、近似标记却要从 store 消失」的那些（实例整个被删由 `unexplained_deletions`
    管）。准删 = db 的 `approx_clears` 或撤例审计里有它，且时间不早于 store 里那条近似的 `created_at`。
    """
    st = DirStore(store_dir)
    rows = {r["instance_id"]: r for r in st.jsonl("approx_labels.jsonl")}
    if not rows:
        return {"planned": 0, "explained": 0, "unexplained": []}
    try:
        have = {r[0] for r in conn.execute("SELECT instance_id FROM approx_labels")}
    except sqlite3.OperationalError:
        have = set()
    keep = db_export_ids(conn)
    planned = [iid for iid in rows if iid not in have and iid in keep]
    bad = []
    for iid in planned:
        created = parse_ts(rows[iid].get("created_at"))
        ts = [db_evicted_at(conn, iid)]
        try:
            ts += [parse_ts(r[0]) for r in conn.execute(
                "SELECT at FROM approx_clears WHERE instance_id=?", (iid,))]
        except sqlite3.OperationalError:
            pass
        ts = [t for t in ts if t]
        if not ts or (created and max(ts) < created):
            bad.append(iid)
    return {"planned": len(planned), "explained": len(planned) - len(bad),
            "unexplained": sorted(bad)}
