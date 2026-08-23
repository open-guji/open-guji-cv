"""种子审查页面侧：按页装配审查批次 + 自包含 HTML + 事件解析。

设计文档 glyph_db_first_design.md §3.5 的「审查交互程序」需求清单的实现。
与流程侧（seed 命令 / seed-ingest）的唯一耦合点是
``open_guji_cv.clustering.seed_queue``（SeedItem / 疑问码 / GUJI-SEED-EVENT），
本模块**不**私加契约字段。

    导出   build_seed_batch() + render_seed_html()  →  单文件 HTML
           （原图内嵌 base64，页面不回管线拿数据；三轮起不再放归一图——
           实审反馈：对人眼定字没有用）
    回收   ingest_seed_events()  →  薄封装 seed_queue.parse_seed_events；
           写库（human provenance 进库）由流程侧 seed-ingest 负责。

持久化三层保险（二轮改整页 publish 后的形态）：
    1. 整页 publish(html)：日志内嵌页面自身随快照发布（files 形式对
       单文件经典 artifact 拒 capability_disabled，首轮实测教训）；
    2. localStorage 崩溃备份，恢复时按 (batch,seq) 与页内嵌日志合并；
    3. 复制/下载兜底：不依赖任何平台能力，永远可用。
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
from pathlib import Path

from ..seed_queue import (ALL_DOUBTS, DOUBT_LABELS, SEED_EVENT_PREFIX,
                          STATUS_CONFIRMED, STATUS_NOT_A_CHAR, STATUS_PENDING,
                          STATUS_REJECTED, STATUS_SKIPPED, SeedItem,
                          parse_seed_events)

# 已裁决 = 不再需要出现在待审批次里的状态（auto_admitted 也算：免审进库；
# confirmed_label_only = 定了字但字形不入库，同样已裁决）
_DECIDED = {"auto_admitted", STATUS_CONFIRMED, "confirmed_label_only",
            STATUS_REJECTED, STATUS_NOT_A_CHAR}
# 待审 = 本批次要出的状态（skipped 留在队列，下批再出）
_REVIEWABLE = {STATUS_PENDING, STATUS_SKIPPED}

# 疑问码 → 设计文档 §3.5 表格里的编号（页面上「疑问 ③」这样引用）
_DOUBT_NO = {code: i + 1 for i, code in enumerate(ALL_DOUBTS)}

MAX_HOTKEYS = 9          # 数字键 1..9 直选的候选上限（多余候选仍可点击）


# ── 批次装配 ─────────────────────────────────────────────

def _page_sort_key(page: str):
    """页号排序：数字页号按数值，其余按字典序排后面。"""
    try:
        return (0, int(page), "")
    except (TypeError, ValueError):
        return (1, 0, str(page))


def _load_queue(queue_path: Path) -> list[SeedItem]:
    if not queue_path.exists():
        raise FileNotFoundError(
            f"种子队列不存在：{queue_path}\n"
            "先跑流程侧 seed 命令生成 phase9_seed/queue.jsonl。")
    items = []
    for ln, line in enumerate(queue_path.read_text(encoding="utf-8")
                              .splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            items.append(SeedItem.from_json(line))
        except (json.JSONDecodeError, TypeError) as e:
            raise ValueError(f"队列第 {ln} 行不是合法 SeedItem：{e}") from e
    if not items:
        raise ValueError(f"种子队列是空的：{queue_path}")
    return items


def _pointer_page(queue_path: Path, by_page: dict[str, list]) -> str | None:
    """推进指针所在页：progress.json（流程侧维护）里找当前页字段。"""
    prog = queue_path.parent / "progress.json"
    if not prog.exists():
        return None
    try:
        d = json.loads(prog.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    # 契约（seed_queue.py）：进度指针字段为 pointer（流程侧 seeding.py
    # 维护，指向最早未 done 的页）；其余键名保留为向后兼容探测。
    for key in ("pointer", "current_page", "page", "next_page"):
        v = d.get(key)
        if v is not None and str(v) in by_page:
            return str(v)
    return None


def _png_b64(path: Path) -> str | None:
    try:
        return base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return None


def _assemble_choices(item: SeedItem) -> list[dict]:
    """把各证据源的候选合成一个去重有序列表（数字键按此顺序 1..9）。

    顺序：proposed（双信号一致的拟进库字）→ OCR topk（prob 降序）→
    整理本对齐字 → 库内候选（cov 降序）。同字合并，保留各源的数值。
    """
    order: list[str] = []
    info: dict[str, dict] = {}

    def add(ch, **kv):
        if not ch:
            return
        if ch not in info:
            order.append(ch)
            info[ch] = {"char": ch, "ocr_prob": None, "align_op": None,
                        "ref_op": None, "db_cov": None, "proposed": False}
        for k, v in kv.items():
            if v is not None and info[ch].get(k) in (None, False):
                info[ch][k] = v

    add(item.proposed, proposed=True)
    ctx = item.context or {}
    if ctx.get("ref_char"):                       # 整理本参考（免闸，1:1 对位）
        add(ctx["ref_char"], ref_op=ctx.get("ref_op"))
    if item.ocr:
        topk = item.ocr.get("topk") or []
        if not topk and item.ocr.get("char"):
            topk = [[item.ocr["char"], item.ocr.get("prob", 0.0)]]
        for ch, p in sorted(topk, key=lambda t: -(t[1] or 0.0)):
            add(ch, ocr_prob=p)
    if item.align and item.align.get("char"):
        add(item.align["char"], align_op=item.align.get("op"))
    if item.match:
        for ch, cov in item.match.get("candidates") or []:
            add(ch, db_cov=cov)
    return [info[ch] for ch in order]


def build_seed_batch(book_out_dir, queue_path, page: str | None = None,
                     limit: int = 200) -> dict:
    """从 queue.jsonl 读待审条目，按页组织成可序列化批次。

    page 选单页（str/int 均可）；缺省取推进指针所在页（progress.json），
    没有指针就取页号最小的仍有待审条目的页。每条含原图 base64、
    OCR 候选、对齐字、疑问码说明、库内候选、跨列上下文——审查所需
    信息全在批次里，页面不回管线拿数据。
    """
    book_dir = Path(book_out_dir)
    queue_path = Path(queue_path)
    items = _load_queue(queue_path)
    book = items[0].book or book_dir.name

    by_page: dict[str, list[SeedItem]] = {}
    for it in items:
        by_page.setdefault(str(it.page), []).append(it)

    pending_pages = sorted(
        (p for p, its in by_page.items()
         if any(i.status in _REVIEWABLE for i in its)),
        key=_page_sort_key)

    if page is not None:
        page = str(page)
        if page not in by_page:
            raise ValueError(
                f"队列里没有第 {page} 页的条目（有条目的页："
                f"{', '.join(sorted(by_page, key=_page_sort_key))}）")
    else:
        page = _pointer_page(queue_path, by_page) or (
            pending_pages[0] if pending_pages else None)
        if page is None:
            raise ValueError(
                f"队列 {queue_path} 里已无待审条目（全部已裁决）。")

    page_items = sorted(by_page[page], key=lambda i: (i.col, i.idx))
    todo = [i for i in page_items if i.status in _REVIEWABLE][:limit]

    entries = []
    for it in todo:
        patch = book_dir / "phase4_chars" / it.patch_path
        entries.append({
            "instance_id": it.instance_id,
            "col": it.col, "idx": it.idx, "tier": it.tier,
            "status": it.status,
            "patch_b64": _png_b64(patch),
            "choices": _assemble_choices(it),
            "ocr": it.ocr,
            "align": it.align,
            "doubts": [{"code": c, "no": _DOUBT_NO.get(c, 0),
                        "label": DOUBT_LABELS.get(c, c)}
                       for c in (it.doubts or [])],
            "db": it.match,
            "context": it.context,
            "note": it.note,
        })

    digest = hashlib.sha1(
        ",".join(e["instance_id"] for e in entries).encode()).hexdigest()[:8]
    n_decided = sum(1 for i in items if i.status in _DECIDED)
    return {
        "book": book,
        "page": page,
        "batch_id": f"{book}-seed-{page}-{digest}",
        "entries": entries,
        # 该页进度（含已裁决底数，页面在此基础上做实时累加）
        "page_total": len(page_items),
        "page_done": sum(1 for i in page_items if i.status in _DECIDED),
        # 全书推进度（队列口径：auto_admitted 也算已裁决）
        "book_total": len(items),
        "book_done": n_decided,
        # 各页剩余待审条数（导航参考）
        "pages_pending": [
            {"page": p,
             "n": sum(1 for i in by_page[p] if i.status in _REVIEWABLE)}
            for p in pending_pages],
    }


# ── HTML 渲染 ────────────────────────────────────────────

def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def _img(b64: str | None, cls: str, cap: str) -> str:
    if not b64:
        return (f'<figure class="{cls}"><div class="noimg">图缺</div>'
                f'<figcaption>{_esc(cap)}</figcaption></figure>')
    return (f'<figure class="{cls}">'
            f'<img src="data:image/png;base64,{b64}" alt="{_esc(cap)}">'
            f'<figcaption>{_esc(cap)}</figcaption></figure>')


def _render_choice(i: int, c: dict) -> str:
    key = (f'<kbd>{i + 1}</kbd>' if i < MAX_HOTKEYS else "")
    tags = []
    if c.get("proposed"):
        tags.append('<span class="tag t-prop">拟</span>')
    if c.get("ref_op"):
        tags.append('<span class="tag t-ref">整理本</span>')
    if c.get("ocr_prob") is not None:
        tags.append(f'<span class="tag t-ocr">OCR {c["ocr_prob"]:.0%}</span>')
    if c.get("align_op"):
        cls = "t-eq" if c["align_op"] == "equal" else "t-rep"
        tags.append(f'<span class="tag {cls}">对齐·{_esc(c["align_op"])}</span>')
    if c.get("db_cov") is not None:
        tags.append(f'<span class="tag t-db">库 {c["db_cov"]:.2f}</span>')
    return (f'<button type="button" class="cand" data-char="{_esc(c["char"])}">'
            f'{key}<b>{_esc(c["char"])}</b>{"".join(tags)}</button>')


def _render_evidence(e: dict) -> str:
    rows = []
    # OCR 行
    if e["ocr"]:
        topk = e["ocr"].get("topk") or [[e["ocr"].get("char"),
                                         e["ocr"].get("prob", 0.0)]]
        chips = "".join(
            f'<span class="chip">{_esc(ch)}<small>{(p or 0.0):.0%}</small></span>'
            for ch, p in sorted(topk, key=lambda t: -(t[1] or 0.0)) if ch)
        rows.append(f'<div class="evi-row"><span class="evi-k">OCR</span>{chips}</div>')
    else:
        rows.append('<div class="evi-row"><span class="evi-k">OCR</span>'
                    '<span class="none">无结果</span></div>')
    # 整理本行：过闸对齐（强参考）与免闸逐位参考（弱参考）分开展示
    if e["align"] and e["align"].get("char"):
        op = e["align"].get("op") or "?"
        cls = "t-eq" if op == "equal" else "t-rep"
        rows.append(
            f'<div class="evi-row"><span class="evi-k">整理本</span>'
            f'<span class="chip">{_esc(e["align"]["char"])}</span>'
            f'<span class="tag {cls}">{_esc(op)}</span></div>')
    else:
        ctx = e.get("context") or {}
        if ctx.get("ref_char"):
            rows.append(
                f'<div class="evi-row"><span class="evi-k">整理本</span>'
                f'<span class="chip big">{_esc(ctx["ref_char"])}</span>'
                f'<span class="tag t-ref">参考·{_esc(ctx.get("ref_op") or "?")}'
                '</span><small class="near">免闸逐位参考，非金标</small></div>')
        else:
            rows.append('<div class="evi-row"><span class="evi-k">整理本</span>'
                        '<span class="none">无对应（该位附近有增/漏字）</span></div>')
    # 库内行
    db = e.get("db")
    if db and (db.get("candidates") or db.get("matched_id")):
        chips = "".join(
            f'<span class="chip">{_esc(ch)}<small>cov {cov:.2f}</small></span>'
            for ch, cov in (db.get("candidates") or []))
        near = ""
        if db.get("matched_id"):
            near = (f'<small class="near">最近刻例 {_esc(db["matched_id"])}'
                    f' cov {db.get("cov", 0):.2f}'
                    f'（{_esc(db.get("verdict", ""))}）</small>')
        guard = (f'<span class="tag t-rep">护栏 {_esc(db["guard"])}</span>'
                 if db.get("guard") else "")
        rows.append(f'<div class="evi-row"><span class="evi-k">库内</span>'
                    f'{chips or "<span class=none>无同字条目</span>"}{guard}{near}</div>')
    else:
        rows.append('<div class="evi-row"><span class="evi-k">库内</span>'
                    '<span class="none">无同字条目</span></div>')
    # 疑问码逐条说明
    marks = "".join(
        f'<li><b>疑问{d["no"]}</b> <code>{_esc(d["code"])}</code> '
        f'{_esc(d["label"])}</li>' for d in e["doubts"])
    if marks:
        rows.append(f'<ul class="doubts">{marks}</ul>')
    return "".join(rows)


_CTX_WIN = 5     # 上下文条：当前字上下各显示几个字


def _render_context(e: dict) -> str:
    """竖排上下文条：该列 OCR 载体文与整理本参考文并排，当前字高亮。

    只开窗 pos±_CTX_WIN（整列可能 20 字，全部竖排比图块还高）；
    截断端加「⋮」。当前字在列首/列尾时，用邻列文补足窗口（三轮实审
    反馈）：上一列末尾接在前、下一列开头接在后，邻列字弱化显示并以
    「▔/▁」界标隔开（古籍阅读序：上一列尾 → 本列 → 下一列首）。
    """
    ctx = e.get("context") or {}
    col_ocr, col_ref, pos = ctx.get("col_ocr"), ctx.get("col_ref"), ctx.get("pos")
    if not col_ocr or pos is None:
        return ""
    lo = max(0, pos - _CTX_WIN)
    hi = min(len(col_ocr), pos + _CTX_WIN + 1)
    need_before = _CTX_WIN - (pos - lo)          # 列首吃不满的窗口量
    need_after = _CTX_WIN - (hi - 1 - pos)       # 列尾吃不满的窗口量

    def vline(text: str | None, prev: str | None, nxt: str | None,
              label: str) -> str:
        if not text:
            return ""
        chars = []
        if need_before > 0 and prev:
            for ch in prev[-need_before:]:
                chars.append(f'<span class="adj">{_esc(ch)}</span>')
            chars.append('<span class="colbrk">▔</span>')
        elif lo > 0:
            chars.append('<span class="ell">⋮</span>')
        for i in range(lo, min(hi, len(text))):
            ch = _esc(text[i])
            chars.append(f'<b class="cur">{ch}</b>' if i == pos
                         else f'<span>{ch}</span>')
        if need_after > 0 and nxt:
            chars.append('<span class="colbrk">▁</span>')
            for ch in nxt[:need_after]:
                chars.append(f'<span class="adj">{_esc(ch)}</span>')
        elif hi < len(text):
            chars.append('<span class="ell">⋮</span>')
        return (f'<div class="vline"><span class="vlab">{label}</span>'
                f'<div class="vtxt">{"".join(chars)}</div></div>')

    return ('<div class="ctx">'
            + vline(col_ocr, ctx.get("prev_ocr"), ctx.get("next_ocr"), "OCR")
            + vline(col_ref, ctx.get("prev_ref"), ctx.get("next_ref"), "整理本")
            + '</div>')


def _render_seed_card(e: dict) -> str:
    iid = _esc(e["instance_id"])
    tier = ('<span class="tag t-rep">degraded</span>'
            if e["tier"] == "degraded" else "")
    skipped = (' <span class="tag t-skip">上批跳过</span>'
               if e["status"] == STATUS_SKIPPED else "")
    choices = "".join(_render_choice(i, c) for i, c in enumerate(e["choices"]))
    return f"""<article class="card" data-iid="{iid}" data-state="open">
