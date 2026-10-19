# -*- coding: utf-8 -*-
"""殿本逐列字数金标的人裁页：两源不一致列 + 一致列随机抽检（doc/design/19 §三）。

    python build_colgold_review.py <sel.json> <ws_with_border_detect> <out.html> [verdicts.jsonl]

- sel.json：[[kind, colgold行], …]，kind ∈ {disagree, audit}（抽样见 doc/design/19 §三.3，种子 20261019）。
- 列条取自**我们的 CADAL 原图**，左右用 Step1 的界行（右上原点，x_tl = W−1−x），上沿多留 150px 给出格抬头。
- 列条切成三段、右起并排（读序：右段在上），字够大，手机上看得清。
- 出题纪律：不一致卡把两份文本记作甲乙、顺序按 id 哈希打散，不写来源；抽检卡只给 daizhige 文本，不给字数。
- 卡 id 冻在 results/colgold_review_cards.jsonl（含甲乙对应），重建页面照旧读。
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / ".claude" / "skills" / "review-artifact" / "scripts"))
from review_shell import render  # noqa: E402

TITLE = "殿本列字数金标人裁"
KEY = "colgold-review-v1"
RAW = Path("/home/user/guji-workspace/96mid1ogzk-欽定四庫全書總目武英殿刻本/data_full/zongmu")
CARDS = HERE / "results" / "colgold_review_cards.jsonl"
UNMAPPED = "〓"

AUDIT_V = [("same", "逐字一致", "ok"), ("chars", "字数对·个别字不同", "ochre"),
           ("count", "字数不对", "zhu"), ("idk", "拿不准", "faint")]
DIS_V = [("A", "甲对", "ok"), ("B", "乙对", "ok"), ("none", "都不对", "zhu"), ("idk", "拿不准", "faint")]


def _pua(s: str) -> str:
    return "".join(UNMAPPED if (0xE000 <= ord(c) <= 0xF8FF or ord(c) >= 0xF0000) else c for c in s)


def _strip_img(ws: Path, vol: str, page: int, col: int) -> str | None:
    from PIL import Image
    bd = ws / "products" / vol / "border_detect" / f"p{page:04d}.json"
    if not bd.exists():
        return None
    b = json.loads(bd.read_text())["borders"]
    vs = b["verticals"]
    if col >= len(vs):
        return None
    im = Image.open(RAW / vol / f"{page}.png").convert("L")
    W, H = im.size
    top = b["top"]["y_at_right"]
    bot = b["bottom"]["y_at_right"]

    def xs(v):   # 这条线在上下版框之间的 x 范围（右上原点）
        return [v["x_at_top"] + v["slope"] * y for y in (top, bot)]
    x_r = min(xs(vs[col - 1])) - 6
    x_l = max(xs(vs[col])) + 6
    y0, y1 = max(0, int(top - 150)), min(H, int(bot + 15))
    strip = im.crop((int(W - 1 - x_l), y0, int(W - 1 - x_r), y1))
    n = 3
    seg_h = (strip.height + n - 1) // n
    segs = [strip.crop((0, i * seg_h, strip.width, min(strip.height, (i + 1) * seg_h))) for i in range(n)]
    h_out = 300
    scale = h_out / seg_h
    w_seg = max(1, int(strip.width * scale))
    out = Image.new("L", (w_seg * n + 6 * (n - 1), h_out), 255)
    for i, s in enumerate(segs):            # 右起：第一段放最右
        s = s.resize((w_seg, max(1, int(s.height * scale))))
        out.paste(s, ((n - 1 - i) * (w_seg + 6), 0))
    out = out.quantize(16)
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def build_cards(sel: list) -> list[dict]:
    if CARDS.exists():
        return [json.loads(ln) for ln in CARDS.read_text(encoding="utf-8").splitlines() if ln.strip()]
    cards = []
    for kind, r in sel:
        cid = f"{r['vol']}:{r['page']}:{r['col']}"
        c = {"id": cid, "kind": kind, "vol": r["vol"], "page": r["page"], "col": r["col"],
             "stratum": kind, "dzg_n": r["dzg"]["n"], "release_n": (r["release"] or {}).get("n")}
        if kind == "audit":
            c["text"] = r["dzg"]["text"]
            c["stratum_weight"] = None   # 由收回脚本按一致列总数 / 抽样数算
        else:
            rel = _pua((r["release"] or {}).get("text") or "")
            swap = int(hashlib.sha1(cid.encode()).hexdigest(), 16) % 2 == 1
            a, b = (rel, r["dzg"]["text"]) if swap else (r["dzg"]["text"], rel)
            c.update({"A": a, "B": b, "A_is": "release" if swap else "dzg", "stratum_weight": 1})
        cards.append(c)
    CARDS.parent.mkdir(parents=True, exist_ok=True)
    CARDS.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cards), encoding="utf-8")
    return cards


CSS = """
.card{background:var(--surface); border:1px solid var(--rule); border-left:3px solid transparent;
  border-radius:3px; padding:12px 13px; box-shadow:var(--shadow);}
