# -*- coding: utf-8 -*-
"""vol03 影子放行核对页：影子≠现字的格，让人裁「图上是哪个字」（overview#269）。

    ~/shadow-venv/bin/python research/shadow_admit/build_vol03_shadow_review.py \
        --picks <out>/shadow_picks_vol03.jsonl --products <snap>/products/vol03 \
        --images <ws>/data_full/zongmu/vol03 --out <out>/vol03_shadow_review.html

出卡两类：已放行格里影子≠现字的全部格（按把握排，不截门槛——≥0.9 只有 7 格）＋ 待审卡里影子把握 ≥0.95 且≠整理本字的格。
**卡上不印哪个是影子、哪个是现字**，两字顺序按 id 哈希打散；机器信息（把握、通道）只进卡片 JSONL 存盘，不上页。
卡 id 冻结在 `<out>/vol03_shadow_review_cards.jsonl`（有就照读）。只读产物与原图。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path

import cv2
import numpy as np

SK = Path(__file__).resolve().parents[2] / ".claude/skills/review-artifact/scripts"
sys.path.insert(0, str(SK))
from review_shell import render  # noqa: E402

TITLE = "vol03 影子≠现字 核对"
KEY = "vol03-shadow-review-v1"
VERDICTS = [("a", "左字", "ok"), ("b", "右字", "ok"), ("neither", "都不是", "zhu"), ("idk", "拿不准", "faint")]


def uri(img, h):
    k = h / img.shape[0]
    img = cv2.resize(img, (max(1, round(img.shape[1] * k)), h), interpolation=cv2.INTER_AREA)
    img = (img // 16) * 16 + 8
    ok, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def bbox(q, W, pad=0):
    """quad_page 是右上角原点（segmentation_v2 口径），x 要翻回图像坐标。"""
    xs, ys = [W - p[0] for p in q], [p[1] for p in q]
    return int(min(xs)) - pad, int(min(ys)) - pad, int(max(xs)) + pad, int(max(ys)) + pad


CSS = """
.card{background:var(--surface); border:1px solid var(--rule); border-left:3px solid transparent;
  border-radius:3px; padding:12px 13px; box-shadow:var(--shadow);}
""" + "".join(f'.card[data-v="{v}"]{{border-left-color:var(--{c})}}\n' for v, _, c in VERDICTS) + """
.card h3{margin:0; font-family:var(--sans); font-size:12px; color:var(--muted); font-weight:500;}
.pics{display:flex; gap:12px; align-items:flex-end; margin-top:8px;}
.pics img.main{height:128px; image-rendering:pixelated; background:var(--tile); border-radius:2px;}
.pics img.ctx{height:260px; image-rendering:pixelated; background:var(--tile); border-radius:2px;}
.ctxt{margin:8px 0 0; font-family:var(--serif); font-size:15px; letter-spacing:1px; color:var(--muted); word-break:break-all;}
.ctxt b{color:var(--ink); background:var(--sunk); padding:0 2px;}
.verdicts{display:grid; grid-template-columns:repeat(4,1fr); gap:6px; margin-top:10px;}
.verdicts button{min-height:48px; border:1px solid var(--rule-hard); border-radius:3px; background:var(--surface);
  color:var(--ink); font-family:var(--sans); font-size:13px; font-weight:500; cursor:pointer;}
.verdicts button .ch{font-family:var(--serif); font-size:24px; display:block; line-height:1.1;}
.verdicts button:focus-visible{outline:2px solid var(--indigo); outline-offset:2px;}
.verdicts button[aria-pressed="true"]{color:var(--on-solid); border-color:transparent;}
""" + "".join(f'.verdicts button.{v}[aria-pressed="true"]{{background:var(--{c})}}\n' for v, _, c in VERDICTS)

PAGE_JS = """
const BODY = `
<header class="top"><div class="top-in">
  <span class="brand">__TITLE__</span>
  <span class="save" id="save">本机</span>
  <span class="count" id="count">0 / 0</span>
</div><div class="bar"><i id="prog"></i></div></header>
<div class="wrap">
  <details class="intro" id="intro" open>
    <summary>怎么裁</summary>
    <p>每张卡是四庫總目 vol03 的一个字位：左图是这一格，右边窄条是这一列上下几格。
       下面两个按钮各是一个候选字，<b>点图上刻的那个字形</b>（异体按刻形分，比如 彝/彞、宫/宮、歷/厯 算不同）。
       两个都不对点「都不是」，看不清点「拿不准」。点错再点一次取消。</p>
    <p>裁决自动存回本页，看右上角小牌子；显示<code>仅存本机</code>时用「复制」把结果贴回对话。</p>
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
  <div class="list" id="list"></div>
</div>
<div class="sheet" id="sheet" hidden><div class="sheet-in">
  <h2>裁决结果</h2><p id="sheet-note"></p>
  <textarea id="sheet-text" readonly></textarea>
  <div class="row"><button class="ghost" id="sheet-copy">复制</button>
  <button class="ghost" id="sheet-close">关闭</button></div>
</div></div>`;

