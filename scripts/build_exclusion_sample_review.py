# -*- coding: utf-8 -*-
"""排除名单收紧候选：按「当初为什么排」分类抽样，看这些图块到底有没有问题。

    PYTHONPATH=. python scripts/build_exclusion_sample_review.py --out artifacts/exclusion_sample_review.html

## 为什么出这一页

`config/crop_exclusions.jsonl` 现在 1982 条，其中 1565 条落在两册金标里，
来源是 `pipeline-suspect` / `gate` / `position` 三档启发式旗标。上游新的
`char-segmentation/instances` 人裁标第一次让这三档能算准确率：
pipeline-suspect **8.9%**、gate **0%**、position **0%**（人裁过的子集上）。
对级实测也显示把它们放回来，操作点几乎不动，可用对却从 36015 涨到 64326。

所以问题不是「要不要收紧」，是「**这三档里到底混着什么**」。这一页按
(来源, 旗标) 分类，每类抽 10 张，看图说话。

**卡上印了类别**——这一页故意违反「别把机器判断印在卡上」的纪律：这里要判的
不是单张图，是**整个类别值不值得排除**，不给类别就没法归因。代价是每类的
判读会互相带节奏，所以每类的数只当**这一类的定性**读，别拿去当总体缺陷率。
"""
from __future__ import annotations

import argparse
import base64
import json
import random
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / ".claude/skills/review-artifact/scripts"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from open_guji_cv.clustering.exclusions import load_exclusions  # noqa: E402
from review_shell import render  # noqa: E402

PIPE_REV = "502fa04d0c"
TITLE = "排除名单复核台"
KEY = "guji-exclusion-sample-v1"
THUMB = 168
GRAY_STEP = 16
PER_CAT = 10
SEED = 7

# 类别 → 一句话说明「当初为什么排」。顺序就是页面上的顺序。
CATS: list[tuple[str, str, str]] = [
    ("pipeline-suspect|boundary_ink", "墨压着格位边界",
     "切格时格位边界上有墨——怀疑把邻字的一笔带进来了，或者自己被切掉一笔。"),
    ("pipeline-suspect|wide_gap", "格内空隙偏大",
     "格子里的墨团之间空隙比常态大——怀疑一格里混了两个东西，或者缺了一块。"),
    ("pipeline-suspect|boundary_ink,wide_gap", "边界有墨 + 空隙偏大",
     "上面两条同时命中。"),
    ("pipeline-suspect|off_center", "重心偏出格心",
     "墨的重心离格心太远——怀疑格位整体错位。"),
    ("position|idx=0", "列首格（idx=0）",
     "位置规则：列首整格排除。当初的依据是列首容易把栏线/天头带进来。"),
    ("position|idx=19", "列尾格（idx=19）",
     "位置规则：列尾整格排除。"),
    ("position|idx=20", "列尾外一格（idx=20）",
     "位置规则：列尾再往外一格，最容易吃到下边框。"),
    ("gate|residue", "残余（gate 判）",
     "进库准入闸判定图块带残余。"),
    ("gate|frame_bar_bottom", "下边框条（gate 判）",
     "进库准入闸判定图块吃到了下边框。"),
    ("gate|truncated", "被截断（gate 判）",
     "进库准入闸判定图块被切断了。"),
]


def gray_root() -> Path:
    root = Path(tempfile.gettempdir()) / f"guji-output-{PIPE_REV}"
    if not (root / ".complete").exists():
        root.mkdir(parents=True, exist_ok=True)
        paths = " ".join(f"output/{b}/phase4_chars" for b in ("vol01", "vol02"))
        subprocess.run(f"git -C {REPO} archive {PIPE_REV} {paths} | tar -x -C {root}",
                       shell=True, check=True)
        (root / ".complete").touch()
    return root / "output"


def load_gray(iid: str, out: Path) -> np.ndarray | None:
    b, p, c, i = iid.split(":")
    f = out / b / "phase4_chars" / "patches" / p / f"{c}_{i}.png"
    return cv2.imread(str(f), cv2.IMREAD_GRAYSCALE) if f.exists() else None


