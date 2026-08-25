# -*- coding: utf-8 -*-
"""形近误判裁决台：把「异字邻居压过同字邻居」的排序倒挂挖出来做成审查页。

    PYTHONPATH=. python scripts/eval_match_pairs.py \
        ../open-guji-dataset/glyph-match/pairs --dump /tmp/pairs.npz
    PYTHONPATH=. python scripts/build_match_inversion_review.py \
        --dump /tmp/pairs.npz --out artifacts/match_inversion_review.html

glyph-match/triplets 的 hard 子集是**人裁**出来的（README：「用户亲眼裁定
本例标签没错」才收），所以扩集的瓶颈从来不是挖不到候选，是没人过目。本脚本
挖的候选是 pairs 集里最尖锐的一种失败形态——

  对同一个实例 x，它打分最高的**同字**邻居 s，和打分最高的**异字**邻居 o，
  如果 cov(x,o) > cov(x,s)，判据在这个实例上就是**排反了**。

这类例子有三种归宿，页内四个裁决键一一对应：
  可入集   标签没错、判据确实排反了 → 进 triplets hard
  标注有误 金标本身错了（切歪、串行、字头认错）→ 回流给标注层，别进集
  异体字   两个「异字」其实是同一个字的异体 → 归 P0 异体字关系层
  拿不准   看不出来 → 不进集，也不算标注问题

裁决经页内「复制裁决」回流（JSONL）。图块用**原始灰度**（未归一化）——
判「这到底是不是那个字」得看原图，二值化 64×64 已经丢掉判断依据了。
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

PIPE_REV = "502fa04d0c"      # 出这批 patch 的管线版本（与 pairs 集同源）
THUMB = 128                  # 缩略图边长（手机上按 ~105 CSS px 显示）
GRAY_STEP = 16               # 灰阶量化步长：16 级灰 + PNG，比同尺寸 JPEG 还小 45%，
                             # 且线条不带振铃——细笔画是这页要看的东西，不能让编码吃掉


# ---------------------------------------------------------------- 候选挖掘
def mine_inversions(dump: Path) -> list[dict]:
    z = np.load(dump, allow_pickle=True)
    pairs, cov = list(z["pairs"]), z["cov"]
    best_same: dict[str, tuple[float, str]] = defaultdict(lambda: (-1.0, ""))
    best_diff: dict[str, tuple[float, str]] = defaultdict(lambda: (-1.0, ""))
    for k, p in enumerate(pairs):
        tgt = best_same if p["label"] == "same" else best_diff
        for x, y in ((p["a"], p["b"]), (p["b"], p["a"])):
            if cov[k] > tgt[x][0]:
                tgt[x] = (float(cov[k]), y)
    rows = []
    for x in sorted(set(best_same) & set(best_diff)):
        cs, s = best_same[x]
        co, o = best_diff[x]
        if co > cs:
            rows.append({"anchor": x, "same": s, "other": o,
                         "cov_same": round(cs, 4), "cov_other": round(co, 4),
                         "margin": round(cs - co, 4)})
    return rows


# ---------------------------------------------------------------- 原始灰度
def gray_sources() -> Path:
    """把出这批 patch 的管线输出从 git 里取回来（只取一次，缓存在 /tmp）。"""
    root = Path(tempfile.gettempdir()) / f"guji-output-{PIPE_REV}"
    if not (root / ".complete").exists():
        root.mkdir(parents=True, exist_ok=True)
        paths = " ".join(f"output/{b}/phase4_chars" for b in ("vol01", "vol02"))
        subprocess.run(f"git -C {REPO} archive {PIPE_REV} {paths} | tar -x -C {root}",
                       shell=True, check=True)
        (root / ".complete").touch()
    return root / "output"


def load_gray(iid: str, out: Path) -> np.ndarray | None:
    book, page, col, idx = iid.split(":")
    for p in (out / book / "phase4_chars" / "patches" / page / f"{col}_{idx}.png",
              REPO / "glyph_store" / "patches" / (iid.replace(":", "_") + ".png")):
        if p.exists():
            img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                return img
    return None


def thumb(img: np.ndarray) -> str:
    h, w = img.shape
    s = THUMB / max(h, w)
    interp = cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC
    img = cv2.resize(img, (max(1, round(w * s)), max(1, round(h * s))),
                     interpolation=interp)
    img = ((img.astype(np.uint16) // GRAY_STEP) * GRAY_STEP).clip(0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    assert ok
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


# ---------------------------------------------------------------- 组装
def build(dataset: Path, dump: Path) -> dict:
    data = json.loads((dataset / "expected.json").read_text(encoding="utf-8"))
    meta = {r["instance_id"]: r for r in data["instances"]}
    out = gray_sources()
    imgs: dict[str, str] = {}
    rows = []
    for i, r in enumerate(mine_inversions(dump)):
        iids = (r["anchor"], r["same"], r["other"])
        grays = [load_gray(x, out) for x in iids]
        if any(g is None for g in grays):
            print(f"  跳过 {r['anchor']}：找不到原图", flush=True)
            continue
        for x, g in zip(iids, grays):
            imgs.setdefault(x, thumb(g))
        a = meta[r["anchor"]]
        rows.append({**r, "id": f"T{i:03d}", "char": a["char"],
                     "same_char": meta[r["same"]]["char"],
                     "other_char": meta[r["other"]]["char"],
                     "book": a["book"], "tier": a["tier"],
                     "ink": a["ink_bucket"]})
    return {"imgs": imgs, "rows": rows,
            "pipeline_version": data.get("pipeline_version", PIPE_REV)}


HTML_HEAD = """<title>形近误判裁决台</title>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Noto+Serif+SC:wght@500;700&display=swap">
"""


def render(payload: dict, css: str, js: str) -> str:
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return (HTML_HEAD + "<style>\n" + css + "\n</style>\n"
            + BODY + '\n<script type="application/json" id="data">'
            + blob.replace("</", "<\\/") + "</script>\n<script>\n" + js + "\n</script>\n")


CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  color-scheme:light dark;
  --ground:#EBE8DF; --surface:#F8F6F1; --sunk:#E3DFD3; --tile:#DBD6C6;
  --ink:#1C1B16; --muted:#6B6659; --faint:#948E7E;
  --rule:#D6D1C3; --rule-hard:#BCB5A2;
  --indigo:#2C4C76; --indigo-soft:#DEE6F1;
  --zhu:#A8342A; --zhu-soft:#F4E2DE;
  --ok:#39684A; --ok-soft:#DFEBE2;
  --ochre:#856418; --ochre-soft:#F0E8D2;
  --on-solid:#FBFAF6;
  --shadow:0 1px 0 rgba(28,27,22,.04),0 2px 10px rgba(28,27,22,.055);
  --sans:"Archivo","Noto Sans SC",system-ui,-apple-system,sans-serif;
  --serif:"Noto Serif SC",Songti SC,SimSun,serif;
  --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,monospace;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --ground:#161612; --surface:#20201A; --sunk:#2A2923; --tile:#B7B2A3;
    --ink:#E9E5D9; --muted:#9A9486; --faint:#7A7568;
    --rule:#32312A; --rule-hard:#4A483E;
    --indigo:#8FB3DE; --indigo-soft:#22303F;
    --zhu:#E28C80; --zhu-soft:#3A2521;
    --ok:#84BA93; --ok-soft:#1E2C23;
    --ochre:#CBA652; --ochre-soft:#302819;
    --on-solid:#14140F;
    --shadow:0 1px 0 rgba(0,0,0,.3),0 2px 10px rgba(0,0,0,.28);
  }
}
:root[data-theme="dark"]{
  --ground:#161612; --surface:#20201A; --sunk:#2A2923; --tile:#B7B2A3;
  --ink:#E9E5D9; --muted:#9A9486; --faint:#7A7568;
  --rule:#32312A; --rule-hard:#4A483E;
  --indigo:#8FB3DE; --indigo-soft:#22303F;
  --zhu:#E28C80; --zhu-soft:#3A2521;
  --ok:#84BA93; --ok-soft:#1E2C23;
  --ochre:#CBA652; --ochre-soft:#302819;
  --on-solid:#14140F;
  --shadow:0 1px 0 rgba(0,0,0,.3),0 2px 10px rgba(0,0,0,.28);
}
body{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:var(--sans); font-size:15px; line-height:1.55;
  -webkit-text-size-adjust:100%;
}
.wrap{max-width:34rem; margin:0 auto; padding:0 14px 96px;}

/* ---- 顶栏 ---- */
.top{
  position:sticky; top:0; z-index:20; background:var(--ground);
  background:color-mix(in srgb,var(--ground) 88%,transparent);
  backdrop-filter:blur(10px) saturate(1.2); border-bottom:1px solid var(--rule);
}
.top-in{max-width:34rem; margin:0 auto; padding:9px 14px 0;
  display:flex; align-items:baseline; gap:10px;}
.brand{font-family:var(--serif); font-weight:700; font-size:16px; letter-spacing:.02em;}
.count{margin-left:auto; font-family:var(--mono); font-size:12px; color:var(--muted);
  font-variant-numeric:tabular-nums; white-space:nowrap;}
.bar{height:3px; background:var(--sunk); margin-top:8px;}
.bar i{display:block; height:100%; background:var(--indigo); width:0;
  transition:width .25s ease;}

/* ---- 说明 ---- */
.intro{margin:18px 0 0; padding:14px 15px; background:var(--surface);
  border:1px solid var(--rule); border-radius:3px; box-shadow:var(--shadow);}
.intro summary{cursor:pointer; font-weight:600; font-size:14px; letter-spacing:.01em;}
.intro summary::marker{color:var(--faint)}
.intro p{margin:10px 0 0; font-size:13.5px; color:var(--muted); line-height:1.65;}
.intro code{font-family:var(--mono); font-size:12px; color:var(--ink);
  background:var(--sunk); padding:1px 4px; border-radius:2px;}
.rubric{margin:12px 0 0; padding:0; display:grid; gap:7px;}
.rubric div{display:grid; grid-template-columns:auto 1fr; gap:9px; align-items:baseline;
  font-size:13px; color:var(--muted);}
.rubric b{font-weight:600; font-size:12.5px; padding:1px 6px; border-radius:2px;
  white-space:nowrap;}
.k-keep b{color:var(--ok); background:var(--ok-soft)}
.k-bad  b{color:var(--zhu); background:var(--zhu-soft)}
.k-var  b{color:var(--ochre); background:var(--ochre-soft)}
.k-idk  b{color:var(--muted); background:var(--sunk)}

/* ---- 控制条 ---- */
.ctrl{display:flex; gap:8px; margin:14px 0 4px; align-items:center;}
.seg{display:flex; background:var(--sunk); border-radius:3px; padding:2px; flex:1;}
.seg button{flex:1; min-height:36px; border:0; background:none; color:var(--muted);
  font-family:var(--sans); font-size:13px; font-weight:500; border-radius:2px;
  cursor:pointer;}
.seg button[aria-pressed="true"]{background:var(--surface); color:var(--ink);
  box-shadow:var(--shadow);}
.ghost{min-height:38px; padding:0 13px; border:1px solid var(--rule-hard);
  background:var(--surface); color:var(--ink); border-radius:3px; cursor:pointer;
  font-family:var(--sans); font-size:13px; font-weight:500; white-space:nowrap;}
.ghost:active{background:var(--sunk)}

/* ---- 卡片 ---- */
.list{display:grid; gap:12px; margin-top:12px;}
.card{background:var(--surface); border:1px solid var(--rule); border-radius:3px;
  box-shadow:var(--shadow); padding:12px 12px 11px; border-left:3px solid var(--rule-hard);}
.card[data-v="keep"]{border-left-color:var(--ok)}
.card[data-v="bad"] {border-left-color:var(--zhu)}
.card[data-v="var"] {border-left-color:var(--ochre)}
.card[data-v="idk"] {border-left-color:var(--faint)}
.ch{display:flex; align-items:center; gap:8px; margin-bottom:10px;}
.pair{font-family:var(--serif); font-weight:700; font-size:20px; line-height:1;
  display:flex; align-items:center; gap:7px;}
.pair .vs{font-family:var(--sans); font-size:12px; color:var(--faint); font-weight:400;}
.pair .w{color:var(--zhu)}
.tags{margin-left:auto; display:flex; gap:5px; align-items:center;}
.tag{font-family:var(--mono); font-size:10.5px; letter-spacing:.02em; color:var(--muted);
  border:1px solid var(--rule); border-radius:2px; padding:1px 5px; white-space:nowrap;}
.tag.deg{color:var(--ochre); border-color:var(--ochre)}
.cid{font-family:var(--mono); font-size:10.5px; color:var(--faint);}

.strip{display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px;}
.pane{margin:0; display:grid; gap:5px; justify-items:center;}
.pane .tile{width:100%; aspect-ratio:1; background:var(--tile);
  border:1px solid var(--rule); border-radius:2px; display:grid; place-items:center;
  overflow:hidden; position:relative;}
.pane.anchor .tile{border-color:var(--indigo); box-shadow:0 0 0 1px var(--indigo) inset;}
.pane.other .tile::after{content:""; position:absolute; inset:0 0 auto 0; height:3px;
  background:var(--zhu);}
.tile img{width:100%; height:100%; object-fit:contain; display:block;}
.role{font-size:10.5px; letter-spacing:.04em; color:var(--faint); line-height:1.2;}
.pane.anchor .role{color:var(--indigo); font-weight:600;}
.pane.other .role{color:var(--zhu); font-weight:600;}
.glyph{font-family:var(--serif); font-weight:500; font-size:17px; line-height:1;}

/* ---- 分数轴 ---- */
.axis{margin:11px 0 2px;}
.track{position:relative; height:22px;}
.track .rail{position:absolute; left:0; right:0; top:9px; height:4px;
  background:var(--sunk); border-radius:2px;}
.track .span{position:absolute; top:9px; height:4px; background:var(--rule-hard);
  border-radius:2px;}
.track .brk{position:absolute; top:4px; width:1px; height:14px; background:var(--rule-hard);}
.track .gate{position:absolute; top:2px; width:1px; height:18px; background:var(--ink);
  opacity:.45;}
.track .pt{position:absolute; border-radius:50%; border:2px solid var(--surface);}
/* 同字点画大、异字点画小叠在上面——两分相等时（差 0.0000）也能看出是两个点 */
.track .pt.s{top:3px; width:16px; height:16px; margin-left:-8px; background:var(--indigo)}
.track .pt.o{top:6px; width:10px; height:10px; margin-left:-5px; background:var(--zhu)}
.nums{display:flex; gap:12px; font-family:var(--mono); font-size:11.5px;
  font-variant-numeric:tabular-nums; color:var(--muted); margin-top:1px;}
.nums b{font-weight:500}
.nums .s b{color:var(--indigo)} .nums .o b{color:var(--zhu)}
.nums .m{margin-left:auto}

/* ---- 裁决 ---- */
.verdicts{display:grid; grid-template-columns:repeat(4,1fr); gap:6px; margin-top:10px;}
.verdicts button{min-height:44px; border:1px solid var(--rule-hard); border-radius:3px;
  background:var(--surface); color:var(--muted); cursor:pointer;
  font-family:var(--sans); font-size:13px; font-weight:500; padding:0 2px;
  letter-spacing:.01em;}
.verdicts button:active{background:var(--sunk)}
.verdicts button:focus-visible{outline:2px solid var(--indigo); outline-offset:2px;}
.verdicts button[aria-pressed="true"]{color:var(--on-solid); border-color:transparent;}
.verdicts button.keep[aria-pressed="true"]{background:var(--ok)}
.verdicts button.bad[aria-pressed="true"] {background:var(--zhu)}
.verdicts button.var[aria-pressed="true"] {background:var(--ochre)}
.verdicts button.idk[aria-pressed="true"] {background:var(--faint)}

.empty{padding:34px 10px; text-align:center; color:var(--faint); font-size:13.5px;}

/* ---- 复制浮层 ---- */
.sheet{position:fixed; inset:0; z-index:40; background:rgba(20,19,15,.5);
  display:grid; place-items:end center; padding:0;}
.sheet[hidden]{display:none}
.sheet-in{width:100%; max-width:34rem; background:var(--surface); border-radius:6px 6px 0 0;
  padding:14px 14px calc(14px + env(safe-area-inset-bottom)); display:grid; gap:10px;
  max-height:82vh;}
.sheet h2{margin:0; font-size:14px; font-weight:600;}
.sheet p{margin:0; font-size:12.5px; color:var(--muted)}
.sheet textarea{width:100%; height:38vh; resize:none; font-family:var(--mono);
  font-size:11px; line-height:1.5; padding:9px; color:var(--ink);
  background:var(--ground); border:1px solid var(--rule); border-radius:3px;}
.sheet .row{display:flex; gap:8px}
.sheet .row .ghost{flex:1; min-height:44px}

@media (prefers-reduced-motion:reduce){*{transition:none!important; animation:none!important}}
@media (min-width:600px){ .verdicts button{font-size:13.5px} }
"""

