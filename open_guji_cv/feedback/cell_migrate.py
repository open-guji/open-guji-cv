"""换图源迁票：按格级对照表把旧人裁／待审票迁到新格（GUJI-748，设计稿 `doc/design/殿本换图源-siku-qiefen-v2.md` §三、§七）。

**只出提案，不写库**：输入旧人裁事件、网站票和格级对照表，输出新格上的事件行、票行和一张「没迁过去」的清单。

对照表（A31 出，ai-team `…/siku-qiefen-v2/results/old_new_cells/<册>.tsv`，可 gzip）列：
`旧格 新格 旧字 新字 类别 IoU 说明`；类别 同格／改号／删／新增。旧格框经页变换后与新格框按 IoU 一对一配对，
**不按同编号**——所以这里也不看编号是否相同，只看表。表里旧格必须取**出单那一版**的切分（`mkcells.py` 的旧产物根），
迁票用的表和标点实体重挂（A33）、字形库改键（A24）是同一张。

迁什么：每格**最新一条人裁 confirm**（`web_votes.latest_human` 口径）。更早被盖掉的、非格级的（切线、整页框等）、
机器事件都不迁，只在报告里数。不迁的人裁和票逐条列进 `pending.tsv` 并给理由，交新待审单处理，不丢、不自动裁：

    表里没有   旧格不在表里（出单版不对，或不是这一册）
    删         新图上没有对应的格（含没对上的页、重拍页）
    IoU低      配上了但 IoU < 门槛（缺省 0.5）
    合并冲突   两个旧格配到同一个新格，且裁决不同
    旧绑定失效 给了旧 main 绑定（``--bind``）而这条在旧 main 上没认上格（review／void／unanchored）

给了旧 main 绑定时按**绑定格**查表（rebound 的原始 key 偏一格）。迁出的事件没有框，新包首跑前要给它们写补锚档
``feedback/anchors/<册>.jsonl``（ai-team ``…/siku-qiefen-v2/scripts/mk_anchors.py``），否则字形库里没有当时图块的
（网站票等）在新包上判 ``unanchored`` 被丢（vol04 10-26 首跑 100 条）。

新事件（人裁）：id、批次名各加 ``~q``（seq、ts 不变，「后到覆盖」的次序保持）；``target.key/page/col/slot`` 换成新格；
``target.anchor`` 只写 ``migrated_from``（旧格键、旧事件 id，改绑过的另记 ``bound``）和 ``source_rev``（新页表 rev），**不带框与图块凭证**——
写入时 ``enrich_events`` 按新产物补 bbox／content_sha，旧的 evidence 指纹换图后必然对不上，故意不带。
``payload.overrides`` 指向的旧事件若也迁了就改指新 id，否则去掉。旧事件不删。

对「定字不同」（表里旧字≠新字）的格：人裁照迁（人优先），另列 ``watch.tsv``，供新 main 出来后核对变字是否进待审。

核对：``输入 = 迁出 + 合并 + 没迁`` 每份报告都算一遍，对不上就是工具的 bug，直接抛错。
"""
from __future__ import annotations

import csv
import gzip
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .anchor import parse_cell_key
from .events import Event
from .web_votes import HUMAN_VS, latest_human, same_verdict

SUFFIX = "~q"
MIN_IOU = 0.5
COLS = ("旧格", "新格", "旧字", "新字", "类别", "IoU", "说明")


@dataclass
class Row:
    old: str
    new: str
    old_char: str
    new_char: str
    kind: str
    iou: float
    note: str

    @property
    def char_changed(self) -> bool:
        return bool(self.old_char and self.new_char and self.old_char != self.new_char)


def load_table(path: str | Path) -> list[Row]:
    p = Path(path)
    opener = gzip.open if p.suffix == ".gz" else open
    with opener(p, "rt", encoding="utf-8", newline="") as f:
        rd = csv.reader(f, delimiter="\t")
        head = next(rd)
        if tuple(head[:len(COLS)]) != COLS:
            raise ValueError(f"{p}：表头应为 {COLS}，实际 {head}")
        rows = []
        for r in rd:
            if not r:
                continue
            r = (r + [""] * len(COLS))[:len(COLS)]
            rows.append(Row(r[0], r[1], r[2], r[3], r[4], float(r[5] or 0), r[6]))
    return rows


