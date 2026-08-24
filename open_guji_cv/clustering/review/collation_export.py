"""对勘复审页：我的定字 × 整理本，逐条比对、可改判、可打印 PDF。

与种子审查页（``seed_export``）的分工：那边审**还没定**的字位，这边复审
**已经定了但与整理本不一致**的字位——两类工作的信息需求不同，混在一个
页面里两边都不好用。

四类差异（分类本身就是信息：改法完全不同）：

- ``variant`` **异体**：正规化后同字（珎/珍、卽/即）。字形层保留精确异体
  是本项目的纪律，所以这类**通常不必改**，列出来只为让人确认「确实是
  异体而不是认错字」；
- ``substitution`` **改字**：底本与整理本用字真的不同（戶/言、淮/准）。
  这类要么是整理本错、要么是我看错，必须逐条裁断；
- ``insertion`` **添字**：锚定页上整理本没有对应字位（对齐认为是衍文，
  或整理本漏收）；
- ``deletion`` **删字**：整理本有字，我判了非字（版框/空格误判，或整理本
  多收）。

**未锚定的页整页排除**（vol01 第 9/11 页是奏折/上谕，语料里根本没有）：
那不是「差异」，是没得比，混进来只会淹没真差异。

裁决沿用 ``GUJI-SEED-EVENT`` 协议（``seed_queue``），故本页产出的记录能
被 ``guji-cv seed-ingest`` 直接回收，不另立第二套契约。
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
from pathlib import Path

import cv2
import numpy as np

from .persist_js import PERSIST_JS
from ..seed_queue import SEED_EVENT_PREFIX, SeedItem
from ..variants import VariantMap

_DECIDED = {"auto_admitted", "confirmed", "confirmed_label_only"}

KIND_LABELS = {
    "substitution": "改字",
    "variant": "异体",
    "insertion": "添字",
    "deletion": "删字",
}
KIND_NOTES = {
    "substitution": "底本与整理本用字不同——要么整理本错，要么我看错，须裁断",
    "variant": "正规化后同字；字形层保留精确异体是纪律，通常不必改",
    "insertion": "整理本此位无字（衍文，或整理本漏收）",
    "deletion": "整理本有字而我判非字（版框/空格误判，或整理本多收）",
}
KIND_ORDER = ("substitution", "insertion", "deletion", "variant")


def _esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def _ref_of(it: SeedItem) -> str | None:
    """本字位的整理本字：过闸对齐优先，其次免闸逐位参考。"""
    if it.align and it.align.get("char"):
        return it.align["char"]
    return (it.context or {}).get("ref_char")


def classify(it: SeedItem, vmap: VariantMap) -> str | None:
    """已定字位 × 整理本 → 差异类别；一致或无从比较时返回 None。"""
    ref = _ref_of(it)
    if it.status == "not_a_char":
        return "deletion" if ref else None
    if it.status not in _DECIDED or not it.decided_char:
        return None
    if ref is None:
        return "insertion"
    if it.decided_char == ref:
        return None
    if vmap.semantic(it.decided_char) == vmap.semantic(ref):
        return "variant"
    return "substitution"


def _col_strip(items: list[SeedItem], root: Path, target_idx: int,
               width: int = 46) -> str | None:
    """整列图块竖排成条，目标格描红框 → base64 PNG。

    这是「在图片上标出这一列」的实现：光给单字图块，人无法判断它在
    版面上是不是真的处在那个位置（对齐错位恰恰是差异的常见成因）。
    """
    tiles: list[np.ndarray] = []
    for it in items:
        g = cv2.imread(str(root / it.patch_path), cv2.IMREAD_GRAYSCALE)
        if g is None:
            g = np.full((width, width), 220, np.uint8)
        h = max(1, int(round(g.shape[0] * width / g.shape[1])))
        g = cv2.resize(g, (width, h), interpolation=cv2.INTER_AREA)
        bgr = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
        if it.idx == target_idx:
            cv2.rectangle(bgr, (1, 1), (width - 2, h - 2), (42, 59, 166), 3)
        tiles.append(bgr)
        tiles.append(np.full((2, width, 3), 205, np.uint8))
    if not tiles:
        return None
    ok, buf = cv2.imencode(".png", np.vstack(tiles[:-1]))
    if not ok:
        return None
    return base64.b64encode(buf.tobytes()).decode("ascii")


def build_collation_batch(book_out_dir, queue_path,
                          kinds: tuple[str, ...] = KIND_ORDER,
                          variants: str | Path | None = None,
                          limit: int = 400) -> dict:
    """队列 → 对勘批次（含列条图、原图、上下文全文、分类）。"""
    book_dir, queue_path = Path(book_out_dir), Path(queue_path)
    root = book_dir / "phase4_chars"
    vmap = VariantMap.load(variants)
    items = [SeedItem.from_json(l) for l in
             queue_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    book = items[0].book if items else book_dir.name

    anchored = {str(it.page) for it in items
                if (it.context or {}).get("ref_char")}
    by_col: dict[tuple[str, int], list[SeedItem]] = {}
    for it in items:
        by_col.setdefault((str(it.page), it.col), []).append(it)
    for v in by_col.values():
        v.sort(key=lambda x: x.idx)

    entries, counts = [], {k: 0 for k in KIND_ORDER}
    n_same = 0
    for it in items:
        page = str(it.page)
        if page not in anchored:
            continue                      # 整页无语料 = 没得比，不是差异
        kind = classify(it, vmap)
        if kind is None:
            if it.status in _DECIDED and it.decided_char:
                n_same += 1
            continue
        counts[kind] += 1
        if kind not in kinds or len(entries) >= limit:
            continue
        ctx = it.context or {}
        try:
            patch = base64.b64encode(
                (root / it.patch_path).read_bytes()).decode("ascii")
        except OSError:
            patch = None
        entries.append({
            "instance_id": it.instance_id, "page": page, "col": it.col,
            "idx": it.idx, "kind": kind,
            "mine": it.decided_char, "ref": _ref_of(it),
            "ref_op": (it.align or {}).get("op") or ctx.get("ref_op"),
            "status": it.status,
            "label_only": it.status == "confirmed_label_only",
            "provenance": it.provenance,
            "ocr": (it.ocr or {}).get("char"),
            "intrusion": list(it.intrusion or []),
            "col_ref": ctx.get("col_ref"), "col_ocr": ctx.get("col_ocr"),
            "pos": ctx.get("pos"),
            "patch": patch,
            "strip": _col_strip(by_col[(page, it.col)], root, it.idx),
        })

    entries.sort(key=lambda e: (KIND_ORDER.index(e["kind"]),
                                int(e["page"]), e["col"], e["idx"]))
    sig = hashlib.sha1(
        (book + "|" + ",".join(e["instance_id"] for e in entries))
        .encode()).hexdigest()[:8]
    return {"book": book, "batch_id": f"{book}-collate-{sig}",
            "entries": entries, "counts": counts, "n_same": n_same,
            "anchored_pages": sorted(anchored, key=int),
            "total_diff": sum(counts.values())}


# ── 渲染 ─────────────────────────────────────────────────

_CSS = """
:root{
  --paper:#f7f4ec; --card:#fffdf7; --sunk:#efe9db;
  --ink:#241f1a; --ink-2:#5c5347; --ink-3:#8b8073;
  --line:#ded5c2; --line-2:#c9bda5; --imgbg:#fff;
  --mine:#a63b2a; --ref:#2f5d8a; --ok:#2f6b4f; --warn:#8a6a17;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --paper:#1a1713; --card:#232019; --sunk:#141210;
  --ink:#ece5d6; --ink-2:#b3a894; --ink-3:#867c6d;
  --line:#38322a; --line-2:#4d4438; --imgbg:#efe9dd;
  --mine:#e0917f; --ref:#8fb4d9; --ok:#8fc9a4; --warn:#d9bb6c;}}
:root[data-theme="dark"]{
  --paper:#1a1713; --card:#232019; --sunk:#141210;
  --ink:#ece5d6; --ink-2:#b3a894; --ink-3:#867c6d;
  --line:#38322a; --line-2:#4d4438; --imgbg:#efe9dd;
  --mine:#e0917f; --ref:#8fb4d9; --ok:#8fc9a4; --warn:#d9bb6c;}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);line-height:1.6;
  font-family:"Noto Serif TC","Songti TC","SimSun",serif}
code,.mono{font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-variant-numeric:tabular-nums}
.top{position:sticky;top:0;z-index:5;background:var(--paper);
  border-bottom:1px solid var(--line-2);padding:.7rem 1rem;
  display:flex;flex-wrap:wrap;gap:.5rem 1rem;align-items:baseline}
.top h1{font-size:1.05rem;margin:0;letter-spacing:.12em}
.top .sum{color:var(--ink-3);font-size:.85rem}
.top button,.filt a{font:inherit;font-size:.82rem;background:none;
  color:var(--ink);border:1px solid var(--line-2);border-radius:3px;
  padding:.15rem .6rem;cursor:pointer;text-decoration:none}
.top button:hover,.filt a:hover{border-color:var(--mine)}
#save-status{font-size:.8rem;color:var(--ink-3)}
#save-status[data-bad="1"]{color:#fff;background:var(--mine);
  padding:.1rem .5rem;border-radius:3px}
