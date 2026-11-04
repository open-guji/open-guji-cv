# -*- coding: utf-8 -*-
"""新字快速确认：把待审格里「整理本字的字头完全不在字形库」的格挑出来，出带图的确认页，
人点完后批量写人裁事件、落库。

每次大批重跑新书后都会冒出很多待审格；其中整理本的字若在字形库里**一例都没有**，库就
没机会自己认出来（5a 只能从库里挑）。这类格人看一眼「整理本对不对」，点一下，落库后
这个字头就有了第一批刻例，之后别的页、别的册同一个字能自动匹配。

三步，一条命令一步，**缺省都不碰中心库**：

    # 1. 挑格 + 出页（只读）。产物根给 pack fetch 取回的目录或本机 products
    python scripts/build_newchar_review.py collect --books vol06,vol07 \\
        --products-root /tmp/prod -w $WS --out /tmp/newchar
    #    → /tmp/newchar/cards.jsonl（卡片冻结，重出页 id 不变）、review.html、crops/<格号>.png、summary.tsv
    #    用 review-artifact 的流程发布 review.html（capabilities={"artifact": {}}），人点；
    #    收回：python .claude/skills/review-artifact/scripts/harvest_verdicts.py read_back.html -o verdicts.jsonl

    # 2. 裁决 → 人裁事件（缺省 dry-run：只写 events.jsonl 与清单，不动事件日志）
    python scripts/build_newchar_review.py apply --cards /tmp/newchar/cards.jsonl \\
        --verdicts verdicts.jsonl --out /tmp/newchar -w $WS
    #    --execute 追加进本机事件日志（带锚）；再加 --admit 本机跑 glyphdb_admit 落 glyph.db。
    #    推中心库（guji db sync）、出 g<N> 要 Sheldon 点头，本脚本不做。

## 裁决（卡上的按钮）
- `ref`      整理本字对 → confirm，shape = 整理本字。
- `pick:字`  库首选／5b 候选里某个字对 → confirm，shape = 该字。
- `seg`      切分有问题 → **不写事件**，列进 seg_issues.tsv 转切分线；
- `unclear`  看不清 → **不写事件**，列进 unclear.tsv；
- `other`    另是别的字（页上没法输字）→ 不写事件，列进 other.tsv，由人回复字后再补。

## 口径（Sheldon 10-25）
只收**意思相同**的字；形近但意思不同的（个/今、己/已/巳）一概不能并，拆不开就点「看不清」。
本脚本从不做归一：确认的是「这格就是这个字头」，落库也按这个字头入。

## 「新字」的定义
整理本字（align_ref 对位出的字）在库里的有效刻例数 < `--min-count`（缺省 1，即一例都没有）。
库 = `glyph.db` 的 instances（label_status 不含 human_stale*）。想把「不足 3 例」也收进来给 `--min-count 3`。
"""
from __future__ import annotations

import argparse
import base64
import collections
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

KEY = "newchar-review-v1"
TITLE = "新字确认"
CTX_RADIUS = 6
IMG_H = 72

DOC = __doc__


# ───────────────────────────── 收集 ─────────────────────────────

def lib_counts(db_path: str | Path) -> collections.Counter:
    """字形库里每个字头的有效刻例数（label_status 不含 human_stale*）。"""
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = c.execute("SELECT label, COUNT(*) FROM instances "
                         "WHERE label IS NOT NULL AND label != '' "
                         "AND COALESCE(label_status,'') NOT LIKE 'human_stale%' GROUP BY label").fetchall()
    finally:
        c.close()
    return collections.Counter({k: n for k, n in rows})


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _cell_sort(cid: str):
    book, page, col, slot, *rest = cid.split(":") + [""]
    sub = rest[0] if rest else ""
    return (book, int(page), int(col), int(slot.rstrip("ab") or 0), slot[-1] if slot[-1:] in "ab" else sub)


