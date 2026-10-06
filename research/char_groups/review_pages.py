# -*- coding: utf-8 -*-
"""字组人裁审查页（overview#437，G1，2026-10-06）：给用户亲自裁的三批随机样本。

用户 10-06 定：G0 缺数据清单第 1 条（放行格随机抽样）由用户人裁，结果记 A 档（`label_origin=human`）。
三批，一批一页（壳：`.claude/skills/review-artifact/scripts/review_shell.py`）：
  ry   日曰   vol02/03/04 每册机器放行格（core、admit、channel≠human）随机 100 格（不足 100 全收）
  rr   入人八 同上
  jys  己已巳 vol04 待审格（core、未放行）全收 + vol05 core 格随机 50

抽样框只取正文页（`page_type=body`；当前只优化正文，三组 dev/val 三册的放行格本来也全在正文）。
种子固定（`SEED`），每张卡记 `stratum`（册）与 `stratum_weight`（框内格数 / 抽中格数），事后才估得出整册放行错率。
卡片 id 冻在 dataset `char-groups/review/<批>_cards.jsonl`：已有就照读，不重抽（重出页面 id 不变，上一轮裁决对得上）。

卡面：字块放大图；刻本读序前后 30 字（目标位挖空高亮）；整理本对应 30 字（同样挖空）；
机器参考（放行字、整理本此处、通道）折叠着，不印在卡面上，免得人顺着机器点；整列小图折叠着，点开才看。
按钮：本组成员字 +「别的字」（可填）+「看不清」。裁决值：成员字本身 / `other:<字>` / `other` / `unclear`。

用法：python research/char_groups/review_pages.py <snap_root> <dataset>/char-groups <ry|rr|jys> -o page.html
收回：python .claude/skills/review-artifact/scripts/harvest_verdicts.py <读回的 html> -o <dataset>/char-groups/review/<批>_verdicts.jsonl
      再跑 build.py（把 review/*_verdicts.jsonl 当 A 档真值源收进来）与 baseline.py。
"""
from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import GROUPS, SNAPS  # noqa: E402

CV = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CV / ".claude/skills/review-artifact/scripts"))
from review_shell import render  # noqa: E402

WS = (glob.glob("/home/user/guji-workspace/96mid1ogzk-*") or [""])[0]
SEED = 20261006
COL_H = 640          # 整列小图高（px，灰度 JPEG；页面每存一次要整页重发，压到每张 ~8KB）

# 批 → 抽样设定：[(册, 框, 抽几格)]；框：admit=机器放行格，pending=未放行格，all=core 全部
BATCHES = {
    "ry": {"name": "日曰", "plan": [("vol02", "admit", 100), ("vol03", "admit", 100), ("vol04", "admit", 100)]},
    "rr": {"name": "入人八", "plan": [("vol02", "admit", 100), ("vol03", "admit", 100), ("vol04", "admit", 100)]},
    "jys": {"name": "己已巳", "plan": [("vol04", "pending", None), ("vol05", "all", 50)]},
    # Z-jys（overview#443）：pool vol05–10 里分类器 S1 给了字的格，按「给的字 × 通道」分层抽；另加 1 格人裁疑误的复核
    "jys2": {"name": "己已巳·放行复核", "base": "jys",
             "plan": [("pool", "已:rule", 5), ("pool", "已:llm+lr", 6), ("pool", "己:rule", 6),
                      ("pool", "己:llm+lr", 5), ("pool", "巳:rule", 8), ("recheck", "vol02:186:7:3", 1)]},
}
RECHECK = ["vol02:186:7:3"]


def in_frame(r, frame):
    if not r["core"] or r["page_type"] != "body" or r["admit"] is None:
        return False
    if frame == "admit":
        return bool(r["admit"]) and r["channel"] != "human"
    if frame == "pending":
        return not r["admit"] and r["channel"] != "human"
    return True


