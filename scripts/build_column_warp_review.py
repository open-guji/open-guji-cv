# -*- coding: utf-8 -*-
"""Step2（单列射影变换 + 去噪 + 界行清除）金标标注页。

    python scripts/build_column_warp_review.py -o output/column_warp_review.html

列图直接读 `output/<book>/step2_columns/<page>/c<N>.png`——生产链路真正会喂给
Step2 的那张图（`scripts/regen_step2_columns.py` 用 `detect_borders` 算法探测
的边线 + `page_column_windows` 逐列窗口生成）。把矫正图和它**沿竖直方向的
投影**摆出来，让人拖两条线定出「文字带」的左右边界，并裁决这一列能不能做到
「界行残墨全在带外、字身墨全在带内」。

**别再从 border-detection 金标现算列图**：那是另一条链路（人工金标边线 +
页级 x=0 锚点），实测边线差 0.76~27.6px、列图宽度差到 38px，标注不通用。
那套的金标归档在数据集的 `column-warp/legacy-page-anchor/`。

金标真源是人拖出来的那两个 x 和那条裁决，投影曲线只是随卡存的快照。

选列规则写在 `pick_columns()` 里，是**明说的四条 + 一条对照**，不是挑跑得好看的：
故意超采样倾斜大 / 梯形大 / 锚点偏差大 / 抬头这四类难例，再配平稳列做对照。
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import statistics
import sys
from pathlib import Path

import cv2
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / ".claude" / "skills" / "review-artifact" / "scripts"))

from open_guji_cv.utils.border_geometry import HLine, VLine  # noqa: E402
from open_guji_cv.utils.column_projection import (  # noqa: E402
    column_profile,
    column_text_band,
    denoise_column,
)
from review_shell import render  # noqa: E402

DATASET = ROOT.parent / "open-guji-dataset"
GOLD_DIR = DATASET / "border-detection" / "samples"
SRC = ROOT / "data_full" / "zongmu" / "{book}" / "{page}.png"
STEP2_COLUMNS = ROOT / "output" / "{book}" / "step2_columns" / "{page}"


def load_windows(book: str, page: str) -> dict[int, dict]:
    """读 regen_step2_columns.py 产的逐列窗口——这是 Step2 的**定版输入**。"""
    f = Path(str(STEP2_COLUMNS).format(book=book, page=page)) / "windows.json"
    if not f.exists():
        raise SystemExit(f"{f} 不存在——先跑 scripts/regen_step2_columns.py {book} {page}")
    return {c["col"]: c for c in json.loads(f.read_text(encoding="utf-8"))["columns"]}

TITLE = "单列矫正·文字带核校"
KEY = "column-warp-band-v3"          # 换页必须换 key —— 见下面这条教训
# ⚠️ **要强制重标就必须换 KEY**。`--drop` 只清页里嵌的那份裁决，而壳是
# `mergeState(D.verdicts, readLocal())`——浏览器 localStorage 里那份**同 key**
# 的旧裁决会在加载时合并回来（`!(k in out)` 那一支：嵌的那份没有的键无条件补上）。
# 2026-09-03 实测吃过一次：全书重跑后 drop 了 23 条要重标的，用户打开页面看到的
# 却仍是旧裁决，23 条里只有 1 条（vol01/42 c9）是真的新点的，其余 22 条时间戳
# 还停在 08-31~09-02，等于**重标根本没发生**，而页面看起来是"都标完了"。
# 换 key = localStorage 读不到旧值 = 只有嵌进去的那份生效。
STRIP_H = 460                          # 矫正图压扁到这个高度（只判 x，y 分辨率无所谓）

VERDICTS = [("clean", "分得开", "ok"),
            ("mixed", "分不开", "zhu"),
            ("idk", "拿不准", "faint")]


# ---------------------------------------------------------------- 几何 / 选列

def page_geometry(book: str, page: str):
    d = json.loads((GOLD_DIR / f"{book}_{page}.json").read_text(encoding="utf-8"))
    top = HLine(d["top_inner"]["y_at_right"], d["top_inner"]["slope"], "top")
    bottom = HLine(d["bottom_inner"]["y_at_right"], d["bottom_inner"]["slope"], "bottom")
    verticals = [VLine(v["x_at_top"], v["slope"]) for v in d["verticals_inner"]]
    raise_y: dict[int, float] = {}
    estimated: set[int] = set()
    for r in d.get("head_raise", []):
        # 同一列可能有两级台阶（vol01/47「御製」）——取最高的一级，才装得下全部抬头字
        raise_y[r["col"]] = min(raise_y.get(r["col"], float("inf")), r["inner_y"])
        if r["estimated"]:
            estimated.add(r["col"])
    return d, top, bottom, verticals, raise_y, estimated


def column_metrics() -> dict[tuple[str, str, int], dict]:
    """逐列算三个几何量：倾斜量、梯形量、x=0 锚点相对列中心的偏差。"""
    out: dict[tuple[str, str, int], dict] = {}
    for f in sorted(GOLD_DIR.glob("*.json")):
        d, top, bottom, vs, raise_y, estimated = page_geometry(*f.stem.split("_", 1))
        for k in range(1, len(vs)):
            right, left = vs[k - 1], vs[k]
            xc = 0.5 * (right.x_at_top + left.x_at_top)
            ty, by = top.y_at(xc), bottom.y_at(xc)
            gap_top = abs(left.x_at(ty) - right.x_at(ty))
            gap_bot = abs(left.x_at(by) - right.x_at(by))
            out[(d["book"], d["page"], k)] = dict(
                drift=abs(0.5 * (left.slope + right.slope) * (by - ty)),
                dgap=abs(gap_bot - gap_top),
                anchor=max(abs(top.y_at(xc) - top.y_at(0)),
                            abs(bottom.y_at(xc) - bottom.y_at(0))),
                raised=k in raise_y, estimated=k in estimated)
    return out


def pick_columns(metrics: dict[tuple[str, str, int], dict]) -> list[dict]:
    """选列规则——明说的四条难例 + 一条对照，不按"跑得好看"挑。"""
    why: dict[tuple[str, str, int], set[str]] = {}

    def add(key, tag):
        why.setdefault(key, set()).add(tag)

    for key, m in metrics.items():
        # vol01/32 那 5 条抬头框是推测值(estimated)，不能当位置基准，排除
        if m["raised"] and not m["estimated"]:
            add(key, "抬头列")
    for field, tag, n in [("drift", "倾斜大", 8), ("dgap", "梯形大", 8),
                           ("anchor", "锚点偏差大", 6)]:
        for key in sorted(metrics, key=lambda k: -metrics[k][field])[:n]:
            add(key, tag)

    med = {f: statistics.median(m[f] for m in metrics.values())
           for f in ("drift", "dgap", "anchor")}
    seen_pages: set[str] = set()
    for key in sorted(metrics, key=lambda k: sum(metrics[k][f] for f in med)):
        m = metrics[key]
        if m["raised"] or key in why or key[1] in seen_pages or len(seen_pages) >= 6:
            continue
        if all(m[f] < med[f] for f in med):
            add(key, "对照·平稳列")
            seen_pages.add(key[1])

    return [dict(book=k[0], page=k[1], col=k[2], tags=sorted(why[k]), **metrics[k])
            for k in sorted(why, key=lambda k: (k[0], int(k[1]), k[2]))]


# ---------------------------------------------------------------- 卡片数据

def build_rows(picked: list[dict]) -> tuple[list[dict], dict[str, str]]:
    rows, imgs = [], {}
    wins: dict[tuple[str, str], dict[int, dict]] = {}
    for p in picked:
        book, page, col = p["book"], p["page"], p["col"]
        if (book, page) not in wins:
            wins[(book, page)] = load_windows(book, page)
        win = wins[(book, page)][col]
        img_path = Path(str(STEP2_COLUMNS).format(book=book, page=page)) / win["file"]
        raw = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
        if raw is None:
            raise SystemExit(f"读不到列图: {img_path}")
        warped = denoise_column(raw)
        seed_l, seed_r = column_text_band(warped)
        prof = column_profile(warped)

        cid = f"{book}_{page}_c{col}"
        squashed = cv2.resize(warped, (warped.shape[1], STRIP_H),
                               interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".png", squashed, [cv2.IMWRITE_PNG_COMPRESSION, 9])
        assert ok
        imgs[cid] = "data:image/png;base64," + base64.b64encode(buf).decode()
        # 「抬头列」以**当前输入**为准重打，别用选列时的旧标签
        tags = [t for t in p["tags"] if t != "抬头列"] + (["抬头列"] if win["raised"] else [])
        rows.append(dict(
            id=cid, book=book, page=page, col=col, tags=sorted(tags),
            raised=bool(win["raised"]), w=int(warped.shape[1]), h=int(warped.shape[0]),
            top_y=round(win["top_y"], 1), bottom_y=round(win["bottom_y"], 1),
            drift=round(p["drift"], 1), dgap=round(p["dgap"], 1),
            anchor=round(p["anchor"], 1), seed=[int(seed_l), int(seed_r)],
            # 投影量化成 0~255 一个字节一点，base64 存——32 列合计几 KB
            prof=base64.b64encode(bytes(int(round(v * 255)) for v in prof)).decode()))
    return rows, imgs


# ---------------------------------------------------------------- 页面

CSS = """
.card{background:var(--surface); border:1px solid var(--rule);
  border-left:3px solid transparent; border-radius:3px; padding:12px 13px;
  box-shadow:var(--shadow);}