def collect_book(book: str, products: Path, counts: collections.Counter, min_count: int,
                 skip: set[str], stats: collections.Counter, only: set[str] | None = None) -> list[dict]:
    """一册里的新字待审格 → 卡片 dict 列表。"""
    root = products / book
    if not (root / "seed_admit").is_dir():
        sys.exit(f"{root}/seed_admit 不存在：产物根不对？（pack fetch --to X 会落在 X/<册>/）")
    out: list[dict] = []
    for sf in sorted((root / "seed_admit").glob("p*.json")):
        key = sf.stem
        page = _read(sf)["seed_admit"]
        ar = root / "align_ref" / sf.name
        gm = root / "glyph_match" / sf.name
        rc = root / "rare_candidates" / sf.name
        align = _read(ar)["align_ref"] if ar.exists() else {"chars": []}
        # 序列对位（chars）没对上的格，坐标对位（coord）常能给出整理本字：seed_admit 的 rare_ref_coord 就吃这个
        chars = list(align.get("chars", []))
        have = {c["id"] for c in chars}
        for c in align.get("coord", []):
            if c["id"] not in have and c.get("ref_char") and c["ref_char"] != "〓":
                chars.append({"id": c["id"], "col": c["col"], "slot": c["slot"], "sub": c.get("sub"),
                              "align_char": c["ref_char"]})
        align = {"chars": chars}
        ref_by_id = {c["id"]: c for c in align.get("chars", [])}
        # 同列按读序排的整理本字，给上下文用
        cols: dict[int, list[dict]] = collections.defaultdict(list)
        for c in align.get("chars", []):
            cols[c["col"]].append(c)
        for v in cols.values():
            v.sort(key=lambda c: (c["slot"], c.get("sub") or ""))
        gm_by_id = {c["id"]: c for col in (_read(gm)["glyph_match"]["columns"] if gm.exists() else [])
                    for c in col["chars"]}
        rc_by_id = {c["id"]: c for col in (_read(rc)["rare_candidates"]["columns"] if rc.exists() else [])
                    for c in col["chars"]}
        for col in page["columns"]:
            for c in col.get("chars", []):
                stats["cells"] += 1
                cid = c["id"]
                if only is not None and cid not in only:
                    continue
                if c["admit"]:
                    if only is not None:
                        stats["admitted_now"] += 1  # 清单里的格这版已放行，不用再看
                    continue
                stats["review"] += 1
                ref = (ref_by_id.get(cid) or {}).get("align_char") or ""
                if only is None:
                    if not ref or len(ref) != 1:
                        stats["no_ref"] += 1
                        continue
                    if counts.get(ref, 0) >= min_count:
                        stats["ref_in_lib"] += 1
                        continue
                    if cid in skip:
                        stats["already_judged"] += 1
                        continue
                elif len(ref) != 1:
                    ref = ""  # 整理本缺字（〓）或多字：没有整理本字，按 5b 首选分组
                g = gm_by_id.get(cid) or {}
                lib_top = (g.get("candidates") or [[None, 0]])[0][0] or c.get("char") or ""
                r5 = []
                for cand in (rc_by_id.get(cid) or {}).get("candidates", []):
                    ch = cand["char"]
                    if ch not in r5:
                        r5.append(ch)
                    if len(r5) == 3:
                        break
                ctx = ""
                if cid in ref_by_id:
                    seq = cols.get(ref_by_id[cid]["col"], [])
                    idx = next((i for i, x in enumerate(seq) if x["id"] == cid), None)
                    if idx is not None:
                        lo, hi = max(0, idx - CTX_RADIUS), idx + CTX_RADIUS + 1
                        ctx = "".join((f"【{x['align_char']}】" if i == idx else (x.get("align_char") or "□"))
                                      for i, x in enumerate(seq[lo:hi], start=lo))
                else:  # 整理本里没这格：拿本列已识别的字当上下文
                    seq = col.get("chars", [])
                    idx = next((i for i, x in enumerate(seq) if x["id"] == cid), None)
                    if idx is not None:
                        lo, hi = max(0, idx - CTX_RADIUS), idx + CTX_RADIUS + 1
                        ctx = "".join((f"【{x.get('char') or '□'}】" if i == idx else
                                       ((x.get("char") or "□") if x.get("admit") else "□"))
                                      for i, x in enumerate(seq[lo:hi], start=lo))
                doubts = [d if isinstance(d, str) else json.dumps(d, ensure_ascii=False) for d in c["doubts"]]
                out.append({
                    "id": cid, "book": book, "page": int(key[1:]),
                    "ref": ref, "ref_n_lib": counts.get(ref, 0) if ref else 0,
                    "grp": ref or (r5[0] if r5 else lib_top), "kind": "ref" if ref else "cand",
                    "lib_top": lib_top, "lib_cov": g.get("cov"), "r5": r5, "ctx": ctx,
                    "doubts": doubts,
                    # 上下文护栏拿整理本字顶上来的格：整理本字未必对，页上黄底单独标
                    "warn": any(d.startswith("ctx_guard_ref") for d in doubts),
                })
    return out


# ───────────────────────────── 字块图 ─────────────────────────────

def _crop_api():
    """取字块图要用的几件东西（同 `guji product patch`）。"""
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.step import RunContext
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.store import ProductStore
    return load_book, RunContext, ImageCache, ProductStore


