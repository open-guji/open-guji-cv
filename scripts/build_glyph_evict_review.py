# -*- coding: utf-8 -*-
"""图块出库裁决台：逐块判「这块图能不能用」，人裁定出全库清理的判据。

    PYTHONPATH=. python scripts/build_glyph_evict_review.py

## 为什么要这一页

形近误判裁决台第一轮（132 例）里 73 例判了「标注有误」，用户看完的结论是：
**大量图块本身带残留**——界行线、版框条、邻字整块混进来、格线上飘把字切了半截。
标签错只是症状。

问题是**判不出来**：现有的 `crop_quality` 判据锚在图块外边界上（碰边才算），
拿这 132 例扫，73 个 bad 只中 35 个，57 个 keep 里还误报 6 个。我试了几组新
特征（墨框纵横比 / 投影干净缝 / 孤立连通体外扩量），AUC 全在 0.43~0.60——
**因为靶子就不对**：`bad` 判的是「金标字头错没错」，不是「这块图脏不脏」。
用它标残留检测器，等于拿症状当病因训。

所以先要一批**逐块的图像质量金标**。这一页就是收它的。

## 候选怎么选（四层，必须分层读）

| 层 | 怎么来 | 干什么用 |
|---|---|---|
| `missed` | 132 例里判了 bad、现有判据却没旗标的 38 块 | 判据的盲区，最该看 |
| `flagged` | 全池 6086 块里被现有判据旗标的（606 块）分层抽样 | 量现有判据的**准**（误报率）|
| `newrule` | 只被新规则（墨框宽高比 ≥1.3 / 投影干净缝）命中的 | 量新规则值不值得进判据 |
| `control` | 全池随机抽的**没有任何旗标**的块 | 量现有判据的**漏**——这层缺了就只会得到一个自我确认的数 |

`control` 层是这页的要害：只看被旗标的块，永远只能证明判据说对了什么，
证不出它漏了什么。四层的先验差着数量级，**误报率与漏检率必须分开报**。

## 裁决

    出库    残留/截断重到这块图不能用——从数据集里降级或剔除
    进测试集 有缺陷，但正好当质量判据的金标留着量
    留着    干净，可用
    拿不准  看不出来

每张卡右边是**归一化后的 64×64**——那才是匹配算法真正看到的东西。残留的
危害主要走这条路：一条离字身 40px 的细线把墨框撑大，字被缩到角落里。

裁决自动存回页面（`artifact` 能力，files 形式重发 index.html），
`Artifact action:"read"` 读 `#data` 的 `verdicts` 即可回收。
"""
from __future__ import annotations

import argparse
import base64
import json
import random
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from open_guji_cv.clustering.crop_quality import assess_crop, detect_intrusion  # noqa: E402
from open_guji_cv.clustering.normalize import (  # noqa: E402
    _drop_stray_components, ink_bbox, normalize_patch, remove_edge_specks,
    sauvola_binarize)

PIPE_REV = "502fa04d0c"
THUMB = 176
GRAY_STEP = 16
SEED = 11
TITLE = "图块出库裁决台"

# 新规则：只保留在 132 例上**零误报**的那几条（见模块头）
AR_HI = 1.30        # 墨框宽高比：邻字左右整块混入
GAP_X = 0.05        # 投影里的干净竖缝（占墨框宽）
GAP_Y = 0.08        # 干净横缝（占墨框高）

QUOTA = {"missed": None, "flagged": 55, "newrule": 25, "control": 40}


# ---------------------------------------------------------------- 判据
def gate_flags(gray: np.ndarray) -> list[str]:
    q = assess_crop(gray)
    fl = set(detect_intrusion(gray))
    if q.truncated:
        fl.add("truncated")
    if q.residue:
        fl.add("residue")
    return sorted(fl)


def new_flags(gray: np.ndarray) -> list[str]:
    """归一化那条路上看得见的残留形态（与 gate 互补，不看是否碰边）。"""
    b = _drop_stray_components(remove_edge_specks(sauvola_binarize(gray)))
    bb = ink_bbox(b)
    if bb is None:
        return []
    x0, y0, x1, y1 = bb
    b = b[y0:y1, x0:x1]
    h, w = b.shape
    out = []
    if w / h >= AR_HI:
        out.append("wide_ink")
    for axis, name, n, thr in ((1, "gap_x", w, GAP_X), (0, "gap_y", h, GAP_Y)):
        p = b.sum(axis).astype(float)
        zero = p <= p.max() * 0.02
        run = 0
        for i, e in enumerate(list(zero) + [False]):
            if e:
                run += 1
                continue
            s = i - run
            if run and s > 0 and i < n:
                lo, hi = p[:s].sum(), p[i:].sum()
                if min(lo, hi) / p.sum() > 0.005 and run / n >= thr:
                    out.append(name)
                    break
            run = 0
    return sorted(set(out))


