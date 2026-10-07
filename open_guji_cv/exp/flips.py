# -*- coding: utf-8 -*-
"""翻转格抽样页：把翻转格出成人裁审查页（壳 = `scripts/_review_shell.py`，见 skill `review-artifact`）。

    guji exp flips sample  <exp> [--n 60]           # 分层抽样 → flips/cards.jsonl（id 冻住）
    guji exp flips page    <exp> [-o flips/review.html]   # 出页（工作区有列图缓存就带字块图）
    guji exp flips harvest <exp> <verdicts.jsonl>   # 收回 → labels_extra.jsonl，再 guji exp report

出题纪律（skill 里那几条）：
- **卡上不印哪边是基线、哪边是变体**，也不印通道与把握度——候选字打乱顺序，只问「这格是哪个字」；
- 每类翻转按层抽，记 `stratum` 与 `stratum_weight`（该层格数 / 抽中格数），事后才估得出该层比例；
- 已有标签的格不再出题；给「都不对」「切坏/非字」「拿不准」三档。

收回的裁决记 `source=human, selection=picked`（只代表被抽中的翻转格，不进总体错率），只写
`<exp>/labels_extra.jsonl`，**不写工作区 `feedback/`**——要落成正式人裁仍走 H 道的规矩。
"""
from __future__ import annotations

import base64
import importlib.util
import json
import random
from pathlib import Path
from typing import Callable

from ..errors import BadRequest
from .labels import PICKED, Label, read_jsonl, write_jsonl

FLIP_KINDS = ("admit_to_review", "review_to_admit", "char_changed")
CARDS = "flips/cards.jsonl"
EXTRA = "labels_extra.jsonl"
MIN_PER_STRATUM = 5


def _report(edir: Path) -> dict:
    p = edir / "report.json"
    if not p.exists():
        raise BadRequest(f"{edir} 还没有 report.json——先 guji exp report")
    return json.loads(p.read_text(encoding="utf-8"))


def allocate(sizes: dict[str, int], n: int, min_each: int = MIN_PER_STRATUM) -> dict[str, int]:
    """按层大小比例分 n 个名额；每个非空层至少 min(min_each, 层大小)。"""
    live = {k: v for k, v in sizes.items() if v > 0}
    if not live:
        return {}
    out = {k: min(v, min_each) for k, v in live.items()}
    left = n - sum(out.values())
    total = sum(live.values())
    if left > 0:
        for k, v in sorted(live.items(), key=lambda x: -x[1]):
            extra = min(v - out[k], round(left * v / total))
            out[k] += max(0, extra)
    return out


def sample(edir: str | Path, n: int = 60, seed: int = 0, resample: bool = False) -> list[dict]:
    edir = Path(edir)
    cards_p = edir / CARDS
    if cards_p.exists() and not resample:
        return [json.loads(x) for x in cards_p.read_text(encoding="utf-8").splitlines() if x.strip()]
    rep = _report(edir)
    labeled = {x.cell for x in read_jsonl(edir / "labels.jsonl")}
    strata: dict[str, list[dict]] = {}
    for vn, comp in rep["comparisons"].items():
        for k in FLIP_KINDS:
            rows = [r for r in comp["flips"][k]["cells"] if r["cell"] not in labeled]
            if rows:
                strata[f"{vn}:{k}"] = rows
    quota = allocate({k: len(v) for k, v in strata.items()}, n)
    rng = random.Random(seed)
    seen: dict[str, dict] = {}
    for st, q in sorted(quota.items()):
        rows = strata[st]
        pick = rng.sample(rows, q) if q < len(rows) else list(rows)
        for r in pick:
            card = seen.get(r["cell"])
            if card is None:
                card = seen[r["cell"]] = {"id": r["cell"], "stratum": st,
                                         "stratum_weight": len(rows) / max(1, q), "options": []}
            for c in (r["A"], r["B"]):
                if c and c not in card["options"]:
                    card["options"].append(c)
    cards = list(seen.values())
    for c in cards:
        rng.shuffle(c["options"])
    rng.shuffle(cards)
    cards_p.parent.mkdir(parents=True, exist_ok=True)
    cards_p.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cards), encoding="utf-8")
    return cards


# ── 出页 ─────────────────────────────────────────────────────────────────
def _shell():
    # 不走 `core.workspace.REPO_ROOT`：那是「仓内默认数据根」，测试里会被改指；壳是代码，跟包走
    p = Path(__file__).resolve().parents[2] / "scripts" / "_review_shell.py"
    spec = importlib.util.spec_from_file_location("_review_shell", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cache_image_fn(cache=None, h: int = 128) -> Callable[[str], str | None]:
    """格 id → 字块缩略图 data URI（工作区 `cache/<book>/char_patch`；没有就 None）。"""
    import cv2

    from ..core.spec import cell_key
    from ..feedback.anchor import parse_cell_key
    from ..products.cache import ImageCache
    cache = cache or ImageCache()

    def fn(cell: str) -> str | None:
        k = parse_cell_key(cell)
        if k is None:
            return None
        book, page, col, slot, sub = k
        p = cache.get(book, "char_patch", cell_key(page, col, slot) + (sub or ""))
        img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) if p else None
        if img is None:
            return None
        if img.shape[0] != h:
            img = cv2.resize(img, (max(1, int(img.shape[1] * h / img.shape[0])), h))
        ok, buf = cv2.imencode(".webp", img, [cv2.IMWRITE_WEBP_QUALITY, 70])
        return "data:image/webp;base64," + base64.b64encode(buf.tobytes()).decode() if ok else None
    return fn