const rowId = r => r.id;
function card(r){
  const v = verdictOf(r.id);
  const b = (k, inner) => `<button class="${k}" data-v="${k}" aria-pressed="${v===k}">${inner}</button>`;
  return `<article class="card" data-id="${r.id}"${v ? ` data-v="${v}"` : ''}>
    <h3>${esc(r.label)}</h3>
    <div class="pics"><img class="main" data-src="${r.id}#m" alt=""><img class="ctx" data-src="${r.id}#c" alt=""></div>
    <p class="ctxt">${esc(r.before)}<b>□</b>${esc(r.after)}</p>
    <div class="verdicts">${b('a', `<span class="ch">${esc(r.a)}</span>`)}${b('b', `<span class="ch">${esc(r.b)}</span>`)}${b('neither','都不是')}${b('idk','拿不准')}</div>
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
function afterVerdict(){ if (filter !== 'all') draw(); }
function payload(){
  return D.rows.filter(r => verdictOf(r.id)).map(r => {
    const v = verdictOf(r.id);
    return JSON.stringify({id: r.id, verdict: v, char: v === 'a' ? r.a : v === 'b' ? r.b : null});
  }).join('\\n');
}
""".replace("__TITLE__", TITLE)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--picks", required=True)
    ap.add_argument("--products", required=True)
    ap.add_argument("--images", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    cards_path = out.with_name(out.stem + "_cards.jsonl")
    picks = [json.loads(l) for l in open(a.picks, encoding="utf-8")]
    by_id = {p["id"]: p for p in picks}

    if cards_path.exists():
        cards = [json.loads(l) for l in open(cards_path, encoding="utf-8")]
    else:
        adm = [p for p in picks if p["admit"] and not p["labeled"] and p["pick"] != p["cur"]]
        adm.sort(key=lambda p: -p["conf"])
        pend = [p for p in picks if not p["admit"] and p["verdict_v"] is None and "excluded" not in p["doubts"]
                and p["conf"] >= 0.95 and p["pick"] != (p["ref_char"] or None)]
        pend.sort(key=lambda p: -p["conf"])
        cards = []
        for grp, rows in (("admitted", adm), ("pending", pend)):
            for p in rows:
                other = p["cur"] if grp == "admitted" else (p["ref_char"] or p["second"])
                pair = [p["pick"], other]
                if int(hashlib.md5(p["id"].encode()).hexdigest(), 16) % 2:
                    pair.reverse()
                cards.append({"id": p["id"], "group": grp, "a": pair[0], "b": pair[1], "shadow": p["pick"],
                              "cur": p["cur"], "ref": p["ref_char"], "conf": round(p["conf"], 4),
                              "channel": p["channel"], "doubts": p["doubts"]})
        with open(cards_path, "w", encoding="utf-8") as f:
            for c in cards:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")

    # 列内上下文文字：按 (页, 列, 格, 子) 排
    def k(i):
        _, p, c, s = i.split(":")
        sub = s[-1] if s[-1] in "ab" else ""
        return int(p), int(c), int(s.rstrip("ab")), sub
    col_seq: dict[tuple, list] = {}
    for p in sorted(picks, key=lambda p: k(p["id"])):
        pg, c, _, _ = k(p["id"])
        col_seq.setdefault((pg, c), []).append(p["id"])

    seg_cache: dict[int, dict] = {}
    img_cache: dict[int, np.ndarray] = {}
    rows, imgs = [], {}
    for c in cards:
        pg, col, slot, sub = k(c["id"])
        if pg not in seg_cache:
            d = json.load(open(Path(a.products) / "row_segment" / f"p{pg:04d}.json", encoding="utf-8"))["cells"]
            seg_cache[pg] = {(cc["col"], ce["slot"], ce.get("sub") or ""): ce for cc in d["columns"] for ce in cc["cells"]}
            img_cache[pg] = cv2.imread(str(Path(a.images) / f"{pg}.png"), cv2.IMREAD_GRAYSCALE)
        im = img_cache[pg]
        cell = seg_cache[pg].get((col, slot, sub))
        if cell is None or im is None:
            print("缺图/缺格", c["id"], file=sys.stderr)
            continue
        x0, y0, x1, y1 = bbox(cell["quad_page"], im.shape[1], 4)
        imgs[c["id"] + "#m"] = uri(im[max(0, y0):y1, max(0, x0):x1], 128)
        near = [ce for (cc, s, _), ce in seg_cache[pg].items() if cc == col and abs(s - slot) <= 3]
        bx = [bbox(ce["quad_page"], im.shape[1]) for ce in near]
        X0, Y0 = min(b[0] for b in bx), min(b[1] for b in bx)
        X1, Y1 = max(b[2] for b in bx), max(b[3] for b in bx)
        strip = cv2.cvtColor(im[max(0, Y0):Y1, max(0, X0):X1], cv2.COLOR_GRAY2BGR)
        cv2.rectangle(strip, (x0 - X0, y0 - Y0), (x1 - X0, y1 - Y0), (0, 0, 0), 5)
        imgs[c["id"] + "#c"] = uri(cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY), 260)
        seq = col_seq[(pg, col)]
        i = seq.index(c["id"])
        txt = lambda ids: "".join((by_id[j]["cur"] or "□") for j in ids)
        rows.append({"id": c["id"], "label": f"{c['id']}", "a": c["a"], "b": c["b"],
                     "before": txt(seq[max(0, i - 6):i]), "after": txt(seq[i + 1:i + 7])})
    html = render(TITLE, KEY, verdicts={}, css=CSS, page_js=PAGE_JS, payload={"rows": rows, "imgs": imgs})
    out.write_text(html, encoding="utf-8")
    print(f"{out}  {len(html) / 1024:.0f} KB  {len(rows)} 卡（卡片存盘 {cards_path}）")


if __name__ == "__main__":
    main()
