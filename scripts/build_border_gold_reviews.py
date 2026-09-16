# -*- coding: utf-8 -*-
"""Step1 的三个金标标注页（列探测 / 抬头 / 外框外延）。

素材由 `scripts/export_border_review_cards.py` 先备好（探测跑一遍出三种卡）。
本脚本只负责把卡拼成页，所以改文案、改裁决档不用重跑探测。

三页各自量什么：

| 页 | key | 判什么 | 为什么值得人裁 |
|---|---|---|---|
| 列探测 | `step1-cols-v1` | 界行是不是都落在字缝上 | 文档里记的**准确率封顶因素**：40 页里 13 页没切对，Step2/Step3 全部连坐 |
| 抬头 | `step1-head-v1` | 这页顶上有没有抬头 | 抬头框金标只有 6 页 18 例，`HR_*` 形态常数有过拟合风险 |
| 外框外延 | `step1-outer-v1` | 画的这条线在不在外条最外沿 | 上框金标口径不统一（外延6/中心3/内沿1），已证实 vol01/14 错了 17px |

出题上守的几条（细节见 `.claude/skills/review-artifact/`）：

- **抬头页不叠任何探测结果**。要量的是召回率，卡上印了机器的判断人就顺着点，
  测出来的是机器自己。外延页必须画线（判的就是那条线），但不写偏移量。
- **卡的顺序打散**（固定种子），别让人按页码顺序形成预期。
- **每页都留「拿不准」一档**。逼人二选一得到的是噪声；实测里这一档扎堆的地方
  往往正是上游有问题的地方。
- **id 冻在 `cards.jsonl` 里**，重出一版页面照旧读它，否则上一轮裁决对不上号。

跑法：
    python scripts/build_border_gold_reviews.py                 # 三页都出
    python scripts/build_border_gold_reviews.py --only cols
发布（`capabilities` 里的 `artifact` 是自存的开关，漏了裁决只存在浏览器本地）：
    Artifact(file_path=…, title=…, favicon="…", capabilities={"artifact": {}})
复审要重发到**同一个 URL**（传 `url=`），台账在 artifacts/README.md。
"""
from __future__ import annotations

import argparse
import base64
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / ".claude" / "skills" / "review-artifact" / "scripts"))

from review_shell import render  # noqa: E402

SRC = ROOT / "output" / "border_review"
OUT = ROOT / "artifacts"
SEED = 20260902

PAGES = {
    "cols": dict(
        title="界行切分裁决台", key="step1-cols-v1", ncol=2,
        favicon="📏",
        howto="红色虚线是算法探到的界行。判它们**是不是都落在字缝上**——"
              "有的缝没被切到、或者线压在字上，都算没切对。"
              "这是下游 Step2/Step3 的地基，一页切错整页连坐。",
        verdicts=[("ok", "都在缝上", "ok"), ("miss", "有缝漏切", "zhu"),
                  ("extra", "线压在字上", "zhu"), ("idk", "拿不准", "faint")],
        label=lambda c: f'{c["book"]} / {c["page"]}',
        note=lambda c: "",
    ),
    "head": dict(
        title="抬头有无裁决台", key="step1-head-v1", ncol=3,
        favicon="🔺",
        howto="这是每页**上版框**那一条横带的原图，<b>没有叠任何算法结果</b>。"
              "判「这页有没有抬头」——判据是<b>版框线本身有台阶</b>（框被顶上去一块），"
              "不是「有字比别的高」。故意不给算法的判断：要量的是漏检率，"
              "卡上印了机器的答案就测不出来了。",
        verdicts=[("yes", "有抬头", "ochre"), ("no", "没有", "ok"),
                  ("idk", "拿不准", "faint")],
        label=lambda c: f'{c["book"]} / {c["page"]}',
        note=lambda c: "",
    ),
    "outer": dict(
        title="外框外延裁决台", key="step1-outer-v1", ncol=3,
        favicon="📐",
        howto="红色虚线是算法量出来的**外框条最外沿**（外延）。判这条线的位置："
              "压在最外沿上=对；还在墨条里面=偏内；跑到墨条外面的白纸上=偏外。"
              "这页没印外框条（或被扫描裁掉）就点「没有外框」。"
              "确认过的线会直接成为金标值。",
        verdicts=[("ok", "在外沿上", "ok"), ("in", "偏内", "zhu"),
                  ("out", "偏外", "zhu"), ("none", "没有外框", "ochre"),
                  ("idk", "拿不准", "faint")],
        label=lambda c: f'{c["book"]} / {c["page"]}　{"上框" if c["side"]=="top" else "下框"}',
        note=lambda c: "",
    ),
}