<header><span class="iid">{iid}</span>
<span class="pos">第{e["col"]}列第{e["idx"]}字</span>{tier}{skipped}
<span class="chosen" data-slot="chosen"></span>
<button type="button" class="reopen">改</button></header>
<div class="row">
<div class="imgs">{_img(e["patch_b64"], "orig", "原图")}{_render_context(e)}</div>
<div class="main">
<div class="cands">{choices}
<span class="other"><input class="other-in" maxlength="4" placeholder="手输正字">
<button type="button" class="other-ok">确定</button></span>
<button type="button" class="nac"><kbd>N</kbd>非字</button>
<button type="button" class="skip"><kbd>S</kbd>存疑跳过</button>
<button type="button" class="noadm" title="图块混有无法剥离的残余时：确认的字只进标注结果，字形不进库当匹配范例"><kbd>B</kbd>字形不入库</button></div>
<div class="evi">{_render_evidence(e)}</div>
</div></div></article>"""


_CSS = """
:root{
  --paper:#faf6ee; --card:#fffdf8; --ink:#2b2620; --muted:#8a7f6e;
  --line:#e3dbc9; --seal:#a63b2a; --seal-ink:#fff6ee;
  --done:#3d7a4f; --doubt:#8a6d1f; --bad:#8a4238; --hl:#f3e9d2;
  --imgbg:#ffffff;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --paper:#1d1a15; --card:#26221b; --ink:#e8e0d0; --muted:#9a8f7c;
    --line:#3a342a; --seal:#d0715e; --seal-ink:#2b1512;
    --done:#7fba8f; --doubt:#cfae4e; --bad:#cf8377; --hl:#3b3527;
    --imgbg:#efe9dd;
  }
}
:root[data-theme="dark"]{
  --paper:#1d1a15; --card:#26221b; --ink:#e8e0d0; --muted:#9a8f7c;
  --line:#3a342a; --seal:#d0715e; --seal-ink:#2b1512;
  --done:#7fba8f; --doubt:#cfae4e; --bad:#cf8377; --hl:#3b3527;
  --imgbg:#efe9dd;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
  font-family:"Noto Serif TC","Songti TC","SimSun",serif;line-height:1.5}