@dataclass
class Pending:
    what: str              # 人裁／票
    key: str               # 旧格键
    reason: str
    detail: str = ""       # 裁决或票的大白话


@dataclass
class Result:
    book: str
    source_rev: str
    min_iou: float
    events: list[dict] = field(default_factory=list)       # 新事件（model_dump）
    id_map: dict[str, str] = field(default_factory=dict)   # 旧事件 id → 新事件 id
    votes: list[dict] = field(default_factory=list)
    pending: list[Pending] = field(default_factory=list)
    watch: list[tuple[str, str, str, str, str]] = field(default_factory=list)   # 旧格, 新格, 旧字, 新字, 人裁/票
    n_events_in: int = 0
    n_merged: int = 0
    n_votes_in: int = 0
    n_watch_events: int = 0
    ignored: Counter = field(default_factory=Counter)      # 没处理的事件：(kind, unit)/被盖掉

    def reasons(self, what: str) -> Counter:
        return Counter(p.reason for p in self.pending if p.what == what)

    def check(self) -> None:
        pe = sum(self.reasons("人裁").values())
        if self.n_events_in != len(self.events) + self.n_merged + pe:
            raise AssertionError(f"人裁数对不上：输入 {self.n_events_in} ≠ 迁出 {len(self.events)} + 合并 {self.n_merged} + 没迁 {pe}")
        pv = sum(self.reasons("票").values())
        if self.n_votes_in != len(self.votes) + pv:
            raise AssertionError(f"票数对不上：输入 {self.n_votes_in} ≠ 迁出 {len(self.votes)} + 没迁 {pv}")


def _lookup(rows: list[Row], book: str, min_iou: float):
    """旧格键 → (Row, 拒绝理由|None)。同一旧格出现多行时取 IoU 最大的。"""
    best: dict[str, Row] = {}
    for r in rows:
        if r.old and r.old.split(":", 1)[0] == book and (r.old not in best or r.iou > best[r.old].iou):
            best[r.old] = r

    def look(key: str) -> tuple[Row | None, str | None, str]:
        r = best.get(key)
        if r is None:
            return None, "表里没有", "旧格不在对照表里（出单版是否对？册号是否对？）"
        if r.kind == "删" or not r.new:
            return r, "删", r.note or "新图上没有对应的格"
        if r.iou < min_iou:
            return r, "IoU低", f"IoU {r.iou:.3f} < {min_iou}"
        return r, None, ""
    return look


def _label(payload: dict) -> str:
    v = payload.get("v") or ""
    extra = payload.get("shape") or payload.get("reason") or payload.get("quality") or payload.get("guess") or ""
    return f"{v} {extra}".strip()


