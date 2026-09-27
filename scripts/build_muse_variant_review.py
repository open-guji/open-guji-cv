# -*- coding: utf-8 -*-
"""muse 新增异体审查台：把 muse 试点判「同一个字」的候选拼成人裁审查页。

    PYTHONPATH=. python scripts/build_muse_variant_review.py

## 为什么要这一页

任务书：overview `进度/字形库/任务书-H-muse新增异体71对审查页.md`。
muse（GLM）按二分口径跑完 bxgb 全部 1,406 对候选字，判「是」158 对——但生僻字上
会编字书依据（上𠀉、三𠀉 自相矛盾就是实例），**进 `config/variants/` 前必须逐条人审**。

候选源文件（`scripts/experiments/muse_variant_pilot/variant_same_bin_muse.jsonl`，
1,406 行，含 `muse.same_char`/`muse.basis` 等字段）复制自 cv 分支
`claude/relaxed-maxwell-vokn4m`，本脚本只读它，不重新调 muse。

## 两节卡片

- **新增**（`muse.same_char == "是"` 且这对字**不在** `variants.json` 里）：
  71 对，覆盖 98 格，按覆盖格数从多到少排，40 卡一页分两页。
- **弱边复核**（`muse.same_char == "是"` 且**已在**表里、但现有来源只有单源
  或 `hydzd-borrowed`(通假)）：本脚本实测 16 对（任务书按上游 done 单估计写的是
  24 对——用户裁定按 `子会话须知` 铁律 5「以实测为准」，口径见脚本内
  `is_weak()`；两个数字的出入已写进 done 单）。

## 图从哪来

真实刻例图查的是 **bxgb（北行日錄）自己的字形库**（`GUJI_WORKSPACE` 指到那本书、
`GUJI_GLYPH_DB` 指到沙箱重建的索引，不碰任何正式库）：
`open_guji_cv.clustering.glyph_ledger.char_detail()` 取实例，
`console.routers.glyphlib._crop_to_ink()` 同一份裁到墨迹的显示逻辑。
书里没有这个字的刻例就退到 `fonts/` 字体渲染（iming→jigmo→genryu→kangxi→…），
卡上标「字体渲染代替」。

字头本身（表头的 `字 vs 字`、"已有关联"列表）也全部走同一套取图逻辑渲成小图
——**不能用原始文字**：这批字里不少是 Unicode 扩展 B/C 区字符，浏览器系统字体
渲不出来会变成空白方块，样例见负结果记录。

## 出题纪律

- 卡片不显示 muse 的判断结论以外的任何算法评分——判的是"人怎么看"。
- 附上该字在 `variants.json` 里**已有**的其它关联（不含本对），
  帮人发现矛盾（上𠀉 案例：𠀉 早已关联到"丘"，与 muse 说的"上"冲突）。
- 上下文用例明确标"自动文本，非真值"，不能当证据用，只帮助理解字义。

裁决自动存回页面（`artifact` 能力，files 形式重发 index.html），
`Artifact action:"read"` 读 `#data` 的 `verdicts` 即可回收
（`.claude/skills/review-artifact/scripts/harvest_verdicts.py`）。
"""
from __future__ import annotations

import argparse
import base64
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from open_guji_cv.core.workspace import glyph_db_path  # noqa: E402
from open_guji_cv.clustering.glyph_ledger import char_detail  # noqa: E402
from open_guji_cv.clustering.glyph_selfcheck import font_renderer  # noqa: E402
from open_guji_cv.console.routers.glyphlib import _crop_to_ink  # noqa: E402

TITLE = "muse 新增异体审查台"
KEY = "muse-variant-review-v1"
FONT_ORDER = ["iming", "jigmo", "genryu", "kangxi", "genwan", "genyo"]
MAX_INSTANCES = 4
THUMB = 176
LABEL_THUMB = 68
PAGE_SIZE = 40


