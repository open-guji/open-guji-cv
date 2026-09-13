# -*- coding: utf-8 -*-
"""切分裁决台：识别证据说「现役切错了」的那批格线，请人看图定夺。

    PYTHONPATH=. python scripts/build_cutline_flip_review.py -o /tmp/cutflip.html

## 这批是怎么挖出来的

2026-09-12 把库匹配 diff 档的候选字带出来之后（原先只显示「? 99%」），
每条候选切法都能看出「按这么切，上下两格分别被认成什么字」。拿它跟整理本
期望字比，vol02 1-50 页 145 条待裁里 **65 条能唯一命中**，其中 **64 条指向
「现役切错了、应该选另一条」**——64:1 这个比例不像噪声，像 `chosen` 规则
本身有问题：

    row_boundaries.py: chosen = 0 if (偏移==0 or 折线穿墨 > SEAM_MAX_INK) else 末条

只要折线绕开了墨且有偏移就一律选折线，**完全不比较 straight 自己穿多少墨**。
隐含假设「straight 有墨 → 折线能绕开就更好」，实测大量情况下不成立：绕开墨
的代价是切线弯进字身，反而把字切坏。

## 为什么必须人裁，不能直接自动采纳

判据用的是「top1 命中整理本期望字」，而期望字来自整理本对齐——用识别结果
裁切分，跟用切分喂识别是同一类循环依赖，只是绕得远一点。所以这一轮要的是
**人看图确认**，拿到三样东西：

1. top1 判据的准确率（它说「现役错」，到底对不对）
2. 这批直接成为 `char-segmentation/touching-cuts` 金标
3. 拿金标校准 `chosen` 规则的阈值，而不是拍脑袋调 `SEAM_MAX_INK`

## ⚠️ 出题纪律：机器的判断不印在卡上

按 skill 的纪律，卡片上**不写**「算法说现役错了」「应选 straight」这类结论,
也不标哪条是现役——写了人就顺着点，测出来的是我自己。卡上只有：
一张图、两条候选切线（颜色区分、随机左右顺序）、整理本期望的两个字。
人只回答一件事：**哪条切线把这两个字切对了。**

候选的真实身份（哪条是现役、哪条是算法推荐）存在 `*_cards.jsonl` 里，
收回裁决后再对账。
"""
from __future__ import annotations

import argparse
import base64
import json
import random
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import open_guji_cv.steps  # noqa: F401,E402  注册产物种类
from _review_shell import render  # noqa: E402
from open_guji_cv.core.spec import column_key  # noqa: E402
from open_guji_cv.core.step import page_key  # noqa: E402
from open_guji_cv.eval import touching as T  # noqa: E402
from open_guji_cv.products.cache import ImageCache  # noqa: E402
from open_guji_cv.products.store import ProductStore  # noqa: E402
from open_guji_cv.review.cards import blocking_cutline_cases  # noqa: E402

TITLE = "切分裁决台"
KEY = "guji-cutflip-v1"
PAD = 10            # 裁片上下各留多少像素，让人看得到字的完整轮廓
MAX_W = 190         # 缩略图宽度上限
# 两条候选切线的颜色：靛蓝 / 赭石。与「裁决按钮」的语义色刻意错开，
# 免得人把「蓝线」跟「通过」联系起来。
LINE_RGB = {"A": (40, 90, 200), "B": (190, 110, 30)}


def top1(m: dict | None) -> str | None:
    """这条候选切法下，该格最像的字：same 档用 char，否则用候选池第一名。"""
    if not m:
        return None
    if m.get("char"):
        return m["char"]
    cs = m.get("cands") or []
    return cs[0][0] if cs else None


def match_map(st, book: str, pg: int, slot: int, cache: dict) -> dict:
    """这一格的候选匹配结果 + 它自己现役那条的匹配结果（口径同 routers/cutline.py）。"""
    k = (pg, slot)
    if k in cache:
        return cache[k]
    out: dict = {"above": {}, "below": {}, "chosen": None}
    m = st.read(book, "glyph_match", page_key(pg), "glyph_match")
    for cc in (m.columns if m else []):
        for r in cc.chars:
            if r.slot != slot or r.sub:
                continue
            out["chosen"] = {"char": r.char, "cov": r.cov, "cands": r.candidates[:3]}
            for cv in (r.cand_variants or []):
                out[cv.side][cv.cand_idx] = {"char": cv.char, "cov": cv.cov,
                                             "cands": cv.candidates[:3]}
            break
    cache[k] = out
    return out


