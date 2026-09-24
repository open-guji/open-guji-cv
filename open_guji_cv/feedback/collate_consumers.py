# -*- coding: utf-8 -*-
"""Step8 复核裁决的三个消费者：`collate_ok` / `char_convention` / `variant_deny`。

与 Step7 那批（`consumers.py`）分居一个模块，因为它们回答的是**另一个问题**：

| | Step7 裁决 | Step8 复核 |
|---|---|---|
| 问题 | 这是什么字？ | **我们和校对本，谁对？** |
| 卡从哪来 | `seed_admit` 说「我不确定」 | **对勘说「你跟校对本不一样」** |
| 是否 block | 是 | 否 |

## 三个出口都**不入字形库**（用户 2026-09-22 定）

那一格的字**没有变**——Step7 早已入过库，再入一次只是重复。
只有「校对本对（我们认错了）」那一支要改字，而它**复用 Step7 现成的 `confirm` 通道**，
不在本模块里：改字、入库、失效产物三件事那边都有，不必重造。

## 为什么「我方对」不再细分

曾设计成选完「我方对」再三选一：整理本录错 / 两本底本不同 / 先维持。
**用户否掉：「无法区分，不分拆」**——只看一部校对本时，「整理本录错了」与
「他们底本就是另一个」在证据上**长得一模一样**，分不开却要人选，
只会逼出瞎猜的数据。要真分开得有第二部校对本，那是 9.3-b 的事。
"""

from __future__ import annotations

import json
from pathlib import Path

from .consumers import ConsumeResult

#: 跨书**负样本**表：人推翻过的「通用异体」边。与书级 `char_conventions`
#: （本书专属正样本）方向相反——一个说「这两个字在这本书里等同」，
#: 一个说「这两个字哪儿都不等同」。
#:
#: 存在的理由：关系图会错。2026-09-22 实测查出 `治/冶`、`輨/轄` 两条错边，
#: 而它们正是被「关系图说是异体」送进成果档的，躺了三天没人看见。
DENY_REL = "config/dicts/variants.deny.tsv"


def _repo_path(rel: str) -> Path:
    from ..core.workspace import REPO_ROOT
    return REPO_ROOT / rel


def collate_ok(events, dry_run: bool = False, **kw) -> ConsumeResult:
    """`collate_ok` → 只记账，**不改产物、不入库**。

    含义：「我看过这一格的图了，我们和校对本就是不一样，维持我方转写」。
    它唯一的作用是**下轮对勘不再出这张卡**——否则每次重跑都要重看同样的 71 条。

    账落在事件日志本身（`EventLog.consumed/collate_ok.jsonl` 由
    `route_and_consume` 记），这里不另写文件：**没有副作用要落**。
    """
    res = ConsumeResult("collate_ok", n_events=len(events))
    for e, _d in events:
        if not (e.target.key or "").strip():
            res.errors.append(f"{e.id}: 没有 target.key，记不了账")
            res.skipped += 1
            continue
        res.added += 1
    return res


def char_convention(events, book_path: str = "", dry_run: bool = False,
                    **kw) -> ConsumeResult:
    """`char_convention` → 写 `books/<id>.yaml` 的 `char_conventions`。

    这是**本书专属**的「刻本 × 校对本用字对照表」：`完→元`（女真姓氏「完顏」
    校对本作「元顏」）、`甫→父`（人名「仁甫/仁父」）这类。

    ## 为什么落书配置而不是全局异体表

    用户 2026-09-22：「在这本书里常用，但在另一本书可能就不常用了」。
    `完` 与 `元` 在别的书里就是两个字，进全局表会污染。

    这张表**同时是产物**——它本身有版本学价值，将来可以直接附在成果里。

    ## 不进任何指纹

    已查清（`core/engine._self_payload`）：`book_deps` 是**显式白名单**，
    只对各 Step 声明过的字段取值。yaml 里加 `char_conventions` 不进任何指纹，
    确认通例**不会触发全链重跑**——否则每确认一条就要重跑 54 页，这个设计不成立。
    """
    import yaml

    res = ConsumeResult("char_convention", n_events=len(events))
    by_book: dict[str, list] = {}
    for e, _d in events:
        p = e.payload or {}
        pair, kind = p.get("pair"), p.get("kind")
        bk = e.target.book or (e.target.key or "").split(":")[0]
        if not (pair and len(pair) == 2 and all(pair) and kind and bk):
            res.errors.append(f"{e.id}: 缺 pair/kind/book")
            res.skipped += 1
            continue
        by_book.setdefault(bk, []).append((pair, kind, p.get("note") or "", e))

    for bk, rows in by_book.items():
        path = Path(book_path) if book_path else _books_dir() / f"{bk}.yaml"
        if not path.exists():
            res.errors.append(f"{bk}: 找不到 {path}")
            res.skipped += len(rows)
            continue
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        cur = doc.get("char_conventions") or []
        known = {tuple(c["pair"]) for c in cur if c.get("pair")}
        new = []
        for pair, kind, note, e in rows:
            if tuple(pair) in known:
                res.skipped += 1
                continue
            known.add(tuple(pair))
            new.append({"pair": list(pair), "kind": kind, "note": note,
                        "confirmed": (e.ts or "")[:10], "source_event": e.id})
        if not new:
            continue
        res.added += len(new)
        if dry_run:
            continue
        doc["char_conventions"] = cur + new
        # ⚠️ 保住行尾与既有格式：yaml.safe_dump 会重排全文。这里只在**文件末尾**
        # 追加/替换 char_conventions 一段，其余字节不动——册 yaml 里有大量
        # 带注释的调参记录，重排等于把那些注释全丢了。
        _rewrite_conventions(path, doc["char_conventions"])
    return res


