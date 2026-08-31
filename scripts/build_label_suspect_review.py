# -*- coding: utf-8 -*-
"""疑似错标裁决台：一个实例反复只跟同一个字撞，多半是它自己标错了。

    PYTHONPATH=. python scripts/build_label_suspect_review.py --dump /tmp/pairs.npz

## 怎么挖的

库匹配的覆盖率天花板是**异字对分数的上尾**：硬约束 `precision ≥ 0.999` 逼着
闸站在 0.9985，只放行 5% 的真同字对。去看那条尾巴里到底是什么，发现签名很齐：

> **一个实例在高分异字对里反复出现，而且几乎只跟同一个字撞。**

`vol02:28:6:12` 标「一」、跟「七」撞 5 次纯度 1.0——调出原图一看，那就是个
「七」。这不是算法把两个字弄混了，是**金标错了**，而一条错标会跟那个字的
所有刻例各撞一次，全挤在尾巴顶上。

判据：`cov ≥ th` 的异字对里出现 ≥ `min_hits` 次，且 ≥80% 的碰撞来自同一个字。

## 为什么值得单独裁

留出口径实测（pairs knn 层）：

    现状                        闸 0.9985  recall 0.0532
    只修 20 个疑似错标            闸 0.9895  recall 0.3131   5.9×
    修错标 + 字体形近护栏          闸 0.9785  recall 0.5974  11.2×

**改几十条标签，覆盖率就是 6 倍。** 这是眼下性价比最高的一件事。

## 卡片怎么读

三格：中间是待判实例，左边是它**现在标的那个字**的别的刻例，右边是它**反复
撞的那个字**的刻例。判的是「这块图到底是哪个字」——像右边就是标错了。
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from open_guji_cv.clustering.exclusions import excluded_ids  # noqa: E402

PIPE_REV = "502fa04d0c"
THUMB = 150
GRAY_STEP = 16
TITLE = "疑似错标裁决台"
N_REF = 2          # 每边放几个参照刻例


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


def mine(dump: Path, dataset: Path, th: float, min_hits: int, purity: float):
    data = json.loads((dataset / "expected.json").read_text(encoding="utf-8"))
    meta = {r["instance_id"]: r for r in data["instances"]}
    ex = excluded_ids()
    z = np.load(dump, allow_pickle=True)
    pairs, cov = list(z["pairs"]), z["cov"]
    hit: dict[str, Counter] = defaultdict(Counter)
    peak: dict[str, float] = defaultdict(float)
    for k, p in enumerate(pairs):
        if p["origin"] != "knn" or p["a"] in ex or p["b"] in ex or cov[k] < th:
            continue
        ca, cb = meta[p["a"]]["char"], meta[p["b"]]["char"]
        if ca == cb:
            continue
        hit[p["a"]][cb] += 1
        hit[p["b"]][ca] += 1
        peak[p["a"]] = max(peak[p["a"]], float(cov[k]))
        peak[p["b"]] = max(peak[p["b"]], float(cov[k]))
    out = []
    for iid, cnt in hit.items():
        n = sum(cnt.values())
        top, tn = cnt.most_common(1)[0]
        if n >= min_hits and tn / n >= purity:
            out.append({"iid": iid, "char": meta[iid]["char"], "rival": top,
                        "hits": n, "purity": round(tn / n, 2),
                        "peak": round(peak[iid], 4),
                        "book": meta[iid]["book"], "tier": meta[iid]["tier"]})
    out.sort(key=lambda r: (-r["hits"], -r["peak"]))
    return out, meta, ex


def refs(char: str, meta: dict, ex, skip: set, k: int) -> list[str]:
    """挑几个参照刻例：排除名单里的不要，疑似错标的也不要（它们本身可疑）。"""
    cand = [i for i, r in meta.items()
            if r["char"] == char and i not in ex and i not in skip]
    cand.sort(key=lambda i: meta[i]["ink_ratio"])
    if not cand:
        return []
    mid = len(cand) // 2
    picks = [cand[mid]]
    if len(cand) > 1:
        picks.append(cand[max(0, mid - len(cand) // 4)])
    return picks[:k]


CSS = """
.card{background:var(--surface); border:1px solid var(--rule); border-radius:3px;
  box-shadow:var(--shadow); padding:12px 12px 11px; border-left:3px solid var(--rule-hard);}
.card[data-v="fix"]  {border-left-color:var(--zhu)}
.card[data-v="ok"]   {border-left-color:var(--ok)}
.card[data-v="other"]{border-left-color:var(--ochre)}
.card[data-v="idk"]  {border-left-color:var(--faint)}
.ch{display:flex; align-items:center; gap:8px; margin-bottom:9px;}
.q{font-family:var(--serif); font-weight:700; font-size:20px; line-height:1;
  display:flex; align-items:center; gap:7px;}
