# -*- coding: utf-8 -*-
"""按字复核页：把指定几个字的**全部**字位排成一页，大图 + 上下文，**当场就能改**。

    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/build_char_review.py --chars 曾會
    … --chars 注註 --books vol01,vol02 --out output/review_zhu.html

用途：形近字（曾/會、日/曰、己已巳）自动放行之后想整体回看一遍。对勘报告只列
「与整理本不一致」的位，而形近字最危险的恰恰是**两边一致但两边都错**，那种位
在对勘报告里根本不出现——所以这里按字取全集，不管对错。

页面按字分组，每格给：
  - 目标字块大图（看得清笔画）
  - 同列上下 2 格的竖条（判断上下文用）
  - 转写 ±6 字、整理本 ±6 字（有对齐时）
  - 来源徽章（人裁 / 自动·通道 / 待审）与库候选前四（看它拿不准的是哪两个）

排序把**可疑的排前面**：库 top1 与最终字不一致的、库前两名分差小的（形近字典型
特征）、待审的，都往上提。

## 能改判（2026-09-06 加）

用户第一版只能看不能标：「我看到了怎么标注呢？有这两个字标反的，也有是别的字的，
还有切分错误的」——三类问题对应三种操作，页面上都给：

  - **改字**：点候选按钮，或直接在框里输入（两个字标反、认成别的字都用这个）
  - **非字**：这一格根本不是字
  - **切坏**：字形不完整 / 混了邻字残墨（对应 truncated / contaminated）

裁决走与审查页**同一套协议**（`POST /api/events` 的 confirm / not_a_char /
seg_defect），落同一个事件日志、同一批消费者，因此复核页改的判和审查页改的判
完全等价，没有第二条数据通路。页面需要控制台在跑（默认 127.0.0.1:8641，
`--api` 可改）；纯离线打开时提交按钮会说明连不上。

只有 己/已/巳 分「字形 / 文意」（`needsReading`，与控制台同一条规则），
其余字一律 reading 跟随 shape，不记转换。
"""
from __future__ import annotations

import argparse
import base64
import html
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import open_guji_cv.steps  # noqa: E402,F401
from open_guji_cv.clustering.align_eval import WINDOW_PAD, anchor_page, build_ngram_index  # noqa: E402
from open_guji_cv.clustering.align_label import is_han  # noqa: E402
from open_guji_cv.core.book import load_book  # noqa: E402
from open_guji_cv.core.spec import cell_key, page_key  # noqa: E402
from open_guji_cv.eval.round_check import load_verdicts  # noqa: E402
from open_guji_cv.products.cache import ImageCache  # noqa: E402
from open_guji_cv.products.store import ProductStore  # noqa: E402

DEFAULT_CORPUS = "corpus/zongmu_wuyingdian_reference.txt"


def _load_cell(cache: ImageCache, book: str, page: int, col: int, slot: int,
               sub: str, h: int):
    key = cell_key(page, col, slot) + (sub or "")
    p = cache.get(book, "char_patch", key)
    if p is None:
        return None
    img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    if img.shape[0] != h:
        w = max(1, int(img.shape[1] * h / img.shape[0]))
        img = cv2.resize(img, (w, h), interpolation=cv2.INTER_CUBIC)
    return img


def _b64(img) -> str | None:
    ok, buf = cv2.imencode(".webp", img, [cv2.IMWRITE_WEBP_QUALITY, 80])
    return base64.b64encode(buf.tobytes()).decode("ascii") if ok else None


def big_b64(cache, book, page, col, slot, sub, h=120):
    img = _load_cell(cache, book, page, col, slot, sub, h)
    return None if img is None else _b64(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR))