""" + "".join(f'.card[data-v="{v}"]{{border-left-color:var(--{c})}}\n'
              for v, _, c in VERDICTS) + """
.card h3{margin:0; font-family:var(--serif); font-size:15px; display:flex;
  align-items:baseline; gap:8px;}
.card h3 em{font-style:normal; font-family:var(--mono); font-size:11px;
  color:var(--muted); font-weight:400;}
.tags{margin:5px 0 0; display:flex; flex-wrap:wrap; gap:5px;}
.tags span{font-size:11px; padding:1px 6px; border-radius:2px;
  background:var(--sunk); color:var(--muted);}
.tags span.raise{background:var(--ochre-soft); color:var(--ochre)}

.stage{position:relative; margin:10px auto 0; width:100%; touch-action:pan-y;
  background:var(--tile); border:1px solid var(--rule-hard); border-radius:2px;
  overflow:hidden; cursor:ew-resize;}
.stage img{display:block; width:100%; height:var(--sh); image-rendering:pixelated;}
.veil{position:absolute; top:0; bottom:0; background:var(--zhu);
  opacity:.26; pointer-events:none;}
.veil.l{left:0} .veil.r{right:0}
.grip{position:absolute; top:0; bottom:0; width:2px; margin-left:-1px;
  background:var(--indigo); pointer-events:none;}