.q .vs{font-family:var(--sans); font-size:12px; color:var(--faint); font-weight:400;}
.q .r{color:var(--zhu)}
.tags{margin-left:auto; display:flex; gap:5px; align-items:center;}
.tag{font-family:var(--mono); font-size:10.5px; color:var(--muted);
  border:1px solid var(--rule); border-radius:2px; padding:1px 5px; white-space:nowrap;}
.tag.deg{color:var(--ochre); border-color:var(--ochre)}
.cid{font-family:var(--mono); font-size:10.5px; color:var(--faint);}
.strip{display:grid; grid-template-columns:1fr 1.15fr 1fr; gap:8px; align-items:start;}
.side{display:grid; gap:4px;}
.side .row{display:grid; grid-auto-flow:column; gap:4px;}
.tile{background:var(--tile); border:1px solid var(--rule); border-radius:2px;
  aspect-ratio:1; overflow:hidden; display:grid; place-items:center;}
.tile img{width:100%; height:100%; object-fit:contain; display:block}
.mid .tile{border-color:var(--indigo); box-shadow:0 0 0 1px var(--indigo) inset;}
.rival .tile{border-color:var(--zhu)}
.cap{font-size:10.5px; letter-spacing:.03em; color:var(--faint); text-align:center;
  line-height:1.25;}
.mid .cap{color:var(--indigo); font-weight:600}
.rival .cap{color:var(--zhu); font-weight:600}
.cap b{font-family:var(--serif); font-size:14px; font-weight:700}
.ev{margin:9px 0 0; font-family:var(--mono); font-size:11.5px; color:var(--muted);
  font-variant-numeric:tabular-nums; display:flex; gap:12px; flex-wrap:wrap;}
.verdicts{display:grid; grid-template-columns:repeat(4,1fr); gap:6px; margin-top:10px;}
.verdicts button{min-height:44px; border:1px solid var(--rule-hard); border-radius:3px;
  background:var(--surface); color:var(--muted); cursor:pointer;
  font-family:var(--sans); font-size:12.5px; font-weight:500; padding:0 2px;}