def draw(col_img: np.ndarray, y0: int, y1: int, x0: int, lines: list[tuple[str, object]]
         ) -> str:
    """裁片 + 画上两条候选切线，返回 dataURI。

    `y` 是 None（straight）时画水平线；否则是逐列 y 数组（列图坐标，从 x0 起）。
    切线画在灰度图上要转彩色——两条线必须能分辨，单看粗细在手机上看不出来。
    """
    crop = col_img[y0:y1]
    rgb = cv2.cvtColor(crop, cv2.COLOR_GRAY2RGB)
    h, w = crop.shape[:2]
    for tag, ys in lines:
        color = LINE_RGB[tag]
        if ys is None:
            continue    # straight 在下面统一按 y_mid 画
        arr = np.asarray(ys)
        for j in range(len(arr)):
            x = x0 + j
            if not (0 <= x < w):
                continue
            yy = int(arr[j]) - y0
            if 0 <= yy < h:
                rgb[max(0, yy - 1):yy + 2, x] = color
    s = MAX_W / max(w, 1)
    if s < 1:
        rgb = cv2.resize(rgb, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    if not ok:
        raise RuntimeError("编码失败")
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def draw_one(col_img: np.ndarray, y0: int, y1: int, x0: int, tag: str,
             ys, y_flat: int) -> str:
    """单条候选一张图——两条线叠一张上人分不清谁是谁，实测不如并排两张。"""
    crop = col_img[y0:y1]
    rgb = cv2.cvtColor(crop, cv2.COLOR_GRAY2RGB)
    h, w = crop.shape[:2]
    color = LINE_RGB[tag]
    if ys is None:
        yy = y_flat - y0
        if 0 <= yy < h:
            rgb[max(0, yy - 1):yy + 2, :] = color
    else:
        arr = np.asarray(ys)
        for j in range(len(arr)):
            x = x0 + j
            if 0 <= x < w:
                yy = int(arr[j]) - y0
                if 0 <= yy < h:
                    rgb[max(0, yy - 1):yy + 2, x] = color
    s = MAX_W / max(w, 1)
    if s < 1:
        rgb = cv2.resize(rgb, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    if not ok:
        raise RuntimeError("编码失败")
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


CSS = """
.ch{display:flex;align-items:baseline;gap:.5rem;flex-wrap:wrap;margin-bottom:.4rem}
.ch .loc{font-size:.78rem;color:var(--faint);font-variant-numeric:tabular-nums}
.ch .exp{font-size:1.5rem;letter-spacing:.12em}
.ch .lab{font-size:.72rem;color:var(--faint)}
.pair{display:flex;gap:.5rem}
.opt{flex:1;min-width:0;text-align:center}
.opt .tile{display:block;background:var(--tile);border-radius:6px;overflow:hidden;
  border:1px solid var(--line)}
.opt img{display:block;width:100%;height:auto;image-rendering:pixelated}
.opt .cap{font-size:.75rem;margin-top:.25rem;color:var(--faint)}
.opt[data-t="A"] .cap b{color:#2850c8}
.opt[data-t="B"] .cap b{color:#be6e1e}
.reads{font-size:.8rem;color:var(--faint);margin-top:.15rem}
.reads b{color:var(--fg);font-weight:600}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .opt[data-t="A"] .cap b{color:#7d9bff}
  :root:not([data-theme="light"]) .opt[data-t="B"] .cap b{color:#e0a05a}}
:root[data-theme="dark"] .opt[data-t="A"] .cap b{color:#7d9bff}
:root[data-theme="dark"] .opt[data-t="B"] .cap b{color:#e0a05a}
"""

PAGE_JS = r"""
const BODY = `
<header class="top">
  <div class="top-in">
    <span class="brand">切分裁决台</span>
    <span class="save" id="save" data-s="idle">本机</span>
    <span class="count" id="count">—</span>
  </div>
  <div class="bar"><i id="prog"></i></div>
</header>
<main class="wrap">
  <details class="intro" id="intro" open>
    <summary>怎么裁</summary>
    <p>每张卡是<b>同一块图的两种切法</b>。这块图里上下叠着两个字，
       蓝线和黄线是两条备选的分界线。<b>上面那行大字是整理本在这两格印的字</b>，
       也就是正确答案应该切出来的两个字。</p>
    <p>你只回答一件事：<b>哪条线把这两个字切对了。</b>
       切对 = 线的上边正好是第一个字、下边正好是第二个字，谁都没被削掉一块、
       也没把对方的笔画带过来。</p>
    <div class="rubric">
      <div class="k-ok"><b>蓝线对</b><span>蓝线切得对</span></div>
      <div class="k-other"><b>黄线对</b><span>黄线切得对</span></div>
      <div class="k-fix"><b>都不对</b><span>两条都切坏了，得手画</span></div>
      <div class="k-idk"><b>拿不准</b><span>看不出来／这块图本身有问题</span></div>
    </div>
    <p class="reads">左右顺序是随机的，蓝黄跟「算法选了哪条」没有关系。</p>
  </details>
  <div class="ctrl">
    <div class="seg" id="filter" role="group" aria-label="筛选">
      <button data-f="todo" aria-pressed="true">未裁</button>
      <button data-f="all" aria-pressed="false">全部</button>
      <button data-f="done" aria-pressed="false">已裁</button>
    </div>
  </div>
  <div class="ctrl">
    <button class="ghost" id="copy" style="flex:1">复制裁决</button>
    <button class="ghost" id="reset">清空</button>
  </div>
  <div class="list" id="list"></div>
</main>
<div class="sheet" id="sheet" hidden>
  <div class="sheet-in">
    <h2>裁决 JSONL</h2>
    <p id="sheet-note">长按选中全文复制，或用下面的按钮。</p>
    <textarea id="sheet-text" readonly spellcheck="false"></textarea>
    <div class="row">
      <button class="ghost" id="sheet-copy">复制到剪贴板</button>
      <button class="ghost" id="sheet-close">关闭</button>
    </div>
  </div>
</div>`;

const rowId = r => r.id;
let filter = 'todo';
function visibleRows(){
  return D.rows.filter(r => filter === 'all' ? true
    : filter === 'done' ? !!verdictOf(r.id) : !verdictOf(r.id));
}
function afterVerdict(){ if (filter === 'todo') draw(); }

function card(r){
  const v = verdictOf(r.id);
  const btn = (k,t) => `<button class="${k}" data-v="${k}" aria-pressed="${v===k}">${t}</button>`;
  // r.opts 是已经随机过顺序的 [{t:'A'|'B', img}]，卡上不体现谁是现役
  const opt = o => `<div class="opt" data-t="${o.t}">
      <span class="tile"><img data-src="${o.img}" alt="" decoding="async"></span>
      <div class="cap"><b>${o.t === 'A' ? '蓝线' : '黄线'}</b></div>
    </div>`;
  return `<article class="card" data-id="${r.id}"${v?` data-v="${v}"`:''}>
    <div class="ch">
      <span class="loc">${esc(r.id)}</span>
      <span class="exp">${esc(r.exp_a)}${esc(r.exp_b)}</span>
      <span class="lab">← 整理本这两格印的字</span>
    </div>
    <div class="pair">${r.opts.map(opt).join('')}</div>
    <div class="verdicts">
      ${btn('ok','蓝线对')}${btn('other','黄线对')}${btn('fix','都不对')}${btn('idk','拿不准')}
    </div>
  </article>`;
}

function payload(){
  return D.rows.filter(r => verdictOf(r.id)).map(r => JSON.stringify({
    id: r.id, verdict: verdictOf(r.id),
    // 蓝=A 黄=B，对应哪条候选存在 cards.jsonl 里，收回后对账
    picked: ({ok:'A', other:'B'})[verdictOf(r.id)] || null,
  })).join('\n');
}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default="/tmp/cutflip.html")
    ap.add_argument("--book", default="vol02")
    ap.add_argument("--pages", default="1-50")
    ap.add_argument("--limit", type=int, default=80,
                    help="一次别超过百来张，人裁到后面会累")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    a, _, b = args.pages.partition("-")
    pgs = list(range(int(a), int(b) + 1)) if b else [int(a)]

    st = ProductStore()
    cache = ImageCache()
    cases = blocking_cutline_cases(args.book, pgs, st)
    T.attach_expected(cases, args.book, st)

    mcache: dict = {}
    per_page: dict = {}
    rows, imgs = [], {}
    rng = random.Random(args.seed)
    stat = Counter()

    for c in cases:
        pg = c["page"]
        if pg not in per_page:
            cells = st.read(args.book, "row_segment", page_key(pg), "cells")
            d = {}
            for cc in (cells.columns if cells else []):
                for cp in (getattr(cc, "cut_candidates", None) or []):
                    d[(cc.col, cp.slot_above)] = cp
            per_page[pg] = d
        cp = per_page[pg].get((c["col"], c["slot_above"]))
        if cp is None:
            continue
        ea, eb = c.get("char_above", ""), c.get("char_below", "")
        if not (ea and eb):
            stat["无整理本期望"] += 1
            continue

        am = match_map(st, args.book, pg, c["slot_above"], mcache)
        bm = match_map(st, args.book, pg, c["slot_below"], mcache)
        hits = []
        for i, x in enumerate(cp.candidates):
            ma = am["chosen"] if i == cp.chosen else am["below"].get(i)
            mb = bm["chosen"] if i == cp.chosen else bm["above"].get(i)
            if top1(ma) == ea and top1(mb) == eb:
                hits.append(i)
        if len(hits) != 1:
            stat["非唯一命中"] += 1
            continue
        win = hits[0]
        if win == cp.chosen:
            stat["确认现役（不入本批）"] += 1
            continue
        stat["推翻现役"] += 1

        path = cache.get(args.book, "column_image", column_key(pg, c["col"]))
        if path is None:
            stat["无列图"] += 1
            continue
        col_img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if col_img is None:
            stat["列图读不出"] += 1
            continue
        h = col_img.shape[0]
        y0 = max(0, c["y0"] - PAD)
        y1 = min(h, c["y1"] + PAD)

        # 两条要对比的候选：算法现役 vs 识别证据指向的那条
        pair = [("chosen", cp.candidates[cp.chosen]), ("flip", cp.candidates[win])]
        rng.shuffle(pair)                       # 随机左右，不让人从位置猜
        tags = ["A", "B"]
        opts, ident = [], {}
        for tag, (role, cand) in zip(tags, pair):
            k = f"{c['id']}|{tag}"
            imgs[k] = draw_one(col_img, y0, y1, c["x0"], tag,
                               cand.y, int(c["y"]))
            opts.append({"t": tag, "img": k})
            ident[tag] = {"role": role, "kind": cand.kind,
                          "seam_ink": int(cand.seam_ink), "dev_max": int(cand.dev_max)}

        rows.append({
            "id": c["id"], "page": pg, "col": c["col"],
            "slot_above": c["slot_above"], "slot_below": c["slot_below"],
            "exp_a": ea, "exp_b": eb,
            "opts": opts,
            # ↓ 机器的判断只进 jsonl，不进卡片（出题纪律）
            "ident": ident,
            "chosen_idx": int(cp.chosen), "flip_idx": int(win),
            "stratum": "flip_unique_top1", "stratum_weight": 1.0,
        })
        if len(rows) >= args.limit:
            break

    html = render(TITLE, KEY,
                  {"ok": "蓝线对", "other": "黄线对", "fix": "都不对", "idk": "拿不准"},
                  CSS, PAGE_JS, {"rows": rows, "imgs": imgs, "verdicts": {}})
    Path(args.out).write_text(html, encoding="utf-8")

    cards = REPO / "artifacts" / "cutline_flip_cards.jsonl"
    cards.parent.mkdir(exist_ok=True)
    cards.write_text("\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True)
                              for r in rows) + "\n", encoding="utf-8")

    print(f"卡 {len(rows)}  图 {len(imgs)}")
    for k, v in stat.most_common():
        print(f"  {k:20} {v}")
    print(f"→ {args.out}  ({Path(args.out).stat().st_size/1e6:.2f} MB)")
    print(f"→ {cards}（身份对账用，收回裁决后配合它算准确率）")


if __name__ == "__main__":
    main()