def sample_jys2(items, gk, root):
    """分类器 S1 在 pool（vol05–10）无强真值 core 格上给了字的格：按「给的字:通道」分层抽（种子同 SEED）。"""
    preds = [json.loads(l) for l in open(f"{root}/jys/classifier_preds.jsonl", encoding="utf-8")]
    rng = random.Random(f"{SEED}:{gk}")
    cards = []
    for kind, key, n in BATCHES[gk]["plan"]:
        if kind == "recheck":
            cards.append({"id": key, "stratum": "recheck", "frame_n": 1, "picked": 1, "stratum_weight": 0})
            continue
        ch, by = key.split(":")
        pool = sorted(o["id"] for o in preds if o["split"] == "pool" and o["gold_tier"] not in ("A_human", "B_vision")
                      and o["final"] == ch and o["by"] == by)
        pick = rng.sample(pool, min(n, len(pool)))
        for i in pick:
            cards.append({"id": i, "stratum": f"pool:{key}", "frame_n": len(pool), "picked": len(pick),
                          "stratum_weight": round(len(pool) / len(pick), 4)})
    rng.shuffle(cards)
    return cards


def sample(items, gk):
    rng = random.Random(f"{SEED}:{gk}")
    cards = []
    for book, frame, n in BATCHES[gk]["plan"]:
        pool = sorted((r for r in items if r["book"] == book and in_frame(r, frame)), key=lambda r: r["id"])
        pick = pool if n is None or n >= len(pool) else rng.sample(pool, n)
        for r in pick:
            cards.append({"id": r["id"], "stratum": f"{book}:{frame}", "frame_n": len(pool), "picked": len(pick),
                          "stratum_weight": round(len(pool) / len(pick), 4)})
    rng.shuffle(cards)       # 打散册序，免得裁到后面只剩一册
    return cards


def b64(buf, mime):
    return f"data:{mime};base64," + base64.b64encode(buf).decode()


def column_strip(snap_root, r, cache):
    """整列小图（灰度 JPEG，高 COL_H）+ 目标格在图里的纵向位置（比例）。取 cell_shrink 本列各格 bbox_page 的并集。"""
    import cv2
    import numpy as np
    from open_guji_cv.core.anchor import to_cv
    book, page = r["book"], r["page"]
    key = (book, page)
    if key not in cache:
        s_cut = SNAPS[book][2]
        p = f"{snap_root}/{s_cut}/products/{book}/cell_shrink/p{page:04d}.json"
        img = cv2.imdecode(np.fromfile(f"{WS}/data_full/zongmu/{book}/{page}.png", np.uint8), 0)
        cols = {}
        if os.path.exists(p) and img is not None:
            for c in json.load(open(p, encoding="utf-8"))["char_index"].get("columns", []):
                # bbox_page 原点在右上角（raw_page_px@top-right），换成左上原点再切
                cols[c["col"]] = {ch["id"]: to_cv(tuple(ch["bbox_page"]), img.shape[1])
                                  for ch in c["chars"] if ch.get("bbox_page")}
        cache.clear()
        cache[key] = (img, cols)
    img, cols = cache[key]
    boxes = cols.get(r["col"]) or {}
    if img is None or r["id"] not in boxes:
        return None
    xs0, ys0, xs1, ys1 = zip(*boxes.values())
    pad = 6
    x0, x1 = max(0, int(min(xs0)) - pad), min(img.shape[1], int(max(xs1)) + pad)
    y0, y1 = max(0, int(min(ys0)) - pad), min(img.shape[0], int(max(ys1)) + pad)
    strip = img[y0:y1, x0:x1]
    sc = COL_H / strip.shape[0]
    strip = cv2.resize(strip, (max(8, round(strip.shape[1] * sc)), COL_H), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", strip, [cv2.IMWRITE_JPEG_QUALITY, 45])
    t = boxes[r["id"]]
    return {"src": b64(buf.tobytes(), "image/jpeg"),
            "top": round((t[1] - y0) / (y1 - y0), 4), "h": round((t[3] - t[1]) / (y1 - y0), 4)}


def crop_img(root, gk, r):
    import cv2
    import numpy as np
    if not r.get("crop"):
        return None
    p = f"{root}/{gk}/{r['crop']}"
    im = cv2.imdecode(np.fromfile(p, np.uint8), 0)
    if im is None:
        return None
    ok, buf = cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, 72])
    return b64(buf.tobytes(), "image/jpeg")