def _books_dir() -> Path:
    from ..core.workspace import workspace_root
    root = workspace_root()
    if root is None:
        raise RuntimeError("没有工作区，定位不到 books/")
    return root / "books"


def _rewrite_conventions(path: Path, rows: list[dict]) -> None:
    """只改 `char_conventions:` 那一段，其余原样。

    册 yaml 里有大量带注释的调参记录（「2026-09-17 把 escalate_threshold 从
    0.85 改 0.95，因为…」），`yaml.safe_dump` 全量重写会把它们连同缩进风格
    一起抹掉。所以这里按行找段、只换那一段。
    """
    import yaml
    txt = path.read_text(encoding="utf-8")
    nl = "\r\n" if "\r\n" in txt else "\n"
    body = yaml.safe_dump({"char_conventions": rows}, allow_unicode=True,
                          sort_keys=False, default_flow_style=False).rstrip("\n")
    block = body.replace("\n", nl)
    lines = txt.split(nl)
    start = next((i for i, ln in enumerate(lines)
                  if ln.startswith("char_conventions:")), None)
    if start is None:
        sep = "" if txt.endswith(nl) else nl
        path.write_text(txt + sep + nl + block + nl, encoding="utf-8", newline="")
        return
    end = start + 1
    while end < len(lines) and (not lines[end].strip() or lines[end][:1] in " -#"):
        end += 1
    path.write_text(nl.join(lines[:start] + block.split(nl) + lines[end:]),
                    encoding="utf-8", newline="")


def mark_jiajie(events, path: str = "", dry_run: bool = False, **kw) -> ConsumeResult:
    """`mark_jiajie` → 写 `config/dicts/jiajie.tsv`（**跨书**通假字对表）。

    异体与通假是**两类**（用户 2026-09-22）：异体是同一个字的不同写法（衞/衛），
    通假是本字不在、借另一个字代替（早/蚤、甫/父）。版本学上两回事，各自审阅。

    自动判据只认得「关系图有边」，分不开这两类，**所以新字对一律先落异体层**，
    人在裁决台点「这是通假」才搬过来。宁可让人搬，不可替人猜——猜错了会把
    「借字」说成「同一个字」，那是版本学上的错话。

    ③ 零星分歧与 ② 本书特有里选了「通假」的字对，也由这条通道搬家。
    """
    from ..report.tiers import JIAJIE_REL
    return _append_pairs(events, "mark_jiajie", path or str(_repo_path(JIAJIE_REL)),
                         dry_run,
                         head=("# 通假字对：本字不在、借另一个字代替（早/蚤、甫/父）。\n"
                               "# 与异体（同一个字的不同写法）分属两类，各自审阅。\n"
                               "# 格式：刻本形\t校对本形\t来源。只追加不删除。\n"
                               "# 由 feedback/collate_consumers.mark_jiajie 写。\n"))