.grip::after{content:""; position:absolute; left:-9px; right:-9px; top:0; bottom:0;}

.prof{display:block; width:100%; height:62px; margin:2px auto 0;
  background:var(--ground); border:1px solid var(--rule); border-top:0;}
.profcap{margin:3px auto 0; font-family:var(--mono); font-size:10.5px;
  color:var(--faint); display:flex; justify-content:space-between;}
.prof path{fill:var(--indigo); fill-opacity:.5; stroke:none}
.prof line{stroke:var(--rule-hard); stroke-width:1; stroke-dasharray:3 3;
  vector-effect:non-scaling-stroke}
.prof rect.cut{fill:var(--zhu); fill-opacity:.18}

.nudge{display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:9px;}
.nudge div{display:flex; align-items:center; gap:5px; font-size:12px; color:var(--muted);}
.nudge button{min-width:34px; min-height:34px; border:1px solid var(--rule-hard);
  border-radius:3px; background:var(--surface); color:var(--ink);
  font-family:var(--mono); font-size:14px; cursor:pointer;}
.nudge button:active{background:var(--sunk)}
.nudge output{font-family:var(--mono); font-size:13px; color:var(--ink);
  min-width:2.6em; text-align:center; font-variant-numeric:tabular-nums;}
.nudge .rst{margin-left:auto; font-size:11px; min-width:0; padding:0 7px;
  font-family:var(--sans); color:var(--muted);}