.top{position:sticky;top:0;z-index:5;background:var(--paper);
  border-bottom:1px solid var(--line);padding:.6rem 1rem;
  display:flex;flex-wrap:wrap;gap:.5rem 1.1rem;align-items:baseline}
.top h1{font-size:1.05rem;margin:0;letter-spacing:.1em}
.top .prog{color:var(--muted);font-variant-numeric:tabular-nums}
#save-status[data-bad="1"]{color:var(--seal-ink);background:var(--bad);
  padding:.1rem .5rem;border-radius:3px;font-size:.8rem}
#copybar[data-pending="1"]{background:var(--doubt);color:var(--seal-ink);
  border-color:var(--doubt);font-weight:600}
.top button{font:inherit;font-size:.85rem;background:none;color:var(--ink);
  border:1px solid var(--line);border-radius:3px;padding:.15rem .6rem;cursor:pointer}
.list{max-width:56rem;margin:0 auto;padding:1rem;display:flex;
  flex-direction:column;gap:.8rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:4px}
.card.active{border-color:var(--seal);box-shadow:0 0 0 1px var(--seal)}
.card>header{display:flex;gap:.7rem;align-items:baseline;flex-wrap:wrap;
  padding:.4rem .8rem;border-bottom:1px solid var(--line)}
.iid{font-family:ui-monospace,monospace;font-size:.75rem;color:var(--muted)}
.pos{font-size:.8rem;color:var(--muted)}
.chosen{font-size:1.2rem;color:var(--done);min-width:1.4em}
.card>header .reopen{display:none;margin-left:auto;font:inherit;font-size:.75rem;
  background:none;border:1px solid var(--line);border-radius:3px;
  color:var(--muted);cursor:pointer;padding:.05rem .5rem}