def thumb(img: np.ndarray) -> str:
    h, w = img.shape
    s = THUMB / max(h, w)
    img = cv2.resize(img, (max(1, round(w * s)), max(1, round(h * s))),
                     interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    img = ((img.astype(np.uint16) // GRAY_STEP) * GRAY_STEP).clip(0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    assert ok
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


CSS = """
.sec{margin:20px 0 0}
.sec h2{margin:0 0 3px; font-family:var(--serif); font-size:16px; font-weight:700}
.sec .why{margin:0 0 2px; font-size:13px; color:var(--muted); line-height:1.6}
.sec .n{font-family:var(--mono); font-size:11.5px; color:var(--faint)}
.card{background:var(--surface); border:1px solid var(--rule);
  border-left:3px solid transparent; border-radius:3px; padding:10px 11px;
  box-shadow:var(--shadow); display:grid; grid-template-columns:auto 1fr; gap:11px;}
.card[data-v="bad"]{border-left-color:var(--zhu)}
.card[data-v="ok"] {border-left-color:var(--ok)}
.card[data-v="idk"]{border-left-color:var(--faint)}
.card img{width:120px; height:120px; object-fit:contain; background:var(--tile);
  border-radius:2px; image-rendering:pixelated;}
.meta{display:grid; align-content:start; gap:5px}
.gold{font-family:var(--serif); font-size:26px; font-weight:700; line-height:1}
.iid{font-family:var(--mono); font-size:11px; color:var(--faint); word-break:break-all}
.verdicts{display:grid; grid-template-columns:repeat(3,1fr); gap:6px; margin-top:auto;}
.verdicts button{min-height:42px; border:1px solid var(--rule-hard); border-radius:3px;
  background:var(--surface); color:var(--ink); font-family:var(--sans);
  font-size:13px; font-weight:500; cursor:pointer;}
.verdicts button:active{background:var(--sunk)}
.verdicts button:focus-visible{outline:2px solid var(--indigo); outline-offset:2px;}
.verdicts button[aria-pressed="true"]{color:var(--on-solid); border-color:transparent;}
.verdicts button.bad[aria-pressed="true"]{background:var(--zhu)}
.verdicts button.ok[aria-pressed="true"] {background:var(--ok)}
.verdicts button.idk[aria-pressed="true"]{background:var(--faint)}
.tally{font-family:var(--mono); font-size:11.5px; color:var(--muted); margin-top:6px}
"""

PAGE_JS = r"""
const BODY = `
<header class="top"><div class="top-in">
  <span class="brand">排除名单复核台</span>
  <span class="save" id="save">本机</span>
  <span class="count" id="count">0 / 0</span>
</div><div class="bar"><i id="prog"></i></div></header>
<div class="wrap">
  <details class="intro" id="intro" open>
    <summary>这一页在问什么</summary>
    <p>这些图块**现在都被排除在测试集和字形库之外**，理由是各种启发式旗标。
       上游新的人裁标显示这些理由多半站不住（pipeline-suspect 准确率 8.9%、
       gate 与 position 在人裁过的子集上是 0%），所以想把它们放回来。</p>
    <p>请按<b>类别</b>看：每类抽了 10 张，判的是「<b>这一张图块本身有没有毛病</b>」——
       缺笔、带边框线、混进邻字的笔画、根本不是完整的字，都算<b>有问题</b>；
       就是个正常的字就点<b>没问题</b>。不用每张都判，每类看几张有数了就行。</p>
    <div class="rubric">
      <div><b style="background:var(--zhu-soft);color:var(--zhu)">有问题</b>
           <span>该排除——图块本身坏了</span></div>
      <div><b style="background:var(--ok-soft);color:var(--ok)">没问题</b>
           <span>不该排除——正常字，白扔了</span></div>
      <div><b style="background:var(--sunk);color:var(--faint)">拿不准</b>
           <span>看不出来</span></div>
    </div>
  </details>
  <div class="ctrl">
    <div class="seg" id="filter">
      <button data-f="all" aria-pressed="true">全部</button>
      <button data-f="todo" aria-pressed="false">未裁</button>
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

const rowId = r => r.iid;

function one(r){
  const v = verdictOf(r.iid);
  const b = (k,t) => `<button class="${k}" data-v="${k}" aria-pressed="${v===k}">${t}</button>`;
  return `<article class="card" data-id="${r.iid}"${v?` data-v="${v}"`:''}>
    <img data-src="${r.iid}" alt="">
    <div class="meta">
      <div class="gold">${esc(r.char || '？')}</div>
      <div class="iid">${esc(r.iid)}</div>
      <div class="verdicts">${b('bad','有问题')}${b('ok','没问题')}${b('idk','拿不准')}</div>
    </div>
  </article>`;
}

/* 一节 = 一个类别：标题 + 为什么当初排它 + 这一节的裁决小计 */
function card(r){ return one(r); }
function visibleRows(){ return D.rows; }

function tallyOf(rows){
  const c = {bad:0, ok:0, idk:0};
  for (const r of rows){ const v = verdictOf(r.iid); if (v) c[v]++; }
  const n = c.bad + c.ok + c.idk;
  return n ? `本类已裁 ${n}/${rows.length}　有问题 ${c.bad}　没问题 ${c.ok}　拿不准 ${c.idk}`
           : `本类 ${rows.length} 张，未裁`;
}

let filter = 'all';
function draw2(){
  const el = document.getElementById('list');
  el.innerHTML = D.cats.map(c => {
    let rows = D.rows.filter(r => r.cat === c.key);
    if (filter !== 'all'){
      const done = filter === 'done';
      rows = rows.filter(r => !!verdictOf(r.iid) === done);
    }
    if (!rows.length) return '';
    return `<section class="sec">
      <h2>${esc(c.name)}</h2>
      <p class="why">${esc(c.why)}</p>
      <p class="n">全库这一类 ${c.total} 张，抽了 ${c.n} 张（权重 ${c.weight}）</p>
      <div class="tally">${tallyOf(D.rows.filter(r => r.cat === c.key))}</div>
      <div class="list" style="margin-top:8px">${rows.map(one).join('')}</div>
    </section>`;
  }).join('') || `<p class="empty">这一档里没有卡片了。</p>`;
  el.querySelectorAll('img[data-src]').forEach(i => io.observe(i));
  tally();
}
let afterVerdict = () => setTimeout(draw2, 60);
document.addEventListener('click', e => {
  const f = e.target.closest('#filter button'); if (!f) return;
  filter = f.dataset.f;
  [...f.parentElement.children].forEach(x => x.setAttribute('aria-pressed', String(x === f)));
  draw2();
});
setTimeout(draw2, 0);

function payload(){
  return D.rows.filter(r => verdictOf(r.iid)).map(r => JSON.stringify({
    instance_id: r.iid, verdict: verdictOf(r.iid), cat: r.cat,
    char: r.char, weight: r.weight
  })).join('\n');
}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="artifacts/exclusion_sample_review.html")
    ap.add_argument("--cards", default="artifacts/exclusion_sample_cards.jsonl")
    ap.add_argument("--dataset", default="../open-guji-dataset")
    a = ap.parse_args()

    ds = Path(a.dataset)
    meta: dict[str, dict] = {}
    for s in ("001-vol01-body", "002-vol02-body"):
        for r in json.loads((ds / f"char-clustering/samples/{s}/expected.json")
                            .read_text(encoding="utf-8"))["instances"]:
            meta[r["instance_id"]] = r

    rows = load_exclusions()
    pool: dict[str, list[str]] = defaultdict(list)
    for iid, r in rows.items():
        if iid not in meta or r["origin"] not in ("pipeline-suspect", "gate", "position"):
            continue
        key = r["origin"] + "|" + ",".join(sorted(r.get("evidence") or []))
        pool[key].append(iid)

    frozen = Path(a.cards)
    picks: dict[str, list[str]] = {}
    if frozen.exists():                      # id 冻住：重出一版页，裁决还对得上
        for line in frozen.read_text(encoding="utf-8").splitlines():
            if line.strip():
                x = json.loads(line)
                picks.setdefault(x["cat"], []).append(x["instance_id"])
    rng = random.Random(SEED)
    out = Path(gray_root())
    cards, cats, imgs = [], [], {}
    for key, name, why in CATS:
        ids = sorted(pool.get(key, []))
        if not ids:
            continue
        sel = picks.get(key) or rng.sample(ids, min(PER_CAT, len(ids)))
        sel = [i for i in sel if i in meta]
        w = round(len(ids) / max(1, len(sel)), 1)
        cats.append({"key": key, "name": name, "why": why,
                     "total": len(ids), "n": len(sel), "weight": w})
        for iid in sel:
            g = load_gray(iid, out)
            if g is None:
                continue
            imgs[iid] = thumb(g)
            cards.append({"iid": iid, "cat": key, "char": meta[iid].get("char"),
                          "weight": w})

    frozen.parent.mkdir(parents=True, exist_ok=True)
    frozen.write_text("\n".join(json.dumps({"instance_id": c["iid"], "cat": c["cat"]},
                                           ensure_ascii=False) for c in cards) + "\n",
                      encoding="utf-8")

    html = render(TITLE, KEY, verdicts={}, css=CSS, page_js=PAGE_JS,
                  payload={"rows": cards, "cats": cats, "imgs": imgs})
    Path(a.out).write_text(html, encoding="utf-8")
    print(f"{a.out}  {len(html)/1024/1024:.2f} MB  {len(cards)} 卡 / {len(cats)} 类")
    for c in cats:
        print(f"  {c['name']:<20}抽 {c['n']:>2} / 全库 {c['total']:>5}（权重 {c['weight']}）")


if __name__ == "__main__":
    main()
