# -*- coding: utf-8 -*-
"""结构金标裁决台（任务卡 2026-09-22 T3 / 设计稿 M2）：300 条真刻例，人裁「IDS 拆法与图上写法符不符」。

    PYTHONIOENCODING=utf-8 python scripts/build_struct_gold_review.py [--out artifacts/struct_gold_review.html]

## 为什么要这 300 条

Step A / A′ 的结构头在 oov_bench 上顶到 ~90 就不动了（设计稿 §13 ④），混淆前几名是
⿱→⿰、⿱→⿸、⿹→⿱、⿳→⿱——这几对本身就是 IDS 表的**口径分歧**。不先分清「标签错」还是
「模型错」，95 那条线没法谈。金标只记人裁结果，不记坐标。

## 抽样（冻结在 artifacts/struct_gold_cards.jsonl，重建页面照旧读）

| 层 | 来源 | 条数 | 抽法 |
|---|---|---|---|
| oov | oov_bench 合体（306） | 200 | 按 src（glyphdb/user）比例分层随机 |
| unseen | glyph_bench unseen 合体（1,325） | 70 | 随机 |
| single | glyph_bench seen_test 独体（47） | 30 | 随机 |

每条带 `stratum` / `stratum_weight`（= 层总数 / 抽样数），事后按权重估总体。

## 卡片怎么读

上面是刻本字块（原 64² 放大，像素边缘故意留着），下面是这个字在 IDS 表里的拆法：
顶层算符 + 各槽位的部件。**卡上不印任何模型预测**——量的是「人怎么看」。裁决四档：
「拆法对」（结构与槽位都符合图上写法）/「结构其实是 …」（点下面一排算符里的那个）/
「结构对、部件写法不同」（异体/刻工写法，槽里的部件不是那个）/「拿不准」。
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

TITLE = "结构金标裁决台"
KEY = "struct-gold-v1"
CARDS = REPO / "artifacts" / "struct_gold_cards.jsonl"
SEED = 20260922
SLOT_ZH = {"L": "左", "R": "右", "T": "上", "B": "下", "M": "中", "O": "外", "I": "内", "A": "甲", "X": "体"}
# 结构符很多手机字体没有（渲成方框），所以每个都配中文名，按钮与拆法行都印名字
OPS = [["⿰", "左右"], ["⿱", "上下"], ["⿲", "左中右"], ["⿳", "上中下"], ["⿴", "全包围"], ["⿵", "上三包"],
       ["⿶", "下三包"], ["⿷", "左三包"], ["⿸", "左上包"], ["⿹", "右上包"], ["⿺", "左下包"], ["⿻", "重叠"],
       ["独体", "独体"]]
OP_ZH = dict(OPS)


def thumb(img01: np.ndarray, size: int = 128) -> str:
    g = (255 - img01.astype(np.uint8) * 255)
    g = cv2.resize(g, (size, size), interpolation=cv2.INTER_NEAREST)
    ok, buf = cv2.imencode(".png", g, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    assert ok
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def sample_cards() -> list[dict]:
    from open_guji_cv.clustering.ids_struct import SINGLE, structure_of, load_table
    from open_guji_cv.clustering.normalize import normalize_patch
    rng = random.Random(SEED)
    tab = load_table()

    def label(ch: str) -> dict:
        st = structure_of(ch)
        e = tab.get(ch)
        ids = e.primary if e else ""
        if st.top == SINGLE:
            return {"top": "独体", "top_zh": "独体", "slots": [], "ids": ids}
        slots = [[SLOT_ZH.get(k, k), "".join(v)] for k, v in st.top_slots().items()]
        return {"top": st.top, "top_zh": OP_ZH.get(st.top, st.top), "slots": slots, "ids": ids}

    oov = [json.loads(l) for l in (REPO / "cache/oov_bench/items.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    gb = [json.loads(l) for l in (REPO / "cache/glyph_bench/items.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    pools: dict[str, list[dict]] = {}
    pools["oov"] = [{"id": f"oov:{it['id']}", "char": it["char"], "src": it["src"],
                     "png": str(REPO / "cache/oov_bench" / it["png"].replace("\\", "/")), "norm": False}
                    for it in oov if structure_of(it["char"]).top != SINGLE]
    pools["unseen"] = [{"id": f"gb:{it['id']}", "char": it["char"], "src": "unseen",
                        "png": str(REPO / it["png"].replace("\\", "/")), "norm": True}
                       for it in gb if it["split"] == "unseen" and structure_of(it["char"]).top != SINGLE]
    pools["single"] = [{"id": f"gb:{it['id']}", "char": it["char"], "src": "seen_test",
                        "png": str(REPO / it["png"].replace("\\", "/")), "norm": True}
                       for it in gb if it["split"] == "seen_test" and structure_of(it["char"]).top == SINGLE]
    want = {"oov": 200, "unseen": 70, "single": 30}
    cards: list[dict] = []
    for stratum, n in want.items():
        pool = pools[stratum]
        if stratum == "oov":
            by = {}
            for r in pool:
                by.setdefault(r["src"], []).append(r)
            pick = []
            for src, lst in by.items():
                k = round(n * len(lst) / len(pool))
                pick += rng.sample(lst, min(k, len(lst)))
            pick = pick[:n]
        else:
            pick = rng.sample(pool, min(n, len(pool)))
        for r in pick:
            cards.append({**r, "stratum": stratum, "stratum_weight": round(len(pool) / len(pick), 3), **label(r["char"])})
    rng.shuffle(cards)     # 打散：别让人连着裁同一层
    return cards


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "artifacts/struct_gold_review.html"))
    ap.add_argument("--seed-verdicts", default=None, help="上一轮收回的 verdicts.jsonl，续裁")
    ap.add_argument("--residual", default=None,
                    help="scripts/struct_gold_residual.py 的输出：只出「模型与表全部拆法都不同、字种没裁过」的卡，每字种一张")
    a = ap.parse_args()
    from _review_shell import render  # noqa: E402
    from open_guji_cv.clustering.normalize import normalize_patch

    if CARDS.exists():
        cards = [json.loads(l) for l in CARDS.read_text(encoding="utf-8").splitlines() if l.strip()]
        for c in cards:                       # 展示字段可以补，id 与抽样不动
            c.setdefault("top_zh", OP_ZH.get(c["top"], c["top"]))
        print(f"卡片冻结在 {CARDS}：{len(cards)} 张（id 不变）")
    else:
        cards = sample_cards()
        CARDS.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cards), encoding="utf-8")
        print(f"抽样 {len(cards)} 张 → {CARDS}")
    residual_also: dict[str, list[str]] = {}
    if a.residual:
        res = json.loads(Path(a.residual).read_text(encoding="utf-8"))
        keep = set(res["residual_ids"]); residual_also = res.get("residual_also", {})
        cards = [c for c in cards if c["id"] in keep]
        print(f"残差模式：{len(cards)} 张（模型与表全部拆法都不同、字种未裁）")
    imgs, rows = {}, []
    for c in cards:
        im = cv2.imread(c["png"], cv2.IMREAD_GRAYSCALE)
        if im is None:
            continue
        g = normalize_patch(im).astype(np.uint8) if c["norm"] else (im > 127).astype(np.uint8)
        imgs["g:" + c["id"]] = thumb(g)
        r = {k: v for k, v in c.items() if k not in ("png", "norm")}
        if c["id"] in residual_also:
            r["also"] = residual_also[c["id"]]          # 同字种的其他卡，裁决随这张
        rows.append(r)
    print(Counter(r["stratum"] for r in rows), Counter(r["top"] for r in rows).most_common(6))

    verdicts = {}
    if a.seed_verdicts and Path(a.seed_verdicts).exists():
        for line in Path(a.seed_verdicts).read_text(encoding="utf-8").splitlines():
            if line.strip():
                x = json.loads(line); verdicts[x["id"]] = {"v": x["verdict"], "t": x.get("t", 0)}

    css = """