.verdicts{display:grid; grid-template-columns:repeat(NCOL,1fr); gap:6px; margin-top:10px;}
.verdicts button{min-height:44px; border:1px solid var(--rule-hard); border-radius:3px;
  background:var(--surface); color:var(--ink); font-family:var(--sans);
  font-size:13px; font-weight:500; cursor:pointer;}
.verdicts button:active{background:var(--sunk)}
.verdicts button:focus-visible{outline:2px solid var(--indigo); outline-offset:2px;}
.verdicts button[aria-pressed="true"]{color:var(--on-solid); border-color:transparent;}
""".replace("NCOL", str(len(VERDICTS))) + "".join(
    f'.verdicts button.{v}[aria-pressed="true"]{{background:var(--{c})}}\n'
    for v, _, c in VERDICTS)


PAGE_JS = r"""
const VERDICTS = __VERDICTS__;
const SH = __SH__;

const BODY = `
<header class="top"><div class="top-in">
  <span class="brand">__TITLE__</span>
  <span class="save" id="save">本机</span>
  <span class="count" id="count">0 / 0</span>
</div><div class="bar"><i id="prog"></i></div></header>
<div class="wrap">
  <details class="intro" id="intro" open>
    <summary>怎么标</summary>
    <p>每张卡是<b>一列</b>矫正之后的样子：上面是整列压扁图（横向 1:1，纵向压过所以字是扁的，
       不影响判左右），下面是它<b>沿竖直方向的投影</b>——每个横向位置上的墨占比。</p>
    <p>拖动两条蓝线，把<b>文字带</b>框出来：<b>带外只该剩界行残墨，带内的字身要完整</b>。
       红色阴影就是会被清掉的部分。手机上拖不准就用下面的 <code>−</code> <code>+</code> 逐像素微调。</p>
    <div class="rubric">
      <div><b style="background:var(--ok-soft);color:var(--ok)">分得开</b>
        <span>存在这样一条界：外侧只有界行、内侧字是完整的。</span></div>
      <div><b style="background:var(--zhu-soft);color:var(--zhu)">分不开</b>
        <span>做不到——界行残墨和字身墨在横向糊在一起，只能二选一。
              （矫正没矫正好的典型症状：界行本该是又窄又高的尖峰，糊了就摊成又宽又矮的鼓包。）</span></div>
      <div><b style="background:var(--sunk);color:var(--faint)">拿不准</b>
        <span>看不清、或者这一列本身有别的毛病（首字被切掉之类）。</span></div>
    </div>
    <p>裁决和拖出来的两个数都<b>自动存回本页</b>，看右上角的小牌子；显示
       <code>仅存本机</code> 就用「复制」把结果贴回对话。</p>
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
  <h2>标注结果</h2><p id="sheet-note"></p>
  <textarea id="sheet-text" readonly></textarea>
  <div class="row"><button class="ghost" id="sheet-copy">复制</button>
  <button class="ghost" id="sheet-close">关闭</button></div>
</div></div>`;

const rowId = r => r.id;
/* page_js 整段跑在壳之前，那会儿 `D` 还在暂时性死区里——索引必须懒建，
   顶层直接 `Object.fromEntries(D.rows…)` 会当场抛错、整页空白。 */
let _rowIdx = null;
const rowOf = id => (_rowIdx || (_rowIdx = Object.fromEntries(D.rows.map(r => [r.id, r]))))[id];