VERDICT_CSS = """
/* 布局：单栏卡片流；卡头一行（字块 + 位置），下面两段 30 字上下文，机器参考与整列折叠在底 */
:root{--hl:#F3D48A; --hl-ink:#3B2A05;}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--hl:#6B5418; --hl-ink:#FBEFC8;}}
:root[data-theme="dark"]{--hl:#6B5418; --hl-ink:#FBEFC8;}
.card{background:var(--surface); border:1px solid var(--rule); border-left:3px solid transparent;
  border-radius:3px; padding:12px 13px; box-shadow:var(--shadow); display:grid; gap:10px; min-width:0;}
.card[data-v]{border-left-color:var(--indigo)}
.card[data-v^="other"]{border-left-color:var(--ochre)}
.card[data-v="unclear"]{border-left-color:var(--faint)}
.head{display:flex; gap:12px; align-items:flex-end;}
.glyph{width:132px; height:132px; flex:none; display:grid; place-items:center;
  background:var(--tile); border-radius:2px; overflow:hidden;}
.glyph img{max-width:100%; max-height:100%; width:auto; height:100%; object-fit:contain;}
.meta{font-family:var(--mono); font-size:11.5px; color:var(--muted); line-height:1.6; min-width:0;}
.meta b{font-family:var(--sans); font-weight:600; color:var(--ink); font-size:12.5px;}
.ctx{font-family:var(--serif); font-size:17px; line-height:1.75; letter-spacing:.06em;
  word-break:break-all; margin:0;}
.ctx .t{background:var(--hl); color:var(--hl-ink); border-radius:2px; padding:0 3px; margin:0 1px;
  font-family:var(--sans); font-size:13px; font-weight:600; letter-spacing:0;}
.lab{font-size:11px; letter-spacing:.06em; color:var(--faint); text-transform:uppercase; margin-bottom:2px;}
.ref .ctx{color:var(--muted); font-size:15.5px;}
details.fold summary{cursor:pointer; font-size:12.5px; color:var(--muted);}
details.fold summary::marker{color:var(--faint)}
details.fold .mach{margin-top:6px; font-size:13px; line-height:1.7;}
details.fold .mach span{font-family:var(--serif); font-size:16px; color:var(--ink);}
.colwrap{position:relative; display:inline-block; margin-top:8px; background:var(--tile); border-radius:2px;}
.colwrap img{display:block; height:min(70vh,900px); width:auto; max-width:none;}
.colwrap i{position:absolute; left:-5px; right:-5px; border:2px solid var(--zhu); border-radius:2px;}
.verdicts{display:grid; grid-template-columns:repeat(NMEM,1fr) 1.15fr 1fr; gap:6px;}
.verdicts button{min-height:46px; border:1px solid var(--rule-hard); border-radius:3px;
  background:var(--surface); color:var(--ink); font-family:var(--sans); font-size:13px;
  font-weight:500; cursor:pointer; padding:0 4px;}
.verdicts button.m{font-family:var(--serif); font-size:21px; font-weight:700;}
.verdicts button:active{background:var(--sunk)}
.verdicts button:focus-visible{outline:2px solid var(--indigo); outline-offset:2px;}
.verdicts button[aria-pressed="true"]{color:var(--on-solid); border-color:transparent; background:var(--indigo);}
.verdicts button.other[aria-pressed="true"]{background:var(--ochre)}
.verdicts button.unclear[aria-pressed="true"]{background:var(--faint)}
.otherbox{display:flex; gap:8px; align-items:center; font-size:12.5px; color:var(--muted);}
.otherbox input{width:4.2em; min-height:40px; font-family:var(--serif); font-size:20px; text-align:center;
  border:1px solid var(--rule-hard); border-radius:3px; background:var(--ground); color:var(--ink);}
.otherbox input:focus-visible{outline:2px solid var(--ochre); outline-offset:1px;}
.ctrl .seg{flex:1 1 auto}
.ctrl{flex-wrap:wrap}
@media (max-width:380px){.glyph{width:108px; height:108px}}
"""

