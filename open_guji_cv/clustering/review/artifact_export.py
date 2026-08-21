"""无命令行审查：批次导出为自包含 HTML + 审查事件回收。

面向"用户只能通过 Claude Code 远程/网页工作"的场景：

    导出   build_batch() + render_html()  →  单文件 HTML（图块内嵌 base64）
           可直接发布为 Claude Artifact（live-doc 自动保存点击结果），
           也可提交到 GitHub Pages 分支静态托管。
    回收   extract_events() + ingest_events()  →  从保存后的页面文本中
           解析 ``GUJI-EVENT {json}`` 行，去重后追加进 labels.jsonl。

持久化三层保险（页面内实现）：
    1. Artifact live-doc：用户点击产生的 DOM 变化（事件日志 <pre>）被自动
       保存，Claude 之后用 WebFetch 读回页面即可回收；
    2. downloads 能力（仅 Artifact 环境）：一键下载 labels.jsonl；
    3. 事件日志可见可复制：任何托管环境下用户都能全选复制贴回对话。

事件行格式（与 labels.jsonl 同构，额外带 batch/seq 供去重）：
    GUJI-EVENT {"op":"confirm","cluster":"c00192","char":"林",
                "batch":"book9all-gain-400-1a2b3c4d","seq":3,"ts":"..."}

mark 事件与 feedback.LabelState 对齐，用 flag 字段（uncertain 表示存疑）。
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import re
from pathlib import Path

from ..feedback import load_events
from .state import ReviewSession

EVENT_RE = re.compile(r"GUJI-EVENT\s+(\{.*\})")

# ── 批次构建 ─────────────────────────────────────────────


def build_batch(book_out_dir: str | Path, limit: int = 400,
                sort: str = "gain", max_members: int = 4,
                max_candidates: int = 5) -> dict:
    """从审查会话取 top-N 可疑簇，装配成可序列化批次。

    每簇：候选（含语义注记）、成员图块 base64、代表实例的
    简略（±3 字）与完整（±3 列）文本上下文。
    """
    session = ReviewSession(book_out_dir)
    queue = session.queue(sort=sort, limit=limit)
    entries = []
    for q in queue:
        cid = q["cluster_id"]
        detail = session.cluster_detail(cid)
        members = [m for m in detail["members"] if not m["removed"]]
        patches = []
        for m in members[:max_members]:
            p = session.patch_file(m["id"])
            if p is None:
                continue
            patches.append({
                "id": m["id"],
                "b64": base64.b64encode(p.read_bytes()).decode("ascii"),
            })
        if not patches:
            continue
        rep = patches[0]["id"]
        entries.append({
            "cluster_id": cid,
            "size": detail["size"],
            "rep": rep,
            "candidates": (detail["candidates"] or [])[:max_candidates],
            "patches": patches,
            "n_more": max(0, len(members) - max_members),
            "ctx_compact": session.context(rep, mode="compact"),
            "ctx_full": session.context(rep, mode="full"),
        })
    cids = ",".join(e["cluster_id"] for e in entries)
    digest = hashlib.sha1(cids.encode()).hexdigest()[:8]
    book = Path(book_out_dir).name
    return {
        "book": book,
        "sort": sort,
        "batch_id": f"{book}-{sort}-{len(entries)}-{digest}",
        "entries": entries,
    }


# ── HTML 渲染 ────────────────────────────────────────────

def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def _render_candidates(entry: dict) -> str:
    out = []
    for c in entry["candidates"]:
        ch, p = c["char"], c.get("p", 0.0)
        sem = c.get("semantic")
        note = (f'<small class="sem">→{_esc(sem)}</small>'
                if sem and sem != ch else "")
        out.append(
            f'<button type="button" class="cand" data-char="{_esc(ch)}">'
            f'<b>{_esc(ch)}</b>{note}<span class="p">{p:.0%}</span></button>')
    return "".join(out)


def _render_compact(ctx: dict) -> str:
    spans = []
    for n in ctx.get("neighbors", []):
        ch = n.get("best") or "□"
        cls = "tgt" if n["is_target"] else "nb"
        spans.append(f'<span class="{cls}">{_esc(ch)}</span>')
    return "".join(spans)


def _render_full(ctx: dict) -> str:
    cols = []
    for col in ctx.get("columns", []):
        chars = []
        for n in col["chars"]:
            ch = n.get("best") or "□"
            cls = "tgt" if n.get("is_target") else "nb"
            chars.append(f'<span class="{cls}">{_esc(ch)}</span>')
        tc = " tcol" if col["is_target_col"] else ""
        cols.append(f'<div class="vcol{tc}">{"".join(chars)}</div>')
    return "".join(cols)


def _render_card(entry: dict) -> str:
    cid = _esc(entry["cluster_id"])
    imgs = "".join(
        f'<img src="data:image/png;base64,{p["b64"]}" alt="{_esc(p["id"])}" '
        f'title="{_esc(p["id"])}">' for p in entry["patches"])
    more = (f'<span class="more">+{entry["n_more"]}</span>'
            if entry["n_more"] else "")
    return f"""<article class="card" data-cid="{cid}" data-state="open">
