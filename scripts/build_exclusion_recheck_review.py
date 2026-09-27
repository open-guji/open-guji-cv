# -*- coding: utf-8 -*-
"""排除名单复核页：名单上每个格，用**现在**的图块问人「还切坏吗」。

    python scripts/build_exclusion_recheck_review.py bxgb -w <workspace> [--out review/batches/x.html]

## 为什么要这一页（2026-09-20）

`config/crop_exclusions.jsonl` 按 id 排除，人裁时看的是**当时**的图块；Step2/Step4 修过截断
之后图块可能已经好了，名单却不会自己退——Step7 照样把它当排除格，9.1 文本里照样是阙文。
bxgb 155 条里 131 条是 seg_defect（truncated 94 / contaminated 37），对勘查出它们都是真字
（「舉手一揖」的 手、「十一月」的 月）。这一页把每格现在的图块（列图上 ±1 格上下文，
绿框 = Step3 格，红框 = Step4 紧框）摆出来，只问一件事：**这一格现在是不是完整的字**。

## 出题纪律

- 不印机器判断。卡上只有人自己当初的标签（truncated/contaminated/not_text）和整理本对齐
  的字（帮人判「缺没缺笔画」，不是让人认字）。
- `stratum` = 当初标签 × 格位置（首/末/中），事后按层看撤名单比例。
- id 冻在 `*_cards.jsonl`，重建页面照旧读。

裁决四档：ok = 现在是完整的字（撤名单）/ bad = 仍切坏或带残留 / nochar = 不是字 / idk = 拿不准。
收回：`harvest_verdicts.py`，然后 `scripts/apply_exclusion_recheck.py`（待写）按 ok 撤名单。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / ".claude" / "skills" / "review-artifact" / "scripts"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

TITLE = "排除名单复核"
VERDICTS = [("ok", "完整的字", "ok"), ("bad", "仍切坏/带残留", "zhu"),
            ("nochar", "不是字", "ochre"), ("idk", "拿不准", "faint")]

CSS = """
.card{background:var(--surface); border:1px solid var(--rule);
  border-left:3px solid transparent; border-radius:3px; padding:12px 13px;
  box-shadow:var(--shadow);}
""" + "".join(f'.card[data-v="{v}"]{{border-left-color:var(--{c})}}\n'
              for v, _, c in VERDICTS) + """