BODY = """
<header class="top">
  <div class="top-in">
    <span class="brand">形近误判裁决台</span>
    <span class="count" id="count">—</span>
  </div>
  <div class="bar"><i id="prog"></i></div>
</header>
<main class="wrap">
  <details class="intro" id="intro" open>
    <summary>怎么裁</summary>
    <p>每张卡是一个<b>排序倒挂</b>：中间是待判字块，左边是它打分最高的<b>同字</b>邻居，
       右边是打分最高的<b>异字</b>邻居——而右边的分数<b>压过了</b>左边。判据在这个实例上排反了。</p>
    <p>要裁的不是「哪个更像」，是<b>这一例的金标有没有错</b>。裁完点顶部的
       <code>复制裁决</code> 带回来。</p>
    <div class="rubric">
      <div class="k-keep"><b>可入集</b><span>标签没错，判据确实排反了——收进 hard 子集</span></div>
      <div class="k-bad"><b>标注有误</b><span>金标本身错了（切歪、串行、字头认错）——回流标注层</span></div>
      <div class="k-var"><b>异体字</b><span>两个字其实是同一个字的异体——归异体字关系层</span></div>
      <div class="k-idk"><b>拿不准</b><span>看不出来，两边都不收</span></div>
    </div>
  </details>
  <div class="ctrl">
    <div class="seg" id="filter" role="group" aria-label="筛选">
      <button data-f="all" aria-pressed="true">全部</button>
      <button data-f="todo" aria-pressed="false">未裁</button>
      <button data-f="done" aria-pressed="false">已裁</button>
    </div>
    <button class="ghost" id="sort" aria-label="切换排序">势均优先</button>
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
</div>
"""