PAGE_JS = r"""
const MEMBERS = __MEMBERS__;
const BODY = `
<header class="top"><div class="top-in">
  <span class="brand">__TITLE__</span>
  <span class="save" id="save">本机</span>
  <span class="count" id="count">0 / 0</span>
</div><div class="bar"><i id="prog"></i></div></header>
<div class="wrap">
  <details class="intro" id="intro" open>
    <summary>怎么裁</summary>
    <p>__INTRO__</p>
    <p>挖空高亮的 <span style="font-family:var(--serif)">〔　〕</span> 就是这一格。上一行是刻本读序前后各 30 字（机器读的，可能有错字），
       下一行是整理本对应位置的 30 字（「·」是整理本这里没对上字）。机器给的字收在「机器参考」里，想核对再点开。</p>
    <p>按钮是这一组的字；不是组里的字点「别的字」再填；图看不清、切坏了点「看不清」。点错再点一次取消。
       裁决自动存回本页，右上角牌子显示<code>已存</code>就是存上了；要是一直是<code>仅存本机</code>，用「复制」把结果贴回对话。</p>
  </details>
  <div class="ctrl">
    <div class="seg" id="filter">
      <button data-f="todo" aria-pressed="true">未裁</button>
      <button data-f="all"  aria-pressed="false">全部</button>
      <button data-f="done" aria-pressed="false">已裁</button>
    </div>
    <button class="ghost" id="copy">复制</button>
    <button class="ghost" id="reset">清空</button>
  </div>
  <div class="list" id="list"></div>
</div>
<div class="sheet" id="sheet" hidden><div class="sheet-in">
  <h2>裁决结果</h2><p id="sheet-note"></p>
  <textarea id="sheet-text" readonly></textarea>
  <div class="row"><button class="ghost" id="sheet-copy">复制</button>
  <button class="ghost" id="sheet-close">关闭</button></div>
</div></div>`;

const rowId = r => r.id;
const HOLE = '<span class="t">〔　〕</span>';

function card(r){
  const v = verdictOf(r.id);
  const isOther = v === 'other' || v.startsWith('other:');
  const mem = MEMBERS.map(c => `<button class="m" data-v="${c}" aria-pressed="${v===c}">${c}</button>`).join('');
  const typed = v.startsWith('other:') ? v.slice(6) : '';
  return `<article class="card" data-id="${r.id}"${v ? ` data-v="${esc(v)}"` : ''}>
    <div class="head">
      <div class="glyph">${r.img ? `<img data-src="c:${r.id}" alt="字块">` : '<span class="meta">无图</span>'}</div>
      <div class="meta"><b>${esc(r.book)}</b> 第 ${r.page} 页<br>第 ${r.col} 列 第 ${r.slot}${r.sub ? r.sub : ''} 字<br>${esc(r.no)}</div>
    </div>
    <div><div class="lab">刻本读序</div><p class="ctx">${esc(r.left)}${HOLE}${esc(r.right)}</p></div>
    <div class="ref"><div class="lab">整理本对应</div><p class="ctx">${esc(r.ref_left)}${HOLE}${esc(r.ref_right)}</p></div>
    <div class="verdicts">${mem}<button class="other" data-v="other" aria-pressed="${isOther}">别的字</button><button class="unclear" data-v="unclear" aria-pressed="${v==='unclear'}">看不清</button></div>
    ${isOther ? `<label class="otherbox">是哪个字：<input id="o-${r.id}" data-id="${r.id}" maxlength="2" value="${esc(typed)}" autocomplete="off"></label>` : ''}
    <details class="fold"><summary>机器参考</summary><div class="mach">
      放行字 <span>${esc(r.m_char || '—')}</span>　整理本此处 <span>${esc(r.m_ref || '—')}</span>　通道 ${esc(r.m_channel || '—')}</div></details>
    ${r.colimg ? `<details class="fold col" data-id="${r.id}"><summary>整列小图</summary><div class="colwrap"><img data-src="k:${r.id}" alt="整列"><i style="top:${r.col_top*100}%;height:${Math.max(r.col_h*100,0.8)}%"></i></div></details>` : ''}
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
/* 整列小图：点开才塞图（不进懒加载观察，免得折叠着也下载） */
document.addEventListener('toggle', e => {
  const d = e.target; if (!d.matches || !d.matches('details.col') || !d.open) return;
  const img = d.querySelector('img[data-src]'); if (!img) return;
  img.src = D.imgs[img.dataset.src]; img.removeAttribute('data-src');
}, true);
/* 「别的字」：点了先记 other，卡下冒出输入框；填了字记成 other:<字> */
function setOther(id, ch){
  ch = (ch || '').trim();
  state[id] = {v: ch ? 'other:' + ch : 'other', t: Date.now()};
  persist(); tally();
  const art = document.querySelector(`.card[data-id="${CSS.escape(id)}"]`);
  if (art) art.dataset.v = state[id].v;
}
document.addEventListener('change', e => {
  const i = e.target.closest('.otherbox input'); if (i) setOther(i.dataset.id, i.value);
});
document.addEventListener('keydown', e => {
  const i = e.target.closest && e.target.closest('.otherbox input');
  if (i && e.key === 'Enter'){ i.blur(); }
});
/* 记下刚点的是哪张卡（捕获阶段，先于壳的处理）；手机上按钮不一定拿得到焦点，别靠 activeElement。
   已填了字的「别的字」再点一次＝取消：先把它退回 other，壳那边同值再点就删掉。 */
let lastId = '';
document.addEventListener('click', e => {
  const b = e.target.closest('.verdicts button'); if (!b) return;
  lastId = b.closest('.card').dataset.id;
  if (b.dataset.v === 'other' && verdictOf(lastId).startsWith('other:')) state[lastId] = {v: 'other', t: Date.now()};
}, true);
function redrawCard(id){
  const art = listEl.querySelector(`.card[data-id="${CSS.escape(id)}"]`); if (!art) return;
  art.outerHTML = card(D.rows.find(r => r.id === id));
  listEl.querySelectorAll('img[data-src^="c:"]').forEach(i => io.observe(i));
}
function afterVerdict(){
  const id = lastId, v = id ? verdictOf(id) : '';
  /* 「别的字」要等人填字：这张卡原地重画、冒出输入框，先别从「未裁」档里拿走 */
  if (v === 'other'){ redrawCard(id); const inp = document.getElementById('o-' + id); if (inp) inp.focus(); return; }
  if (filter !== 'all'){ const y = scrollY; draw(); scrollTo(0, y); }
  else if (id) redrawCard(id);
}
function payload(){
  return D.rows.filter(r => verdictOf(r.id)).map(r => JSON.stringify({id: r.id, verdict: verdictOf(r.id),
    stratum: r.stratum, stratum_weight: r.stratum_weight})).join('\n');
}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("snap_root")
    ap.add_argument("root", help="<dataset>/char-groups")
    ap.add_argument("group", choices=sorted(BATCHES))
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--seed-verdicts", help="上一轮收回的 verdicts.jsonl，嵌进页里续裁")
    a = ap.parse_args()
    gk, root = a.group, a.root
    gdir = BATCHES[gk].get("base", gk)       # 数据目录（jys2 复用 jys 的 items/crops）
    items = {r["id"]: r for r in (json.loads(l) for l in open(f"{root}/{gdir}/items.jsonl", encoding="utf-8"))}
    cpath = Path(root) / "review" / f"{gk}_cards.jsonl"
    if cpath.exists():
        cards = [json.loads(l) for l in open(cpath, encoding="utf-8")]
        print(f"照读冻结卡片 {cpath}（{len(cards)} 张）", file=sys.stderr)
    else:
        cards = sample_jys2(items.values(), gk, root) if gk == "jys2" else sample(items.values(), gk)
        cpath.parent.mkdir(parents=True, exist_ok=True)
        with open(cpath, "w", encoding="utf-8") as f:
            for c in cards:
                f.write(json.dumps({**c, "group": gk, "seed": SEED}, ensure_ascii=False) + "\n")
    members = list(GROUPS[gdir]["members"])
    rows, imgs, cache = [], {}, {}
    for i, c in enumerate(cards, 1):
        r = items[c["id"]]
        crop = crop_img(root, gdir, r)
        try:
            col = column_strip(a.snap_root, r, cache)
        except (FileNotFoundError, KeyError, OSError, ImportError):
            col = None            # 本机没有原图/快照：整列小图缺省（卡面其余不受影响）
        if crop:
            imgs[f"c:{r['id']}"] = crop
        if col:
            imgs[f"k:{r['id']}"] = col["src"]
        rows.append(dict(
            id=r["id"], no=f"#{i:03d}", book=r["book"], page=r["page"], col=r["col"], slot=r["slot"], sub=r["sub"],
            left=r["left"], right=r["right"], ref_left=r["ref_left"], ref_right=r["ref_right"],
            m_char=r["char"], m_ref=r["ref"] or r["coord_ref"], m_channel=r["channel"],
            img=bool(crop), colimg=bool(col), col_top=col["top"] if col else None, col_h=col["h"] if col else None,
            stratum=c["stratum"], stratum_weight=c["stratum_weight"],
        ))
    verdicts = {}
    if a.seed_verdicts:
        for l in open(a.seed_verdicts, encoding="utf-8"):
            x = json.loads(l)
            verdicts[x["id"]] = {"v": x["verdict"], "t": x.get("t") or 0}
    name = BATCHES[gk]["name"]
    plan = ("、".join(f"{b} {sum(1 for c in cards if c['stratum'].startswith(b))} 格" for b, _, _ in BATCHES[gk]["plan"][:1] + BATCHES[gk]["plan"][-1:])
            if gk == "jys2" else "、".join(f"{b} {sum(1 for c in cards if c['stratum'].startswith(b))} 格" for b, _, _ in BATCHES[gk]["plan"]))
    frame_txt = {"ry": "机器已放行的格里随机抽", "rr": "机器已放行的格里随机抽",
                 "jys": "vol04 全部待审格，加 vol05 随机抽 50 格",
                 "jys2": "vol05–10 里机器已给字的格，按给的字与通道分层随机抽（含 1 格上轮人裁疑有误的复核）"}[gk]
    intro = f"字组「{name}」人裁：{frame_txt}（{plan}，共 {len(rows)} 格）。看字块和上下文，点这一格实际是哪个字。"
    title = f"{name}人裁"
    js = (PAGE_JS.replace("__MEMBERS__", json.dumps(members, ensure_ascii=False))
          .replace("__TITLE__", title).replace("__INTRO__", intro))
    css = VERDICT_CSS.replace("NMEM", str(len(members)))
    html = render(title, f"char-groups-{gk}-review-" + ("z1" if gk == "jys2" else "g1"), verdicts=verdicts, css=css, page_js=js,
                  payload={"rows": rows, "imgs": imgs, "group": gk, "seed": SEED})
    Path(a.out).write_text(html, encoding="utf-8")
    print(f"{a.out}  {len(html) / 1024 / 1024:.2f} MB  {len(rows)} 卡  {plan}", file=sys.stderr)


if __name__ == "__main__":
    main()