# ---------------------------------------------------------------- 图源
def gray_sources() -> Path:
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
    p = out / book / "phase4_chars" / "patches" / page / f"{col}_{idx}.png"
    return cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) if p.exists() else None


def png_b64(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    assert ok
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def thumb(img: np.ndarray) -> str:
    h, w = img.shape
    s = THUMB / max(h, w)
    img = cv2.resize(img, (max(1, round(w * s)), max(1, round(h * s))),
                     interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    img = ((img.astype(np.uint16) // GRAY_STEP) * GRAY_STEP).clip(0, 255).astype(np.uint8)
    return png_b64(img)


def norm_thumb(gray: np.ndarray) -> str:
    n = normalize_patch(gray)
    big = cv2.resize((1 - n) * 255, (128, 128), interpolation=cv2.INTER_NEAREST)
    return png_b64(big.astype(np.uint8))


# ---------------------------------------------------------------- 选样
def pick(dataset: Path, verdicts: Path, out: Path) -> list[dict]:
    data = json.loads((dataset / "expected.json").read_text(encoding="utf-8"))
    meta = {r["instance_id"]: r for r in data["instances"]}
    judged = [json.loads(l) for l in verdicts.read_text(encoding="utf-8").splitlines()
              if l.strip()]

    cache: dict[str, tuple[list[str], list[str]]] = {}

    def flags(iid):
        if iid not in cache:
            g = load_gray(iid, out)
            cache[iid] = ([], []) if g is None else (gate_flags(g), new_flags(g))
        return cache[iid]

    rows: dict[str, dict] = {}

    # ① missed：判了 bad 且现有判据没旗标的
    for r in judged:
        if r["verdict"] != "bad":
            continue
        g, n = flags(r["anchor"])
        if not g:
            rows[r["anchor"]] = {"layer": "missed", "gate": g, "new": n,
                                 "note": f"{r['id']} 判了标注有误"}
    print(f"  ① missed {len(rows)}")

    seen = set(rows)
    judged_all = {x for r in judged for x in (r["anchor"], r["same"], r["other"])}
    rng = random.Random(SEED)
    pool = [i for i in meta if i not in judged_all]
    rng.shuffle(pool)

    # ② flagged：按旗标分层抽（每类配额均分）
    by: dict[str, list[str]] = defaultdict(list)
    for iid in pool:
        g, _ = flags(iid)
        for f in g:
            by[f].append(iid)
    per = max(1, QUOTA["flagged"] // max(1, len(by)))
    for f, lst in sorted(by.items()):
        for iid in lst[:per]:
            if iid in seen:
                continue
            g, n = flags(iid)
            rows[iid] = {"layer": "flagged", "gate": g, "new": n, "note": ""}
            seen.add(iid)
    print(f"  ② flagged {sum(1 for v in rows.values() if v['layer']=='flagged')}")

    # ③ newrule：只被新规则命中的
    k = 0
    for iid in pool:
        if k >= QUOTA["newrule"] or iid in seen:
            continue
        g, n = flags(iid)
        if n and not g:
            rows[iid] = {"layer": "newrule", "gate": g, "new": n, "note": ""}
            seen.add(iid)
            k += 1
    print(f"  ③ newrule {k}")

    # ④ control：全池随机、任何旗标都没有的
    k = 0
    for iid in pool:
        if k >= QUOTA["control"] or iid in seen:
            continue
        g, n = flags(iid)
        if not g and not n:
            rows[iid] = {"layer": "control", "gate": [], "new": [], "note": ""}
            seen.add(iid)
            k += 1
    print(f"  ④ control {k}")

    order = {"missed": 0, "flagged": 1, "newrule": 2, "control": 3}
    return [{"iid": i, **v, "char": meta[i]["char"], "book": meta[i]["book"],
             "tier": meta[i]["tier"], "ink": meta[i]["ink_bucket"]}
            for i, v in sorted(rows.items(), key=lambda kv: (order[kv[1]["layer"]], kv[0]))]


CSS = """
.card{background:var(--surface); border:1px solid var(--rule); border-radius:3px;
  box-shadow:var(--shadow); padding:12px 12px 11px; border-left:3px solid var(--rule-hard);}
.card[data-v="out"] {border-left-color:var(--zhu)}
.card[data-v="test"]{border-left-color:var(--ochre)}
.card[data-v="keep"]{border-left-color:var(--ok)}
.card[data-v="idk"] {border-left-color:var(--faint)}
.ch{display:flex; align-items:center; gap:9px; margin-bottom:9px;}
.glyph{font-family:var(--serif); font-weight:700; font-size:21px; line-height:1;}
.tags{margin-left:auto; display:flex; gap:5px; align-items:center;}
.tag{font-family:var(--mono); font-size:10.5px; color:var(--muted);
  border:1px solid var(--rule); border-radius:2px; padding:1px 5px; white-space:nowrap;}
.tag.deg{color:var(--ochre); border-color:var(--ochre)}
.cid{font-family:var(--mono); font-size:10.5px; color:var(--faint);}
.two{display:grid; grid-template-columns:1fr 1fr; gap:10px;}
.two figure{margin:0; display:grid; gap:5px; justify-items:center;}
.tile{width:100%; aspect-ratio:1; background:var(--tile); border:1px solid var(--rule);
  border-radius:2px; overflow:hidden; display:grid; place-items:center;}
.tile.n{background:var(--sunk); border-style:dashed;}
.tile img{width:100%; height:100%; object-fit:contain; display:block;}
.cap{font-size:10.5px; letter-spacing:.04em; color:var(--faint);}
.verdicts{display:grid; grid-template-columns:repeat(4,1fr); gap:6px; margin-top:11px;}
.verdicts button{min-height:44px; border:1px solid var(--rule-hard); border-radius:3px;
  background:var(--surface); color:var(--muted); cursor:pointer;
  font-family:var(--sans); font-size:13px; font-weight:500; padding:0 2px;}
.verdicts button:active{background:var(--sunk)}
.verdicts button:focus-visible{outline:2px solid var(--indigo); outline-offset:2px;}
.verdicts button[aria-pressed="true"]{color:var(--on-solid); border-color:transparent;}
.verdicts button.out[aria-pressed="true"] {background:var(--zhu)}
.verdicts button.test[aria-pressed="true"]{background:var(--ochre)}
.verdicts button.keep[aria-pressed="true"]{background:var(--ok)}
.verdicts button.idk[aria-pressed="true"] {background:var(--faint)}
.k-out b{color:var(--zhu); background:var(--zhu-soft)}
.k-test b{color:var(--ochre); background:var(--ochre-soft)}
.k-keep b{color:var(--ok); background:var(--ok-soft)}
.k-idk b{color:var(--muted); background:var(--sunk)}
"""

PAGE_JS = r"""
const BODY = `
<header class="top">
  <div class="top-in">
    <span class="brand">图块出库裁决台</span>
    <span class="save" id="save" data-s="idle">本机</span>
    <span class="count" id="count">—</span>
  </div>
  <div class="bar"><i id="prog"></i></div>
</header>
<main class="wrap">
  <details class="intro" id="intro" open>
    <summary>怎么裁</summary>
    <p>判的不是字认得对不对，是<b>这块图能不能用</b>。左边是原图块，右边是
       <b>归一化后的 64×64</b>——那才是匹配算法真正看到的东西。残留的害处主要走这条路：
       一条离字身几十像素的细线把墨框撑大，字就被缩到角落里去了。</p>
    <p>卡片<b>不显示</b>它是被哪条判据挑出来的，顺序也是打乱的——显示了就等于
       提前告诉你答案，那这批裁决就没法拿来量判据的漏检率了。</p>
    <div class="rubric">
      <div class="k-out"><b>出库</b><span>残留/截断重到这块图不能用——从数据集里降级或剔除</span></div>
      <div class="k-test"><b>进测试集</b><span>有缺陷，但正好留着当质量判据的金标</span></div>
      <div class="k-keep"><b>留着</b><span>干净，可用</span></div>
      <div class="k-idk"><b>拿不准</b><span>看不出来</span></div>
    </div>
  </details>
  <div class="ctrl">
    <div class="seg" id="filter" role="group" aria-label="筛选">
      <button data-f="all" aria-pressed="true">全部</button>
      <button data-f="todo" aria-pressed="false">未裁</button>
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

const rowId = r => r.iid;
let filter = 'all';
function visibleRows(){
  return D.rows.filter(r => filter === 'all' ? true
    : filter === 'done' ? !!verdictOf(r.iid) : !verdictOf(r.iid));
}
function card(r){
  const v = verdictOf(r.iid);
  const btn = (k, t) => `<button class="${k}" data-v="${k}" aria-pressed="${v===k}">${t}</button>`;
  const [book, page, col, idx] = r.iid.split(':');
  return `<article class="card" data-id="${r.iid}"${v?` data-v="${v}"`:''}>
    <div class="ch">
      <span class="glyph">${esc(r.char)}</span>
      <span class="tags">
        <span class="tag">${esc(book)}</span>
        <span class="tag${r.tier==='degraded'?' deg':''}">${r.tier==='degraded'?'漫漶':'清晰'}</span>
        <span class="cid">${page}:${col}:${idx}</span>
      </span>
    </div>
    <div class="two">
      <figure><span class="tile"><img data-src="p:${r.iid}" alt="原图块" decoding="async"></span>
        <span class="cap">原图块</span></figure>
      <figure><span class="tile n"><img data-src="n:${r.iid}" alt="归一化" decoding="async"></span>
        <span class="cap">归一 64×64</span></figure>
    </div>
    <div class="verdicts">${btn('out','出库')}${btn('test','进测试集')}${btn('keep','留着')}${btn('idk','拿不准')}</div>
  </article>`;
}
function payload(){
  return D.rows.filter(r => verdictOf(r.iid)).map(r => JSON.stringify({
    instance_id: r.iid, verdict: verdictOf(r.iid), char: r.char,
    book: r.book, tier: r.tier
  })).join('\n');
}
let afterVerdict = () => { if (filter !== 'all') setTimeout(draw, 180); };
document.addEventListener('click', e => {
  const f = e.target.closest('#filter button'); if (!f) return;
  filter = f.dataset.f;
  [...f.parentElement.children].forEach(x => x.setAttribute('aria-pressed', String(x === f)));
  draw();
});
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="../open-guji-dataset/glyph-match/pairs")
    ap.add_argument("--verdicts", default="artifacts/match_inversion_verdicts.jsonl")
    ap.add_argument("--seed", default="artifacts/glyph_evict_verdicts.jsonl")
    ap.add_argument("--out", default="artifacts/glyph_evict_review.html")
    ap.add_argument("--cards", default="artifacts/glyph_evict_cards.jsonl")
    args = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _review_shell import render  # noqa: E402

    out = gray_sources()
    rows = pick(Path(args.dataset), Path(args.verdicts), out)
    imgs: dict[str, str] = {}
    kept = []
    for r in rows:
        g = load_gray(r["iid"], out)
        if g is None:
            continue
        imgs[f"p:{r['iid']}"] = thumb(g)
        imgs[f"n:{r['iid']}"] = norm_thumb(g)
        kept.append(r)
    Path(args.cards).write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in kept) + "\n",
        encoding="utf-8")

    # 顺序打乱：分层挨着排会让人先看到一串坏的，锚定后面的判断
    random.Random(SEED + 1).shuffle(kept)

    verdicts = {}
    seed = Path(args.seed)
    if seed.exists():
        for line in seed.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                verdicts[r["instance_id"]] = {"v": r["verdict"], "t": 1}

    payload = {"rows": kept, "imgs": imgs, "verdicts": verdicts}
    html = render(TITLE, "guji-evict-v1",
                  {"out": "出库", "test": "进测试集", "keep": "留着", "idk": "拿不准"},
                  CSS, PAGE_JS, payload)
    Path(args.out).write_text(html, encoding="utf-8")
    lay = defaultdict(int)
    for r in kept:
        lay[r["layer"]] += 1
    print(f"卡 {len(kept)} {dict(lay)}  图 {len(imgs)}  已嵌裁决 {len(verdicts)}")
    print(f"→ {args.out}  ({Path(args.out).stat().st_size/1e6:.2f} MB)")


if __name__ == "__main__":
    main()