.card:not([data-state="open"])>header .reopen{display:inline-block}
.row{display:flex;gap:1.1rem;padding:.8rem;flex-wrap:wrap}
.imgs{display:flex;gap:.6rem;align-items:flex-start}
.imgs figure{margin:0;text-align:center}
.imgs img,.imgs .noimg{width:7.5rem;height:7.5rem;object-fit:contain;
  border:1px solid var(--line);border-radius:2px;background:var(--imgbg)}
.imgs .norm img{image-rendering:pixelated}
.imgs .noimg{display:flex;align-items:center;justify-content:center;
  color:var(--muted);font-size:.8rem}
.imgs figcaption{font-size:.72rem;color:var(--muted);letter-spacing:.2em;
  margin-top:.2rem}
.main{flex:1;min-width:18rem;display:flex;flex-direction:column;gap:.6rem}
.cands{display:flex;flex-wrap:wrap;gap:.45rem;align-items:center}
.cand{font:inherit;display:inline-flex;align-items:baseline;gap:.35rem;
  border:1px solid var(--line);background:none;color:var(--ink);
  border-radius:3px;padding:.25rem .6rem;cursor:pointer}
.cand b{font-size:1.5rem;font-weight:600}
.cand:hover,.cand:focus-visible{border-color:var(--seal)}
kbd{font-family:ui-monospace,monospace;font-size:.68rem;color:var(--muted);
  border:1px solid var(--line);border-radius:3px;padding:0 .3em;
  align-self:center}
.tag{font-size:.68rem;border-radius:3px;padding:.05rem .35rem;
  border:1px solid var(--line);color:var(--muted);align-self:center;
  white-space:nowrap}
.t-prop{color:var(--done);border-color:var(--done)}
.t-eq{color:var(--done);border-color:var(--done)}
.t-rep,.t-skip{color:var(--doubt);border-color:var(--doubt)}
.t-ocr,.t-db{color:var(--muted)}
.t-ref{color:var(--seal);border-color:var(--seal)}
.chip.big{font-size:1.3rem}
.ctx{display:flex;gap:.35rem;align-items:flex-start}
.vline{display:flex;flex-direction:column;align-items:center;gap:.25rem}
.vlab{font-size:.62rem;color:var(--muted);letter-spacing:.1em;
  writing-mode:horizontal-tb}
.vtxt{writing-mode:vertical-rl;text-orientation:upright;
  font-size:1.02rem;line-height:1.35;letter-spacing:.12em;
  border:1px solid var(--line);border-radius:2px;background:var(--paper);
  color:var(--ink);padding:.35rem .15rem;min-height:7.5rem}
.vtxt .cur{color:var(--seal);background:var(--hl);border-radius:2px}
.vtxt .ell{color:var(--muted)}
.vtxt .adj{color:var(--muted);opacity:.75}
.vtxt .colbrk{color:var(--muted);font-size:.6em;letter-spacing:0}
.other{display:inline-flex;gap:.3rem}
.other-in{font:inherit;font-size:1.1rem;width:5em;background:var(--paper);
  color:var(--ink);border:1px solid var(--line);border-radius:3px;
  padding:.15rem .4rem}
.other-ok,.nac,.skip{font:inherit;font-size:.85rem;background:none;
  color:var(--ink);border:1px solid var(--line);border-radius:3px;
  padding:.2rem .55rem;cursor:pointer;display:inline-flex;gap:.3rem}