CSS_BASE = """
.card{background:var(--surface); border:1px solid var(--rule);
  border-left:3px solid transparent; border-radius:3px; padding:11px 12px 12px;
  box-shadow:var(--shadow); margin-bottom:12px;}
.card h3{margin:0; font-family:var(--mono); font-size:14px; font-weight:500;
  color:var(--muted); letter-spacing:.02em;}
.card img{width:100%; background:var(--tile); border-radius:2px;
  display:block; margin:8px 0 0;}
.card.wide img{image-rendering:pixelated;}
.verdicts{display:grid; grid-template-columns:repeat(NCOL,1fr); gap:6px; margin-top:10px;}
.verdicts button{min-height:44px; border:1px solid var(--rule-hard); border-radius:3px;
  background:var(--surface); color:var(--ink); font-family:var(--sans);
  font-size:13px; font-weight:500; cursor:pointer;}
.verdicts button:active{background:var(--sunk)}
.verdicts button:focus-visible{outline:2px solid var(--indigo); outline-offset:2px;}
.verdicts button[aria-pressed="true"]{color:var(--on-solid); border-color:transparent;}
"""

PAGE_JS = """
const VERDICTS = __VERDICTS__;

const BODY = `
<header class="top"><div class="top-in">
  <span class="brand">__TITLE__</span>
  <span class="save" id="save">本机</span>
  <span class="count" id="count">0 / 0</span>
</div><div class="bar"><i id="prog"></i></div></header>
<div class="wrap">
  <details class="intro" id="intro" open>
    <summary>怎么裁</summary>
    <p>__HOWTO__</p>
    <p>一张卡一裁，点错再点一次取消。裁决自动存回本页，状态看右上角的小牌子；
       显示<code>仅存本机</code>就说明没存上，用「复制」把结果贴回对话。</p>
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

function card(r){
  const v = verdictOf(r.id);
  const btn = ([k, t]) => `<button class="${k}" data-v="${k}" aria-pressed="${v===k}">${t}</button>`;
  return `<article class="card wide" data-id="${r.id}"${v ? ` data-v="${v}"` : ''}>
    <h3>${esc(r.label)}</h3>
    <img data-src="${r.img}" alt="">
    <div class="verdicts">${VERDICTS.map(btn).join('')}</div>
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
"""


def build(kind: str, cards: list[dict], verdicts: dict) -> tuple[Path, int]:
    spec = PAGES[kind]
    rows, imgs = [], {}
    for c in cards:
        key = c["id"]
        imgs[key] = "data:image/jpeg;base64," + base64.b64encode(
            (SRC / "img" / c["img"]).read_bytes()).decode()
        rows.append(dict(id=c["id"], label=spec["label"](c), img=key))
    random.Random(SEED).shuffle(rows)          # 打散顺序，别让人按页码形成预期

    css = (CSS_BASE.replace("NCOL", str(spec["ncol"]))
           + "".join(f'.card[data-v="{v}"]{{border-left-color:var(--{c})}}\n'
                     for v, _, c in spec["verdicts"])
           + "".join(f'.verdicts button.{v}[aria-pressed="true"]{{background:var(--{c})}}\n'
                     for v, _, c in spec["verdicts"]))
    js = (PAGE_JS
          .replace("__VERDICTS__", json.dumps([[v, t] for v, t, _ in spec["verdicts"]],
                                              ensure_ascii=False))
          .replace("__TITLE__", spec["title"])
          .replace("__HOWTO__", spec["howto"]))
    html = render(spec["title"], spec["key"], verdicts=verdicts, css=css, page_js=js,
                  payload={"rows": rows, "imgs": imgs})
    out = OUT / f"border_gold_{kind}.html"
    out.write_text(html, encoding="utf-8")
    return out, len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", default="", help="只出某一页：cols / head / outer")
    ap.add_argument("--verdicts", default="", help="上一轮收回的裁决 JSONL，用来续裁")
    a = ap.parse_args()
    cards = [json.loads(x) for x in (SRC / "cards.jsonl").read_text(encoding="utf-8").splitlines() if x]
    prev = {}
    if a.verdicts:
        for line in Path(a.verdicts).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                prev[r["id"]] = r["verdict"]
    OUT.mkdir(parents=True, exist_ok=True)
    for kind in (["cols", "head", "outer"] if not a.only else [a.only]):
        sub = [c for c in cards if c["kind"] == kind]
        if not sub:
            print(f"{kind}: 没有卡，跳过")
            continue
        vs = {k: v for k, v in prev.items() if k.startswith(kind + ":")}
        out, n = build(kind, sub, vs)
        print(f"{PAGES[kind]['title']}: {n} 卡　{out.stat().st_size/1024/1024:.1f} MB　{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