def _append_pairs(events, name: str, path_s: str, dry_run: bool, head: str) -> ConsumeResult:
    """把事件里的 `payload.pair` 追加进一张 TSV，已有的跳过。

    `variant_deny` 与 `mark_jiajie` 共用：两者都是「人给某个字对贴了个跨书标签」，
    只是落点与表头不同。
    """
    res = ConsumeResult(name, n_events=len(events))
    path = Path(path_s)
    known: set[tuple[str, str]] = set()
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                parts = ln.split("\t")
                if len(parts) >= 2:
                    known.add((parts[0], parts[1]))
    rows = []
    for e, _d in events:
        pair = (e.payload or {}).get("pair")
        if not (pair and len(pair) == 2 and all(pair)):
            res.errors.append(f"{e.id}: 缺 pair")
            res.skipped += 1
            continue
        key = (pair[0], pair[1])
        if key in known:
            res.skipped += 1
            continue
        known.add(key)
        rows.append(f"{pair[0]}\t{pair[1]}\thuman:{e.id}")
    res.added = len(rows)
    if rows and not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_head = head if not path.exists() else ""
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            if write_head:
                f.write(write_head)
            f.write("\n".join(rows) + "\n")
    return res


def variant_deny(events, deny_path: str = "", dry_run: bool = False,
                 **kw) -> ConsumeResult:
    """`variant_deny` → 写 `config/dicts/variants.deny.tsv`（**跨书**负样本）。

    人在 ① 通用异体那层点了「不是异体·要改」：这条关系图边从此不算数，
    **任何书**都不再拿它当异体，该字对退回 ③ 逐条判。

    只追加不删除，与 `variants.tsv` 同格式（`异体字<TAB>正字<TAB>来源`），
    多一列来源事件 id 便于回溯。
    """
    return _append_pairs(events, "variant_deny", deny_path or str(_repo_path(DENY_REL)),
                         dry_run,
                         head=("# 人推翻过的「异体」边：任何书都不再拿它当异体。\n"
                               "# 格式：刻本形\t校对本形\t来源。只追加不删除。\n"
                               "# 由 feedback/collate_consumers.variant_deny 写。\n"))


def collate_verdict(events, dry_run: bool = False, **kw) -> ConsumeResult:
    """`collate_verdict` → 只记账（2026-09-24 两层分类）。

    状态本身就在事件日志里（`collate_state.human_verdicts` 读回），没有别的文件要写；
    改字、标通假这些副作用由同一次提交里另写的 `confirm` / `mark_jiajie` /
    `unmark_jiajie` 各走各的消费者。
    """
    res = collate_ok(events, dry_run=dry_run)
    res.consumer = "collate_verdict"
    return res


def unmark_jiajie(events, path: str = "", dry_run: bool = False, **kw) -> ConsumeResult:
    """`unmark_jiajie` → 从 `jiajie.tsv` 删掉**本书标的**那行。

    字对被人从「通假字」挪走、本书里再没有一处归通假时发。`jiajie.tsv` 是跨书表，
    所以只删来源是本书复核批次（`human:evt_<book>-collate_…`）的行——别的书标的
    不归这本书撤。
    """
    from ..report.tiers import JIAJIE_REL
    res = ConsumeResult("unmark_jiajie", n_events=len(events))
    p = Path(path or str(_repo_path(JIAJIE_REL)))
    drop: set[tuple[str, str, str]] = set()
    for e, _d in events:
        pl = e.payload or {}
        pair, book = pl.get("pair"), pl.get("book") or e.target.book
        if not (pair and len(pair) == 2 and book):
            res.errors.append(f"{e.id}: 缺 pair/book")
            res.skipped += 1
            continue
        drop.add((pair[0], pair[1], f"human:evt_{book}-collate_"))
    if not drop or not p.exists():
        res.skipped += len(drop)
        return res
    keep, n = [], 0
    for ln in p.read_text(encoding="utf-8").splitlines():
        parts = ln.split("\t")
        if (not ln.startswith("#") and len(parts) >= 3
                and any(parts[0] == a and parts[1] == b and parts[2].startswith(src)
                        for a, b, src in drop)):
            n += 1
            continue
        keep.append(ln)
    res.added = n
    if n and not dry_run:
        p.write_text("\n".join(keep) + "\n", encoding="utf-8", newline="\n")
    return res


COLLATE_CONSUMERS = {
    "collate_ok": collate_ok,
    "char_convention": char_convention,
    "variant_deny": variant_deny,
    "mark_jiajie": mark_jiajie,
    "collate_verdict": collate_verdict,
    "unmark_jiajie": unmark_jiajie,
}