.nac{color:var(--bad);border-color:var(--bad)}
.skip{color:var(--doubt);border-color:var(--doubt)}
.noadm{font:inherit;font-size:.85rem;background:none;color:var(--muted);
  border:1px dashed var(--line);border-radius:3px;padding:.2rem .55rem;
  cursor:pointer;display:inline-flex;gap:.3rem}
.card[data-noadmit="1"] .noadm{color:var(--seal);border-color:var(--seal);
  border-style:solid;background:var(--hl)}
.evi{display:flex;flex-direction:column;gap:.3rem;font-size:.92rem}
.evi-row{display:flex;gap:.5rem;align-items:baseline;flex-wrap:wrap}
.evi-k{font-size:.72rem;color:var(--muted);letter-spacing:.15em;min-width:3.2em}
.chip{display:inline-flex;align-items:baseline;gap:.25rem;
  border:1px solid var(--line);border-radius:3px;padding:.05rem .4rem}
.chip small{color:var(--muted);font-size:.7rem;font-variant-numeric:tabular-nums}
.none{color:var(--muted);font-size:.8rem}
.near{color:var(--muted);font-size:.75rem}
.doubts{margin:.2rem 0 0;padding-left:1.2rem;color:var(--doubt);
  font-size:.82rem}
.doubts code{font-size:.72rem;color:var(--muted)}
.card:not([data-state="open"]) .row{display:none}
.card[data-state="done"]{border-left:3px solid var(--done)}
.card[data-state="nac"]{border-left:3px solid var(--bad)}
.card[data-state="nac"] .chosen{color:var(--bad);font-size:.9rem}
.card[data-state="skip"]{border-left:3px solid var(--doubt);opacity:.6}
.card[data-state="skip"] .chosen{color:var(--doubt);font-size:.9rem}
.foot{max-width:56rem;margin:0 auto;padding:0 1rem 3rem}
.foot summary{cursor:pointer;color:var(--muted);font-size:.85rem}
.log{font-family:ui-monospace,monospace;font-size:.72rem;background:var(--card);
  border:1px solid var(--line);border-radius:4px;padding:.6rem;
  overflow-x:auto;white-space:pre;min-height:2rem}