<header><span class="cid">{cid}</span><span class="sz">×{entry["size"]}</span>
<span class="chosen" data-slot="chosen"></span>
<button type="button" class="reopen">改</button>
<button type="button" class="skip">稍後</button></header>
<div class="row">
<div class="patches">{imgs}{more}</div>
<div class="main">
<div class="cands">{_render_candidates(entry)}
<span class="other"><input class="other-in" maxlength="4" placeholder="其他字">
<button type="button" class="other-ok">確定</button></span>
<button type="button" class="doubt" data-inst="{_esc(entry["rep"])}">存疑</button></div>
<div class="ctx"><span class="ctx-label">同列</span>
<span class="ctx-compact">{_render_compact(entry["ctx_compact"])}</span>
<details class="ctx-more"><summary>±3 列全文</summary>
<div class="vwrap">{_render_full(entry["ctx_full"])}</div></details></div>
</div></div></article>"""


_CSS = """
:root{
  --paper:#faf6ee; --card:#fffdf8; --ink:#2b2620; --muted:#8a7f6e;
  --line:#e3dbc9; --seal:#a63b2a; --seal-ink:#fff6ee;
  --done:#3d7a4f; --doubt:#8a6d1f; --hl:#f3e9d2;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --paper:#1d1a15; --card:#26221b; --ink:#e8e0d0; --muted:#9a8f7c;
    --line:#3a342a; --seal:#d0715e; --seal-ink:#2b1512;
    --done:#7fba8f; --doubt:#cfae4e; --hl:#3b3527;
  }
}
:root[data-theme="dark"]{
  --paper:#1d1a15; --card:#26221b; --ink:#e8e0d0; --muted:#9a8f7c;
  --line:#3a342a; --seal:#d0715e; --seal-ink:#2b1512;
  --done:#7fba8f; --doubt:#cfae4e; --hl:#3b3527;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
  font-family:"Noto Serif TC","Songti TC","SimSun",serif;line-height:1.5}
.top{position:sticky;top:0;z-index:5;background:var(--paper);
  border-bottom:1px solid var(--line);padding:.6rem 1rem;
  display:flex;flex-wrap:wrap;gap:.6rem 1.2rem;align-items:baseline}
.top h1{font-size:1.05rem;margin:0;letter-spacing:.12em}
.top .prog{color:var(--muted);font-variant-numeric:tabular-nums}
.top button{font:inherit;font-size:.85rem;background:none;color:var(--ink);
  border:1px solid var(--line);border-radius:3px;padding:.15rem .6rem;cursor:pointer}
.top button[data-on="1"]{background:var(--seal);color:var(--seal-ink);border-color:var(--seal)}
.list{max-width:52rem;margin:0 auto;padding:1rem;display:flex;
  flex-direction:column;gap:.8rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:4px}
.card>header{display:flex;gap:.7rem;align-items:baseline;
  padding:.4rem .8rem;border-bottom:1px solid var(--line)}
.cid{font-family:ui-monospace,monospace;font-size:.75rem;color:var(--muted)}
.sz{font-size:.75rem;color:var(--muted);font-variant-numeric:tabular-nums}
.chosen{font-size:1.15rem;color:var(--done);min-width:1.4em}
.card>header button{margin-left:auto;font:inherit;font-size:.75rem;
  background:none;border:1px solid var(--line);border-radius:3px;
  color:var(--muted);cursor:pointer;padding:.05rem .5rem}