#copybar[data-pending="1"]{background:var(--warn);color:var(--paper);
  border-color:var(--warn);font-weight:600}
.filt{display:flex;flex-wrap:wrap;gap:.4rem;padding:.6rem 1rem;
  border-bottom:1px solid var(--line);background:var(--sunk)}
.filt a.on{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.list{max-width:58rem;margin:0 auto;padding:1.2rem 1rem 5rem;
  display:flex;flex-direction:column;gap:1rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:4px;
  display:flex;gap:1rem;padding:.9rem}
.card.active{border-color:var(--mine);box-shadow:0 0 0 1px var(--mine)}
.card[data-done="1"]{opacity:.62}
.strip img{width:3rem;border:1px solid var(--line);background:var(--imgbg);
  display:block}
.body{flex:1;min-width:0;display:flex;flex-direction:column;gap:.6rem}
.hd{display:flex;flex-wrap:wrap;gap:.5rem;align-items:baseline;
  font-size:.8rem;color:var(--ink-3)}
.hd .loc{color:var(--ink);font-weight:600}
.tag{font-size:.7rem;border:1px solid var(--line-2);border-radius:3px;
  padding:.05rem .4rem;color:var(--ink-2)}
.tag.k-substitution{color:var(--mine);border-color:var(--mine)}
.tag.k-variant{color:var(--warn);border-color:var(--warn)}
.tag.k-insertion,.tag.k-deletion{color:var(--ref);border-color:var(--ref)}
.cmp{display:flex;gap:1rem;flex-wrap:wrap;align-items:flex-start}
.cell{text-align:center;min-width:5rem}
.cell img{width:5rem;height:5rem;object-fit:contain;border:1px solid var(--line);
  background:var(--imgbg);border-radius:2px;display:block}
.big{font-size:2.7rem;line-height:5rem;height:5rem;border:1px solid var(--line);
  border-radius:2px;background:var(--paper)}
.big.mine{color:var(--mine);border-color:var(--mine)}
.big.ref{color:var(--ref);border-color:var(--ref)}
.big.none{color:var(--ink-3)}
.lab{font-size:.7rem;color:var(--ink-3);letter-spacing:.12em;margin-top:.25rem}
.ctxline{font-size:.95rem;color:var(--ink-2);word-break:break-all}
.ctxline b{color:var(--mine);background:var(--sunk);border-radius:2px;
  padding:0 .12em}
.ctxline .k{font-size:.72rem;color:var(--ink-3);letter-spacing:.1em;
  margin-right:.5em}
.acts{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center}
.acts button{font:inherit;font-size:.85rem;border:1px solid var(--line-2);
  background:none;color:var(--ink);border-radius:3px;padding:.25rem .7rem;
  cursor:pointer}
.acts button:hover{border-color:var(--mine)}
.acts .other-in{font:inherit;font-size:1rem;width:5.5rem;padding:.2rem .4rem;
  border:1px solid var(--line-2);border-radius:3px;background:var(--paper);
  color:var(--ink)}
.acts label{font-size:.8rem;color:var(--ink-2);display:inline-flex;
  align-items:center;gap:.3rem}
.verdict{font-size:.85rem;color:var(--ok);min-height:1.2em}
.verdict[data-bad="1"]{color:var(--mine)}
.log{background:var(--sunk);border:1px solid var(--line);border-radius:3px;
  padding:.6rem;font-size:.68rem;color:var(--ink-3);max-height:9rem;
  overflow:auto;white-space:pre;margin:0 1rem}
:focus-visible{outline:2px solid var(--mine);outline-offset:2px}
@media print{
  .top,.filt,.acts,.log,.noprint{display:none !important}
  body{background:#fff;color:#000}
  .list{max-width:none;padding:0;gap:.4rem}
  .card{break-inside:avoid;page-break-inside:avoid;border-color:#999;
    opacity:1 !important;background:#fff}
  .big{background:#fff}
  .card[data-hidden="1"]{display:none}
}
"""

_JS = """
(function(){
""" + PERSIST_JS + """

  // ── 卡片状态 ──
  function cards(){ return list.querySelectorAll('.card'); }
  function cardOf(iid){
    for(var i = 0, cs = cards(); i < cs.length; i++)
      if(cs[i].getAttribute('data-iid') === iid) return cs[i];
    return null; }
  function setActive(card){
    var a = list.querySelector('.card.active');
    if(a) a.classList.remove('active');
    if(card){ card.classList.add('active');
      card.scrollIntoView({block:'center', behavior:'smooth'}); } }
  function progress(){
    var done = list.querySelectorAll('.card[data-done="1"]').length;
    var el = document.getElementById('prog');
    if(el) el.textContent = '已复审 ' + done + ' / ' + cards().length; }
  function verdict(card, txt, bad){
    var v = card.querySelector('[data-slot="verdict"]');
    if(v){ v.textContent = txt; v.setAttribute('data-bad', bad ? '1' : '0'); }
    card.setAttribute('data-done', txt ? '1' : '0'); }

  // ── 裁决：沿用 GUJI-SEED-EVENT，seed-ingest 可直接回收 ──
  function decide(card, ch, admit){
    var iid = card.getAttribute('data-iid');
    emit(admit === false
      ? {op:'confirm', instance_id:iid, char:ch, admit:false}
      : {op:'confirm', instance_id:iid, char:ch});
    verdict(card, '改判为「' + ch + '」' + (admit === false ? '（不入库）' : ''), true); }
  function keepMine(card){
    // 维持原判不必发事件（队列里已经是这个字），只标记「已看过」
    verdict(card, '维持原判', false); }
  function markNotChar(card){
    emit({op:'not_a_char', instance_id:card.getAttribute('data-iid')});
    verdict(card, '标为非字', true); }

  list.addEventListener('click', function(e){
    var card = e.target.closest('.card');
    if(!card) return;
    var b = e.target.closest('button');
    if(!b){ if(!e.target.closest('input')) setActive(card); return; }
    var act = b.getAttribute('data-act');
    var admit = !card.querySelector('.noadm').checked;
    if(act === 'keep') keepMine(card);
    else if(act === 'ref') decide(card, b.getAttribute('data-char'), admit);
    else if(act === 'notchar') markNotChar(card);
    else if(act === 'other'){
      var inp = card.querySelector('.other-in');
      var v = (inp.value || '').trim();
      if(v){ decide(card, v[0], admit); inp.value = ''; } }
  });
  list.addEventListener('keydown', function(e){
    if(e.key !== 'Enter') return;
    var inp = e.target.closest('.other-in');
    if(!inp) return;
    e.preventDefault();
    var card = inp.closest('.card');
    var v = (inp.value || '').trim();
    if(v){ decide(card, v[0], !card.querySelector('.noadm').checked);
           inp.value = ''; }
  });

  // ── 过滤（打印时隐藏的卡片一并不打印）──
  var filt = document.getElementById('filt');
  if(filt) filt.addEventListener('click', function(e){
    var a = e.target.closest('a'); if(!a) return;
    e.preventDefault();
    var k = a.getAttribute('data-kind');
    filt.querySelectorAll('a').forEach(function(x){
      x.classList.toggle('on', x === a); });
    cards().forEach(function(c){
      var show = (k === 'all') || c.getAttribute('data-kind') === k;
      c.style.display = show ? '' : 'none';
      c.setAttribute('data-hidden', show ? '0' : '1'); });
  });

  var pb = document.getElementById('printbtn');
  if(pb) pb.addEventListener('click', function(){ window.print(); });
  var cb = document.getElementById('copybar');
  if(cb) cb.addEventListener('click', function(){
    var t = log.textContent;
    if(navigator.clipboard) navigator.clipboard.writeText(t);
    markExported(lines().length); });

  // ── 恢复：页内嵌日志（上次整页发布带回）∪ localStorage ──
  (function restore(){
    var local = '';
    try { local = localStorage.getItem(LSKEY) || ''; } catch(e){}
    var seen = {}, merged = [];
    (log.textContent + '\\n' + local).match(/GUJI-SEED-EVENT .*/g) &&
      (log.textContent + '\\n' + local).match(/GUJI-SEED-EVENT .*/g)
        .forEach(function(l){ if(!seen[l]){ seen[l] = 1; merged.push(l); } });
    if(merged.length){
      log.textContent = merged.join('\\n') + '\\n';
      var mx = 0;
      events().forEach(function(ev){
        if(ev.seq > mx) mx = ev.seq;
        var c = cardOf(ev.instance_id); if(!c) return;
        if(ev.op === 'not_a_char') verdict(c, '标为非字', true);
        else if(ev.op === 'confirm')
          verdict(c, '改判为「' + ev.char + '」' +
                  (ev.admit === false ? '（不入库）' : ''), true);
      });
      log.setAttribute('data-seq', String(mx));
    }
    progress(); refreshBar(); restoreView();
  })();
})();
"""


def _entry_html(e: dict) -> str:
    iid = _esc(e["instance_id"])
    kind = e["kind"]
    strip = (f'<div class="strip"><img src="data:image/png;base64,{e["strip"]}"'
             f' alt="第{_esc(e["col"])}列"></div>') if e.get("strip") else ""
    patch = (f'<img src="data:image/png;base64,{e["patch"]}" alt="原图">'
             if e.get("patch") else '<div class="big none">—</div>')
    ref_cell = (
        f'<div class="cell"><div class="big ref">{_esc(e["ref"])}</div>'
        f'<div class="lab">整理本{" · " + _esc(e["ref_op"]) if e.get("ref_op") else ""}</div></div>'
        if e.get("ref") else
        '<div class="cell"><div class="big none">∅</div>'
        '<div class="lab">整理本无字</div></div>')
    mine_cell = (
        f'<div class="cell"><div class="big mine">{_esc(e["mine"])}</div>'
        f'<div class="lab">我的定字</div></div>'
        if e.get("mine") else
        '<div class="cell"><div class="big none">✕</div>'
        '<div class="lab">我判非字</div></div>')

    tags = [f'<span class="tag k-{kind}">{_esc(KIND_LABELS[kind])}</span>']
    if e.get("label_only"):
        tags.append('<span class="tag">仅定字·不入库</span>')
    for c in e.get("intrusion") or []:
        tags.append(f'<span class="tag">混入·{_esc(c)}</span>')
    if e.get("ocr"):
        tags.append(f'<span class="tag">OCR {_esc(e["ocr"])}</span>')

    line = ""
    cr, pos = e.get("col_ref"), e.get("pos")
    if cr and pos is not None and 0 <= pos < len(cr):
        line = ('<div class="ctxline"><span class="k">整理本本列</span>'
                + _esc(cr[:pos]) + f'<b>{_esc(cr[pos])}</b>'
                + _esc(cr[pos + 1:]) + '</div>')

    back = (f'<button data-act="ref" data-char="{_esc(e["ref"])}">'
            f'换回整理本「{_esc(e["ref"])}」</button>') if e.get("ref") else ""
    return f'''<article class="card" data-iid="{iid}" data-kind="{kind}"
 data-done="0" data-hidden="0">
{strip}
<div class="body">
<div class="hd"><span class="loc mono">第{_esc(e["page"])}页 · 第{_esc(e["col"])}列 · 第{_esc(e["idx"])}字</span>
<span class="mono">{iid}</span>{"".join(tags)}</div>
<div class="cmp">
<div class="cell">{patch}<div class="lab">原图</div></div>
{mine_cell}{ref_cell}
</div>
{line}
<div class="acts noprint">
<button data-act="keep">维持原判</button>{back}
<input class="other-in" maxlength="4" placeholder="手输正字" aria-label="手输正字">
<button data-act="other">用此字</button>
<button data-act="notchar">标为非字</button>
<label><input type="checkbox" class="noadm"> 不入库</label>
</div>
<div class="verdict" data-slot="verdict"></div>
</div></article>'''


def render_collation_html(batch: dict) -> str:
    """批次 → 自包含 HTML（可改判、可打印、可分享）。"""
    c = batch["counts"]
    chips = "".join(
        f'<a href="#" data-kind="{k}">{_esc(KIND_LABELS[k])} {c.get(k, 0)}</a>'
        for k in KIND_ORDER if c.get(k))
    notes = " · ".join(f"{KIND_LABELS[k]}：{KIND_NOTES[k]}"
                       for k in KIND_ORDER if c.get(k))
    body = "\n".join(_entry_html(e) for e in batch["entries"])
    return f"""<title>{_esc(batch["book"])} 对勘复审</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+TC:wght@400;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>{_CSS}</style>
<div class="top noprint">
  <h1>{_esc(batch["book"])} 对勘复审</h1>
  <span class="sum">差异 {batch["total_diff"]} · 一致 {batch["n_same"]} ·
    锚定页 {_esc("、".join(batch["anchored_pages"]))}</span>
  <span class="sum" id="prog"></span>
  <span id="save-status" data-bad="0"></span>
  <button id="copybar">尚无记录</button>
  <button id="printbtn">打印 / 存 PDF</button>
</div>
<nav class="filt noprint" id="filt">
  <a href="#" data-kind="all" class="on">全部 {batch["total_diff"]}</a>{chips}
</nav>
<p class="log noprint" style="max-height:none;white-space:normal">{_esc(notes)}</p>
<div class="list" id="list">
{body}
</div>
<pre class="log noprint" id="guji-log" data-seq="0"
 data-batch="{_esc(batch["batch_id"])}"></pre>
<script>var BATCH = {json.dumps(batch["batch_id"])};</script>
<script>{_JS}</script>
"""