.hint{color:var(--muted);font-size:.8rem}
"""

# 与 artifact_export._JS 同构的三层持久化 + 种子专用交互（单键 / 顺序前进）。
# 注意：本串不是 f-string；JS 字符串里的换行一律写 \\n。
_JS = """
(function(){
  var log = document.getElementById('guji-log');
  var list = document.getElementById('list');
  var PREFIX = 'GUJI-SEED-EVENT';
  var LSKEY = 'guji-seed:' + BATCH;
  var undoStack = [];

  function lines(){
    return log.textContent.match(/GUJI-SEED-EVENT .*/g) || []; }
  function events(){
    return lines().map(function(l){
      try { return JSON.parse(l.slice(PREFIX.length + 1)); }
      catch(e){ return null; }
    }).filter(Boolean); }
  function status(msg, bad){
    var el = document.getElementById('save-status');
    if(!el) return;
    el.textContent = msg;
    el.setAttribute('data-bad', bad ? '1' : '0'); }
  function fail(why){
    disabled = true;
    status(why + ' — 記錄仍在本機，請點上方「複製記錄」貼回對話', true); }

  // ── 持久化：整頁 publish(html)。單文件經典 artifact 只有這條自動路徑
  // ——files 形式對它拒 capability_disabled（vol01 第 4 頁首輪實測）。
  // 日誌內嵌在 #guji-log 裡隨頁面一起發布：發布成功後 shell 會重載本視
  // 圖到新版本，重載前把滾動位置存 sessionStorage，重載後日誌已在頁裡、
  // 狀態由 restore() 重放。複製/下載兜底照舊，永遠可用。
  var pubTimer = 0, disabled = false, publishing = false;
  function withTimeout(pr, ms, tag){
    return new Promise(function(res, rej){
      var done = false;
      var t = setTimeout(function(){
        if(!done){ done = true; rej({code: tag + '_timeout'}); } }, ms);
      pr.then(function(v){ if(!done){ done=true; clearTimeout(t); res(v); } },
              function(e){ if(!done){ done=true; clearTimeout(t); rej(e); } });
    }); }
  var nsPromise = (window.claude && window.claude.use)
    ? withTimeout(window.claude.use('artifact'), 15000, 'use')
        .catch(function(){ return null; })
    : Promise.resolve(null);

  function saveLocal(){
    try { localStorage.setItem(LSKEY, log.textContent); } catch(e){} }
  function exportedCount(){
    try { return parseInt(localStorage.getItem(LSKEY + ':exported') || '0', 10); }
    catch(e){ return 0; } }
  function markExported(n){
    try { localStorage.setItem(LSKEY + ':exported', String(n)); } catch(e){}
    refreshBar(); }
  function refreshBar(){
    var n = lines().length, pending = n - exportedCount();
    var bar = document.getElementById('copybar');
    if(!bar) return;
    bar.textContent = pending > 0
      ? '複製 ' + n + ' 條記錄（' + pending + ' 條未匯出）'
      : (n ? '複製 ' + n + ' 條記錄' : '尚無記錄');
    bar.setAttribute('data-pending', pending > 0 ? '1' : '0'); }

  function snapshotHtml(){
    // 當前 DOM 就是要發布的頁面：日誌/卡片狀態已寫在屬性與文本裡，
    // 重開時 restore() 按日誌重放即可。active 高亮不入快照。
    var a = list.querySelector('.card.active');
    if(a) a.classList.remove('active');
    var html = '<!doctype html>\\n' + document.documentElement.outerHTML;
    if(a) a.classList.add('active');
    return html; }
  function stashView(){
    try {
      var a = list.querySelector('.card.active');
      sessionStorage.setItem(LSKEY + ':view', JSON.stringify({
        iid: a ? a.getAttribute('data-iid') : null,
        y: window.scrollY || 0 }));
    } catch(e){} }
  function restoreView(){
    try {
      var raw = sessionStorage.getItem(LSKEY + ':view');
      if(!raw) return;
      sessionStorage.removeItem(LSKEY + ':view');
      var v = JSON.parse(raw);
      if(v.iid){ var c = cardOf(v.iid); if(c){ setActive(c); return; } }
      if(v.y) window.scrollTo(0, v.y);
    } catch(e){} }

  function publishNow(){
    if(disabled || publishing) return;
    var t = document.querySelector('.other-in:focus');
    if(t && t.value){ schedulePublish(); return; }   // 正在手輸，等一等
    nsPromise.then(function(ns){
      if(!ns){ fail('此視圖無自動儲存'); return; }
      publishing = true;
      status('儲存中…');
      saveLocal(); stashView();
      withTimeout(ns.publish(snapshotHtml()), 30000, 'publish')
        .then(function(){
          // 成功後 shell 會把本視圖重載到新版本；此行多半來不及顯示
          publishing = false; disabled = false;
          status('已儲存 ' + lines().length + ' 條');
        }).catch(function(e){
          publishing = false;
          var c = (e && e.code) || 'unknown';
          if(c === 'rate_limited'){
            status('儲存排隊中…'); pubTimer = setTimeout(publishNow, 30000); }
          else if(c === 'upstream_error' || c === 'publish_timeout'){
            pubTimer = setTimeout(publishNow, 5000 + Math.random() * 4000); }
          else if(c === 'conflict'){ saveLocal(); /* shell 正在重載到新版 */ }
          else { fail('自動儲存失效（' + c + '）'); }
        });
    }); }
  function schedulePublish(){
    status('未儲存…');
    clearTimeout(pubTimer); pubTimer = setTimeout(publishNow, 6000); }
  window.addEventListener('beforeunload', function(){ saveLocal(); });
  document.addEventListener('visibilitychange', function(){
    if(document.visibilityState === 'hidden'){ saveLocal(); } });

  // ── 事件發射 ──
  function seqNext(){
    var n = parseInt(log.getAttribute('data-seq') || '0', 10) + 1;
    log.setAttribute('data-seq', String(n)); return n; }
  function emit(ev){
    ev.batch = BATCH; ev.seq = seqNext();
    ev.ts = new Date().toISOString().slice(0, 19) + '+00:00';
    log.textContent += PREFIX + ' ' + JSON.stringify(ev) + '\\n';
    saveLocal(); schedulePublish(); progress(); refreshBar(); }

  // ── 卡片狀態 ──
  function cards(){ return list.querySelectorAll('.card'); }
  function cardOf(iid){
    for(var i = 0, cs = cards(); i < cs.length; i++)
      if(cs[i].getAttribute('data-iid') === iid) return cs[i];
    return null; }
  function setChosen(card, txt){
    card.querySelector('[data-slot="chosen"]').textContent = txt; }
  function applyVisual(ev){
    var card = cardOf(ev.instance_id); if(!card) return;
    if(ev.op === 'confirm'){
      card.setAttribute('data-state', 'done');
      card.removeAttribute('data-noadmit');
      setChosen(card, ev.admit === false ? ev.char + '·不入庫' : ev.char); }
    else if(ev.op === 'not_a_char'){
      card.setAttribute('data-state', 'nac'); setChosen(card, '非字'); }
    else if(ev.op === 'skip'){
      // 撤銷用 skip 事件回到「留隊列」——視覺上重新打開待審
      card.setAttribute('data-state',
        card.getAttribute('data-undone') === '1' ? 'open' : 'skip');
      setChosen(card, card.getAttribute('data-undone') === '1' ? '' : '疑');
      card.removeAttribute('data-undone'); } }

  function progress(){
    var done = list.querySelectorAll(
      '[data-state="done"],[data-state="nac"]').length;
    document.getElementById('prog').textContent =
      '本頁 ' + (PAGE_DONE + done) + ' / ' + PAGE_TOTAL;
    document.getElementById('bookprog').textContent =
      '全書 ' + (BOOK_DONE + done) + ' / ' + BOOK_TOTAL; }

  // ── 順序前進 ──
  function activeCard(){
    var a = list.querySelector('.card.active');
    if(a) return a;
    var open = list.querySelector('.card[data-state="open"]');
    if(open) setActive(open);
    return open; }
  function setActive(card){
    var a = list.querySelector('.card.active');
    if(a && a !== card) a.classList.remove('active');
    if(card){ card.classList.add('active');
      card.scrollIntoView({block: 'center', behavior: 'smooth'}); } }
  function advance(from){
    var cs = cards(), start = -1;
    for(var i = 0; i < cs.length; i++) if(cs[i] === from) start = i;
    for(var j = start + 1; j < cs.length; j++)
      if(cs[j].getAttribute('data-state') === 'open'){ setActive(cs[j]); return; }
    for(var k = 0; k < cs.length; k++)
      if(cs[k].getAttribute('data-state') === 'open'){ setActive(cs[k]); return; }
    status('本頁已審完，請點「複製記錄」貼回對話'); }

  // ── 裁決 ──
  function decide(card, op, ch){
    var iid = card.getAttribute('data-iid');
    var ev = {op: op, instance_id: iid};
    if(op === 'confirm'){
      ev.char = ch;
      // 「字形不入库」拨钮开着 → 定字进标注结果、字形不进 GlyphDB
      if(card.getAttribute('data-noadmit') === '1') ev.admit = false;
    }
    emit(ev);
    undoStack.push({iid: iid, op: op});
    applyVisual(ev);
    progress(); advance(card); }
  function confirmChar(card, ch){
    ch = (ch || '').trim(); if(!ch) return;
    decide(card, 'confirm', ch); }
  function undo(){
    var last = undoStack.pop();
    if(!last){ status('沒有可撤銷的操作'); return; }
    var card = cardOf(last.iid); if(!card) return;
    if(last.op === 'skip'){
      // skip 本就「留隊列」，撤銷只需重新打開卡片
      card.setAttribute('data-state', 'open'); setChosen(card, '');
    } else {
      // confirm/not_a_char 的撤銷：發 skip 事件把它退回隊列
      card.setAttribute('data-undone', '1');
      var ev = {op: 'skip', instance_id: last.iid};
      emit(ev); applyVisual(ev);
    }
    progress(); setActive(card); }
  function reopen(card){
    var st = card.getAttribute('data-state');
    if(st === 'done' || st === 'nac'){
      card.setAttribute('data-undone', '1');
      var ev = {op: 'skip', instance_id: card.getAttribute('data-iid')};
      emit(ev); applyVisual(ev);
    } else { card.setAttribute('data-state', 'open'); setChosen(card, ''); }
    progress(); setActive(card); }

  // ── 恢復：頁內嵌日誌（上次整頁發布帶回）∪ localStorage，
  //          按 (batch,seq) 合併去重、按 seq 順序重放 ──
  function restore(){
    var saved = log.textContent || '';
    var localTxt = '';
    try { localTxt = localStorage.getItem(LSKEY) || ''; } catch(e){}
    var seen = {}, merged = [], extra = 0;
    function add(l, isLocal){
      try { var ev = JSON.parse(l.slice(PREFIX.length + 1)); }
      catch(e){ return; }
      var key = ev.batch + '#' + ev.seq;
      if(seen[key]) return;
      seen[key] = 1; merged.push(l);
      if(isLocal) extra++; }
    (saved.match(/GUJI-SEED-EVENT .*/g) || []).forEach(function(l){ add(l, 0); });
    (localTxt.match(/GUJI-SEED-EVENT .*/g) || []).forEach(function(l){ add(l, 1); });
    if(merged.length){
      log.textContent = merged.join('\\n') + '\\n';
      var mx = 0;
      var evs = events();
      evs.forEach(function(ev){
        if(ev.batch === BATCH && ev.seq > mx) mx = ev.seq; });
      log.setAttribute('data-seq', String(mx));
      // 卡片可能已带上次快照的视觉状态：先归零再按日志重放，
      // 保证「日志是唯一真源」（快照状态与日志不可能分叉）
      for(var i = 0, cs = cards(); i < cs.length; i++){
        cs[i].setAttribute('data-state', 'open');
        cs[i].removeAttribute('data-undone');
        setChosen(cs[i], ''); }
      // 按 seq 順序重放：同一 instance 後到覆蓋
      evs.sort(function(a, b){ return (a.seq||0) - (b.seq||0); });
      evs.forEach(function(ev){
        if(ev.op === 'skip'){
          var c = cardOf(ev.instance_id);
          if(c) c.removeAttribute('data-undone'); }
        applyVisual(ev);
        undoStack.push({iid: ev.instance_id, op: ev.op}); });
    }
    progress();
    if(extra) schedulePublish();
    else if(merged.length) status('已儲存 ' + merged.length + ' 條');
    restoreView();
    if(!list.querySelector('.card.active')) advance(null); }

  // ── 交互：滑鼠 ──
  document.addEventListener('click', function(e){
    var card = e.target.closest('.card');
    var btn = e.target.closest('button');
    if(card && !btn && !e.target.closest('input')) setActive(card);
    if(!btn || !card) return;
    if(btn.classList.contains('cand'))
      confirmChar(card, btn.getAttribute('data-char'));
    else if(btn.classList.contains('other-ok'))
      confirmChar(card, card.querySelector('.other-in').value);
    else if(btn.classList.contains('nac')) decide(card, 'not_a_char');
    else if(btn.classList.contains('skip')) decide(card, 'skip');
    else if(btn.classList.contains('noadm')) toggleNoAdmit(card);
    else if(btn.classList.contains('reopen')) reopen(card);
  });
  function toggleNoAdmit(card){
    if(card.getAttribute('data-noadmit') === '1')
      card.removeAttribute('data-noadmit');
    else { card.setAttribute('data-noadmit', '1');
           status('已標記「字形不入庫」：接下來選的字只進標注結果'); }
    setActive(card); }

  // ── 交互：單鍵 ──
  document.addEventListener('keydown', function(e){
    if(e.ctrlKey || e.metaKey || e.altKey) return;
    var t = e.target;
    if(t && t.classList && t.classList.contains('other-in')){
      if(e.key === 'Enter'){
        confirmChar(t.closest('.card'), t.value); e.preventDefault(); }
      else if(e.key === 'Escape'){ t.value = ''; t.blur(); }
      return; }
    if(e.key === 'u' || e.key === 'U'){ undo(); e.preventDefault(); return; }
    var card = activeCard(); if(!card) return;
    if(e.key >= '1' && e.key <= '9'){
      var btns = card.querySelectorAll('.cand');
      var i = parseInt(e.key, 10) - 1;
      if(i < btns.length){
        confirmChar(card, btns[i].getAttribute('data-char'));
        e.preventDefault(); } }
    else if(e.key === 'n' || e.key === 'N'){
      decide(card, 'not_a_char'); e.preventDefault(); }
    else if(e.key === 's' || e.key === 'S'){
      decide(card, 'skip'); e.preventDefault(); }
    else if(e.key === 'b' || e.key === 'B'){
      toggleNoAdmit(card); e.preventDefault(); }
    else if(e.key === 'ArrowDown' || e.key === 'j'){
      advance(card); e.preventDefault(); }
    else if(e.key === 'ArrowUp' || e.key === 'k'){
      var cs = cards(), idx = -1;
      for(var i2 = 0; i2 < cs.length; i2++) if(cs[i2] === card) idx = i2;
      for(var j2 = idx - 1; j2 >= 0; j2--)
        if(cs[j2].getAttribute('data-state') === 'open'){
          setActive(cs[j2]); break; }
      e.preventDefault(); }
    else if(e.key.length === 1 || e.key === 'Process'){
      // 其他可打字鍵（含 IME 起手）→ 落進當前卡的手輸框
      var inp = card.querySelector('.other-in');
      if(inp){ inp.focus(); } }
  });

  // ── 匯出：複製為主，下載/全選兜底 ──
  var dlNs = null;
  if(window.claude && window.claude.use){
    withTimeout(window.claude.use('downloads'), 15000, 'use')
      .then(function(dl){ dlNs = dl; }).catch(function(){}); }
  function selectLog(msg){
    var det = log.closest('details');
    if(det) det.open = true;
    log.scrollIntoView({block: 'center'});
    try {
      var r = document.createRange(); r.selectNodeContents(log);
      var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
    } catch(e){}
    status(msg); }
  function payload(){
    return lines().join('\\n'); }
  document.getElementById('copybar').addEventListener('click', function(){
    var text = payload();
    if(!text){ status('還沒有審查記錄'); return; }
    var n = lines().length;
    if(navigator.clipboard && navigator.clipboard.writeText){
      navigator.clipboard.writeText(text).then(function(){
        markExported(n); status('已複製 ' + n + ' 條，貼回對話即可');
      }).catch(function(){
        selectLog('已全選 ' + n + ' 條：按 Ctrl/Cmd+C 複製'); });
    } else {
      selectLog('已全選 ' + n + ' 條：按 Ctrl/Cmd+C 複製'); } });
  document.getElementById('dl').addEventListener('click', function(){
    var text = payload();
    if(!text){ status('還沒有審查記錄'); return; }
    if(!dlNs){ selectLog('此處無法下載：日誌已全選，按 Ctrl/Cmd+C 複製'); return; }
    dlNs.save({filename: BATCH + '.seed_events.txt', data: text})
      .then(function(){ markExported(lines().length);
                        status('已下載 ' + lines().length + ' 條'); })
      .catch(function(){
        selectLog('下載被拒絕：日誌已全選，按 Ctrl/Cmd+C 複製'); }); });

  restore();
  refreshBar();
})();
"""


def render_seed_html(batch: dict, title: str | None = None) -> str:
    """批次 → 自包含单文件 HTML（可发布为 Artifact，也可静态托管）。"""
    title = title or f'{batch["book"]} 种子审查 · 第{batch["page"]}页'
    cards = "\n".join(_render_seed_card(e) for e in batch["entries"])
    pages_nav = "、".join(f'{p["page"]}({p["n"]})'
                          for p in batch.get("pages_pending", [])[:12])
    consts = (f'var BATCH = {json.dumps(batch["batch_id"])};'
              f'var PAGE_TOTAL = {batch["page_total"]};'
              f'var PAGE_DONE = {batch["page_done"]};'
              f'var BOOK_TOTAL = {batch["book_total"]};'
              f'var BOOK_DONE = {batch["book_done"]};')
    return f"""<title>{_esc(title)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+TC:wght@400;600&display=swap">
<style>{_CSS}</style>
<header class="top">
<h1>{_esc(title)}</h1>
<span class="prog" id="prog">本頁 {batch["page_done"]} / {batch["page_total"]}</span>
<span class="prog" id="bookprog">全書 {batch["book_done"]} / {batch["book_total"]}</span>
<span class="prog" id="save-status"></span>
<button type="button" id="copybar" data-pending="0">尚無記錄</button>
<button type="button" id="dl">下載存檔</button>
</header>
<main class="list" id="list">
{cards}
</main>
<footer class="foot">
<p class="hint">單鍵：<kbd>1</kbd>–<kbd>9</kbd> 選候選 ｜ 直接打字手輸正字（Enter 確認）
｜ <kbd>N</kbd> 非字 ｜ <kbd>S</kbd> 存疑跳過 ｜ <kbd>B</kbd> 字形不入庫（先撥開，再選字：
圖塊混殘余時字只進標注結果、不進字形庫當範例）｜ <kbd>U</kbd> 撤銷上一條
｜ <kbd>↑</kbd><kbd>↓</kbd> 移動。已裁決卡片自動收起，點「改」可復查。
停手約 6 秒自動儲存（儲存瞬間頁面會刷新一下，位置自動接續），關頁重開會自動恢復。
審完後告訴 Claude 一聲即可——裁決已隨頁面儲存，Claude 能直接讀取；
「複製記錄」是不依賴任何平台功能的兜底路徑。
{'尚有待審頁：' + _esc(pages_nav) if pages_nav else ''}</p>
<details><summary>事件日誌（審查記錄，可全選複製）</summary>
<pre class="log" id="guji-log" data-seq="0" data-batch="{_esc(batch["batch_id"])}"></pre>
</details>
</footer>
<script>{consts}{_JS}</script>
"""


# ── 事件回收（页面侧只负责解析验证，写库由流程侧 seed-ingest 做）─────

def ingest_seed_events(text: str) -> list[dict]:
    """从页面回收文本解析种子决策事件（薄封装 parse_seed_events）。

    返回去重后的事件列表；空文本 / 无合法事件返回 []。前缀常量与
    op 白名单都在 seed_queue 契约里，这里不复制判断逻辑。
    """
    if not text:
        return []
    return parse_seed_events(text)


def export_seed_batch(book_out_dir, queue_path, page: str | None = None,
                      out_path=None, limit: int = 200,
                      title: str | None = None) -> Path:
    """装配 + 渲染 + 落盘，返回 HTML 路径（CLI 的主入口）。"""
    batch = build_seed_batch(book_out_dir, queue_path, page=page, limit=limit)
    out = (Path(out_path) if out_path
           else Path(queue_path).parent / f'{batch["batch_id"]}.html')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_seed_html(batch, title=title), encoding="utf-8")
    return out


# 供页面/测试引用的事件前缀（单一事实源在 seed_queue）
__all__ = ["build_seed_batch", "render_seed_html", "ingest_seed_events",
           "export_seed_batch", "SEED_EVENT_PREFIX"]