def migrate_events(events, rows: list[Row], book: str, source_rev: str, *, min_iou: float = MIN_IOU,
                   result: Result | None = None, bindings: dict[str, dict] | None = None) -> Result:
    """``bindings``：旧 main 上的现行绑定 ``{事件 id: {bound, status}}``（`bindings.book_bindings`）。给了就按
    **绑定格**查表——rebound 的事件原始 key 偏了一格，按 key 迁会落到邻格（vol04 10-26 有 7 条）；
    旧 main 上没认上格的（review／void／unanchored）本来就没采信，不迁，列进待审。"""
    res = result or Result(book, str(source_rev), min_iou)
    look = _lookup(rows, book, min_iou)
    evs = []
    for e in events:
        if (e.target.anchor or {}).get("migrated_from"):
            res.ignored["已是迁移事件（新页号）"] += 1     # 数据目录里已有上一轮迁出的 ~q 事件，不再迁
        else:
            evs.append(e)
    latest = latest_human(evs)
    keep = {e.id for e in latest.values()}
    for e in evs:
        t = e.target
        if e.id in keep:
            continue
        if t.unit == "cell" and e.kind == "confirm" and (e.payload or {}).get("v") in HUMAN_VS:
            res.ignored["被同格更晚的人裁盖掉"] += 1
        else:
            res.ignored[f"非格级人裁 {e.kind}/{t.unit}"] += 1
    res.n_events_in += len(latest)

    by_new: dict[str, list[tuple[Event, Row]]] = defaultdict(list)
    src: dict[str, str] = {}
    for e in sorted(latest.values(), key=lambda e: (e.ts, e.batch, e.seq)):
        k = e.target.key
        if bindings is not None and e.id in bindings:
            from .bindings import usable
            b = bindings[e.id] or {}
            u = usable(b) if "status" in b else b.get("bound")
            if not u:
                res.pending.append(Pending("人裁", k, "旧绑定失效",
                                           f"{_label(e.payload)}（{e.id}）；旧 main 上 {b.get('status')}，本来就没采信"))
                continue
            k = u
        src[e.id] = k
        r, why, detail = look(k)
        if why:
            res.pending.append(Pending("人裁", k, why, f"{_label(e.payload)}（{e.id}）；{detail}"))
            continue
        by_new[r.new].append((e, r))

    for new_key, group in by_new.items():
        group.sort(key=lambda g: (g[0].ts, g[0].batch, g[0].seq))
        win_e, win_r = group[-1]
        losers = []
        for e, r in group[:-1]:
            if src[e.id] == src[win_e.id]:
                # 改绑后与更晚的事件落在旧 main 的同一格：旧 main 上就是后到覆盖（bindings R1），不算冲突
                res.ignored["被同格更晚的人裁盖掉"] += 1
                res.n_events_in -= 1
                res.id_map[e.id] = win_e.id + SUFFIX
            elif same_verdict(e.payload, win_e.payload):
                res.n_merged += 1                     # 同一个裁决落到同一格，留最晚那条
                res.id_map[e.id] = win_e.id + SUFFIX
            else:
                losers.append((e, r))
        for e, r in losers:
            res.pending.append(Pending("人裁", e.target.key, "合并冲突",
                                       f"{_label(e.payload)}（{e.id}）与 {win_e.target.key} 的 {_label(win_e.payload)} 同配到 {new_key}"))
        res.events.append(_new_event(win_e, new_key, source_rev, win_r, bound=src[win_e.id]))
        res.id_map[win_e.id] = win_e.id + SUFFIX
        if win_r.char_changed:
            res.watch.append((src[win_e.id], new_key, win_r.old_char, win_r.new_char, _label(win_e.payload)))
            res.n_watch_events += 1

    for d in res.events:                              # overrides 指向的旧事件迁了就换新 id，没迁就去掉
        o = d["payload"].get("overrides")
        if o:
            if o in res.id_map:
                d["payload"]["overrides"] = res.id_map[o]
            else:
                del d["payload"]["overrides"]
    return res


def _new_event(e: Event, new_key: str, source_rev: str, r: Row, bound: str | None = None) -> dict:
    pk = parse_cell_key(new_key)
    d = e.model_dump(mode="json")
    t = d["target"]
    mf = {"key": e.target.key, "id": e.id}
    if bound and bound != e.target.key:
        mf["bound"] = bound                          # 旧 main 上改绑到的格（按它查的表）
    t["anchor"] = {"migrated_from": mf, "source_rev": str(source_rev)}
    t["key"] = new_key
    if pk is not None:
        t["book"], t["page"], t["col"], t["slot"] = pk[0], pk[1], pk[2], pk[3]
    d["id"] = e.id + SUFFIX
    d["batch"] = e.batch + SUFFIX
    d["payload"] = {**(e.payload or {}), "migrated_iou": round(r.iou, 3)}
    return d