JS = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const KEY = 'guji-inversion-verdicts-v1';
const V = {keep:'可入集', bad:'标注有误', var:'异体字', idk:'拿不准'};
const load = () => { try { return JSON.parse(localStorage.getItem(KEY)||'{}'); }
                     catch(e){ return {}; } };
const save = s => { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch(e){} };
let state = load(), filter = 'all', tight = true;

/* 折轴：0~0.90 占左 26%，0.90~1.00 占右 74%——分数几乎都挤在 0.9 以上，
   全线性画出来两个点会重叠成一个。折点画一道竖线明示。 */
const BRK = 0.90, LEFT = 26;
const pos = v => v <= BRK ? Math.max(0, v)/BRK*LEFT
                          : LEFT + (v-BRK)/(1-BRK)*(100-LEFT);
const GATE = 0.996;

let flashT = 0;
function flash(msg){
  const el = document.getElementById('count');
  el.textContent = msg; clearTimeout(flashT);
  flashT = setTimeout(tally, 2200);
}
const esc = s => String(s).replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

function pane(cls, role, iid, ch){
  return `<figure class="pane ${cls}">
    <span class="role">${role}</span>
    <span class="tile"><img data-src="${iid}" alt="${esc(ch)} 字块" decoding="async"></span>
    <span class="glyph">${esc(ch)}</span></figure>`;
}