.verdicts button:active{background:var(--sunk)}
.verdicts button:focus-visible{outline:2px solid var(--indigo); outline-offset:2px;}
.verdicts button[aria-pressed="true"]{color:var(--on-solid); border-color:transparent;}
.verdicts button.fix[aria-pressed="true"]  {background:var(--zhu)}
.verdicts button.ok[aria-pressed="true"]   {background:var(--ok)}
.verdicts button.other[aria-pressed="true"]{background:var(--ochre)}
.verdicts button.idk[aria-pressed="true"]  {background:var(--faint)}
.verdicts b{font-family:var(--serif); font-weight:700}
.k-fix b{color:var(--zhu); background:var(--zhu-soft)}
.k-ok b{color:var(--ok); background:var(--ok-soft)}
.k-other b{color:var(--ochre); background:var(--ochre-soft)}
.k-idk b{color:var(--muted); background:var(--sunk)}
"""

PAGE_JS = r"""
const BODY = `
<header class="top">
  <div class="top-in">
    <span class="brand">疑似错标裁决台</span>
    <span class="save" id="save" data-s="idle">本机</span>
    <span class="count" id="count">—</span>
  </div>
  <div class="bar"><i id="prog"></i></div>
</header>
<main class="wrap">
  <details class="intro" id="intro" open>
    <summary>怎么裁</summary>
    <p>中间蓝框是<b>待判的那块图</b>。左边是它<b>现在标的那个字</b>的别的刻例，
       右边红框是它<b>反复撞上的那个字</b>的刻例。判的只有一件事：
       <b>这块图到底是哪个字。</b></p>
    <p>这批是这么挖出来的：一个实例在高分异字对里反复出现、而且几乎只跟同一个字撞——
       那多半不是算法把两个字弄混了，是<b>它自己标错了</b>，
       于是跟那个字的每个刻例各撞一次，全挤在分数尾巴的顶上。</p>
    <div class="rubric">
      <div class="k-fix"><b>标错了</b><span>它其实是右边那个字——改标签</span></div>
      <div class="k-ok"><b>标的没错</b><span>确实是左边这个字，两个字就是长得像</span></div>
      <div class="k-other"><b>都不是</b><span>两边都不对，或者这块图根本不能用</span></div>
      <div class="k-idk"><b>拿不准</b><span>看不出来</span></div>
    </div>
  </details>
  <div class="ctrl">
    <div class="seg" id="filter" role="group" aria-label="筛选">
      <button data-f="todo" aria-pressed="true">未裁</button>
      <button data-f="all" aria-pressed="false">全部</button>
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
let filter = 'todo';
function visibleRows(){
  return D.rows.filter(r => filter === 'all' ? true
    : filter === 'done' ? !!verdictOf(r.iid) : !verdictOf(r.iid));
}
const img = k => `<span class="tile"><img data-src="${k}" alt="" decoding="async"></span>`;
function card(r){
  const v = verdictOf(r.iid);
  const btn = (k,t) => `<button class="${k}" data-v="${k}" aria-pressed="${v===k}">${t}</button>`;
  const [book, page, col, idx] = r.iid.split(':');
  return `<article class="card" data-id="${r.iid}"${v?` data-v="${v}"`:''}>
    <div class="ch">
      <span class="q"><span>${esc(r.char)}</span><span class="vs">反复撞上</span>
        <span class="r">${esc(r.rival)}</span></span>
      <span class="tags">
        <span class="tag">${esc(book)}</span>
        <span class="tag${r.tier==='degraded'?' deg':''}">${r.tier==='degraded'?'漫漶':'清晰'}</span>
        <span class="cid">${page}:${col}:${idx}</span>
      </span>
    </div>
    <div class="strip">
      <figure class="side" style="margin:0">
        <span class="row">${r.ref_char.map(img).join('')}</span>
        <span class="cap">现标 <b>${esc(r.char)}</b> 的别的刻例</span></figure>
      <figure class="side mid" style="margin:0">
        <span class="row">${img('q:'+r.iid)}</span>
        <span class="cap">待判</span></figure>
      <figure class="side rival" style="margin:0">
        <span class="row">${r.ref_rival.map(img).join('')}</span>
        <span class="cap"><b>${esc(r.rival)}</b> 的刻例</span></figure>
    </div>
    <div class="ev"><span>撞 ${r.hits} 次</span><span>纯度 ${r.purity}</span>
      <span>最高分 ${r.peak.toFixed(4)}</span></div>
    <div class="verdicts">${btn('fix','标错了')}${btn('ok','标的没错')}${btn('other','都不是')}${btn('idk','拿不准')}</div>
  </article>`;
}
function payload(){
  return D.rows.filter(r => verdictOf(r.iid)).map(r => JSON.stringify({
    instance_id: r.iid, verdict: verdictOf(r.iid),
    char: r.char, rival: r.rival, hits: r.hits, peak: r.peak
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
    ap.add_argument("--dump", required=True)
    ap.add_argument("--th", type=float, default=0.97)
    ap.add_argument("--min-hits", type=int, default=2)
    ap.add_argument("--purity", type=float, default=0.8)
    ap.add_argument("--seed", default="artifacts/label_suspect_verdicts.jsonl")
    ap.add_argument("--out", default="artifacts/label_suspect_review.html")
    args = ap.parse_args()

    from _review_shell import render  # noqa: E402

    rows, meta, ex = mine(Path(args.dump), Path(args.dataset),
                          args.th, args.min_hits, args.purity)
    skip = {r["iid"] for r in rows}
    out = gray_root()
    imgs: dict[str, str] = {}

    def put(iid, key=None):
        g = load_gray(iid, out)
        if g is None:
            return None
        k = key or iid
        imgs.setdefault(k, thumb(g))
        return k

    kept = []
    for r in rows:
        if put(r["iid"], "q:" + r["iid"]) is None:
            continue
        r["ref_char"] = [k for k in
                         (put(i) for i in refs(r["char"], meta, ex, skip, N_REF)) if k]
        r["ref_rival"] = [k for k in
                          (put(i) for i in refs(r["rival"], meta, ex, skip, N_REF)) if k]
        kept.append(r)

    verdicts = {}
    seed = Path(args.seed)
    if seed.exists():
        for line in seed.read_text(encoding="utf-8").splitlines():
            if line.strip():
                x = json.loads(line)
                verdicts[x["instance_id"]] = {"v": x["verdict"], "t": 1}

    html = render(TITLE, "guji-labelsuspect-v1",
                  {"fix": "标错了", "ok": "标的没错", "other": "都不是", "idk": "拿不准"},
                  CSS, PAGE_JS, {"rows": kept, "imgs": imgs, "verdicts": verdicts})
    Path(args.out).write_text(html, encoding="utf-8")
    Path("artifacts/label_suspect_cards.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in kept) + "\n",
        encoding="utf-8")
    print(f"卡 {len(kept)}（口径 cov≥{args.th} 撞≥{args.min_hits} 纯度≥{args.purity}）"
          f"  图 {len(imgs)}  已嵌裁决 {len(verdicts)}")
    print("  最常见：", ", ".join(f"{a}→{b}×{n}" for (a, b), n in
                                 Counter((r["char"], r["rival"]) for r in kept).most_common(10)))
    print(f"→ {args.out}  ({Path(args.out).stat().st_size/1e6:.2f} MB)")


if __name__ == "__main__":
    main()