/* 文字带存成另一条 state 记录（id 后缀 #band，值 "L,R"），跟裁决一起自动存回。 */
const bandKey = id => id + '#band';
function bandOf(id){
  const raw = (state[bandKey(id)] || {}).v;
  if (raw){ const [a, b] = raw.split(',').map(Number);
            if (Number.isFinite(a) && Number.isFinite(b)) return [a, b]; }
  return rowOf(id).seed.slice();
}
function setBand(id, band){
  const r = rowOf(id);
  let [a, b] = band.map(v => Math.round(v));
  a = Math.max(0, Math.min(a, r.w - 1));
  b = Math.max(a + 1, Math.min(b, r.w));
  state[bandKey(id)] = {v: a + ',' + b, t: Date.now()};
  persist();
  return [a, b];
}
const touched = id => !!state[bandKey(id)];

function unpackProf(s){
  const bin = atob(s), out = new Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i) / 255;
  return out;
}

function profSvg(r){
  const p = unpackProf(r.prof), n = p.length;
  /* 纵轴按本列自己的峰值归一——列与列之间墨量差好几倍，固定 0~1 会把
     磨损界行那种矮峰压成一条平线，而"尖峰还是鼓包"正是这页要看的东西。
     峰值原值写在下面的说明里，免得读者以为纵轴可跨列比。 */
  const pmax = Math.max(...p, 0.02);
  /* 阶梯折线：每个像素画成一格，别插值——插值会把 1px 宽的尖峰画成缓坡。 */
  let d = 'M0,100';
  for (let i = 0; i < n; i++){ const y = 100 - p[i] / pmax * 96;
    d += ` L${i},${y} L${i + 1},${y}`; }
  d += ` L${n},100 Z`;
  return `<svg class="prof" viewBox="0 0 ${n} 100" preserveAspectRatio="none"
     style="max-width:${n * 2}px">
    <rect class="cut" data-side="l" x="0" y="0" width="0" height="100"></rect>
    <rect class="cut" data-side="r" x="${n}" y="0" width="0" height="100"></rect>
    <path d="${d}"></path>
    <line x1="0" y1="52" x2="${n}" y2="52"></line></svg>
    <div class="profcap" style="max-width:${n * 2}px">
      <span>沿竖直方向的投影（纵轴按本列峰值归一，虚线=半峰）</span>
      <span>峰 ${pmax.toFixed(2)}</span></div>`;
}

function card(r){
  const v = verdictOf(r.id), [a, b] = bandOf(r.id);
  const btn = ([k, t]) => `<button class="${k}" data-v="${k}" aria-pressed="${v === k}">${t}</button>`;
  const tag = t => `<span class="${t === '抬头列' ? 'raise' : ''}">${esc(t)}</span>`;
  return `<article class="card" data-id="${r.id}"${v ? ` data-v="${v}"` : ''}>
    <h3>${r.book}/${r.page} 第 ${r.col} 列 <em>宽 ${r.w}px</em></h3>
    <div class="tags">${r.tags.map(tag).join('')}${touched(r.id) ? '<span>已改过界</span>' : ''}</div>
    <div class="stage" style="--sh:${SH}px; max-width:${r.w * 2}px">
      <img data-src="${r.id}" alt="">
      <div class="veil l"></div><div class="veil r"></div>
      <div class="grip gl"></div><div class="grip gr"></div>
    </div>
    ${profSvg(r)}
    <div class="nudge">
      <div><button data-n="l,-1">−</button><output class="ol">${a}</output><button data-n="l,1">+</button>
        <span>左界</span></div>
      <div><button data-n="r,-1">−</button><output class="or">${b}</output><button data-n="r,1">+</button>
        <span>右界</span><button class="rst" data-n="reset">复位</button></div>
    </div>
    <div class="verdicts">${VERDICTS.map(btn).join('')}</div>
  </article>`;
}

function paint(art){
  const r = rowOf(art.dataset.id), [a, b] = bandOf(r.id);
  const pl = a / r.w * 100, pr = b / r.w * 100;
  art.querySelector('.veil.l').style.width = pl + '%';
  art.querySelector('.veil.r').style.width = (100 - pr) + '%';
  const gl = art.querySelector('.gl'), gr = art.querySelector('.gr');
  gl.style.left = pl + '%'; gr.style.left = pr + '%';
  art.querySelector('.ol').textContent = a; art.querySelector('.or').textContent = b;
  const cl = art.querySelector('.cut[data-side="l"]'), cr = art.querySelector('.cut[data-side="r"]');
  cl.setAttribute('width', a); cr.setAttribute('x', b); cr.setAttribute('width', r.w - b);
}
function paintAll(){ listEl.querySelectorAll('.card').forEach(paint); }

