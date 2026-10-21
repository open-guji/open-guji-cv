#!/usr/bin/env python3
"""粗校台账：统一人审率口径（GUJI-667 / D6.1；口径用户 2026-10-20 定，设计 doc/design/M9-平台粗校-调研与总设计.md D6-1）。

    人审率 ＝ 正文页送 M10 的待审格数 ÷ 正文页字格总数（不含标题槽、不含非字格）
    重切清单格数、非正文页待审数另报。

此前至少三套口径（close-check 审卡队列、pending.json 格数、人审率分析的「去标题槽」），同一册 vol04
报过 0.78%／0.88%／1.27%／1.35%。本脚本是唯一的算法：`review_rate()` 纯函数算数，CLI 取数并追加一行台账。

用法：
  python scripts/zhengli/ledger.py --ws <工作区> --book vol04 \\
      [--pending <NNN.pending.json>] [--pages-json <NNN.pages.json>] [--recut <册-重切清单.tsv>] \\
      [--punct <NNN.punct.json>] [--out <台账.jsonl>]
缺省：pages.json 取 `guji export format` 的默认落点 `<工作区>/reports/<册>/<NNN>.pages.json`；
pending 取数据目录 `feedback/lists/proofing/*/<NNN>.pending.json`（恰好一份才用，否则要 --pending）；
重切清单取数据目录 `feedback/lists/<册>-重切清单.tsv`（没有就当空单）；
台账取数据目录 `feedback/lists/ledger/<册>.jsonl`（数据目录 = `ops.release_gates.lists_dir()`，迁过中心库的
工作区落在 `$GUJI_DATA_HOME/<分支>/<工作区 id>/`）。只读产物，只写台账一个文件。

## 各项怎么判（都复用现有数据字段，不另立规则）

- **送 M10 的待审格**：pending.json（book-text F-OV-07：`cells[]` 每项有 `cell`＝锚点 `页:列:格[a|b]`
  与 `review`）里的格，按 `cell` 去重。`review` 是 M10 的进度（pending／human…），**不影响是否计入**——
  送过去就算；各状态的数另报在 `review_status`。
- **字格／非字格**：以导出的 pages.json（`guji-pages/0.1`，`formats/guji_format.to_guji_format`）为准。
  它的 `cells[]` 就是字格（guji-page 的 glyph）；非字格在导出时已经被 `report/slots._to_slot` 摘成
  `marks`（`kind=excluded`：排除名单·非字、印章区放行空字 `lane_seal`、坐标对位说空格的遮挡格
  `occluded.ref_blank`；`kind=blank`：版式留白），不进 `cells`——即 runbook S17「close-check 待审数 ≠
  导出 pending 数，差的是非字格」那条口径。所以分母天然不含非字格；分子里落在非字 mark 上的待审格
  计入 `nonchar_review`、不进人审率。
- **标题槽**：cv 产物里**没有**标记标题的字段（Step1–7 都不判标题；`report/absent.py` 的卷端题／卷末题
  要拿语料查「证人里有没有」，是对勘用的，不是标题判定）。现有数据里唯一明写标题的是 book-text 的
  punct 层（GUJI-240，`kind: heading`，`pos: before` 锚标题首字，标题到下一个分段符 `kind: break` 为止）。
  所以：给了 `--punct` 就按它的 heading→break 区间（按 pages.json 格序、用锚点对）扣标题槽；**没给就
  不扣**，`title_source` 记 `none`。四庫總目 vol04–10 现在还没有 punct（只有 001–003 有），这几册的数
  **含标题槽**——与人审率分析（去标题槽，口径未入库）会差一点，差的就是卷端题列。
- **正文页**：页型逐页按以下来源取，先到先用，`page_type_source` 记各来源页数：
  1. pages.json 页上的 `page.page_type`（guji-page §3.1，导出时 `--meta` 给的；现有 meta 都没给）；
  2. 工作区裁决表 `page-type` 分片（`feedback.consumers.verdict_store()`，`eval/touching._pages_of_type`
     同一来源，「这本书的事实」）；
  3. 产物 `border_detect_gate` 的 `page_type`（Step1 闸1，`clustering.page_type.classify_page_type`）。
  正文 ＝ `page_type` 为 `body` 或 `blank`（空栏页是 body 子类，`page_type.py` 用户 09-13 定；职名 roster、
  目录 toc 算非正文）。**近似**：第 3 条来源只分得出
  封面／书签／空栏／牌记／上諭，职名、目录在切分前分不开、一律记成 body（`page_type.py` 实测职名 31 页、
  目录 47 页全归 body）；三条都没有的页按 body 计（同 `page_type.py`「存疑一律归 body」），记在
  `pages_untyped`。没有裁决表的册，职名／目录页的待审会算进正文——看 `page_type_source`。
- **重切清单**：`ops.release_gates.RecutList`（页／页:列／格三种粒度，close-check 2c/2d 同一份解析）。
  `recut_cells` ＝ 正文页字格（去标题槽）里被清单覆盖的格数；**不从人审率里扣**（用户口径：另报）。
  待审格同时在清单上的数另报 `review_on_recut`。

同一输入重算结果相同（除 `ts`）：所有计数按键排序输出，输入文件另记 sha256。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

LEDGER_SCHEMA = "guji-rough-ledger/0.1"
#: 口径名：改口径就换名，台账里新旧行才分得开。
RATE_DEF = "D6-1：正文页 pending 格 ÷ 正文页字格（去标题槽、非字格）"
#: 正文页型。`blank`（空栏页）是 body 的子类（`clustering.page_type` 2026-09-13 用户定），一并算正文；
#: 职名 roster、目录 toc 虽同套九列网格，按用户口径是非正文。
BODY_TYPES = frozenset({"body", "blank"})
NONE_KEY = "none"                     # 待审格没写 cls／why 时计在这个键下（同 proof_fields.NO_DOUBT）


# ---------------------------------------------------------------- 纯函数
def _anchor_page(a: str) -> int:
    return int(a.split(":", 1)[0])


def _strip_book(cell: str) -> str:
    """`vol04:9:7:17` → `9:7:17`（pending 规范里不带册前缀，带了也认）。"""
    parts = cell.split(":")
    return ":".join(parts[1:]) if len(parts) == 4 else cell


def _mark_anchor(m: dict, page_of_marks: int | None) -> str | None:
    """非字 mark 的锚点：excluded 有 `cv_id`（`book:页:列:格`）；blank 只有 `col`＝`cN` 与 `slot`。"""
    if m.get("cv_id"):
        return _strip_book(str(m["cv_id"]))
    col, slot = m.get("col"), m.get("slot")
    if page_of_marks is None or not isinstance(col, str) or not col.startswith("c") or slot is None:
        return None
    return f"{page_of_marks}:{col[1:]}:{slot}"


def index_pages(pages_json: dict) -> dict:
    """pages.json → 字格（按格序）、非字格、每页的 page_type（若导出带了）。"""
    glyphs: list[tuple[str, int]] = []           # (锚点, 页)，导出顺序即阅读顺序
    nonchar: dict[str, str] = {}                 # 锚点 → mark kind
    ptype: dict[int, str] = {}
    for p in pages_json.get("pages", []):
        pg_cells = [c["a"] for c in p.get("cells", []) if c.get("a")]
        ws_page = _anchor_page(pg_cells[0]) if pg_cells else None
        if ws_page is None:
            for m in p.get("marks", []):
                if m.get("cv_id"):
                    ws_page = _anchor_page(_strip_book(str(m["cv_id"])))
                    break
        if ws_page is None and isinstance(p.get("page"), dict) and isinstance(p["page"].get("index"), int):
            ws_page = p["page"]["index"]
        for a in pg_cells:
            glyphs.append((a, _anchor_page(a)))
        for m in p.get("marks", []):
            if m.get("kind") in ("excluded", "blank"):
                a = _mark_anchor(m, ws_page)
                if a:
                    nonchar[a] = m["kind"]
        t = (p.get("page") or {}).get("page_type") if isinstance(p.get("page"), dict) else None
        if t and ws_page is not None:
            ptype[ws_page] = str(t)
    return {"glyphs": glyphs, "nonchar": nonchar, "page_types": ptype}


def title_cells(order: list[str], punct: dict | None) -> tuple[set[str], int]:
    """punct 的 heading→下一个 break（含）覆盖的字格锚点；返回 (锚点集, 对不上的 heading 数)。

    按锚点在 pages.json 格序里找；heading 锚点不在、或到下一个 heading 之前找不到 break 的，算对不上、不扣。"""
    if not punct:
        return set(), 0
    pos = {a: i for i, a in enumerate(order)}
    items = punct.get("punctuations") or []
    heads = sorted(pos[p["anchor"]] for p in items
                   if p.get("kind") == "heading" and p.get("anchor") in pos)
    unresolved = sum(1 for p in items if p.get("kind") == "heading" and p.get("anchor") not in pos)
    breaks = sorted(pos[p["anchor"]] for p in items if p.get("kind") == "break" and p.get("anchor") in pos)
    out: set[str] = set()
    for k, s in enumerate(heads):
        nxt = heads[k + 1] if k + 1 < len(heads) else len(order)
        e = next((b for b in breaks if b >= s), None)
        if e is None or e >= nxt:
            unresolved += 1
            continue
        out.update(order[s:e + 1])
    return out, unresolved


def review_rate(pages_json: dict, pending_json: dict, *, body_only: bool = True,
                page_types: dict[int, str] | None = None, punct: dict | None = None,
                recut=None) -> dict:
    """统一口径的人审率（D6-1）。判法见模块头。

    参数：
      pages_json   导出的 `NNN.pages.json`（guji-pages/0.1）。
      pending_json 送 M10 的 `NNN.pending.json`（F-OV-07）。
      body_only    True＝只算正文页（统一口径）；False＝分子分母含非正文页（对照用，`nonbody_review` 照报）。
      page_types   {工作区页号: page_type}，pages.json 自带的页型优先于它；都没有的页按 body 计。
      punct        book-text 的 `NNN.punct.json`；给了才扣标题槽。
      recut        有 `covers_cell(锚点)` 的重切清单（`ops.release_gates.RecutList`）；None＝空单。

    返回（计数都是格数）：
      total_cells          分母：（正文页）字格数，已去标题槽；非字格本来不在 pages.json 的 cells 里
      review_cells         分子：其中在 pending.json 上的格
      rate                 review_cells / total_cells（6 位小数；分母 0 时 None）
      nonbody_review       非正文页上的待审字格（另报，不进 rate；body_only=False 时已含在分子里）
      nonbody_cells        非正文页字格数
      title_slots_excluded 分母里扣掉的标题槽格数（`title_review`＝其中待审的）
      nonchar_excluded     （计入页上）pages.json 的非字格数（excluded/blank mark，本来就不在分母）
      nonchar_review       （计入页上）待审格落在非字格上的数（不进 rate）
      unmatched_review     待审格在 pages.json 里找不到（页没导出／产物过期），不进 rate；`unmatched_sample` 前 10 个
      recut_cells          分母口径的字格里被重切清单覆盖的数（另报，不扣）
      review_on_recut      分子里同时在重切清单上的数
      reasons              分子各格的 `cls`／`why` 计数（why 一格多码各计一次）
      review_status        分子各格 `review` 状态计数
      body_pages / nonbody_pages / pages_untyped
    """
    idx = index_pages(pages_json)
    types = dict(page_types or {})
    types.update(idx["page_types"])
    order = [a for a, _ in idx["glyphs"]]
    titles, title_bad = title_cells(order, punct)

    def is_body(pg: int) -> bool:
        return types.get(pg, "body") in BODY_TYPES

    pending: dict[str, dict] = {}
    for c in pending_json.get("cells", []):
        if c.get("cell"):
            pending.setdefault(_strip_book(str(c["cell"])), c)

    glyph_page = dict(idx["glyphs"])
    pages = sorted({pg for _, pg in idx["glyphs"]})
    total = nonbody_cells = title_n = title_review = recut_n = 0
    for a, pg in idx["glyphs"]:
        body = is_body(pg)
        if not body:
            nonbody_cells += 1
        if body_only and not body:
            continue
        if a in titles:
            title_n += 1
            title_review += a in pending
            continue
        total += 1
        if recut is not None and recut.covers_cell(a):
            recut_n += 1

    def counted(pg: int) -> bool:
        return is_body(pg) or not body_only

    nonchar_n = sum(1 for a in idx["nonchar"] if counted(_anchor_page(a)))
    review = nonbody_review = nonchar_review = on_recut = 0
    unmatched: list[str] = []
    cls_c: Counter = Counter()
    cause_c: Counter = Counter()                 # 主成因码（republish 并进单子的 cause，GUJI-668）
    why_c: Counter = Counter()
    status_c: Counter = Counter()
    for a, c in pending.items():
        if a not in glyph_page:
            if a in idx["nonchar"]:
                nonchar_review += counted(_anchor_page(a))
            else:
                unmatched.append(a)
            continue
        body = is_body(glyph_page[a])
        if not body:
            nonbody_review += 1
        if (body_only and not body) or a in titles:
            continue
        review += 1
        on_recut += bool(recut is not None and recut.covers_cell(a))
        cls_c[c.get("cls") or NONE_KEY] += 1
        if c.get("cause"):
            cause_c[c["cause"]] += 1
        for w in (c.get("why") or [NONE_KEY]):
            why_c[w] += 1
        status_c[str(c.get("review") or NONE_KEY)] += 1

    def _sorted(cn: Counter) -> dict:
        return dict(sorted(cn.items(), key=lambda kv: (-kv[1], kv[0])))

    unmatched.sort(key=_anchor_key)
    untyped = [pg for pg in pages if pg not in types]
    return {
        "total_cells": total,
        "review_cells": review,
        "rate": round(review / total, 6) if total else None,
        "nonbody_review": nonbody_review,
        "nonbody_cells": nonbody_cells,
        "title_slots_excluded": title_n,
        "title_review": title_review,
        "title_unresolved": title_bad,
        "nonchar_excluded": nonchar_n,
        "nonchar_review": nonchar_review,
        "unmatched_review": len(unmatched),
        "unmatched_sample": unmatched[:10],
        "recut_cells": recut_n,
        "review_on_recut": on_recut,
        "reasons": {"cls": _sorted(cls_c), "why": _sorted(why_c), **({"cause": _sorted(cause_c)} if cause_c else {})},
        "review_status": _sorted(status_c),
        "pending_cells": len(pending),
        "body_only": body_only,
        "body_pages": sum(1 for pg in pages if is_body(pg)),
        "nonbody_pages": sum(1 for pg in pages if not is_body(pg)),
        "pages_untyped": len(untyped),
    }


def _anchor_key(a: str) -> list:
    return [(0, int(x), "") if x.lstrip("-").isdigit() else (1, 0, x)
            for x in re.split(r":|(?<=\d)(?=[ab]$)", a) if x]


# ---------------------------------------------------------------- 取数（CLI）
def _sha(p: Path | None) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p and p.is_file() else None


def _load(p: Path | None):
    return json.loads(p.read_text(encoding="utf-8")) if p else None


def chapter_of(book: str) -> str | None:
    """册号 → book-text 章号（vol04 → 004），同 `cli_v2.cmd_export`。"""
    m = re.fullmatch(r"vol(\d+)", book)
    return f"{int(m.group(1)):03d}" if m else None


def cv_commit() -> tuple[str | None, bool | None]:
    root = Path(__file__).resolve().parents[2]
    try:
        sha = subprocess.run(["git", "-C", str(root), "rev-parse", "--short=8", "HEAD"],
                             capture_output=True, text=True, timeout=60)
        st = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
                            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None, None
    if sha.returncode != 0:
        return None, None
    return sha.stdout.strip(), (bool(st.stdout.strip()) if st.returncode == 0 else None)


def book_pins(book: str) -> dict:
    """册 yaml 的 cv_version／corpus／glyph_pin；取不到写 None 并记原因。"""
    try:
        from open_guji_cv.core.book import load_book
        bk = load_book(book)
    except Exception as e:  # noqa: BLE001 — 取不到就记，不中断
        return {"cv_version": None, "corpus": None, "glyph_pin": None,
                "pins_error": f"{type(e).__name__}: {e}"}
    return {"cv_version": bk.cv_version, "corpus": bk.corpus, "glyph_pin": bk.glyph_pin}


def gather_page_types(book: str, pages: list[int]) -> tuple[dict[int, str], dict[int, str]]:
    """{页: page_type} 与 {页: 来源}：裁决表 page-type 分片 > border_detect_gate 产物（见模块头）。"""
    types: dict[int, str] = {}
    src: dict[int, str] = {}
    try:
        from open_guji_cv.feedback.consumers import verdict_store
        for it in verdict_store().list("page-type", legacy=False):
            if str(it.anchor.book) == book and it.anchor.page is not None:
                t = (it.expected or {}).get("page_type")
                if t and int(it.anchor.page) not in types:
                    types[int(it.anchor.page)] = str(t)
                    src[int(it.anchor.page)] = "verdict"
    except Exception:  # noqa: BLE001 — 没有裁决表就退到产物
        pass
    from open_guji_cv.core.workspace import products_root
    gate_dir = products_root() / book / "border_detect_gate"
    for pg in pages:
        if pg in types:
            continue
        f = gate_dir / f"p{pg:04d}.json"
        if not f.is_file():
            continue
        t = (json.loads(f.read_text(encoding="utf-8")).get("border_detect_gate_manifest") or {}).get("page_type")
        if t:
            types[pg], src[pg] = str(t), "border_detect_gate"
    return types, src


def _default_pending(book: str) -> Path:
    from open_guji_cv.ops.release_gates import lists_dir
    nnn = chapter_of(book)
    hits = sorted((lists_dir() / "proofing").glob(f"*/{nnn}.pending.json")) if nnn else []
    if len(hits) != 1:
        raise SystemExit(f"找到 {len(hits)} 份 {lists_dir() / 'proofing'}/*/{nnn}.pending.json，请用 --pending 指定")
    return hits[0]


def _default_pages_json(book: str) -> Path:
    from open_guji_cv.core.workspace import reports_root
    d = reports_root() / book
    nnn = chapter_of(book)
    p = d / f"{nnn}.pages.json" if nnn else None
    if p and p.is_file():
        return p
    hits = sorted(d.glob("*.pages.json"))
    if len(hits) != 1:
        raise SystemExit(f"{d} 下找到 {len(hits)} 个 pages.json：先 `guji export format {book} -w <工作区>`，"
                         f"或用 --pages-json 指定")
    return hits[0]


def build_row(book: str, pages_json: Path, pending: Path, recut: Path | None, punct: Path | None,
              body_only: bool = True, now: datetime | None = None) -> dict:
    from open_guji_cv.ops.release_gates import RecutList, _rows
    pj, pd = _load(pages_json), _load(pending)
    rl = RecutList(_rows(recut)) if recut else None
    order_pages = sorted({_anchor_page(a) for a, _ in index_pages(pj)["glyphs"]})
    types, src = gather_page_types(book, order_pages)
    in_pj = index_pages(pj)["page_types"]
    for pg in in_pj:
        src[pg] = "pages_json"
    res = review_rate(pj, pd, body_only=body_only, page_types=types, punct=_load(punct), recut=rl)
    sha, dirty = cv_commit()
    ts = (now or datetime.now(ZoneInfo("America/Los_Angeles"))).isoformat(timespec="seconds")
    row = {"ts": ts, "schema": LEDGER_SCHEMA, "rate_def": RATE_DEF, "book": book,
           **book_pins(book), "cv_commit": sha, "cv_dirty": dirty,
           "pending_rev": pd.get("rev"), "pending_cv_commit": pd.get("cv_commit"),
           "pending_cv_version": pd.get("cv_version")}
    row.update(res)
    row["recut_rows"] = (len(rl.pages) + len(rl.cols) + len(rl.cells)) if rl else 0
    row["recut_bad"] = list(rl.bad) if rl else []
    row["title_source"] = "punct" if punct else "none"
    row["page_type_source"] = dict(sorted(Counter(src.get(pg, "default_body") for pg in order_pages).items()))
    row["inputs"] = {"pages_json": _sha(pages_json), "pending": _sha(pending),
                     "recut": _sha(recut), "punct": _sha(punct)}
    return row


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ws", required=True, help="书的工作区（同 -w）")
    ap.add_argument("--book", required=True, help="册 id，如 vol04")
    ap.add_argument("--pending", help="送 M10 的 NNN.pending.json；缺省在数据目录 feedback/lists/proofing/*/ 下找")
    ap.add_argument("--pages-json", help="导出的 NNN.pages.json；缺省 <工作区>/reports/<册>/<NNN>.pages.json")
    ap.add_argument("--recut", help="重切清单 tsv（位置<TAB>原因）；缺省数据目录 feedback/lists/<册>-重切清单.tsv")
    ap.add_argument("--punct", help="book-text 的 NNN.punct.json；给了才扣标题槽（heading→break）")
    ap.add_argument("--all-pages", action="store_true", help="分子分母含非正文页（对照用，不是统一口径）")
    ap.add_argument("--out", help="台账 jsonl（追加一行）；缺省数据目录 feedback/lists/ledger/<册>.jsonl")
    a = ap.parse_args(argv)
    os.environ["GUJI_WORKSPACE"] = str(Path(a.ws).expanduser().resolve())
    from open_guji_cv.ops.release_gates import lists_dir, recut_path

    pages_json = Path(a.pages_json) if a.pages_json else _default_pages_json(a.book)
    pending = Path(a.pending) if a.pending else _default_pending(a.book)
    for p in (pages_json, pending):
        if not p.is_file():
            raise SystemExit(f"没有 {p}")
    recut = Path(a.recut) if a.recut else recut_path(a.book)
    if a.recut and not recut.is_file():
        raise SystemExit(f"没有 {recut}")
    recut = recut if recut.is_file() else None
    punct = Path(a.punct) if a.punct else None
    if punct and not punct.is_file():
        raise SystemExit(f"没有 {punct}")
    row = build_row(a.book, pages_json, pending, recut, punct, body_only=not a.all_pages)
    out = Path(a.out) if a.out else lists_dir() / "ledger" / f"{a.book}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False)
    with out.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)
    r = row["rate"]
    print(f"{a.book}：待审 {row['review_cells']} / 正文字格 {row['total_cells']} = "
          f"{'—' if r is None else f'{r * 100:.2f}%'}；非正文待审 {row['nonbody_review']}，"
          f"重切清单格 {row['recut_cells']}；标题槽 {row['title_source']}；→ {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