CSS = """
.card{background:var(--surface); border:1px solid var(--rule); border-left:3px solid transparent;
  border-radius:3px; padding:12px 13px; box-shadow:var(--shadow);}
.card[data-v^="c"]{border-left-color:var(--ok)} .card[data-v="none"]{border-left-color:var(--zhu)}
.card[data-v="defect"]{border-left-color:var(--ochre)} .card[data-v="idk"]{border-left-color:var(--faint)}
.card h3{margin:0; font-family:var(--sans); font-size:12px; color:var(--muted); font-weight:500;}
.card img{height:128px; image-rendering:pixelated; background:var(--tile); border-radius:2px; display:block; margin:8px auto 0;}
.card .noimg{height:64px; display:flex; align-items:center; justify-content:center; color:var(--faint); font-size:12px;}
.verdicts{display:flex; flex-wrap:wrap; gap:6px; margin-top:10px;}
.verdicts button{flex:1 1 64px; min-height:44px; border:1px solid var(--rule-hard); border-radius:3px;
  background:var(--surface); color:var(--ink); font-size:13px; cursor:pointer;}
.verdicts button.c{font-family:var(--serif); font-size:22px;}
.verdicts button:focus-visible{outline:2px solid var(--indigo); outline-offset:2px;}
.verdicts button[aria-pressed="true"]{color:var(--on-solid); border-color:transparent;}
.verdicts button.c[aria-pressed="true"]{background:var(--ok)}
.verdicts button.none[aria-pressed="true"]{background:var(--zhu)}
.verdicts button.defect[aria-pressed="true"]{background:var(--ochre)}
.verdicts button.idk[aria-pressed="true"]{background:var(--faint)}
"""

PAGE_JS = r"""
const BODY = `
<header class="top"><div class="top-in">
  <span class="brand">__TITLE__</span>
  <span class="save" id="save">本机</span>
  <span class="count" id="count">0 / 0</span>
</div><div class="bar"><i id="prog"></i></div></header>
<div class="wrap">
  <details class="intro" id="intro" open>
    <summary>怎么裁</summary>
    <p>每张卡是一格刻本字。看图，点它是哪个字；都不是就点「都不对」，切坏了或不是字点「切坏/非字」，
       看不清点「拿不准」。点错再点一次取消。裁决自动存回本页（右上角牌子）；存不上就用「复制」贴回对话。</p>
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
  const b = (k, t, cls) => `<button class="${cls}" data-v="${k}" aria-pressed="${v===k}">${esc(t)}</button>`;
  const opts = r.options.map((c, i) => b('c' + i, c, 'c')).join('');
  return `<article class="card" data-id="${r.id}"${v ? ` data-v="${v}"` : ''}>
    <h3>${esc(r.id)}</h3>
    ${r.img ? `<img data-src="${r.img}" alt="">` : '<div class="noimg">（无字块图）</div>'}
    <div class="verdicts">${opts}${b('none','都不对','none')}${b('defect','切坏/非字','defect')}${b('idk','拿不准','idk')}</div>
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
    .map(r => JSON.stringify({id: r.id, verdict: verdictOf(r.id)})).join('\n');
}
"""


def build_page(edir: str | Path, out: str | Path | None = None,
               image_fn: Callable[[str], str | None] | None = None) -> Path:
    edir = Path(edir)
    cards = sample(edir)
    if not cards:
        raise BadRequest("没有可出题的翻转格（都已有标签，或没有翻转）")
    name = edir.name
    title = f"翻转格 · {name}"
    imgs, rows = {}, []
    for i, c in enumerate(cards):
        uri = image_fn(c["id"]) if image_fn else None
        key = None
        if uri:
            key = f"i{i}"
            imgs[key] = uri
        rows.append({"id": c["id"], "options": c["options"], "img": key})
    html = _shell().render(title, f"exp-flips-{name}", verdicts={}, css=CSS,
                           page_js=PAGE_JS.replace("__TITLE__", title),
                           payload={"rows": rows, "imgs": imgs})
    out = Path(out) if out else edir / "flips" / "review.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


# ── 收回 ─────────────────────────────────────────────────────────────────
def harvest(edir: str | Path, verdicts_jsonl: str | Path) -> dict:
    """`harvest_verdicts.py -o` 的输出 → `labels_extra.jsonl`（同格后到覆盖）。"""
    edir = Path(edir)
    cards = {c["id"]: c for c in sample(edir)}
    got: dict[str, Label] = {x.cell: x for x in read_jsonl(edir / EXTRA)}
    tally = {"chars": 0, "none": 0, "defect": 0, "idk": 0, "unknown": 0}
    for ln in Path(verdicts_jsonl).read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        c = cards.get(r.get("id"))
        v = r.get("verdict")
        if c is None or not v:
            tally["unknown"] += 1
            continue
        lab = Label(cell=c["id"], source="human", selection=PICKED, ref=f"flips:{c['stratum']}")
        if v.startswith("c") and v[1:].isdigit() and int(v[1:]) < len(c["options"]):
            lab.truth = c["options"][int(v[1:])]
            tally["chars"] += 1
        elif v == "none":
            lab.wrong = set(c["options"])
            tally["none"] += 1
        elif v == "defect":
            lab.defect = True
            tally["defect"] += 1
        else:
            tally["idk"] += 1
            continue
        got[lab.cell] = lab
    write_jsonl(sorted(got.values(), key=lambda x: x.cell), edir / EXTRA)
    return tally