def crop_images(cards: list[dict], crops_dir: Path) -> dict[str, str]:
    import cv2
    import numpy as np
    from open_guji_cv.core.spec import cell_key
    load_book, RunContext, ImageCache, ProductStore = _crop_api()
    crops_dir.mkdir(parents=True, exist_ok=True)
    st, cache = ProductStore(), ImageCache()
    ctxs: dict[str, object] = {}
    imgs: dict[str, str] = {}
    for card in cards:
        book = card["book"]
        if book not in ctxs:
            ctxs[book] = RunContext(load_book(book), st, cache, log=lambda s: None)
        _, page, col, slot, *rest = card["id"].split(":") + [""]
        sub = rest[0] if rest else ""
        m = re.match(r"(\d+)(.*)", slot)  # 槽号带字母后缀（如 8b）：后缀算 sub
        if not m:  # 槽号 -1 等（抬头外的特殊位）：没有字块图
            print(f"  [无图] {card['id']}: 槽号 {slot!r} 不是正常格", file=sys.stderr)
            continue
        slot, sub = m.group(1), (m.group(2) + sub)
        key = cell_key(int(page), int(col), int(slot)) + (sub or "")
        try:
            f = cache.get(book, "char_patch", key) or ctxs[book].materialize("char_patch", key)
            raw = Path(f).read_bytes()
        except Exception as e:  # noqa: BLE001
            print(f"  [无图] {card['id']}: {e}", file=sys.stderr)
            continue
        (crops_dir / (card["id"].replace(":", "_") + ".png")).write_bytes(raw)
        im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
        if im is None:
            continue
        h, w = im.shape
        s = IMG_H / h
        im = cv2.resize(im, (max(1, round(w * s)), IMG_H), interpolation=cv2.INTER_AREA)
        im = (im // 16 * 16 + 8).astype("uint8")  # 16 级灰，压体积
        ok, buf = cv2.imencode(".png", im)
        if ok:
            imgs[card["id"]] = "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()
    return imgs


# ───────────────────────────── 页 ─────────────────────────────

CSS = """
.card{background:var(--surface);border:1px solid var(--rule);border-left:3px solid transparent;
  border-radius:3px;padding:10px 12px;box-shadow:var(--shadow);margin-top:10px}
.card[data-v="ref"],.card[data-v^="pick"]{border-left-color:var(--ok)}
.card[data-v="seg"]{border-left-color:var(--zhu)}
.card[data-v="other"]{border-left-color:var(--ochre)}
.card[data-v="unclear"]{border-left-color:var(--faint)}
.card.warn{background:var(--ochre-soft)}
.row1{display:flex;gap:12px;align-items:center}
.row1 img{height:96px;background:var(--tile);border-radius:2px;image-rendering:pixelated;flex:none;max-width:45%}
.noimg{height:96px;width:70px;display:flex;align-items:center;justify-content:center;color:var(--faint);
  font-size:12px;background:var(--sunk);border-radius:2px;flex:none}
.big{font-family:var(--serif);font-size:44px;line-height:1.1}
.meta{font-size:12px;color:var(--muted);margin:2px 0 0}
.ctx{font-family:var(--serif);font-size:15px;margin:8px 0 0;word-break:break-all}
.tag{display:inline-block;font-size:11px;padding:0 5px;border-radius:2px;background:var(--sunk);color:var(--muted);margin-right:4px}
.tag.w{background:var(--ochre-soft);color:var(--ochre)}
.verdicts{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.verdicts button{min-height:44px;min-width:64px;padding:0 10px;border:1px solid var(--rule-hard);border-radius:3px;
  background:var(--surface);color:var(--ink);font-family:var(--sans);font-size:13px;font-weight:500;cursor:pointer}
.verdicts button .c{font-family:var(--serif);font-size:20px;margin-left:4px}
.verdicts button:active{background:var(--sunk)}
.verdicts button[aria-pressed="true"]{color:var(--on-solid);border-color:transparent}
.verdicts button.ref[aria-pressed="true"],.verdicts button.pick[aria-pressed="true"]{background:var(--ok)}
.verdicts button.sg[aria-pressed="true"]{background:var(--zhu)}
.verdicts button.other[aria-pressed="true"]{background:var(--ochre)}
.verdicts button.unclear[aria-pressed="true"]{background:var(--faint)}
.bulk{margin:10px 0 0}
.bulk button{min-height:40px;padding:0 12px;border:1px dashed var(--rule-hard);border-radius:3px;background:var(--surface);
  color:var(--ink);font-size:13px;cursor:pointer}
.bulk button.armed{background:var(--ok);color:var(--on-solid);border-style:solid}
"""

PAGE_JS = r"""
const BODY = `
<header class="top"><div class="top-in">
  <span class="brand">__TITLE__</span>
  <span class="save" id="save">本机</span>
  <span class="count" id="count">0 / 0</span>
</div><div class="bar"><i id="prog"></i></div></header>
<div class="wrap">
  <details class="intro" id="intro" open>
    <summary>怎么裁</summary>
    <p>这些格的整理本字，字形库里<b>一例都没有</b>。看图：整理本字对就点第一个按钮；
       库首选／5b 候选里有对的字就点那个字；切分有问题或看不清单独点，<b>不会入库</b>。
       黄底 ⚠ = 上下文护栏拿整理本字顶上来的格，整理本字未必对，请重点看。<br>
       <b>只收意思相同的字</b>：形近但意思不同的（个/今、己/已/巳）不能并，拆不开就点「看不清」。</p>
  </details>
  <div class="ctrl">
    <div class="seg" id="filter">
      <button data-f="todo" aria-pressed="true">未裁</button>
      <button data-f="all" aria-pressed="false">全部</button>
      <button data-f="done" aria-pressed="false">已裁</button>
    </div>
    <button class="ghost" id="copy">复制</button>
    <button class="ghost" id="reset">清空</button>
  </div>
  <div class="bulk"><button id="bulk">未裁且无 ⚠ 的全标「整理本字对」</button></div>
  <div class="list" id="list"></div>
</div>
<div class="sheet" id="sheet" hidden><div class="sheet-in">
  <h2>裁决结果</h2><p id="sheet-note"></p>
  <textarea id="sheet-text" readonly></textarea>
  <div class="row"><button class="ghost" id="sheet-copy">复制</button>
  <button class="ghost" id="sheet-close">关闭</button></div>
</div></div>`;

const rowId = r => r.id;

function buttons(r){
  const bs = [['ref', 'ref', '整理本字对', r.ref]];
  const seen = new Set([r.ref]);
  const add = (ch, lab) => { if (ch && !seen.has(ch)){ seen.add(ch); bs.push(['pick', 'pick:' + ch, lab, ch]); } };
  add(r.lib_top, '库首选');
  (r.r5 || []).forEach(ch => add(ch, '5b'));
  bs.push(['sg', 'seg', '切分有问题', ''], ['unclear', 'unclear', '看不清', ''], ['other', 'other', '另有其字', '']);
  return bs;
}

function card(r){
  const v = verdictOf(r.id);
  const btn = ([cls, val, lab, ch]) =>
    `<button class="${cls}" data-v="${esc(val)}" aria-pressed="${v === val}">${lab}${ch ? `<span class="c">${esc(ch)}</span>` : ''}</button>`;
  const img = D.imgs[r.id] ? `<img data-src="${esc(r.id)}" alt="">` : `<div class="noimg">无图</div>`;
  return `<article class="card${r.warn ? ' warn' : ''}" data-id="${esc(r.id)}"${v ? ` data-v="${esc(v)}"` : ''}>
    <div class="row1">${img}
      <div><div class="big">${esc(r.ref)}</div>
        <p class="meta">${r.warn ? '<span class="tag w">⚠ 护栏顶上来的</span>' : ''}<span class="tag">${esc(r.id)}</span></p>
        <p class="meta">库首选 ${esc(r.lib_top || '—')}${r.lib_cov ? ' cov ' + r.lib_cov : ''}　5b ${esc((r.r5 || []).join(' ') || '—')}</p></div></div>
    <p class="ctx">${esc(r.ctx)}</p>
    <div class="verdicts">${buttons(r).map(btn).join('')}</div>
  </article>`;
}

let filter = 'todo';
function visibleRows(){
  if (filter === 'all') return D.rows;
  const done = filter === 'done';
  return D.rows.filter(r => !!verdictOf(r.id) === done);
}
document.addEventListener('click', e => {
  const b = e.target.closest('#filter button'); if (!b) return;
  filter = b.dataset.f;
  [...b.parentElement.children].forEach(x => x.setAttribute('aria-pressed', String(x === b)));
  draw();
});
/* 批量：两下才生效，防手滑。只动「未裁、无 ⚠」的卡 */
let bulkArmed = 0;
document.addEventListener('click', e => {
  const b = e.target.closest('#bulk'); if (!b) return;
  if (!bulkArmed){
    const n = D.rows.filter(r => !verdictOf(r.id) && !r.warn).length;
    b.textContent = `再点一次：把 ${n} 张标成「整理本字对」`; b.classList.add('armed');
    bulkArmed = setTimeout(() => { bulkArmed = 0; b.classList.remove('armed');
      b.textContent = '未裁且无 ⚠ 的全标「整理本字对」'; }, 4000);
    return;
  }
  clearTimeout(bulkArmed); bulkArmed = 0; b.classList.remove('armed');
  b.textContent = '未裁且无 ⚠ 的全标「整理本字对」';
  const t = Date.now();
  D.rows.forEach(r => { if (!verdictOf(r.id) && !r.warn) state[r.id] = {v: 'ref', t}; });
  persist(); draw();
});
function afterVerdict(){ if (filter !== 'all') draw(); }

function payload(){
  return D.rows.filter(r => verdictOf(r.id))
    .map(r => JSON.stringify({id: r.id, verdict: verdictOf(r.id)})).join('\n');
}
""".replace("__TITLE__", TITLE)


def build_html(cards: list[dict], imgs: dict[str, str], verdicts: dict | None = None) -> str:
    sys.path.insert(0, str(REPO / ".claude" / "skills" / "review-artifact" / "scripts"))
    from review_shell import render
    return render(TITLE, KEY, verdicts=verdicts or {}, css=CSS, page_js=PAGE_JS,
                  payload={"rows": cards, "imgs": imgs})



# ───────────────────────────── 一字一卡 ─────────────────────────────

GROUP_CSS = r"""
.g-card{background:var(--surface);border:1px solid var(--rule);border-radius:3px;padding:10px 12px;
  box-shadow:var(--shadow);margin-top:12px}
.g-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.g-head .big{font-family:var(--serif);font-size:40px;line-height:1.1}
.g-head .gm{font-size:12px;color:var(--muted);flex:1;min-width:8rem}
.g-head .gm b{color:var(--ink);font-weight:600}
.gbtns{display:flex;gap:6px}
.gbtn{min-height:40px;padding:0 10px;border:1px solid var(--rule-hard);border-radius:3px;background:var(--surface);
  color:var(--ink);font-size:13px;font-weight:500;cursor:pointer}
.gbtn.ok{border-color:var(--ok);color:var(--ok)}
.gbtn:active{background:var(--sunk)}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(104px,1fr));gap:8px;margin-top:10px}
.tile{border:1px solid var(--rule);border-left:3px solid var(--rule-hard);border-radius:3px;padding:5px 6px;
  background:var(--ground);cursor:pointer;min-width:0;user-select:none}
.tile.warn{background:var(--ochre-soft)}
.tile img{display:block;height:64px;max-width:100%;margin:0 auto;background:var(--tile);border-radius:2px;
  image-rendering:pixelated}
.tile .noimg{height:64px;width:100%}
.tile .tl{font-size:12px;font-weight:600;margin-top:3px;min-height:1.2em;color:var(--faint)}
.tile .tc{font-family:var(--serif);font-size:12px;line-height:1.35;word-break:break-all;color:var(--ink)}
.tile .tm{font-size:10.5px;color:var(--muted);line-height:1.3;margin-top:2px;word-break:break-all}
.tile[data-v="ok"]{border-left-color:var(--ok)} .tile[data-v="ok"] .tl{color:var(--ok)}
.tile[data-v="pick"]{border-left-color:var(--indigo)} .tile[data-v="pick"] .tl{color:var(--indigo)}
.tile[data-v="seg"]{border-left-color:var(--zhu)} .tile[data-v="seg"] .tl{color:var(--zhu)}
.tile[data-v="other"]{border-left-color:var(--ochre)} .tile[data-v="other"] .tl{color:var(--ochre)}
.tile[data-v="unclear"]{border-left-color:var(--faint)}
.ctrl2{display:flex;gap:8px;margin:8px 0 0}
.g-note{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:8px}
.g-note input{min-height:40px;width:7.5rem;padding:0 8px;border:1px solid var(--rule-hard);border-radius:3px;
  background:var(--ground);color:var(--ink);font-family:var(--serif);font-size:18px}
.g-note .chip{min-height:36px;min-width:36px;padding:0 8px;border:1px solid var(--rule-hard);border-radius:3px;
  background:var(--surface);color:var(--ink);font-family:var(--serif);font-size:18px;cursor:pointer}
.g-note small{color:var(--muted);font-size:11.5px}
"""

GROUP_JS = r"""
const BODY = `
<header class="top"><div class="top-in">
  <span class="brand">__TITLE__</span>
  <span class="save" id="save">本机</span>
  <span class="count" id="count">0 / 0</span>
</div><div class="bar"><i id="prog"></i></div></header>
<div class="wrap">
  <details class="intro" id="intro" open>
    <summary>怎么裁（一字一卡）</summary>
    <p>每张卡是<b>一个字</b>，下面是这个字的所有待审格。<b>点格子</b>切换：
       <b>✓ 对</b>（整理本字或 5b 首选字就是这格的字）→ <b>看不清</b> → <b>切分有问题</b> → <b>另有其字</b> → 清除。
       一组基本都对时点<b>「整组都对」</b>，只会标还没裁的格，之后把例外的格点掉即可。
       黄底 ⚠ = 上下文护栏拿整理本字顶上来的格，整理本字未必对。<br>
       <b>整理本缺字</b>那类没有整理本字，卡头是 5b 首选字，只能看图判断是不是这个字。
       <b>只收意思相同的字</b>：形近但意思不同的（个/今、己/已/巳）不能并，拆不开就点「看不清」。</p>
  </details>
  <div class="ctrl">
    <div class="seg" id="filter">
      <button data-f="todo" aria-pressed="true">未裁</button>
      <button data-f="all" aria-pressed="false">全部</button>
      <button data-f="done" aria-pressed="false">已裁</button>
    </div>
    <button class="ghost" id="copy">复制</button>
    <button class="ghost" id="reset">清空</button>
  </div>
  <div class="ctrl2"><div class="seg" id="kfilter">
      <button data-k="" aria-pressed="true">全部类</button>
      <button data-k="ref" aria-pressed="false">有整理本字</button>
      <button data-k="pua" aria-pressed="false">未收字（按码位）</button>
      <button data-k="cand" aria-pressed="false">其它缺字</button>
  </div></div>
  <div class="list" id="list"></div>
</div>
<div class="sheet" id="sheet" hidden><div class="sheet-in">
  <h2>裁决结果</h2><p id="sheet-note"></p>
  <textarea id="sheet-text" readonly></textarea>
  <div class="row"><button class="ghost" id="sheet-copy">复制</button>
  <button class="ghost" id="sheet-close">关闭</button></div>
</div></div>`;

const rowId = r => r.id;
let _groups = null;  /* page_js 先于壳里的 D 初始化，所以分组要用到时才建 */
const groups = () => _groups || (_groups = (() => {
  const m = new Map();
  D.rows.forEach(r => {
    const k = r.kind + ':' + r.grp;
    if (!m.has(k)) m.set(k, {id: 'G:' + k, key: r.grp, kind: r.kind, cells: []});
    m.get(k).cells.push(r);
  });
  return [...m.values()].sort((a, b) => b.cells.length - a.cells.length || a.key.localeCompare(b.key));
})());
const okVal = r => r.kind === 'ref' ? 'ref' : r.kind === 'pua' ? 'same' : 'pick:' + r.grp;
const CYCLE = r => [okVal(r), 'unclear', 'seg', 'other'];
function vclass(r, v){
  if (!v) return '';
  if (v === okVal(r)) return 'ok';
  if (v.startsWith('pick:')) return 'pick';
  return v;
}
function vlabel(r, v){
  if (!v) return '';
  if (v === okVal(r)) return '✓ 对';
  if (v.startsWith('pick:')) return '→ ' + v.slice(5);
  return {unclear: '看不清', seg: '切分有问题', other: '另有其字', ref: '✓ 对', same: '✓ 同字'}[v] || v;
}
function short(ctx){
  const i = ctx.indexOf('【'), j = ctx.indexOf('】');
  if (i < 0) return ctx;
  return ctx.slice(Math.max(0, i - 3), i) + ctx.slice(i, j + 1) + ctx.slice(j + 1, j + 4);
}
function tile(r){
  const v = verdictOf(r.id), img = D.imgs[r.id] ? `<img data-src="${esc(r.id)}" alt="">` : `<div class="noimg">无图</div>`;
  const cand = (r.lib_top ? '库 ' + r.lib_top : '') + (r.r5 && r.r5.length ? ' · 5b ' + r.r5.slice(0, 2).join('') : '');
  return `<div class="tile${r.warn ? ' warn' : ''}" data-cell="${esc(r.id)}"${v ? ` data-v="${vclass(r, v)}"` : ''}
    title="${esc(r.id)}">${img}<div class="tl">${esc(vlabel(r, v))}</div>
    <div class="tc">${esc(short(r.ctx || ''))}</div><div class="tm">${esc(cand)}</div></div>`;
}
function ghead(g){
  const n = g.cells.length, d = g.cells.filter(r => verdictOf(r.id)).length;
  const kind = g.kind === 'ref' ? '整理本字' : g.kind === 'pua' ? '整理本未收字（同码位＝同一个字）' : '整理本缺字 · 5b 首选字';
  const lib = g.kind === 'ref' ? `　库内 <b>${g.cells[0].ref_n_lib}</b> 例` : '';
  return `<span class="big">${esc(g.key)}</span><div class="gm"><b>${n}</b> 格　${kind}${lib}<br>已裁 <b>${d}</b> / ${n}</div>
    <div class="gbtns"><button class="gbtn ok" data-a="ok">${g.kind === 'pua' ? '整组同字' : '整组都对'}</button><button class="gbtn" data-a="unclear">整组看不清</button></div>`;
}
function gnote(g){
  const cnt = {};
  g.cells.forEach(r => [r.lib_top].concat((r.r5 || []).slice(0, 1)).forEach(ch => { if (ch) cnt[ch] = (cnt[ch] || 0) + 1; }));
  const top = Object.entries(cnt).sort((a, b) => b[1] - a[1]).slice(0, 4).map(x => x[0]);
  const cur = (verdictOf('N:' + g.key) || '').replace(/^char:/, '');
  return `<div class="g-note"><input type="text" data-note="${esc(g.key)}" value="${esc(cur)}" placeholder="这个字是…" autocomplete="off">
    ${top.map(c => `<button class="chip" data-chip="${esc(c)}" title="库首选或 5b 里出现最多的字">${esc(c)}</button>`).join('')}
    <small>输入近似字，没有就留空；可写 IDS（如 ⿰言反）</small></div>`;
}
function card(g){
  return `<article class="g-card" data-id="${esc(g.id)}"><div class="g-head">${ghead(g)}</div>
    ${g.kind === 'pua' ? gnote(g) : ''}<div class="tiles">${g.cells.map(tile).join('')}</div></article>`;
}
let filter = 'todo', kfilter = '';
function visibleRows(){
  return groups().filter(g => (!kfilter || g.kind === kfilter) &&
    (filter === 'all' || (filter === 'done') === (g.cells.every(r => verdictOf(r.id)) && (g.kind !== 'pua' || !!verdictOf('N:' + g.key)))));
}
function groupOf(art){ return groups().find(g => g.id === art.dataset.id); }
function repaint(art, r){
  const g = groupOf(art);
  if (r){
    const t = art.querySelector(`.tile[data-cell="${CSS.escape(r.id)}"]`), v = verdictOf(r.id);
    if (v) t.dataset.v = vclass(r, v); else t.removeAttribute('data-v');
    t.querySelector('.tl').textContent = vlabel(r, v);
  }
  art.querySelector('.g-head').innerHTML = ghead(g);
  tally();
}
function setNote(key, val){
  val = (val || '').trim();
  if (val) state['N:' + key] = {v: 'char:' + val, t: Date.now()}; else delete state['N:' + key];
  persist();
}
document.addEventListener('input', e => { const i = e.target.closest('input[data-note]'); if (i) setNote(i.dataset.note, i.value); });
document.addEventListener('click', e => {
  let b = e.target.closest('.chip');
  if (b){ const i = b.closest('.g-note').querySelector('input'); i.value = b.dataset.chip; setNote(i.dataset.note, i.value); return; }
  b = e.target.closest('#filter button');
  if (b){ filter = b.dataset.f; [...b.parentElement.children].forEach(x => x.setAttribute('aria-pressed', String(x === b))); draw(); return; }
  b = e.target.closest('#kfilter button');
  if (b){ kfilter = b.dataset.k; [...b.parentElement.children].forEach(x => x.setAttribute('aria-pressed', String(x === b))); draw(); return; }
  b = e.target.closest('.gbtn');
  if (b){
    const art = b.closest('.g-card'), g = groupOf(art), t = Date.now();
    g.cells.forEach(r => { if (!verdictOf(r.id)) state[r.id] = {v: b.dataset.a === 'ok' ? okVal(r) : 'unclear', t}; });
    persist();
    g.cells.forEach(r => repaint(art, r));
    return;
  }
  b = e.target.closest('.tile');
  if (b){
    const art = b.closest('.g-card'), g = groupOf(art), r = g.cells.find(x => x.id === b.dataset.cell);
    const cyc = CYCLE(r), cur = verdictOf(r.id), i = cyc.indexOf(cur);
    if (cur && i < 0) delete state[r.id];
    else if (i === cyc.length - 1) delete state[r.id];
    else state[r.id] = {v: cyc[i + 1], t: Date.now()};
    persist(); repaint(art, r);
  }
});
function afterVerdict(){}
function payload(){
  return D.rows.filter(r => verdictOf(r.id))
    .map(r => JSON.stringify({id: r.id, verdict: verdictOf(r.id)})).join('\n');
}
"""


def build_html_grouped(cards: list[dict], imgs: dict[str, str], verdicts: dict | None = None) -> str:
    sys.path.insert(0, str(REPO / ".claude" / "skills" / "review-artifact" / "scripts"))
    from review_shell import render
    return render(TITLE, KEY + "-g", verdicts=verdicts or {}, css=CSS + GROUP_CSS,
                  page_js=GROUP_JS.replace("__TITLE__", TITLE), payload={"rows": cards, "imgs": imgs})


def order_cards(cards: list[dict]) -> list[dict]:
    """⚠ 的排前面；其余同字头挨着（字头按出现格数多的先）。"""
    g = lambda c: c.get("grp") or c["ref"]  # noqa: E731
    n = collections.Counter(g(c) for c in cards)
    return sorted(cards, key=lambda c: (not c["warn"], -n[g(c)], g(c), _cell_sort(c["id"])))


# ───────────────────────────── collect ─────────────────────────────

def _judged_cells(books: list[str]) -> set[str]:
    """本机事件日志里已经有定字类裁决的格（再出卡就是重复劳动）。"""
    try:
        from open_guji_cv.feedback.events import EventLog
        out = set()
        for e in EventLog().iter_all_cached():
            if e.kind == "confirm" and e.target.unit == "cell" and (e.target.book in books):
                out.add(e.target.key)
        return out
    except Exception as e:  # noqa: BLE001
        print(f"  [警告] 读事件日志失败，不去重：{e}", file=sys.stderr)
        return set()


def cmd_collect(a) -> None:
    products = Path(a.products_root).resolve()
    os.environ["GUJI_PRODUCTS_DIR"] = str(products)
    books = [b for b in a.books.split(",") if b]
    if a.workspace:
        os.environ["GUJI_WORKSPACE"] = str(Path(a.workspace).resolve())
    from open_guji_cv.core.workspace import glyph_db_path
    db = Path(a.db) if a.db else glyph_db_path()
    counts = lib_counts(db)
    print(f"字形库 {db}：{len(counts)} 个字头，{sum(counts.values())} 例")
    only = None
    if a.cells_file:
        only = {ln.split("\t")[0].strip() for ln in Path(a.cells_file).read_text(encoding="utf-8").splitlines()[1:]
                if ln.strip()}
        if a.books == "auto":
            books = sorted({c.split(":")[0] for c in only})
    skip = _judged_cells(books)
    cards: list[dict] = []
    for b in books:
        st: collections.Counter = collections.Counter()
        got = collect_book(b, products, counts, a.min_count, skip, st, only)
        cards += got
        print(f"  {b}: 格 {st['cells']}  待审 {st['review']}  无整理本字 {st['no_ref']}  "
              f"整理本字库里有 {st['ref_in_lib']}  已有人裁 {st['already_judged']}  这版已放行 {st['admitted_now']}  →格 {len(got)}")
    if only is not None:
        missing = only - {c["id"] for c in cards}
        (Path(a.out)).mkdir(parents=True, exist_ok=True)
        (Path(a.out) / "not_pending.txt").write_text("\n".join(sorted(missing)), encoding="utf-8")
        print(f"  清单 {len(only)} 格，出卡 {len(cards)}，不在这版待审里 {len(missing)}（见 not_pending.txt）")
    if a.kind:
        cards = [c for c in cards if c["kind"] == a.kind]
    if a.refs:
        keep = set(a.refs)
        cards = [c for c in cards if c["ref"] in keep]
        print(f"  --refs：只留整理本字属 {len(keep)} 字头的格 → {len(cards)} 格")
    cards = order_cards(cards)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    imgs = {} if a.no_images else crop_images(cards, out / "crops")
    with (out / "cards.jsonl").open("w", encoding="utf-8") as f:
        for c in cards:
            f.write(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n")
    pre = {}
    if a.preset:
        for ln in Path(a.preset).read_text(encoding="utf-8").splitlines():
            if ln.strip():
                d = json.loads(ln)
                pre[d["id"]] = {"v": d["verdict"], "t": d.get("t") or int(time.time() * 1000)}
    html = (build_html_grouped(cards, imgs, pre) if a.group else build_html(cards, imgs))
    (out / "review.html").write_text(html, encoding="utf-8")
    ref_n = collections.Counter(c.get("grp") or c["ref"] for c in cards)
    with (out / "summary.tsv").open("w", encoding="utf-8") as f:
        f.write("字头\t格数\t⚠格数\t格号\n")
        for ch, n in ref_n.most_common():
            cs = [c for c in cards if (c.get("grp") or c["ref"]) == ch]
            f.write(f"{ch}\t{n}\t{sum(c['warn'] for c in cs)}\t{' '.join(c['id'] for c in cs)}\n")
    print(f"→ {out}/review.html  {len(html)/1024:.0f} KB　{len(cards)} 格 / {len(ref_n)} 个新字头"
          f"（⚠ {sum(c['warn'] for c in cards)} 格）；无图 {len(cards) - len(imgs)} 格")


# ───────────────────────────── apply ─────────────────────────────

def load_verdicts(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            if d.get("verdict"):
                out[d["id"]] = d["verdict"]
    return out


def verdict_to_char(card: dict, v: str) -> str | None:
    if v == "ref":
        return card["ref"]
    if v.startswith("pick:"):
        ch = v[5:]
        return ch if len(ch) == 1 else None
    return None


def cmd_apply(a) -> None:
    cards = {}
    for line in Path(a.cards).read_text(encoding="utf-8").splitlines():
        if line.strip():
            c = json.loads(line)
            cards[c["id"]] = c
    verdicts = load_verdicts(Path(a.verdicts))
    # 整理本未收字按码位成组：组头 `N:<码位>` 的值 `char:<近似字>` 展开给该组里标了 `same` 的格
    notes = {k[2:]: v[5:].strip() for k, v in verdicts.items() if k.startswith("N:") and v.startswith("char:")}
    verdicts = {k: v for k, v in verdicts.items() if not k.startswith("N:")}
    unknown = [k for k in verdicts if k not in cards]
    if unknown:
        sys.exit(f"裁决里有 {len(unknown)} 个格号不在 cards.jsonl（页换过版？）：{unknown[:5]}")
    batch = a.batch or f"H-newchar-{time.strftime('%m%d')}-{a.tag}"
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.workspace:
        os.environ["GUJI_WORKSPACE"] = str(Path(a.workspace).resolve())
    from open_guji_cv.feedback.events import EventTarget, make_event

    events, lists = [], collections.defaultdict(list)
    for cid in sorted(verdicts, key=_cell_sort):
        v, card = verdicts[cid], cards[cid]
        if card.get("kind") == "pua" and v == "same":
            ch = notes.get(card["grp"], "")
            if not ch:
                lists["pua_nochar"].append(card)
                continue
            tgt = EventTarget(step="seed_admit", unit="cell", key=cid, book=card["book"])
            # approx=True：走既有「近似字」侧表（approx_labels），库里查得出来；ids 只在近似字是多字 IDS 时填
            pl = {"v": "confirm", "shape": ch[0] if len(ch) == 1 else ch, "approx": True, "via": "newchar_review",
                  "note": f"近似异体字（Unicode 未收字，整理本码位 {card['grp']}），非精确字形；意思相同的最近似字",
                  "source": a.source}
            if len(ch) > 1:
                pl["ids"] = ch
            events.append(make_event(batch, len(events) + 1, "confirm", tgt, pl, reviewer=a.reviewer))
            continue
        ch = verdict_to_char(card, v)
        if ch:
            tgt = EventTarget(step="seed_admit", unit="cell", key=cid, book=card["book"])
            note = ("新字确认：整理本字对" if v == "ref" else f"新字确认：改为 {ch}（整理本字 {card['ref']}）")
            events.append(make_event(batch, len(events) + 1, "confirm", tgt,
                                     {"v": "confirm", "shape": ch, "via": "newchar_review", "note": note,
                                      "source": a.source}, reviewer=a.reviewer))
        elif v in ("seg", "unclear", "other"):
            lists[v].append(card)
        else:
            print(f"  [跳过] {cid}: 不认识的裁决 {v!r}", file=sys.stderr)

    with (out / "events.jsonl").open("w", encoding="utf-8") as f:
        for e in events:
            f.write(e.model_dump_json() + "\n")
    names = {"seg": "seg_issues.tsv", "unclear": "unclear.tsv", "other": "other.tsv", "pua_nochar": "pua_nochar.tsv"}
    for k, rows in lists.items():
        with (out / names[k]).open("w", encoding="utf-8") as f:
            f.write("格号\t整理本字\t库首选\t5b\t上下文\n")
            for c in rows:
                f.write(f"{c['id']}\t{c['ref']}\t{c['lib_top']}\t{' '.join(c['r5'])}\t{c['ctx']}\n")
    heads = collections.Counter(e.payload["shape"] for e in events)
    print(f"批次 {batch}：裁了 {len(verdicts)} / {len(cards)} 格 → 人裁事件 {len(events)} 条，"
          f"涉及 {len(heads)} 个字头；seg {len(lists['seg'])} / unclear {len(lists['unclear'])} / other {len(lists['other'])}"
          f"（这三类不写事件，见 {out}）")
    print(f"→ {out}/events.jsonl（dry-run，事件日志未动）" if not a.execute else "")

    if not a.execute:
        return
    if a.products_root:
        os.environ["GUJI_PRODUCTS_DIR"] = str(Path(a.products_root).resolve())
    from open_guji_cv.feedback.anchor import enrich_events
    from open_guji_cv.feedback.events import EventLog
    log = EventLog()
    enriched = enrich_events(events)
    # 换过图源的册（页号重编）：旧页号的裁决不写，列出来等在新产物上重新取格
    from open_guji_cv.feedback.events import _target_dict
    gate = log._rev_gate()
    stale = [e for e in events if not gate.admits(e.kind, _target_dict(e.target))]
    if stale:
        sid = {e.id for e in stale}
        events = [e for e in events if e.id not in sid]
        with (out / "stale_source.tsv").open("w", encoding="utf-8") as f:
            f.write("格号\t字\n" + "\n".join(f"{e.target.key}\t{e.payload['shape']}" for e in stale) + "\n")
        print(f"  [换图源] {len(stale)} 条所属册已换图源（{sorted({e.target.book for e in stale})}），不写，见 {out}/stale_source.tsv")
    n = log.append(events)
    print(f"已追加 {n} 条（补锚 {enriched}）→ {log.batch_path(batch)}")
    if a.admit:
        from open_guji_cv.feedback.consumers import route_and_consume
        res = route_and_consume(log, batch, dry_run=False)
        for r in res["results"]:
            print(f"  {r['consumer']}: added={r['added']} skipped={r['skipped']} errors={r['errors']}")
    print("本机事件日志已写；推中心库用 `guji db sync`，需要 Sheldon 点头，脚本不做。")


# ───────────────────────────── 入口 ─────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="新字快速确认：挑格、出确认页、裁决转人裁事件",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=DOC)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect", help="挑新字待审格，出 cards.jsonl + review.html（只读）")
    c.add_argument("--books", required=True, help="逗号分隔，如 vol06,vol07；配 --cells-file 时可写 auto")
    c.add_argument("--products-root", required=True, help="产物根（内含 <册>/seed_admit/…）")
    c.add_argument("-w", "--workspace", help="工作区（取 glyph.db、册配置、原图）")
    c.add_argument("--db", help="字形库 glyph.db（缺省取工作区的）")
    c.add_argument("--min-count", type=int, default=1, help="整理本字在库里刻例数低于它算新字（缺省 1）")
    c.add_argument("--cells-file", help="只收这个 TSV 第一列列出的格（跳过新字判定；整理本缺字的格没有整理本字，按 5b 首选字分组）")
    c.add_argument("--group", action="store_true", help="按整理本字（缺字格按 5b 首选字）一字一卡出页")
    c.add_argument("--preset", help="已有的裁决 jsonl（harvest_verdicts 出的），预置进新页")
    c.add_argument("--kind", choices=["ref", "cand"], help="只出一类：ref=有整理本字，cand=整理本缺字")
    c.add_argument("--refs", help="只收这些整理本字（字符串里每个字符算一个字头），如补库候选清单的字头")
    c.add_argument("--no-images", action="store_true", help="不出字块图（没原图时用）")
    c.add_argument("--out", required=True)
    c.set_defaults(fn=cmd_collect)
    p = sub.add_parser("apply", help="收回的裁决 → 人裁事件（缺省 dry-run）")
    p.add_argument("--cards", required=True)
    p.add_argument("--verdicts", required=True, help="harvest_verdicts.py -o 出的 jsonl")
    p.add_argument("--out", required=True)
    p.add_argument("-w", "--workspace")
    p.add_argument("--products-root", help="--execute 补锚要读产物时给")
    p.add_argument("--batch", help="事件批次名（缺省 H-newchar-<月日>-<tag>）")
    p.add_argument("--tag", default="1", help="批次名后缀")
    p.add_argument("--reviewer", default="claude-newchar-review")
    p.add_argument("--source", default="新字确认页，人点确认")
    p.add_argument("--execute", action="store_true", help="追加进本机事件日志（带锚）")
    p.add_argument("--admit", action="store_true", help="--execute 之上，本机跑 glyphdb_admit 落 glyph.db")
    p.set_defaults(fn=cmd_apply)
    a = ap.parse_args()
    if getattr(a, "admit", False) and not a.execute:
        sys.exit("--admit 要和 --execute 一起用")
    a.fn(a)


if __name__ == "__main__":
    main()