function card(r){
  const v = state[r.id] || '';
  const btn = k => `<button class="${k}" data-v="${k}" aria-pressed="${v===k}">${V[k]}</button>`;
  const lo = Math.min(r.cov_same, r.cov_other), hi = Math.max(r.cov_same, r.cov_other);
  return `<article class="card" data-id="${r.id}"${v?` data-v="${v}"`:''}>
    <div class="ch">
      <span class="pair"><span>${esc(r.char)}</span><span class="vs">敌不过</span>
        <span class="w">${esc(r.other_char)}</span></span>
      <span class="tags">
        <span class="tag">${esc(r.book)}</span>
        <span class="tag${r.tier==='degraded'?' deg':''}">${r.tier==='degraded'?'漫漶':'清晰'}</span>
        <span class="cid">${r.id}</span>
      </span>
    </div>
    <div class="strip">
      ${pane('same','同字最像', r.same, r.same_char)}
      ${pane('anchor','待判', r.anchor, r.char)}
      ${pane('other','异字最像', r.other, r.other_char)}
    </div>
    <div class="axis">
      <div class="track">
        <span class="rail"></span>
        <span class="span" style="left:${pos(lo)}%;right:${100-pos(hi)}%"></span>
        <span class="brk" style="left:${LEFT}%"></span>
        <span class="gate" style="left:${pos(GATE)}%" title="放行闸 ${GATE}"></span>
        <span class="pt s" style="left:${pos(r.cov_same)}%"></span>
        <span class="pt o" style="left:${pos(r.cov_other)}%"></span>
      </div>
      <div class="nums">
        <span class="s">同 <b>${r.cov_same.toFixed(4)}</b></span>
        <span class="o">异 <b>${r.cov_other.toFixed(4)}</b></span>
        <span class="m">差 ${r.margin.toFixed(4)}</span>
      </div>
    </div>
    <div class="verdicts">${btn('keep')}${btn('bad')}${btn('var')}${btn('idk')}</div>
  </article>`;
}