/* 拖：按下时认最近的一条界，之后跟着指头走。事件委托到 #list 上，
   卡片是 draw() 重画出来的，直接挂在元素上会在重画后失效。 */
let drag = null;
function xOf(e, stage, r){
  const box = stage.getBoundingClientRect();
  return Math.max(0, Math.min(r.w, (e.clientX - box.left) / box.width * r.w));
}
document.addEventListener('pointerdown', e => {
  const stage = e.target.closest('.stage'); if (!stage) return;
  const art = stage.closest('.card'), r = rowOf(art.dataset.id);
  const x = xOf(e, stage, r), [a, b] = bandOf(r.id);
  const dl = Math.abs(x - a), dr = Math.abs(x - b);
  /* 离两条界都远就不接管——滚页面时手指扫过图上，不该把界拽到正文中间 */
  if (Math.min(dl, dr) > 40) return;
  drag = {art, stage, r, side: dl <= dr ? 'l' : 'r'};
  stage.setPointerCapture(e.pointerId);
  move(e);
});
function move(e){
  if (!drag) return;
  const x = xOf(e, drag.stage, drag.r), [a, b] = bandOf(drag.r.id);
  setBand(drag.r.id, drag.side === 'l' ? [x, b] : [a, x]);
  paint(drag.art);
  e.preventDefault();
}
document.addEventListener('pointermove', move);
document.addEventListener('pointerup', () => { drag = null; });
document.addEventListener('pointercancel', () => { drag = null; });

document.addEventListener('click', e => {
  const nb = e.target.closest('.nudge button');
  if (nb){
    const art = nb.closest('.card'), r = rowOf(art.dataset.id);
    if (nb.dataset.n === 'reset') state[bandKey(r.id)] = {v: r.seed.join(','), t: Date.now()};
    else {
      const [side, d] = nb.dataset.n.split(','), [a, b] = bandOf(r.id);
      setBand(r.id, side === 'l' ? [a + +d, b] : [a, b + +d]);
      paint(art); return;
    }
    persist(); paint(art); return;
  }
  const fb = e.target.closest('#filter button'); if (!fb) return;
  filter = fb.dataset.f;
  [...fb.parentElement.children].forEach(x => x.setAttribute('aria-pressed', String(x === fb)));
  draw(); paintAll();
});

let filter = 'todo';
function visibleRows(){
  if (filter === 'all') return D.rows;
  const done = filter === 'done';
  return D.rows.filter(r => !!verdictOf(r.id) === done);
}
function afterVerdict(){ if (filter !== 'all') draw(); paintAll(); }

function payload(){
  return D.rows.filter(r => verdictOf(r.id)).map(r => {
    const [a, b] = bandOf(r.id);
    return JSON.stringify({id: r.id, book: r.book, page: r.page, col: r.col,
                            verdict: verdictOf(r.id), band: [a, b],
                            seed: r.seed, moved: touched(r.id), w: r.w});
  }).join('\n');
}

/* draw() 只吐 innerHTML，蒙版/手柄的位置得画完再补一遍。壳在整段脚本的最后
   才第一次 draw()，所以初次补画排到宏任务里——那时 #list 才存在。 */