def strip_b64(cache, book, page, col_slots, k, radius=2, h=44):
    """同列上下各 radius 格，目标格红框。"""
    lo, hi = max(0, k - radius), min(len(col_slots), k + radius + 1)
    cells = []
    for i in range(lo, hi):
        s = col_slots[i]
        img = _load_cell(cache, book, page, s["col"], s["slot"], s["sub"], h)
        if img is None:
            img = np.full((h, h), 235, np.uint8)
        cells.append((i == k, img))
    if not cells:
        return None
    w = max(c.shape[1] for _, c in cells) + 6
    total_h = sum(c.shape[0] for _, c in cells) + 3 * (len(cells) - 1) + 6
    canvas = np.full((total_h, w, 3), 255, np.uint8)
    y = 3
    for is_t, c in cells:
        x = (w - c.shape[1]) // 2
        canvas[y:y + c.shape[0], x:x + c.shape[1]] = cv2.cvtColor(c, cv2.COLOR_GRAY2BGR)
        if is_t:
            cv2.rectangle(canvas, (x - 2, y - 2),
                          (x + c.shape[1] + 1, y + c.shape[0] + 1), (30, 38, 179), 2)
        y += c.shape[0] + 3
    return _b64(canvas)


def _reading_order(chars):
    """夹注 a 行读完再读 b 行（同 build_collation_report）。"""
    out, run = [], {}

    def flush():
        for sub in sorted(run):
            out.extend(run[sub])
        run.clear()

    for r in sorted(chars, key=lambda x: (x.slot, x.sub or "")):
        if r.sub:
            run.setdefault(r.sub, []).append(r)
        else:
            flush()
            out.append(r)
    flush()
    return out


def collect(book: str, pages: list[int], chars: set[str], st, corpus, index):
    """→ [条目]。取**最终字**落在 chars 里的全部字位（人裁优先）。"""
    truth = load_verdicts(book)
    cache = ImageCache()
    out = []
    for pg in pages:
        a = st.read(book, "seed_admit", page_key(pg), "seed_admit")
        if a is None:
            continue
        m = st.read(book, "glyph_match", page_key(pg), "glyph_match")
        mm = {r.id: r for cc in (m.columns if m else []) for r in cc.chars}
        # 页文本 + 列内序，供上下文与竖条用
        page_slots, by_col = [], defaultdict(list)
        for cc in a.columns:
            if not cc.ok:
                continue
            for r in _reading_order(cc.chars):
                h = truth.get(r.id)
                ch = h or r.char or "□"
                d = {"id": r.id, "col": cc.col, "slot": r.slot, "sub": r.sub or "",
                     "char": ch, "human": h, "admit": bool(r.admit),
                     "channel": r.channel, "rec": r}
                page_slots.append(d)
                by_col[cc.col].append(d)
        pos_in_col = {s["id"]: i for col in by_col.values() for i, s in enumerate(col)}
        text = "".join(s["char"] for s in page_slots)
        off = anchor_page(text, index)
        lo = max(0, off - WINDOW_PAD) if off is not None else None
        window = corpus[lo:min(len(corpus), off + len(text) + WINDOW_PAD)] if off is not None else ""
        # 页内位置 → 整理本位置（等长对齐段才有；这里只做粗略映射，够看上下文）
        import difflib
        ref_at = {}
        if off is not None:
            sm = difflib.SequenceMatcher(None, text, window, autojunk=False)
            for tag, i1, i2, j1, j2 in sm.get_opcodes():
                if tag in ("equal", "replace"):
                    for k in range(min(i2 - i1, j2 - j1)):
                        ref_at[i1 + k] = j1 + k
        for i, s in enumerate(page_slots):
            if s["char"] not in chars:
                continue
            r = s["rec"]
            mr = mm.get(s["id"])
            cands = [(c, round(v, 4)) for c, v in (mr.candidates or [])[:4]] if mr else []
            j = ref_at.get(i)
            ref_ctx = ""
            ref_ch = ""
            if j is not None:
                a_ = lo + j
                ref_ch = corpus[a_] if a_ < len(corpus) else ""
                ref_ctx = (corpus[max(0, a_ - 6):a_] + "【" + ref_ch + "】"
                           + corpus[a_ + 1:a_ + 7])
            k = pos_in_col[s["id"]]
            out.append({
                "book": book, "id": s["id"], "page": pg, "col": s["col"],
                "slot": s["slot"], "sub": s["sub"], "char": s["char"],
                "source": "人裁" if s["human"] else ("自动" if s["admit"] else "待审"),
                "channel": s["channel"] or "",
                "lib1": cands[0][0] if cands else "", "cands": cands,
                "gap": round(cands[0][1] - cands[1][1], 4) if len(cands) > 1 else None,
                "ref": ref_ch, "ref_ctx": ref_ctx,
                "hyp_ctx": (text[max(0, i - 6):i] + "【" + s["char"] + "】" + text[i + 1:i + 7]),
                "big": big_b64(cache, book, pg, s["col"], s["slot"], s["sub"]),
                "strip": strip_b64(cache, book, pg, by_col[s["col"]], k),
            })
    return out