const io = new IntersectionObserver(es => {
  for (const e of es) if (e.isIntersecting){
    const img = e.target, iid = img.dataset.src;
    if (iid && D.imgs[iid]) img.src = D.imgs[iid];
    img.removeAttribute('data-src'); io.unobserve(img);
  }
}, {rootMargin: '600px 0px'});

const listEl = document.getElementById('list');
function draw(){
  let rows = D.rows.filter(r => filter === 'all' ? true
    : filter === 'done' ? !!state[r.id] : !state[r.id]);
  rows = rows.slice().sort((a,b) => tight ? Math.abs(a.margin)-Math.abs(b.margin)
                                          : Math.abs(b.margin)-Math.abs(a.margin));
  listEl.innerHTML = rows.length ? rows.map(card).join('')
    : `<p class="empty">这一档里没有卡片了。</p>`;
  listEl.querySelectorAll('img[data-src]').forEach(i => io.observe(i));
  tally();
}

function tally(){
  const done = D.rows.filter(r => state[r.id]).length;
  document.getElementById('count').textContent = `${done} / ${D.rows.length} 已裁`;
  document.getElementById('prog').style.width = (done / D.rows.length * 100) + '%';
}

listEl.addEventListener('click', e => {
  const b = e.target.closest('.verdicts button'); if (!b) return;
  const art = b.closest('.card'), id = art.dataset.id, v = b.dataset.v;
  if (state[id] === v) delete state[id]; else state[id] = v;
  save(state);
  art.querySelectorAll('.verdicts button').forEach(x =>
    x.setAttribute('aria-pressed', String(state[id] === x.dataset.v)));
  if (state[id]) art.dataset.v = state[id]; else art.removeAttribute('data-v');
  tally();
  if (filter !== 'all') setTimeout(draw, 180);
});