def png_b64(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    assert ok
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def thumb_bytes(png_bytes: bytes, size: int = THUMB) -> str:
    img = cv2.imdecode(np.frombuffer(png_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return ""
    h, w = img.shape
    s = size / max(h, w)
    if s < 1:
        img = cv2.resize(img, (max(1, round(w * s)), max(1, round(h * s))),
                          interpolation=cv2.INTER_AREA)
    return png_b64(img)


def load_variants(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))["pairs"]


def in_table(pairs: dict, a: str, b: str):
    if a in pairs and b in pairs[a]:
        return pairs[a][b]
    if b in pairs and a in pairs[b]:
        return pairs[b][a]
    return None


def related(pairs: dict, char: str, exclude: str) -> list[tuple[str, list[str]]]:
    """char 在 variants.json 里已有的其它关联（不含本对里的另一半）。"""
    out = []
    for other, srcs in pairs.get(char, {}).items():
        if other != exclude:
            out.append((other, srcs))
    for a, edges in pairs.items():
        if char in edges and a != char and a != exclude:
            out.append((a, edges[char]))
    return out


def is_weak(srcs: list[str]) -> bool:
    """弱边＝只有单源，或来源里带 hydzd-borrowed（通假）。"""
    return "hydzd-borrowed" in srcs or len(set(srcs)) < 2


CSS = """
.seg2{margin-top:8px}
.card{background:var(--surface); border:1px solid var(--rule); border-radius:3px;
  box-shadow:var(--shadow); padding:12px 12px 11px; border-left:3px solid var(--rule-hard);}
.card[data-v="in"]  {border-left-color:var(--ok)}
.card[data-v="out"] {border-left-color:var(--zhu)}
.card[data-v="idk"] {border-left-color:var(--faint)}
.ch{display:flex; align-items:center; gap:9px; margin-bottom:6px; flex-wrap:wrap;}
.glyphs{display:flex; align-items:center; gap:5px;}
.glyphs img{width:34px; height:34px; object-fit:contain; background:var(--tile);
  border:1px solid var(--rule); border-radius:2px;}
.glyphs .vs{font-size:12px; font-weight:400; color:var(--faint); margin:0 1px;}
.tags{flex:1 1 auto; min-width:0; display:flex; gap:5px; align-items:center; flex-wrap:wrap;}
.tag{font-family:var(--mono); font-size:10.5px; color:var(--muted);
  border:1px solid var(--rule); border-radius:2px; padding:1px 5px; white-space:nowrap;}
.tag.cells{color:var(--indigo); border-color:var(--indigo-soft); background:var(--indigo-soft)}
.tag.weak{color:var(--ochre); border-color:var(--ochre-soft); background:var(--ochre-soft)}
.two{display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:8px;}
.col h4{margin:0 0 5px; font-size:12px; font-weight:600; color:var(--muted);
  display:flex; align-items:center; gap:6px;}
.col h4 img.g{width:22px; height:22px; object-fit:contain; background:var(--tile);
  border:1px solid var(--rule); border-radius:2px;}
.pics{display:flex; gap:5px; flex-wrap:wrap;}
.tile{width:64px; aspect-ratio:1; background:var(--tile); border:1px solid var(--rule);
  border-radius:2px; overflow:hidden; display:grid; place-items:center; flex:0 0 auto;}
.tile img{width:100%; height:100%; object-fit:contain; display:block;}
.fontnote{font-size:10px; color:var(--ochre); margin-top:3px;}
.basis{margin:9px 0 0; padding:8px 10px; background:var(--sunk); border-radius:3px;
  font-size:12.5px; color:var(--ink); line-height:1.55;}
.basis b{color:var(--muted); font-weight:600; font-size:11px;
  display:block; margin-bottom:2px; letter-spacing:.03em;}
.canon{font-size:11px; color:var(--muted); margin-top:5px;}
.rel{margin-top:6px; font-size:11.5px; color:var(--muted); display:flex;
  align-items:center; gap:5px; flex-wrap:wrap;}
.rel b{color:var(--faint); font-weight:500;}
.rel .relchar{display:inline-flex; align-items:center; gap:2px;}
.rel .relchar img{width:16px; height:16px; object-fit:contain; background:var(--tile);
  border:1px solid var(--rule); border-radius:1px; vertical-align:-3px;}
.ctxbox{margin-top:7px;}
.ctxbox summary{font-size:11px; color:var(--faint); cursor:pointer;}
.ctxbox p{margin:4px 0 0; font-size:12px; color:var(--muted); font-family:var(--serif);}
.verdicts{display:grid; grid-template-columns:repeat(3,1fr); gap:6px; margin-top:11px;}
.verdicts button{min-height:44px; border:1px solid var(--rule-hard); border-radius:3px;
  background:var(--surface); color:var(--muted); cursor:pointer;
  font-family:var(--sans); font-size:13px; font-weight:500; padding:0 2px;}
.verdicts button:active{background:var(--sunk)}
.verdicts button:focus-visible{outline:2px solid var(--indigo); outline-offset:2px;}
.verdicts button[aria-pressed="true"]{color:var(--on-solid); border-color:transparent;}
.verdicts button.in[aria-pressed="true"] {background:var(--ok)}
.verdicts button.out[aria-pressed="true"]{background:var(--zhu)}
.verdicts button.idk[aria-pressed="true"]{background:var(--faint)}
.k-in b{color:var(--ok); background:var(--ok-soft)}
.k-out b{color:var(--zhu); background:var(--zhu-soft)}
.k-idk b{color:var(--muted); background:var(--sunk)}
"""

PAGE_JS = r"""
const SECTIONS = {
  new1: {label:'新增 1/2', match: r => r.sec==='new' && r.pageIdx===1},
  new2: {label:'新增 2/2', match: r => r.sec==='new' && r.pageIdx===2},
  weak: {label:'弱边复核', match: r => r.sec==='weak'},
};

const BODY = `
<header class="top">
  <div class="top-in">
    <span class="brand">muse 新增异体审查台</span>
    <span class="save" id="save" data-s="idle">本机</span>
    <span class="count" id="count">—</span>
  </div>
  <div class="bar"><i id="prog"></i></div>
</header>
<main class="wrap">
  <details class="intro" id="intro" open>
    <summary>怎么裁</summary>
    <p>每张卡是 muse 判「同一个字」的一对字。左右各是该字在<b>本书（北行日錄）</b>
       里的真实刻例图（取不到刻例的字用字体渲染代替，卡上会注明「字体渲染」）。
       卡上还附了 muse 给出的依据原文，以及这个字在异体表里<b>已有</b>的其它关联
       （帮你看出矛盾，比如同一个 𠀉 不能同时等于「上」又等于「三」）。</p>
    <p><b>「新增」两页</b>：muse 判定同字、但目前<b>不在</b> <code>config/variants/variants.json</code>
       里的 71 对，按覆盖格数从多到少排，按 40 卡一页分成两页。</p>
    <p><b>「弱边复核」</b>：已经在表里、但只有单源或通假这类弱证据支撑的对
       （muse 认为是同字，可供参考要不要升级成严格异体）。</p>
    <div class="rubric">
      <div class="k-in"><b>同一个字，进表</b><span>认可 muse 的判断（或认可升级为严格异体）</span></div>
      <div class="k-out"><b>不是</b><span>muse 判错了，不进表 / 不升级</span></div>
      <div class="k-idk"><b>拿不准</b><span>证据不够，留给下一轮</span></div>
    </div>
  </details>
  <div class="ctrl">
    <div class="seg" id="section" role="group" aria-label="分节">
      <button data-sec="new1" aria-pressed="true">新增 1/2</button>
      <button data-sec="new2" aria-pressed="false">新增 2/2</button>
      <button data-sec="weak" aria-pressed="false">弱边复核</button>
    </div>
  </div>
  <div class="ctrl">
    <div class="seg2 seg" id="filter" role="group" aria-label="筛选">
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

const rowId = r => r.id;
let section = 'new1';
let filter = 'all';

function visibleRows(){
  const bySec = D.rows.filter(SECTIONS[section].match);
  if (filter === 'all') return bySec;
  const done = filter === 'done';
  return bySec.filter(r => !!verdictOf(r.id) === done);
}

function picsHtml(pics, font){
  const tiles = pics.map(k => `<span class="tile"><img data-src="${esc(k)}" alt="" decoding="async"></span>`).join('');
  return tiles + (font ? `<div class="fontnote">字体渲染代替（${esc(font)}）</div>` : '');
}
function relHtml(rel){
  if (!rel || !rel.length) return '';
  const items = rel.slice(0, 6).map(x =>
    `<span class="relchar"><img data-src="${esc(x.lbl)}" alt="">(${x.srcs.length})</span>`).join('、');
  return `<div class="rel"><b>已有关联：</b>${items}</div>`;
}

function card(r){
  const v = verdictOf(r.id);
  const btn = (k, t) => `<button class="${k}" data-v="${k}" aria-pressed="${v===k}">${t}</button>`;
  const weakTag = r.sec === 'weak'
    ? `<span class="tag weak">现有来源 ${esc((r.existing_srcs||[]).join('/'))}</span>` : '';
  const ctx = (r.ctx||[]).map(c => `<p>${esc(c)}</p>`).join('');
  return `<article class="card" data-id="${r.id}"${v?` data-v="${v}"`:''}>
    <div class="ch">
      <span class="glyphs"><img data-src="${esc(r.lbl_a)}" alt="${esc(r.a)}" title="U+${r.a.codePointAt(0).toString(16).toUpperCase()}">
        <span class="vs">vs</span><img data-src="${esc(r.lbl_b)}" alt="${esc(r.b)}" title="U+${r.b.codePointAt(0).toString(16).toUpperCase()}"></span>
      <span class="tags">
        <span class="tag cells">覆盖 ${r.cells} 格</span>
        ${weakTag}
      </span>
    </div>
    <div class="two">
      <div class="col"><h4><img class="g" data-src="${esc(r.lbl_a)}" alt="${esc(r.a)}">本书刻例${r.n_real_a?`（${r.n_real_a}）`:''}</h4>
        <div class="pics">${picsHtml(r.pics_a, r.font_a)}</div>
        ${relHtml(r.rel_a)}
      </div>
      <div class="col"><h4><img class="g" data-src="${esc(r.lbl_b)}" alt="${esc(r.b)}">本书刻例${r.n_real_b?`（${r.n_real_b}）`:''}</h4>
        <div class="pics">${picsHtml(r.pics_b, r.font_b)}</div>
        ${relHtml(r.rel_b)}
      </div>
    </div>
    <div class="basis"><b>muse 依据${r.tongjia?'（另标通假）':''}</b>${esc(r.basis)}
      <div class="canon">muse 认为正字：${esc(r.canonical==='a'?r.a:(r.canonical==='b'?r.b:'未定'))}</div>
    </div>
    ${ctx ? `<details class="ctxbox"><summary>本书上下文用例（自动文本，非真值）</summary>${ctx}</details>` : ''}
    <div class="verdicts">${btn('in','同一个字，进表')}${btn('out','不是')}${btn('idk','拿不准')}</div>
  </article>`;
}

function payload(){
  return D.rows.filter(r => verdictOf(r.id)).map(r => JSON.stringify({
    id: r.id, sec: r.sec, a: r.a, b: r.b, cells: r.cells, verdict: verdictOf(r.id)
  })).join('\n');
}
let afterVerdict = () => { if (filter !== 'all') setTimeout(draw, 180); };
document.addEventListener('click', e => {
  const s = e.target.closest('#section button');
  if (s){
    section = s.dataset.sec;
    [...s.parentElement.children].forEach(x => x.setAttribute('aria-pressed', String(x === s)));
    draw();
    return;
  }
  const f = e.target.closest('#filter button');
  if (f){
    filter = f.dataset.f;
    [...f.parentElement.children].forEach(x => x.setAttribute('aria-pressed', String(x === f)));
    draw();
  }
});
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--muse", default="scripts/experiments/muse_variant_pilot/variant_same_bin_muse.jsonl")
    ap.add_argument("--variants", default="config/variants/variants.json")
    ap.add_argument("--out", default="artifacts/muse_variant_review.html")
    ap.add_argument("--cards", default="artifacts/muse_variant_cards.jsonl")
    args = ap.parse_args()

    sys.path.insert(0, str(REPO / "scripts"))
    from _review_shell import render  # noqa: E402

    pairs = load_variants(REPO / args.variants)
    rows = [json.loads(l) for l in (REPO / args.muse).open(encoding="utf-8")]
    yes = [r for r in rows if r["muse"]["same_char"] == "是"]

    new_pairs, weak_pairs = [], []
    for r in yes:
        a, b = r["a"], r["b"]
        srcs = in_table(pairs, a, b)
        if srcs is None:
            new_pairs.append(r)
        elif is_weak(srcs):
            weak_pairs.append((r, srcs))
    new_pairs.sort(key=lambda r: -r["cells"])
    weak_pairs.sort(key=lambda r: -r[0]["cells"])
    print(f"new={len(new_pairs)} cells={sum(r['cells'] for r in new_pairs)}  "
          f"weak={len(weak_pairs)} cells={sum(r[0]['cells'] for r in weak_pairs)}")

    db_path = glyph_db_path()
    print("glyph db:", db_path)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    font_cache: dict[str, np.ndarray | None] = {}

    def patch_png(instance_id: str) -> bytes | None:
        row = conn.execute("SELECT patch_png FROM instances WHERE instance_id=?",
                            (instance_id,)).fetchone()
        return bytes(row[0]) if row else None

    def real_instances(char: str, n: int = MAX_INSTANCES) -> list[str]:
        try:
            d = char_detail(db_path, char)
        except Exception:
            return []
        ex = [e for e in d["exemplars"] if not e["duplicate"]]
        ex.sort(key=lambda e: (e.get("fidelity") == "degraded", e["instance_id"]))
        out = []
        for e in ex:
            if patch_png(e["instance_id"]):
                out.append(e["instance_id"])
            if len(out) >= n:
                break
        return out

    def font_fallback(char: str) -> tuple[str, np.ndarray] | None:
        for font in FONT_ORDER:
            key = f"{font}:{char}"
            if key not in font_cache:
                r = font_renderer(font)
                font_cache[key] = r.render(char) if r and len(char) == 1 else None
            if font_cache[key] is not None:
                return font, font_cache[key]
        return None

    imgs: dict[str, str] = {}
    fallback_count = {"new": 0, "weak": 0}
    none_count = {"new": 0, "weak": 0}
    label_cache: dict[str, str] = {}

    def label_key(char: str) -> str:
        """小字头图：本书有刻例用刻例，没有就字体渲染，同一字全页只算一次。
        不能用原始文字——这批字里不少是 Ext-B/C，系统字体渲不出来会变空白方块。"""
        if char in label_cache:
            return label_cache[char]
        k = f"lb:{char}"
        insts = real_instances(char, n=1)
        if insts:
            imgs[k] = thumb_bytes(_crop_to_ink(patch_png(insts[0])), size=LABEL_THUMB)
        else:
            fb = font_fallback(char)
            if fb:
                _, img = fb
                ok, buf = cv2.imencode(".png", img)
                imgs[k] = thumb_bytes(_crop_to_ink(buf.tobytes()), size=LABEL_THUMB)
            else:
                imgs[k] = ""
        label_cache[char] = k
        return k

    def gather_char(char: str, sec_tag: str) -> dict:
        key_prefix = f"c:{char}"
        insts = real_instances(char)
        pics = []
        for iid in insts:
            k = f"{key_prefix}:{iid}"
            if k not in imgs:
                imgs[k] = thumb_bytes(_crop_to_ink(patch_png(iid)))
            pics.append(k)
        used_font = None
        if not pics:
            fb = font_fallback(char)
            if fb:
                font, img = fb
                k = f"{key_prefix}:font:{font}"
                if k not in imgs:
                    ok, buf = cv2.imencode(".png", img)
                    imgs[k] = thumb_bytes(_crop_to_ink(buf.tobytes()))
                pics.append(k)
                used_font = font
                fallback_count[sec_tag] += 1
            else:
                none_count[sec_tag] += 1
        return {"pics": pics, "font": used_font, "n_real": len(insts)}

    def rel_with_labels(char: str, exclude: str) -> list[dict]:
        return [{"char": c, "srcs": s, "lbl": label_key(c)}
                for c, s in related(pairs, char, exclude)]

    out_rows = []
    pid = 0
    for r in new_pairs:
        pid += 1
        a, b = r["a"], r["b"]
        ga, gb = gather_char(a, "new"), gather_char(b, "new")
        out_rows.append({
            "id": f"new{pid:03d}", "sec": "new", "a": a, "b": b,
            "lbl_a": label_key(a), "lbl_b": label_key(b),
            "cells": r["cells"], "tags": r["tags"],
            "basis": r["muse"]["basis"], "canonical": r["muse"]["canonical"],
            "tongjia": r["muse"]["tongjia"], "ctx": r["ctx"],
            "rel_a": rel_with_labels(a, b), "rel_b": rel_with_labels(b, a),
            "pics_a": ga["pics"], "pics_b": gb["pics"],
            "font_a": ga["font"], "font_b": gb["font"],
            "n_real_a": ga["n_real"], "n_real_b": gb["n_real"],
        })
    for r, srcs in weak_pairs:
        pid += 1
        a, b = r["a"], r["b"]
        ga, gb = gather_char(a, "weak"), gather_char(b, "weak")
        out_rows.append({
            "id": f"weak{pid:03d}", "sec": "weak", "a": a, "b": b,
            "lbl_a": label_key(a), "lbl_b": label_key(b),
            "cells": r["cells"], "tags": r["tags"], "existing_srcs": srcs,
            "basis": r["muse"]["basis"], "canonical": r["muse"]["canonical"],
            "tongjia": r["muse"]["tongjia"], "ctx": r["ctx"],
            "rel_a": rel_with_labels(a, b), "rel_b": rel_with_labels(b, a),
            "pics_a": ga["pics"], "pics_b": gb["pics"],
            "font_a": ga["font"], "font_b": gb["font"],
            "n_real_a": ga["n_real"], "n_real_b": gb["n_real"],
        })

    new_rows = [r for r in out_rows if r["sec"] == "new"]
    for i, r in enumerate(new_rows):
        r["pageIdx"] = 1 if i < PAGE_SIZE else 2

    Path(args.cards).write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in out_rows) + "\n",
        encoding="utf-8")
    print("fallback(font) counts:", fallback_count, "no-image counts:", none_count)
    print("total imgs:", len(imgs))

    payload = {"rows": out_rows, "imgs": imgs}
    html = render(TITLE, KEY, verdicts={}, css=CSS, page_js=PAGE_JS, payload=payload)
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"→ {args.out}  ({Path(args.out).stat().st_size/1e6:.2f} MB)  "
          f"new1={sum(1 for r in new_rows if r['pageIdx']==1)} "
          f"new2={sum(1 for r in new_rows if r['pageIdx']==2)} "
          f"weak={sum(1 for r in out_rows if r['sec']=='weak')}")


if __name__ == "__main__":
    main()