def suspicion(e: dict) -> tuple:
    """越可疑越靠前：待审 > 库 top1 与最终字不符 > 前二分差小 > 与整理本不符。"""
    return (
        0 if e["source"] == "待审" else 1,
        0 if (e["lib1"] and e["lib1"] != e["char"]) else 1,
        e["gap"] if e["gap"] is not None else 9,
        0 if (e["ref"] and e["ref"] != e["char"]) else 1,
    )


def render(chars: str, entries: list[dict], meta: dict) -> str:
    by_char = defaultdict(list)
    for e in entries:
        by_char[e["char"]].append(e)
    src_cnt = Counter(e["source"] for e in entries)

    def _e(s):
        return html.escape("" if s is None else str(s), quote=True)

    def card(e):
        img = (f'<img class="big" src="data:image/webp;base64,{e["big"]}" alt="">'
               if e["big"] else '<div class="big nop">无图</div>')
        strip = (f'<img class="strip" src="data:image/webp;base64,{e["strip"]}" alt="">'
                 if e["strip"] else "")
        # 可选的字：库候选 + 整理本字 + 当前字，去重后都做成按钮，点一下就是改判
        picks, seen = [], set()
        for c in ([e["char"], e["ref"]] + [x for x, _ in e["cands"]]):
            if c and c not in seen:
                seen.add(c)
                picks.append(c)
        btns = "".join(
            f'<button class="pick{" on" if c == e["char"] else ""}" data-ch="{_e(c)}">{_e(c)}</button>'
            for c in picks)
        cands = " ".join(f'<span class="cd{" hit" if c == e["char"] else ""}">{_e(c)}<sub>{v}</sub></span>'
                         for c, v in e["cands"]) or "—"
        refline = (f'<div class="ln"><span class="k">整理本</span>'
                   f'<b class="{"bad" if e["ref"] and e["ref"] != e["char"] else ""}">{_e(e["ref"]) or "—"}</b>'
                   f'<span class="ctx">{_e(e["ref_ctx"])}</span></div>')
        cls = "card" + (" susp" if (e["lib1"] and e["lib1"] != e["char"]) or e["source"] == "待审" else "")
        return f"""<div class="{cls}" data-src="{_e(e['source'])}" data-char="{_e(e['char'])}"
     data-book="{_e(e['book'])}" data-id="{_e(e['id'])}" data-orig="{_e(e['char'])}">
  <div class="imgs">{img}{strip}</div>
  <div class="body">
    <div class="hd"><b class="ch">{_e(e['char'])}</b>
      <span class="mono">{_e(e['id'])}</span>
      <span class="badge b-{_e(e['source'])}">{_e(e['source'])}{('·' + _e(e['channel'])) if e['channel'] else ''}</span>
      <span class="state"></span>
    </div>
    <div class="ln"><span class="k">库候选</span>{cands}</div>
    <div class="ln"><span class="k">转写</span><span class="ctx">{_e(e['hyp_ctx'])}</span></div>
    {refline}
    <div class="act">
      <span class="k">改判</span>{btns}
      <input class="txt" placeholder="其它字" size="4">
      <span class="rd" hidden>→ <input class="txtrd" placeholder="文意" size="4"
            title="只有 己/已/巳 才分字形与文意"></span>
      <button class="mk" data-mark="non" title="这一格根本不是字">非字</button>
      <button class="mk" data-mark="truncated" title="笔画被切掉了一部分">切坏</button>
      <button class="mk" data-mark="contaminated" title="混进了邻字残墨/界行/版框">有噪声</button>
      <button class="undo" title="撤销这一格的改动">↺</button>
    </div>
  </div>
</div>"""

    secs = []
    for ch in sorted(by_char, key=lambda c: -len(by_char[c])):
        es = sorted(by_char[ch], key=suspicion)
        secs.append(f'<section id="c-{_e(ch)}"><h2>{_e(ch)} <span class="cnt">{len(es)}</span></h2>'
                    f'<div class="grid">{"".join(card(e) for e in es)}</div></section>')

    return f"""<title>{_e(chars)} 字位复核</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+TC:wght@500;700&family=Noto+Sans+TC:wght@400;500&family=IBM+Plex+Mono&display=swap">
<style>
  :root {{ --paper:#F5F4F0; --panel:#FFF; --ink:#1B1F24; --mute:#6A7383; --rule:#DAD9D3;
          --indigo:#2B4C7E; --zhu:#B3261E; --ok:#2F7D4F;
          --serif:"Noto Serif TC","Source Han Serif TC",serif; --sans:"Noto Sans TC",sans-serif;
          --mono:"IBM Plex Mono",Consolas,monospace; color-scheme:light; }}
  @media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
    --paper:#16191E; --panel:#1E2228; --ink:#E4E3DD; --mute:#9AA3B2; --rule:#2E343D;
    --indigo:#8FB0E0; --zhu:#E57368; --ok:#7CC29A; color-scheme:dark; }} }}
  :root[data-theme="dark"] {{ --paper:#16191E; --panel:#1E2228; --ink:#E4E3DD; --mute:#9AA3B2;
    --rule:#2E343D; --indigo:#8FB0E0; --zhu:#E57368; --ok:#7CC29A; color-scheme:dark; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--paper); color:var(--ink); font-family:var(--sans);
         line-height:1.6; padding:1.2rem 1.4rem 3rem; }}
  header {{ border-bottom:2px solid var(--ink); padding-bottom:.7rem; margin-bottom:1rem; }}
  h1 {{ font-family:var(--serif); font-size:1.7rem; margin:.2rem 0 .5rem; }}
  .sum {{ display:flex; gap:1.6rem; flex-wrap:wrap; font-size:.9rem; }}
  .sum b {{ font-size:1.25rem; font-family:var(--serif); }}
  .note {{ color:var(--mute); font-size:.85rem; margin-top:.5rem; max-width:64ch; }}
  h2 {{ font-family:var(--serif); font-size:1.3rem; margin:1.6rem 0 .6rem;
       border-bottom:1px solid var(--rule); padding-bottom:.3rem; }}
  .cnt {{ font-size:.85rem; color:var(--mute); font-family:var(--sans); }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(23rem,1fr)); gap:.7rem; }}
  .card {{ display:grid; grid-template-columns:auto 1fr; gap:.7rem; background:var(--panel);
          border:1px solid var(--rule); border-radius:4px; padding:.6rem; min-width:0; }}
  .card.susp {{ border-left:3px solid var(--zhu); }}
  .imgs {{ display:flex; gap:.3rem; align-items:flex-start; }}
  .big {{ width:78px; height:78px; object-fit:contain; background:#fff; border:1px solid var(--rule); }}
  .big.nop {{ display:flex; align-items:center; justify-content:center; font-size:.7rem; color:var(--mute); }}
  .strip {{ height:132px; background:#fff; border:1px solid var(--rule); }}
  .body {{ min-width:0; }}
  .hd {{ display:flex; align-items:center; gap:.4rem; flex-wrap:wrap; margin-bottom:.2rem; }}
  .ch {{ font-family:var(--serif); font-size:1.4rem; }}
  .mono {{ font-family:var(--mono); font-size:.72rem; color:var(--mute); }}
  .badge {{ font-size:.68rem; padding:.05rem .35rem; border-radius:2px; border:1px solid var(--rule); }}
  .b-人裁 {{ background:var(--ok); color:#fff; border-color:var(--ok); }}
  .b-自动 {{ color:var(--mute); }}
  .b-待审 {{ background:var(--zhu); color:#fff; border-color:var(--zhu); }}
  .ln {{ font-size:.85rem; display:flex; gap:.35rem; align-items:baseline; flex-wrap:wrap; }}
  .k {{ font-size:.7rem; color:var(--mute); min-width:3.2em; }}
  .ctx {{ font-family:var(--serif); }}
  .cd {{ font-family:var(--serif); margin-right:.3rem; }}
  .cd sub {{ font-family:var(--mono); font-size:.62rem; color:var(--mute); }}
  .cd.hit {{ color:var(--indigo); font-weight:700; }}
  .bad {{ color:var(--zhu); }}
  .filters {{ position:sticky; top:0; background:var(--paper); padding:.5rem 0; z-index:5;
             border-bottom:1px solid var(--rule); font-size:.85rem;
             display:flex; gap:.9rem; flex-wrap:wrap; align-items:center; }}
  .act {{ display:flex; gap:.25rem; align-items:center; flex-wrap:wrap; margin-top:.35rem;
         padding-top:.35rem; border-top:1px dashed var(--rule); }}
  .act button {{ font-family:var(--serif); font-size:.95rem; padding:.05rem .4rem;
                border:1px solid var(--rule); background:var(--panel); color:var(--ink);
                border-radius:3px; cursor:pointer; }}
  .act button.on {{ background:var(--indigo); color:#fff; border-color:var(--indigo); }}
  .act button.mk, .act button.undo {{ font-family:var(--sans); font-size:.7rem; color:var(--mute); }}
  .act button.mk.on {{ background:var(--zhu); color:#fff; border-color:var(--zhu); }}
  .act input {{ font-family:var(--serif); font-size:.95rem; padding:.05rem .3rem;
               border:1px solid var(--rule); background:var(--panel); color:var(--ink); border-radius:3px; }}
  .card.dirty {{ background:color-mix(in srgb, var(--indigo) 7%, var(--panel)); }}
  .state {{ font-size:.68rem; color:var(--indigo); font-weight:700; }}
  .bar {{ position:sticky; bottom:0; background:var(--panel); border-top:2px solid var(--ink);
         padding:.6rem .8rem; margin:1.5rem -1.4rem -3rem; display:flex; gap:1rem;
         align-items:center; flex-wrap:wrap; z-index:6; }}
  .bar button {{ font-size:.9rem; padding:.35rem 1rem; border-radius:3px; cursor:pointer;
                border:1px solid var(--indigo); background:var(--indigo); color:#fff; }}
  .bar button:disabled {{ opacity:.45; cursor:default; }}
  .bar .msg {{ font-size:.85rem; color:var(--mute); }}
  @media (max-width:640px) {{ .card {{ grid-template-columns:1fr; }} }}
</style>
<header>
  <h1>{_e(chars)} 字位复核</h1>
  <div class="sum">
    <span><b>{len(entries)}</b> 字位</span>
    {"".join(f'<span><b>{n}</b> {_e(k)}</span>' for k, n in src_cnt.most_common())}
    <span><b>{meta['books']}</b></span>
  </div>
  <p class="note">按字分组，<b>可疑的排前面</b>：待审 → 库 top1 与最终字不符 → 库前两名分差小
  （形近字的典型特征）→ 与整理本不符。左侧红边 = 值得先看。大图看笔画，右边竖条看同列上下文。</p>
</header>
<div class="filters">
  <span class="k">筛</span>
  <label><input type="checkbox" class="f-src" value="人裁" checked> 人裁</label>
  <label><input type="checkbox" class="f-src" value="自动" checked> 自动</label>
  <label><input type="checkbox" class="f-src" value="待审" checked> 待审</label>
  <label><input type="checkbox" id="only-susp"> 只看可疑</label>
  <span id="shown" class="mono"></span>
</div>
{"".join(secs)}
<div class="bar">
  <button id="submit" disabled>提交改判</button>
  <span class="msg" id="msg">改了 0 条</span>
  <span class="msg">批次 <code class="mono">{_e(meta['batch'])}</code> · API <code class="mono">{_e(meta['api'])}</code></span>
</div>
<script>
const API={meta['api']!r}, BATCH={meta['batch']!r};
// 只有 己/已/巳 分字形与文意（与控制台 needsReading 同一条规则）
const SPLIT=new Set(['己','已','巳']);
const cards=[...document.querySelectorAll('.card')];
const edits={{}};   // id -> {{shape, reading, mark}}

function apply(){{
  const srcs=new Set([...document.querySelectorAll('.f-src:checked')].map(i=>i.value));
  const susp=document.getElementById('only-susp').checked;
  let n=0;
  cards.forEach(c=>{{
    const ok=srcs.has(c.dataset.src)&&(!susp||c.classList.contains('susp'));
    c.hidden=!ok; if(ok)n++;
  }});
  document.querySelectorAll('section').forEach(s=>{{
    s.hidden=![...s.querySelectorAll('.card')].some(c=>!c.hidden);
  }});
  document.getElementById('shown').textContent=n+' / '+cards.length;
}}
document.querySelectorAll('.f-src,#only-susp').forEach(i=>i.addEventListener('change',apply));

function paint(card){{
  const id=card.dataset.id, e=edits[id];
  card.classList.toggle('dirty', !!e);
  const st=card.querySelector('.state');
  st.textContent = e ? (e.mark ? ({{non:'标为非字',truncated:'标为切坏',contaminated:'标为有噪声'}})[e.mark]
                               : ('改为 '+e.shape+(e.reading&&e.reading!==e.shape?(' / 文意 '+e.reading):'')))
                     : '';
  card.querySelectorAll('.pick').forEach(b=>
    b.classList.toggle('on', e&&!e.mark ? b.dataset.ch===e.shape : b.dataset.ch===card.dataset.orig));
  card.querySelectorAll('.mk').forEach(b=>
    b.classList.toggle('on', !!e&&e.mark===b.dataset.mark));
  const rd=card.querySelector('.rd');
  rd.hidden = !(e&&!e.mark&&SPLIT.has(e.shape));
  const n=Object.keys(edits).length;
  document.getElementById('msg').textContent='改了 '+n+' 条';
  document.getElementById('submit').disabled = n===0;
}}
function setEdit(card, patch){{
  const id=card.dataset.id;
  if(patch===null){{ delete edits[id]; }}
  else {{
    const cur=edits[id]||{{}};
    const nx={{...cur, ...patch}};
    if(nx.shape && !nx.mark) nx.reading = SPLIT.has(nx.shape) ? (nx.reading||'') : nx.shape;
    // 改回原样且没标记 = 等于没改
    if(!nx.mark && nx.shape===card.dataset.orig && (!SPLIT.has(nx.shape)||!nx.reading||nx.reading===nx.shape))
      {{ delete edits[id]; }}
    else edits[id]=nx;
  }}
  paint(card);
}}
document.addEventListener('click', ev=>{{
  const card=ev.target.closest('.card'); if(!card) return;
  const p=ev.target.closest('.pick');
  if(p) return setEdit(card, {{shape:p.dataset.ch, mark:''}});
  const m=ev.target.closest('.mk');
  if(m){{
    const cur=edits[card.dataset.id];
    return setEdit(card, (cur&&cur.mark===m.dataset.mark) ? null : {{mark:m.dataset.mark, shape:''}});
  }}
  if(ev.target.closest('.undo')) return setEdit(card, null);
}});
document.addEventListener('input', ev=>{{
  const card=ev.target.closest('.card'); if(!card) return;
  if(ev.target.classList.contains('txt')){{
    const v=ev.target.value.trim();
    setEdit(card, v ? {{shape:v, mark:''}} : null);
  }} else if(ev.target.classList.contains('txtrd')){{
    const cur=edits[card.dataset.id]; if(cur) setEdit(card, {{reading:ev.target.value.trim()}});
  }}
}});

document.getElementById('submit').onclick=async()=>{{
  const btn=document.getElementById('submit'), msg=document.getElementById('msg');
  const rows=[], now=Date.now();
  for(const [id,e] of Object.entries(edits)){{
    if(e.mark==='non') rows.push({{id, v:'not_a_char', client_ts:now}});
    else if(e.mark) rows.push({{id, v:'seg_defect', quality:e.mark, shape:'', reading:'', client_ts:now}});
    else {{
      const rd = SPLIT.has(e.shape) ? (e.reading||e.shape) : e.shape;
      rows.push({{id, v:'confirm', shape:e.shape, reading:rd,
                 conversion: rd!==e.shape ? 1 : 0, client_ts:now}});
    }}
  }}
  btn.disabled=true; msg.textContent='提交中…';
  try{{
    const r=await fetch(API+'/api/events', {{method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{batch:BATCH, step:'seed_admit', unit:'cell', kind:'confirm', events:rows}})}});
    if(!r.ok) throw new Error('HTTP '+r.status+' '+(await r.text()).slice(0,120));
    const d=await r.json();
    msg.textContent='已提交 '+rows.length+' 条'+(d.consumed!=null?('，已消费 '+JSON.stringify(d.consumed)):'')
      +'。重跑 seed_admit 后本页需重新生成。';
    for(const id of Object.keys(edits)) delete edits[id];
    cards.forEach(paint);
    document.getElementById('msg').textContent=msg.textContent;
  }}catch(err){{
    btn.disabled=false;
    msg.textContent='提交失败：'+err.message+'（控制台没在跑？先起 guji-cv console）';
  }}
}};
apply();
</script>"""