setTimeout(paintAll, 0);
""".replace("__VERDICTS__", json.dumps([[v, t] for v, t, _ in VERDICTS], ensure_ascii=False)) \
   .replace("__TITLE__", TITLE).replace("__SH__", str(STRIP_H))


def load_existing(path: str | None, drop: set[str]) -> dict:
    """带回旧页里的裁决；`drop` 里的列（几何漂了、标注已失效）连同它的 #band 一起丢。

    重发一律**先 read 回来再 build**，否则覆盖掉用户还没收割的标注
    （规矩见 artifacts/README.md）。"""
    if not path:
        return {}
    html = Path(path).read_text(encoding="utf-8")
    m = re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S)
    if not m:
        raise SystemExit("这份 HTML 里没有 #data")
    st = json.loads(m.group(1).replace("<\\/", "</")).get("verdicts", {})
    return {k: v for k, v in st.items()
            if k.split("#")[0] not in drop}


_TAGS_FROZEN: dict[tuple[str, str, int], list[str]] = {}


def frozen_columns(path: str) -> list[tuple[str, str, int]]:
    """从冻好的卡集里读列表。Step1 每改一次几何，`pick_columns` 用的三个指标
    就跟着变、选出来的列也会变——已经标过的那一批必须冻住，不然重出一版页
    列换了，上一轮的标注全对不上号。"""
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        r = json.loads(line)
        key = (r["book"], r["page"], r["col"])
        _TAGS_FROZEN[key] = r.get("tags", [])
        out.append(key)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default="output/column_warp_review.html")
    ap.add_argument("--cards", default="output/column_warp_cards.jsonl",
                    help="卡片 id 冻在这里——重出一版页照旧读，否则上一轮的标注对不上号")
    ap.add_argument("--freeze", help="按这个卡集里的列重建（不重跑 pick_columns）")
    ap.add_argument("--carry", help="读回来的旧页 HTML，把仍然有效的裁决带过来")
    ap.add_argument("--only", default="",
                    help="逗号分隔的 id：只放这些卡（要重标时用，别让人在一堆"
                         "已裁的卡里找那几张）")
    ap.add_argument("--drop", default="", help="逗号分隔的列 id，几何漂了、标注已失效，清掉重标")
    args = ap.parse_args()

    metrics = column_metrics()
    if args.freeze:
        keep = frozen_columns(args.freeze)
        # 没有 border-detection 金标的页（比如专门筛 mixed 候选的新页）量不出
        # 三个几何指标——那三个数只是卡片元数据，标注界面不展示，缺了给 0
        # 占位即可，不该因此挡住这一批标注。
        _NO_METRICS = dict(drift=0.0, dgap=0.0, anchor=0.0, raised=False, estimated=False)
        picked = [dict(book=b, page=p, col=c,
                        tags=sorted(_TAGS_FROZEN.get((b, p, c), [])),
                        **metrics.get((b, p, c), _NO_METRICS))
                   for b, p, c in keep]
    else:
        picked = pick_columns(metrics)
    drop = {x for x in args.drop.split(",") if x}
    only = {x for x in args.only.split(",") if x}
    if only:
        # 重标时只放要重标的列——别让人在一堆已裁的卡里翻那几张
        picked = [p for p in picked if f"{p['book']}_{p['page']}_c{p['col']}" in only]
        if not picked:
            raise SystemExit(f"--only 里的 id 一个都没匹配上：{sorted(only)}")
    existing = load_existing(args.carry, drop)
    rows, imgs = build_rows(picked)
    if only:
        keep = {r["id"] for r in rows}
        existing = {k: v for k, v in existing.items() if k.split("#")[0] in keep}

    cards = Path(args.cards)
    cards.parent.mkdir(parents=True, exist_ok=True)
    cards.write_text("\n".join(
        json.dumps({k: v for k, v in r.items() if k != "prof"}, ensure_ascii=False)
        for r in rows) + "\n", encoding="utf-8")

    # 第三个参数是**已有裁决**（{id:{v,t}}），不是按钮文案——文案在 page_js 里
    html = render(TITLE, KEY, verdicts=existing, css=CSS, page_js=PAGE_JS,
                   payload={"rows": rows, "imgs": imgs})
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    done = len({k.split('#')[0] for k in existing})
    print(f"{len(rows)} 列 / {len({(r['book'], r['page']) for r in rows})} 页"
          f"，带过来 {done} 列的裁决、清掉 {len(drop)} 列 -> {out} "
          f"({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