def migrate_votes(votes: list[dict], rows: list[Row], book: str, source_rev: str, *, min_iou: float = MIN_IOU,
                  new_rev: str | None = None, result: Result | None = None) -> Result:
    """``votes`` 已经 `web_votes.latest_votes` 过（本书本 rev 的合法票）。票上的 ``a`` 不带册号，如 ``15:8:20``。"""
    res = result or Result(book, str(source_rev), min_iou)
    look = _lookup(rows, book, min_iou)
    res.n_votes_in += len(votes)
    for v in votes:
        key = f"{book}:{v['a']}"
        r, why, detail = look(key)
        lab = v["choice"] + (f"={v['char']}" if v.get("char") else "")
        if why:
            res.pending.append(Pending("票", key, why, f"{lab}（{v.get('voter', '')}）；{detail}"))
            continue
        nv = {**v, "a": r.new.split(":", 1)[1], "migrated_from_a": v["a"], "source_rev": str(source_rev)}
        if new_rev:
            nv["rev"] = new_rev
        res.votes.append(nv)
        if r.char_changed:
            res.watch.append((key, r.new, r.old_char, r.new_char, lab))
    return res


def write_report(res: Result, out: Path, *, cells_path: str = "", extra: dict | None = None) -> None:
    res.check()
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "events.jsonl", "w", encoding="utf-8") as f:
        for d in res.events:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    with open(out / "votes.jsonl", "w", encoding="utf-8") as f:
        for d in res.votes:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    with open(out / "id_map.tsv", "w", encoding="utf-8") as f:
        f.write("旧事件id\t新事件id\n")
        for a, b in sorted(res.id_map.items()):
            f.write(f"{a}\t{b}\n")
    with open(out / "pending.tsv", "w", encoding="utf-8") as f:
        f.write("类别\t旧格\t理由\t说明\n")
        for p in res.pending:
            f.write(f"{p.what}\t{p.key}\t{p.reason}\t{p.detail}\n")
    with open(out / "watch.tsv", "w", encoding="utf-8") as f:
        f.write("旧格\t新格\t旧字\t新字\t人裁或票\n")
        for r in res.watch:
            f.write("\t".join(r) + "\n")
    pe, pv = res.reasons("人裁"), res.reasons("票")
    n_moved = sum(1 for d in res.events if d["payload"] and d["target"]["anchor"]["migrated_from"]["key"] != d["target"]["key"])
    L = [f"# {res.book} 迁票提案（只读，没有写库）", "",
         f"- 对照表：{cells_path or '—'}；新页表 rev：{res.source_rev}；IoU 门槛 {res.min_iou}", "",
         "## 人裁（每格最新一条）", "",
         f"- 输入 {res.n_events_in} = 迁出 {len(res.events)} + 合并 {res.n_merged} + 没迁 {sum(pe.values())}（核对通过）",
         f"- 迁出里新格键与旧格键不同的 {n_moved} 条（页号重编，预期几乎全部）；人裁字与新字不同、需新 main 出来后复核的 {res.n_watch_events} 格（watch.tsv 共 {len(res.watch)} 行，含票）"]
    L += [f"- 没迁：{k} {n}" for k, n in sorted(pe.items())]
    if res.n_votes_in:
        L += ["", "## 待审票", "",
              f"- 输入 {res.n_votes_in} = 迁出 {len(res.votes)} + 没迁 {sum(pv.values())}（核对通过）"]
        L += [f"- 没迁：{k} {n}" for k, n in sorted(pv.items())]
    if res.ignored:
        L += ["", "## 没处理的事件（不在迁移范围）", ""] + [f"- {k}：{n}" for k, n in sorted(res.ignored.items())]
    for k, v in (extra or {}).items():
        L.append(f"\n- {k}：{v}")
    L += ["", "文件：events.jsonl（新事件）、votes.jsonl（新格上的票）、id_map.tsv（旧→新事件 id，待审单 `prior.id` 按它改）、"
          "pending.tsv（没迁的，进新待审单）、watch.tsv（定字不同的格）。"]
    (out / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