def main() -> int:
    ap = argparse.ArgumentParser(description="按字复核页")
    ap.add_argument("--chars", required=True, help="要复核的字，连写如 曾會")
    ap.add_argument("--books", default="vol01,vol02")
    ap.add_argument("--pages", default="", help="页表达式；空 = 各书全部有产物的页")
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--out", default=None)
    ap.add_argument("--api", default="http://127.0.0.1:8641",
                    help="控制台地址（页面提交改判用）")
    ap.add_argument("--batch", default=None,
                    help="事件批次名；默认 <书>-review-<字>")
    a = ap.parse_args()

    t0 = time.time()
    chars = set(a.chars)
    st = ProductStore()
    raw = (REPO / a.corpus).read_text(encoding="utf-8")
    corpus = "".join(c for c in raw if is_han(c))
    index = build_ngram_index(corpus)

    entries = []
    for book in [b.strip() for b in a.books.split(",") if b.strip()]:
        bk = load_book(book)
        if a.pages:
            pages = bk.resolve_pages(a.pages)
        else:
            d = st.root / book / "seed_admit"
            pages = sorted(int(p.stem[1:]) for p in d.glob("p*.json")) if d.exists() else []
        got = collect(book, pages, chars, st, corpus, index)
        print(f"  {book}: {len(pages)} 页 → {len(got)} 个字位")
        entries.extend(got)

    batch = a.batch or f"{a.books.split(',')[0].strip()}-review-{a.chars}"
    out = Path(a.out) if a.out else REPO / "output" / f"review_{a.chars}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(a.chars, entries,
                          {"books": a.books, "api": a.api.rstrip("/"), "batch": batch}),
                   encoding="utf-8")
    cnt = Counter(e["source"] for e in entries)
    susp = sum(1 for e in entries if (e["lib1"] and e["lib1"] != e["char"]) or e["source"] == "待审")
    print(f"共 {len(entries)} 字位（{dict(cnt)}），可疑 {susp}")
    print(f"HTML {out.stat().st_size / 1e6:.2f} MB → {out}；{time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