.card{background:var(--surface); border:1px solid var(--rule); border-left:3px solid transparent;
  border-radius:3px; padding:12px 13px; box-shadow:var(--shadow);}
.card[data-v="ok"]{border-left-color:var(--ok)} .card[data-v="slot"]{border-left-color:var(--ochre)}
.card[data-v="idk"]{border-left-color:var(--faint)} .card[data-v^="struct:"]{border-left-color:var(--zhu)}
.glyph{display:flex; gap:14px; align-items:flex-start;}
.glyph img{width:128px; height:128px; image-rendering:pixelated; background:#fff; border:1px solid var(--rule); border-radius:2px; flex:none;}
.lab{font-family:var(--serif);}
.lab .ch{font-size:34px; line-height:1.1;}
.lab .ids{font-size:15px; margin-top:4px; word-break:break-all;}
.lab .st{font-size:16px; margin-top:6px;}
.lab .st b{font-size:22px; margin-right:6px;}
.lab .meta{font-size:11px; color:var(--muted); margin-top:6px;}
.verdicts{display:grid; grid-template-columns:repeat(3,1fr); gap:6px; margin-top:10px;}
.verdicts button{min-height:44px; border:1px solid var(--rule-hard); border-radius:3px; background:var(--surface);
  color:var(--ink); font-family:var(--sans); font-size:13px; font-weight:500; cursor:pointer;}
.verdicts button:active{background:var(--sunk)}
.verdicts button[aria-pressed="true"]{color:var(--on-solid); border-color:transparent;}
.verdicts button.ok[aria-pressed="true"]{background:var(--ok)}
.verdicts button.slot[aria-pressed="true"]{background:var(--ochre)}
.verdicts button.idk[aria-pressed="true"]{background:var(--faint)}
.verdicts button.st[aria-pressed="true"]{background:var(--zhu)}
.ops{display:grid; grid-template-columns:repeat(4,1fr); gap:5px; margin-top:8px;}
.ops .cap{grid-column:1 / -1; font-size:12px; color:var(--muted); margin-top:4px;}
.ops button{min-height:40px; font-size:16px; font-family:var(--serif); line-height:1.1;}
.ops button small{display:block; font-size:11px; font-family:var(--sans); font-weight:400;}
"""
    page_js = """
const BODY = `
<header class="top"><div class="top-in">
  <span class="brand">__TITLE__</span>
  <span class="save" id="save">本机</span>
  <span class="count" id="count">0 / 0</span>
</div><div class="bar"><i id="prog"></i></div></header>
<div class="wrap">
  <details class="intro" id="intro" open>
    <summary>怎么裁</summary>
    __RESIDUAL_NOTE__<p>上面是刻本字块，下面是 IDS 表给这个字的拆法（顶层结构 + 各槽位部件）。
       问的是：<b>按图上刻的写法，这个拆法对不对？</b></p>
    <p>「拆法对」= 结构与槽位都符合；结构不对就在下面一排里点它<b>实际的</b>结构；
       「部件写法不同」= 结构对，但某个槽里刻的不是表里那个部件（异体 / 刻工写法）；
       拿不准就点拿不准，别硬猜。裁决自动存回本页；存不上会显示<code>仅存本机</code>，那就用「复制」贴回对话。</p>
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
const OPS = __OPS__;
const rowId = r => r.id;
function card(r){
  const v = verdictOf(r.id);
  const b = (k, cls, t) => `<button class="${cls}" data-v="${k}" aria-pressed="${v===k}">${t}</button>`;
  const slots = r.slots.map(([n, c]) => `${n}:${esc(c)}`).join('　');
  const ops = OPS.filter(([o]) => o !== r.top).map(([o, zh]) => b('struct:' + o, 'st', `${o} <small>${zh}</small>`)).join('');
  return `<article class="card" data-id="${r.id}"${v ? ` data-v="${v}"` : ''}>
    <div class="glyph"><img data-src="g:${r.id}" alt="">
      <div class="lab"><div class="ch">${esc(r.char)}</div>
        <div class="ids">${esc(r.ids || '（表里没有拆法）')}</div>
        <div class="st"><b>${esc(r.top)}</b>${esc(r.top_zh || '')}　${slots}</div>
        <div class="meta">${esc(r.stratum)} · ${esc(r.src)} · ${esc(r.id)}</div></div></div>
    <div class="verdicts">${b('ok','ok','拆法对')}${b('slot','slot','结构对、部件写法不同')}${b('idk','idk','拿不准')}</div>
    <div class="verdicts ops"><span class="cap">结构其实是：</span>${ops}</div>
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
    .map(r => JSON.stringify({id: r.id, char: r.char, stratum: r.stratum, top: r.top, verdict: verdictOf(r.id)})).join('\\n');
}
""".replace("__TITLE__", TITLE).replace("__OPS__", json.dumps(OPS, ensure_ascii=False)).replace(
        "__RESIDUAL_NOTE__",
        ("<p><b>只剩这几张。</b>300 张里模型和 IDS 表说法一致的（含表的备选拆法）不用人看，"
         "已裁过的字种也不再出；这里每张都是<b>模型和表的每一种拆法都不一样</b>的字，一个字种一张，"
         "同字的其他图跟着算。卡上仍不印模型说法，照图裁。</p>") if a.residual else "")
    html = render(TITLE, KEY, verdicts=verdicts, css=css, page_js=page_js, payload={"rows": rows, "imgs": imgs})
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"{out}  {len(html)/1024:.0f} KB  {len(rows)} 卡")


if __name__ == "__main__":
    main()