.card[data-v="same"],.card[data-v="A"],.card[data-v="B"]{border-left-color:var(--ok)}
.card[data-v="chars"]{border-left-color:var(--ochre)}
.card[data-v="count"],.card[data-v="none"]{border-left-color:var(--zhu)}
.card[data-v="idk"]{border-left-color:var(--faint)}
.card h3{margin:0; font-family:var(--serif); font-size:14px; color:var(--muted); font-weight:500}
.card img{display:block; margin:8px auto 0; max-width:100%; height:300px; background:var(--tile); border-radius:2px;}
.txt{font-family:var(--serif); font-size:18px; line-height:1.6; margin:8px 0 0; word-break:break-all;}
.txt b{font-family:var(--sans); font-size:12px; color:var(--muted); margin-right:6px; font-weight:600}
.verdicts{display:grid; grid-template-columns:repeat(2,1fr); gap:6px; margin-top:10px;}
.verdicts button{min-height:44px; border:1px solid var(--rule-hard); border-radius:3px; background:var(--surface);
  color:var(--ink); font-family:var(--sans); font-size:13px; font-weight:500; cursor:pointer;}
.verdicts button:active{background:var(--sunk)}
.verdicts button:focus-visible{outline:2px solid var(--indigo); outline-offset:2px;}
.verdicts button[aria-pressed="true"]{color:var(--on-solid); border-color:transparent;}
.verdicts button.same[aria-pressed="true"],.verdicts button.A[aria-pressed="true"],.verdicts button.B[aria-pressed="true"]{background:var(--ok)}
.verdicts button.chars[aria-pressed="true"]{background:var(--ochre)}
.verdicts button.count[aria-pressed="true"],.verdicts button.none[aria-pressed="true"]{background:var(--zhu)}
.verdicts button.idk[aria-pressed="true"]{background:var(--faint)}
"""

PAGE_JS = """
const AUDIT_V = __AUDIT_V__, DIS_V = __DIS_V__;
const BODY = `
<header class="top"><div class="top-in">
  <span class="brand">__TITLE__</span>
  <span class="save" id="save">本机</span>
  <span class="count" id="count">0 / 0</span>
</div><div class="bar"><i id="prog"></i></div></header>
<div class="wrap">
  <details class="intro" id="intro" open>
    <summary>怎么裁</summary>
    <p>每张卡是殿本某页的<b>一整列</b>，切成三段从右往左并排（右段是列的上端）。</p>
    <p><b>抽检卡</b>：下面那串字是不是这一列印着的字？要紧的是<b>字数</b>——
       字数对、只有个别字形不同（异体、〓）点「字数对·个别字不同」。</p>
    <p><b>甲乙卡</b>：两串字哪一串跟图上一致（看字数）。都不对就点「都不对」。</p>
    <p>裁决自动存回本页，看右上角小牌子；存不上就用「复制」把结果贴回对话。</p>
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
  const vs = r.kind === 'audit' ? AUDIT_V : DIS_V;
  const btn = ([k, t]) => `<button class="${k}" data-v="${k}" aria-pressed="${v===k}">${t}</button>`;
  const txt = r.kind === 'audit'
    ? `<p class="txt">${esc(r.text)}</p>`
    : `<p class="txt"><b>甲</b>${esc(r.A)}</p><p class="txt"><b>乙</b>${esc(r.B)}</p>`;
  return `<article class="card" data-id="${r.id}"${v ? ` data-v="${v}"` : ''}>
    <h3>${esc(r.label)}</h3>
    ${r.img ? `<img data-src="${r.img}" alt="">` : '<p class="txt">（无图）</p>'}
    ${txt}
    <div class="verdicts">${vs.map(btn).join('')}</div>
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
  return D.rows.filter(r => verdictOf(r.id))
    .map(r => JSON.stringify({id: r.id, verdict: verdictOf(r.id)})).join('\\n');
}
""".replace("__AUDIT_V__", json.dumps([[v, t] for v, t, _ in AUDIT_V], ensure_ascii=False)) \
   .replace("__DIS_V__", json.dumps([[v, t] for v, t, _ in DIS_V], ensure_ascii=False)) \
   .replace("__TITLE__", TITLE)


def main() -> None:
    sel = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    ws, out = Path(sys.argv[2]), Path(sys.argv[3])
    verdicts = {}
    if len(sys.argv) > 4:
        for ln in Path(sys.argv[4]).read_text(encoding="utf-8").splitlines():
            if ln.strip():
                d = json.loads(ln)
                verdicts[d["id"]] = d["verdict"]
    cards = build_cards(sel)
    # 甲乙卡排前面（量小、先裁）；抽检卡按 id 哈希打散，别按册页顺序
    cards.sort(key=lambda c: (c["kind"] != "disagree", hashlib.sha1(c["id"].encode()).hexdigest()))
    rows, imgs = [], {}
    for i, c in enumerate(cards):
        key = f"i{i}"
        img = _strip_img(ws, c["vol"], c["page"], c["col"])
        if img:
            imgs[key] = img
        row = {"id": c["id"], "kind": c["kind"], "label": f"{c['vol']} 第{c['page']}页 第{c['col']}列",
               "img": key if img else None}
        if c["kind"] == "audit":
            row["text"] = c["text"]
        else:
            row["A"], row["B"] = c["A"], c["B"]
        rows.append(row)
    html = render(TITLE, KEY, verdicts=verdicts, css=CSS, page_js=PAGE_JS, payload={"rows": rows, "imgs": imgs})
    out.write_text(html, encoding="utf-8")
    print(f"{out}  {len(html) / 1024:.0f} KB  {len(rows)} 卡（无图 {sum(1 for r in rows if not r['img'])}）")


if __name__ == "__main__":
    main()