document.getElementById('filter').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  filter = b.dataset.f;
  [...e.currentTarget.children].forEach(x =>
    x.setAttribute('aria-pressed', String(x === b)));
  draw();
});
const sortBtn = document.getElementById('sort');
sortBtn.addEventListener('click', () => {
  tight = !tight; sortBtn.textContent = tight ? '势均优先' : '悬殊优先'; draw();
});

/* ---- 复制 ---- */
const sheet = document.getElementById('sheet');
const sheetText = document.getElementById('sheet-text');
function payload(){
  return D.rows.filter(r => state[r.id]).map(r => JSON.stringify({
    id: r.id, verdict: state[r.id], anchor: r.anchor, same: r.same, other: r.other,
    char: r.char, other_char: r.other_char,
    cov_same: r.cov_same, cov_other: r.cov_other
  })).join('\n');
}
document.getElementById('copy').addEventListener('click', async () => {
  const txt = payload();
  if (!txt){ flash('还没有裁决可复制。'); return; }
  sheetText.value = txt; sheet.hidden = false;
  try { await navigator.clipboard.writeText(txt);
        document.getElementById('sheet-note').textContent =
          '已复制到剪贴板。下面是全文，可再手动选。'; }
  catch(e){ document.getElementById('sheet-note').textContent =
          '长按选中全文复制，或用下面的按钮。'; }
});
document.getElementById('sheet-copy').addEventListener('click', async () => {
  sheetText.focus(); sheetText.select();
  try { await navigator.clipboard.writeText(sheetText.value);
        document.getElementById('sheet-note').textContent = '已复制。'; }
  catch(e){ document.getElementById('sheet-note').textContent = '复制没成功，请长按选中。'; }
});
document.getElementById('sheet-close').addEventListener('click', () => sheet.hidden = true);
sheet.addEventListener('click', e => { if (e.target === sheet) sheet.hidden = true; });
const resetBtn = document.getElementById('reset');
let armed = 0;
resetBtn.addEventListener('click', () => {
  if (!armed){ armed = 1; resetBtn.textContent = '确认清空？';
               setTimeout(() => { armed = 0; resetBtn.textContent = '清空'; }, 3000);
               return; }
  armed = 0; resetBtn.textContent = '清空';
  state = {}; save(state); draw(); flash('已清空。');
});

/* 说明栏的展开状态记住——同一个人反复来，不该每次都被推下去 200px */
const intro = document.getElementById('intro');
try { if (localStorage.getItem('guji-inversion-intro') === 'shut') intro.open = false; }
catch(e){}
intro.addEventListener('toggle', () => {
  try { localStorage.setItem('guji-inversion-intro', intro.open ? 'open' : 'shut'); }
  catch(e){}
});

draw();
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="../open-guji-dataset/glyph-match/pairs")
    ap.add_argument("--dump", required=True, help="eval_match_pairs.py --dump 出的 npz")
    ap.add_argument("--out", default="artifacts/match_inversion_review.html")
    ap.add_argument("--json", default=None, help="顺便存一份候选 JSON")
    args = ap.parse_args()

    payload = build(Path(args.dataset), Path(args.dump))
    print(f"候选 {len(payload['rows'])} 例，去重后图 {len(payload['imgs'])} 张")
    if args.json:
        Path(args.json).write_text(json.dumps(payload, ensure_ascii=False),
                                   encoding="utf-8")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(payload, CSS, JS), encoding="utf-8")
    print(f"→ {out}  ({out.stat().st_size/1e6:.2f} MB)")


if __name__ == "__main__":
    main()
