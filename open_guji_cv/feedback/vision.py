"""看图结论：模型看图判的「这格放行字对不对」（overview#428，2026-10-06）。

S8 / S10 里模型放大字块看图下的结论，以前只写进 md，攒不成强真值。这里给它一条事件通道：
`guji events import-vision <jsonl> -w <工作区>` 把整理那边存的 jsonl 写成 `kind="vision_check"`、
`actor="model"`、`payload.source="vision"`、`payload.judge=<模型名>` 的事件。

**它不是人裁**——模型判的可能有错，不能和用户亲裁混在一起：

- 存 `<feedback>/vision/<批次>.jsonl`，**不进 `feedback/events/`**。读人裁的地方几十处都直接扫
  `events/`（`human_chars`、`decided_view`、绑定表、replay、收尾闸……），放在一起只要漏一处就成了
  「人裁」；分目录是缺省安全。那些读者另外都过了 `events.counts_as_human`，误写进 `events/`
  的 `vision_check`／`source="vision"` 事件也不认（双保险）。注意**不是按 `actor="model"` 排除**：
  `events/` 里早有码位统一、乱码还原这类 `actor="model"` 的人裁机械更正，它们得照旧生效；
- 不进字形库、`human_chars` 不认、不算「已裁」（格不会被藏出队列）、不进绑定表；
- 进裁决表（金标）时 `label_origin="vision"`，分片 `VISION_SHARD`，评测按来源分层；
- 判 `wrong` 的格**只用来送人审**：`review/cards.py` 把它捞回待审队列、挂 doubt `vision_flag`
  和 `vision` 字段，不改字、不碰 Step。人在控制台裁过（写出普通的 user confirm）才算数。

## jsonl 格式（一行一格，UTF-8）

    {"cell": "vol04:12:3:5", "v": "wrong", "char": "曰", "shown": "日", "judge": "claude-opus-5-5",
     "note": "中横右端不接框", "group": "日曰", "ref": "曰", "ts": "2026-10-06T09:00:00Z"}

| 键 | 必填 | 说明 |
|---|---|---|
| `cell` | 是 | 字位 id `<册>:<页>:<列>:<格>`（夹注格末尾带 a/b），与控制台、事件同一口径 |
| `v` | 是 | `ok`（放行字对）/ `wrong`（放行字错）/ `unsure`（看不出） |
| `char` | `wrong` 时建议填 | 看图认为该是的字（单字）；认不出可留空，照样送审 |
| `shown` | 建议 | 判的时候这格放行的是什么字。用来认「已经改过了」：现行字 ≠ `shown` 时不再送审 |
| `judge` | 是 | 模型名；命令行 `--judge` 可给缺省值 |
| `note` / `group` / `ref` | 否 | 理由 / 形近组（己已巳、日曰、入人八…）/ 整理本此位的字 |
| `ts` | 否 | 判的时刻（ISO，UTC）；缺省取导入时刻 |

别的键一律报错（防手误拼错键名静默丢字段）。同一格多行按 `ts` 后到覆盖。

**只追加**：批次缺省 `vision-<文件名>`，`seq` = 行号，所以同一文件改完再导一遍，没动的行不重复写；
想改结论就在文件末尾追加一行新的，别改旧行（改了旧行会按新内容另记一条，旧的留在账上）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .anchor import parse_cell_key
from .events import Event, EventLog, EventTarget, make_event
from .mojibake import is_legal_shape

VERDICTS = ("ok", "wrong", "unsure")
#: 裁决表里看图结论的分片。与人裁的分片分开，`gold import` 要显式点名才进测试集。
VISION_SHARD = "char-recognition/vision-checks"
#: 待审卡上的 doubt 码。
VISION_DOUBT = "vision_flag"
_KEYS = {"cell", "v", "char", "shown", "judge", "note", "group", "ref", "ts"}
_STEP = "seed_admit"


class VisionLog(EventLog):
    """看图结论的日志：同 `EventLog` 的格式与追加纪律，只是落 `<feedback>/vision/`。"""

    @property
    def events_dir(self) -> Path:
        return self.root / "vision"

    @property
    def consumed_dir(self) -> Path:
        return self.root / "vision_consumed"


@dataclass
class ParseResult:
    events: list[Event] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def default_batch(path: Path) -> str:
    return f"vision-{Path(path).stem}"


def parse_jsonl(path: Path, batch: str, judge: str | None = None, ts: str | None = None,
                book: str | None = None) -> ParseResult:
    """jsonl → 事件（不落盘）。有一行不合格式就记一条错，合格的照出——调用方决定要不要整批拒收。"""
    res = ParseResult()
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    for no, line in enumerate(lines, 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        where = f"第 {no} 行"
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            res.errors.append(f"{where}：不是 JSON（{e.msg}）")
            continue
        if not isinstance(row, dict):
            res.errors.append(f"{where}：要一个对象")
            continue
        bad = sorted(set(row) - _KEYS)
        if bad:
            res.errors.append(f"{where}：不认识的键 {bad}（只认 {sorted(_KEYS)}）")
            continue
        cell = str(row.get("cell") or "").strip()
        pk = parse_cell_key(cell)
        if pk is None:
            res.errors.append(f"{where}：cell {cell!r} 不是 <册>:<页>:<列>:<格>")
            continue
        if book and pk[0] != book:
            res.errors.append(f"{where}：{cell} 不是 {book} 的格")
            continue
        v = str(row.get("v") or "").strip()
        if v not in VERDICTS:
            res.errors.append(f"{where}：v={v!r}，只认 {'/'.join(VERDICTS)}")
            continue
        jd = str(row.get("judge") or judge or "").strip()
        if not jd:
            res.errors.append(f"{where}：缺 judge（模型名），或命令行给 --judge")
            continue
        bad_shape = [k for k in ("char", "shown", "ref") if row.get(k) and not is_legal_shape(str(row[k]))]
        if bad_shape:
            res.errors.append(f"{where}：{bad_shape} 不是单字")
            continue
        payload = {"source": "vision", "judge": jd, "v": v}
        for k in ("char", "shown", "note", "group", "ref"):
            if row.get(k):
                payload[k] = str(row[k])
        bk, page, col, slot, _sub = pk
        target = EventTarget(step=_STEP, unit="cell", key=cell, book=bk, page=page, col=col, slot=slot)
        res.events.append(make_event(batch, no, "vision_check", target, payload, actor="model",
                                     ts=str(row.get("ts") or "") or ts))
    return res


def import_vision(path: Path, log: VisionLog | None = None, batch: str | None = None,
                  judge: str | None = None, book: str | None = None, gold: bool = True,
                  gold_store=None, dry_run: bool = False) -> dict:
    """jsonl → `feedback/vision/` 事件（+ 裁决表 `VISION_SHARD`，`label_origin="vision"`）。

    **有错就整批不写**：一册的看图结论是一份账，写一半等于账对不上。"""
    log = log or VisionLog()
    batch = batch or default_batch(path)
    pr = parse_jsonl(path, batch, judge, book=book)
    out = {"file": str(path), "batch": batch, "rows": len(pr.events), "errors": pr.errors,
           "by_v": {v: sum(1 for e in pr.events if e.payload["v"] == v) for v in VERDICTS},
           "path": str(log.batch_path(batch)), "dry_run": dry_run}
    if pr.errors or dry_run:
        out["written"] = 0
        return out
    out["written"] = log.append(pr.events)
    if gold:
        out["gold"] = vision_gold(pr.events, gold_store)
    return out


def vision_gold(events: list[Event], store=None) -> dict:
    """看图结论 → 裁决表（`gold_add` 记 `label_origin="vision"`；`unsure` 记 uncertain）。"""
    from .consumers import gold_add, verdict_store
    from .routes import Destination
    pairs = [(e, Destination("gold_add", shard=VISION_SHARD)) for e in events if e.kind == "vision_check"]
    return gold_add(pairs, store=store or verdict_store(), why="看图结论导入").to_dict()


def rebuild_vision_gold(log: VisionLog | None = None, store=None) -> dict:
    """`gold rebuild` 用：从 `feedback/vision/` 全量重放看图结论进裁决表（幂等，按 id upsert）。"""
    log = log or VisionLog()
    if not log.events_dir.exists():
        return {"events": 0}
    evs = sorted(log.iter_all(), key=lambda e: e.order)
    return {"events": len(evs), **vision_gold(evs, store)}


def vision_checks(book: str, log: VisionLog | None = None) -> dict[str, dict]:
    """这本书每格**最新**一条看图结论 → `{字位: {v, char, shown, judge, note, group, ts, id}}`。"""
    out: dict[str, dict] = {}
    pre = f"{book}:"
    log = log or VisionLog()
    try:
        evs = sorted(log.iter_all(), key=lambda e: (e.ts, e.batch, e.seq))
    except FileNotFoundError:
        return out
    for e in evs:
        if e.kind != "vision_check" or not e.target.key.startswith(pre):
            continue
        p = e.payload or {}
        out[e.target.key] = {**{k: p.get(k) for k in ("v", "char", "shown", "judge", "note", "group")},
                             "ts": e.ts, "id": e.id}
    return out


def flag_active(chk: dict | None, current: str | None) -> bool:
    """这条看图结论现在还该不该把格送回人审：最新一条判 `wrong`，且现行字没已经改成看图认的字、
    也没换掉判的那个字（`shown` 给了且 ≠ 现行字 = 字已经动过，旧结论说的不是现在这个字）。"""
    if not chk or chk.get("v") != "wrong":
        return False
    if chk.get("char") and current == chk["char"]:
        return False
    if chk.get("shown") and current is not None and current != chk["shown"]:
        return False
    return True


def vision_flags(book: str, log: VisionLog | None = None) -> dict[str, dict]:
    """最新一条判 `wrong` 的格（不看现行字；现行字的比较在 `flag_active`）。"""
    return {k: v for k, v in vision_checks(book, log).items() if v.get("v") == "wrong"}


def vision_pending(book: str, pages: list[int], store=None, log: VisionLog | None = None,
                   decided: set[str] | None = None) -> list[dict]:
    """收尾报告项：看图判错、人还没裁、现行字仍是判错的那个的格。**不要求为 0**——是给人扫的单子，
    清掉它的办法是在控制台裁（`doubt=vision_flag` 一键筛出来）。→ `[{id, page, char, vision, judge}]`。"""
    from ..core.spec import page_key
    from ..products.store import ProductStore
    from ..report.slots import ADMIT_KIND, ADMIT_STEP
    flags = vision_flags(book, log)
    if not flags:
        return []
    if decided is None:
        from ..review.verdict_view import decided_cells
        decided = decided_cells(book)
    st = store or ProductStore()
    want: dict[int, set[str]] = {}
    for k in flags:
        if k not in decided:
            want.setdefault(int(k.split(":")[1]), set()).add(k)
    out: list[dict] = []
    for pg in pages:
        ids = want.get(pg)
        if not ids:
            continue
        a = st.read(book, ADMIT_STEP, page_key(pg), ADMIT_KIND)
        if a is None:
            continue
        for cc in a.columns:
            for r in cc.chars:
                if r.id in ids and flag_active(flags[r.id], r.char):
                    out.append({"id": r.id, "page": pg, "char": r.char, "vision": flags[r.id].get("char"),
                                "judge": flags[r.id].get("judge")})
    return out