.card h3{margin:0; font-family:var(--serif); font-size:15px; display:flex; gap:10px; align-items:baseline;}
.card h3 .ref{font-size:22px;}
.card h3 .pos{font-size:12px; color:var(--muted); font-family:var(--sans); font-weight:400;}
.card p{margin:6px 0 0; font-size:13px; color:var(--muted);}
.card img{width:100%; max-width:220px; image-rendering:auto;
  background:var(--tile); border-radius:2px; display:block; margin:8px 0 0;}
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
    <p>这些格当初被你标成「切坏 / 带残留 / 不是字」进了排除名单，之后切分改过，
       图块可能已经好了。图是<b>现在</b>的列图：绿框 = 切出来的格，红框 = 紧框；
       大字是整理本对齐到这一格的字，只用来帮你看缺没缺笔画。
       只答一题：<b>红框里现在是不是一个完整的字？</b>
       完整 → 撤名单；仍切坏或带着邻字/框线残留 → 仍排除；根本不是字 → 不是字。
       点错再点一次取消，裁决自动存回本页。</p>
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
  return `<article class="card" data-id="${r.id}"${v ? ` data-v="${v}"` : ''}>
    <h3><span class="ref">${esc(r.ref || '？')}</span><span class="pos">${esc(r.pos)}</span></h3>
    <p>当初标的：${esc(r.label)}</p>
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
    .map(r => JSON.stringify({id: r.id, verdict: verdictOf(r.id), stratum: r.stratum})).join('\\n');
}
""".replace("__VERDICTS__", json.dumps([[v, t] for v, t, _ in VERDICTS],
                            ensure_ascii=False)).replace("__TITLE__", TITLE)

LABEL_CN = {"truncated": "切坏（truncated）", "contaminated": "带残留（contaminated）",
            "not_text": "不是字（not_text）", "damaged": "原刻残（damaged）"}


def _parse_id(iid: str) -> tuple[int, int, int, str]:
    _, pg, col, s = iid.split(":")
    sub = s[-1] if s[-1] in "ab" else ""
    return int(pg), int(col), int(s.rstrip("ab")), sub


def _png_uri(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def build(book: str, out: Path, key: str) -> None:
    from open_guji_cv.core.spec import column_key
    from open_guji_cv.core.workspace import exclusions_path
    from open_guji_cv.products.cache import ImageCache

    ic = ImageCache()
    recs = [json.loads(l) for l in exclusions_path().read_text(encoding="utf-8").splitlines() if l.strip()]
    recs = [r for r in recs if r["instance_id"].startswith(book + ":")]
    ws = Path(os.environ["GUJI_WORKSPACE"])
    prod = ws / "products" / book
    cells_cache: dict[int, dict] = {}
    chars_cache: dict[int, dict] = {}
    align_cache: dict[int, dict] = {}

    def load(pg: int):
        if pg in cells_cache:
            return
        d = json.load(open(prod / "row_segment" / f"p{pg:04d}.json", encoding="utf-8"))["cells"]
        cells_cache[pg] = {(c["col"], y["slot"], y.get("sub") or ""): (y, c) for c in d["columns"] for y in c["cells"]}
        d = json.load(open(prod / "cell_shrink" / f"p{pg:04d}.json", encoding="utf-8"))["char_index"]
        chars_cache[pg] = {r["id"]: r for c in d["columns"] for r in (c.get("chars") or [])}
        try:
            d = json.load(open(prod / "align_ref" / f"p{pg:04d}.json", encoding="utf-8"))["align_ref"]
            align_cache[pg] = {r["id"]: r.get("align_char") for r in (d.get("chars") or [])}
        except FileNotFoundError:
            align_cache[pg] = {}

    rows, imgs, skipped = [], {}, []
    for r in recs:
        iid = r["instance_id"]
        pg, col, slot, sub = _parse_id(iid)
        try:
            load(pg)
        except FileNotFoundError:
            skipped.append(iid); continue
        cell, colrec = cells_cache[pg].get((col, slot, sub), (None, None))
        cr = chars_cache[pg].get(iid)
        if cell is None or cr is None:
            skipped.append(iid); continue
        path = ic.get(book, "column_image", column_key(pg, col))
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) if path else None
        if img is None:
            skipped.append(iid); continue
        H = img.shape[0]
        y0 = max(0, int(cell["y0"]) - int(cell["y1"] - cell["y0"]))
        y1 = min(H, int(cell["y1"]) + int(cell["y1"] - cell["y0"]))
        crop = cv2.cvtColor(img[y0:y1, :], cv2.COLOR_GRAY2BGR)
        crop = (crop // 16) * 16                                   # 16 级灰，压体积
        cv2.rectangle(crop, (int(cell["x0"]), int(cell["y0"]) - y0), (int(cell["x1"]), int(cell["y1"]) - y0), (0, 170, 0), 1)
        bb = cr["bbox_col"]
        cv2.rectangle(crop, (int(bb[0]), int(bb[1]) - y0), (int(bb[2]), int(bb[3]) - y0), (0, 0, 230), 1)
        if y0 == 0:
            cv2.line(crop, (0, 0), (crop.shape[1] - 1, 0), (230, 120, 0), 2)
        if y1 == H:
            cv2.line(crop, (0, crop.shape[0] - 1), (crop.shape[1] - 1, crop.shape[0] - 1), (230, 120, 0), 2)
        imgs[iid] = _png_uri(crop)
        n_body = colrec["n_body_slots"]
        pos = "首" if slot <= 1 else ("末" if slot >= n_body else "中")
        ev = (r.get("evidence") or ["?"])[0]
        ev = ev if not ev.startswith("guess=") else r["reason"]
        rows.append({"id": iid, "pos": f"p{pg} 第{col}列 第{slot}格{sub}",
                     "label": LABEL_CN.get(ev, ev), "ref": align_cache[pg].get(iid) or "",
                     "img": iid, "stratum": f"{ev}:{pos}"})

    from review_shell import render
    html = render(TITLE, key, verdicts={}, css=CSS, page_js=PAGE_JS, payload={"rows": rows, "imgs": imgs})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    cards = out.with_name(out.stem + "_cards.jsonl")
    cards.write_text("".join(json.dumps({k: v for k, v in r.items() if k != "img"}, ensure_ascii=False) + "\n"
                             for r in rows), encoding="utf-8")
    print(f"{out}  {len(html)/1e6:.1f} MB  {len(rows)} 卡  跳过 {len(skipped)} {skipped[:5]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("book")
    ap.add_argument("-w", "--workspace", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--key", default=None)
    a = ap.parse_args()
    os.environ["GUJI_WORKSPACE"] = str(Path(a.workspace).resolve())
    import open_guji_cv.steps  # noqa: F401
    from datetime import date
    tag = date.today().strftime("%Y%m%d")
    out = Path(a.out) if a.out else Path(a.workspace) / "review" / "batches" / f"exclusion_recheck_{tag}.html"
    build(a.book, out, a.key or f"{a.book}-exclusion-recheck-{tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