.card>header .reopen{display:none;margin-left:auto}
.card>header .skip{margin-left:0}
.card[data-state="done"]>header .reopen,
.card[data-state="doubt"]>header .reopen{display:inline-block}
.card[data-state="done"]>header .skip,
.card[data-state="doubt"]>header .skip{display:none}
.row{display:flex;gap:1rem;padding:.7rem .8rem;flex-wrap:wrap}
.patches{display:flex;gap:.35rem;align-items:flex-start;flex-wrap:wrap;max-width:14rem}
.patches img{width:3.2rem;height:3.2rem;object-fit:contain;
  border:1px solid var(--line);border-radius:2px;background:#fff}
.more{color:var(--muted);font-size:.8rem;align-self:center}
.main{flex:1;min-width:16rem;display:flex;flex-direction:column;gap:.55rem}
.cands{display:flex;flex-wrap:wrap;gap:.45rem;align-items:center}
.cand{font:inherit;display:inline-flex;align-items:baseline;gap:.3rem;
  border:1px solid var(--line);background:none;color:var(--ink);
  border-radius:3px;padding:.2rem .55rem;cursor:pointer}
.cand b{font-size:1.25rem;font-weight:600}
.cand .p{font-size:.72rem;color:var(--muted);font-variant-numeric:tabular-nums}
.cand .sem{color:var(--muted);font-size:.72rem}
.cand:hover,.cand:focus-visible{border-color:var(--seal)}
.other{display:inline-flex;gap:.3rem}
.other-in{font:inherit;width:4.5em;background:var(--paper);color:var(--ink);
  border:1px solid var(--line);border-radius:3px;padding:.15rem .4rem}
.other-ok,.doubt{font:inherit;font-size:.85rem;background:none;color:var(--ink);
  border:1px solid var(--line);border-radius:3px;padding:.15rem .55rem;cursor:pointer}
.doubt{color:var(--doubt);border-color:var(--doubt)}
.ctx{font-size:1rem;display:flex;gap:.6rem;align-items:baseline;flex-wrap:wrap}
.ctx-label{font-size:.72rem;color:var(--muted);letter-spacing:.15em}
.ctx-compact .nb{margin:0 .06em}
.tgt{background:var(--hl);border:1px solid var(--seal);border-radius:2px;
  padding:0 .1em;color:var(--seal)}
.ctx-more summary{cursor:pointer;font-size:.78rem;color:var(--muted)}
.vwrap{display:flex;flex-direction:row-reverse;justify-content:flex-end;
  align-items:flex-start;gap:.9rem;padding:.6rem 0;overflow-x:auto}
.vcol{display:flex;flex-direction:column;gap:.18em;font-size:1.05rem;
  line-height:1.15;text-align:center}
.vcol.tcol{color:inherit}
.vcol:not(.tcol){color:var(--muted)}
.card[data-state="done"] .row,.card[data-state="doubt"] .row,
.card[data-state="skip"] .row{display:none}
.card[data-state="done"]{border-left:3px solid var(--done)}
.card[data-state="doubt"]{border-left:3px solid var(--doubt)}
.card[data-state="skip"]{opacity:.55}
.list[data-local-filter="open"] .card:not([data-state="open"]):not([data-state="skip"]){display:none}
.list[data-local-filter="done"] .card[data-state="open"],
.list[data-local-filter="done"] .card[data-state="skip"]{display:none}
.foot{max-width:52rem;margin:0 auto;padding:0 1rem 3rem}
.foot summary{cursor:pointer;color:var(--muted);font-size:.85rem}
.log{font-family:ui-monospace,monospace;font-size:.72rem;background:var(--card);
  border:1px solid var(--line);border-radius:4px;padding:.6rem;
  overflow-x:auto;white-space:pre;min-height:2rem}
.hint{color:var(--muted);font-size:.8rem}
@media (prefers-reduced-motion: no-preference){
  .card{transition:opacity .15s ease}}
"""

_JS = """
(function(){
  var log = document.getElementById('guji-log');
  var list = document.getElementById('list');
  function events(){
    return (log.textContent.match(/GUJI-EVENT .*/g) || []).length; }
  function seqNext(){
    var n = parseInt(log.getAttribute('data-seq') || '0', 10) + 1;
    log.setAttribute('data-seq', String(n)); return n; }
  function emit(ev){
    ev.batch = BATCH; ev.seq = seqNext();
    ev.ts = new Date().toISOString().slice(0, 19) + '+00:00';
    log.textContent += 'GUJI-EVENT ' + JSON.stringify(ev) + '\\n';
    progress(); }
  function progress(){
    var done = list.querySelectorAll(
      '[data-state="done"],[data-state="doubt"]').length;
    var total = list.querySelectorAll('.card').length;
    document.getElementById('prog').textContent =
      done + ' / ' + total + ' 簇 · ' + events() + ' 條記錄'; }
  function setState(card, s){ card.setAttribute('data-state', s); progress(); }
  function choose(card, ch){
    ch = (ch || '').trim(); if(!ch) return;
    emit({op:'confirm', cluster: card.getAttribute('data-cid'), char: ch});
    card.querySelector('[data-slot="chosen"]').textContent = ch;
    setState(card, 'done'); }
  document.addEventListener('click', function(e){
    var btn = e.target.closest('button'); if(!btn) return;
    var card = btn.closest('.card');
    if(btn.classList.contains('cand')) choose(card, btn.getAttribute('data-char'));
    else if(btn.classList.contains('other-ok'))
      choose(card, card.querySelector('.other-in').value);
    else if(btn.classList.contains('doubt')){
      emit({op:'mark', instance: btn.getAttribute('data-inst'), flag:'uncertain'});
      card.querySelector('[data-slot="chosen"]').textContent = '疑';
      setState(card, 'doubt'); }
    else if(btn.classList.contains('skip')) setState(card, 'skip');
    else if(btn.classList.contains('reopen')){
      card.querySelector('[data-slot="chosen"]').textContent = '';
      setState(card, 'open'); }
    else if(btn.hasAttribute('data-f')){
      list.setAttribute('data-local-filter', btn.getAttribute('data-f'));
      document.querySelectorAll('[data-f]').forEach(function(b){
        b.setAttribute('data-on', b === btn ? '1' : '0'); }); }
  });
  document.addEventListener('keydown', function(e){
    if(e.key === 'Enter' && e.target.classList &&
       e.target.classList.contains('other-in')){
      choose(e.target.closest('.card'), e.target.value); }});
  progress();
  var dlBtn = document.getElementById('dl');
  if(window.claude && window.claude.use){
    window.claude.use('downloads').then(function(dl){
      if(!dl) return;
      dlBtn.hidden = false;
      dlBtn.addEventListener('click', function(){
        var lines = (log.textContent.match(/GUJI-EVENT (.*)/g) || [])
          .map(function(l){ return l.slice('GUJI-EVENT '.length); })
          .join('\\n');
        dl.save({filename: BATCH + '.labels.jsonl', data: lines})
          .catch(function(){}); });
    }).catch(function(){});
  }
})();
"""


def render_html(batch: dict, title: str | None = None) -> str:
    title = title or f'{batch["book"]} 字勘'
    cards = "\n".join(_render_card(e) for e in batch["entries"])
    n = len(batch["entries"])
    return f"""<title>{_esc(title)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+TC:wght@400;600&display=swap">
<style>{_CSS}</style>
<header class="top">
<h1>{_esc(title)}</h1>
<span class="prog" id="prog">0 / {n} 簇</span>
<button type="button" data-f="all" data-on="1">全部</button>
<button type="button" data-f="open" data-on="0">未審</button>
<button type="button" data-f="done" data-on="0">已審</button>
<button type="button" id="dl" hidden>下載 labels.jsonl</button>
</header>
<main class="list" id="list" data-local-filter="all">
{cards}
</main>
<footer class="foot">
<p class="hint">點候選字確認；不在候選中則填「其他字」；拿不準點「存疑」。
所有操作即時保存，隨時可以離開再回來。</p>
<details><summary>事件日誌（審查記錄，可全選複製）</summary>
<pre class="log" id="guji-log" data-seq="0" data-batch="{_esc(batch["batch_id"])}"></pre>
</details>
</footer>
<script>var BATCH = {json.dumps(batch["batch_id"])};{_JS}</script>
"""


def export_batch(book_out_dir: str | Path, out_path: str | Path | None = None,
                 limit: int = 400, sort: str = "gain",
                 title: str | None = None) -> Path:
    book_out_dir = Path(book_out_dir)
    batch = build_batch(book_out_dir, limit=limit, sort=sort)
    out = (Path(out_path) if out_path
           else book_out_dir / "phase7_review" / f'{batch["batch_id"]}.html')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(batch, title=title), encoding="utf-8")
    return out


# ── 事件回收 ─────────────────────────────────────────────

def extract_events(text: str) -> list[dict]:
    """从任意文本（保存后的页面 HTML / WebFetch 转写 / 粘贴内容）提取事件。

    容错：只认 ``GUJI-EVENT {json}`` 行，无法解析的行静默跳过。
    """
    out = []
    for m in EVENT_RE.finditer(text):
        try:
            ev = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(ev, dict) and ev.get("op"):
            out.append(ev)
    return out


def ingest_events(book_out_dir: str | Path, text: str) -> dict:
    """解析文本中的审查事件，去重（batch+seq）后写入 labels.jsonl。

    逐条经 ReviewSession.post_event 校验（未知簇/实例记入 errors，
    不中断），与本地审查界面产生的事件完全同构。
    """
    session = ReviewSession(book_out_dir)
    existing = {(e.get("batch"), e.get("seq"))
                for e in load_events(session.labels_path)
                if e.get("batch") is not None and e.get("seq") is not None}
    parsed = extract_events(text)
    new = dup = 0
    errors: list[str] = []
    for ev in parsed:
        key = (ev.get("batch"), ev.get("seq"))
        if key[0] is not None and key in existing:
            dup += 1
            continue
        if ev.get("op") == "mark" and "flag" not in ev:
            ev["flag"] = ev.pop("note", "uncertain")   # 兼容旧字段名
        try:
            session.post_event(ev)
            existing.add(key)
            new += 1
        except (ValueError, KeyError) as e:
            errors.append(f"{ev.get('op')}/{ev.get('cluster') or ev.get('instance')}: {e}")
    return {"parsed": len(parsed), "new": new,
            "duplicate": dup, "errors": errors}
