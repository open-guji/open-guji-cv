"""无命令行审查：批次导出为自包含 HTML + 审查事件回收。

面向"用户只能通过 Claude Code 远程/网页工作"的场景：

    导出   build_batch() + render_html()  →  单文件 HTML（图块内嵌 base64）
           可直接发布为 Claude Artifact（live-doc 自动保存点击结果），
           也可提交到 GitHub Pages 分支静态托管。
    回收   extract_events() + ingest_events()  →  从保存后的页面文本中
           解析 ``GUJI-EVENT {json}`` 行，去重后追加进 labels.jsonl。

持久化三层保险（页面内实现）：
    1. artifact 能力 files-publish：每次操作后防抖 3s 调
       ``artifact.publish({"labels.jsonl": 日志})`` 发布数据文件新版本
       （经典 Artifact 无手势自动保存——live-doc 才有；本视图不重载）。
       重开页面时 fetch("labels.jsonl") 恢复并重放卡片状态；
    2. localStorage 崩溃备份：每次操作同步写入，恢复时与已发布日志按
       (batch,seq) 合并，多出的自动补发布；
    3. downloads 一键下载 + 事件日志可见可复制：任何托管环境下的兜底。

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

from ..feedback import load_events, remap_events
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
            # 成员实例 id：簇 id 会随重跑聚类变号，回收时靠成员重绑
            "members": [m["id"] for m in members],
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


# 簇级问题标记（与 review.state.CLUSTER_FLAGS 对齐）
FLAG_BUTTONS = [
    ("impure",       "不同字混簇", True),    # 仅多成员簇显示
    ("truncated",    "截斷",       False),
    ("contaminated", "混入邊框/鄰字", False),
    ("not_text",     "非文字",     False),
]


def _render_flags(entry: dict) -> str:
    out = []
    for flag, label, multi_only in FLAG_BUTTONS:
        if multi_only and entry["size"] < 2:
            continue
        out.append(f'<button type="button" class="flag" data-flag="{flag}" '
                   f'data-label="{_esc(label)}">{_esc(label)}</button>')
    return "".join(out)


def _render_card(entry: dict) -> str:
    cid = _esc(entry["cluster_id"])
    imgs = "".join(
        f'<img src="data:image/png;base64,{p["b64"]}" alt="{_esc(p["id"])}" '
        f'title="{_esc(p["id"])}">' for p in entry["patches"])
    more = (f'<span class="more">+{entry["n_more"]}</span>'
            if entry["n_more"] else "")
    members = ",".join(entry.get("members", []))
    return f"""<article class="card" data-cid="{cid}" data-members="{_esc(members)}" data-state="open">
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
<div class="flags"><span class="ctx-label">問題</span>{_render_flags(entry)}</div>
<div class="ctx"><span class="ctx-label">同列</span>
<span class="ctx-compact">{_render_compact(entry["ctx_compact"])}</span>
<details class="ctx-more"><summary>±3 列全文</summary>
<div class="vwrap">{_render_full(entry["ctx_full"])}</div></details></div>
</div></div></article>"""


_CSS = """
:root{
  --paper:#faf6ee; --card:#fffdf8; --ink:#2b2620; --muted:#8a7f6e;
  --line:#e3dbc9; --seal:#a63b2a; --seal-ink:#fff6ee;
  --done:#3d7a4f; --doubt:#8a6d1f; --bad:#8a4238; --hl:#f3e9d2;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --paper:#1d1a15; --card:#26221b; --ink:#e8e0d0; --muted:#9a8f7c;
    --line:#3a342a; --seal:#d0715e; --seal-ink:#2b1512;
    --done:#7fba8f; --doubt:#cfae4e; --bad:#cf8377; --hl:#3b3527;
  }
}
:root[data-theme="dark"]{
  --paper:#1d1a15; --card:#26221b; --ink:#e8e0d0; --muted:#9a8f7c;
  --line:#3a342a; --seal:#d0715e; --seal-ink:#2b1512;
  --done:#7fba8f; --doubt:#cfae4e; --bad:#cf8377; --hl:#3b3527;
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
.card[data-state="doubt"]>header .reopen,
.card[data-state="flag"]>header .reopen{display:inline-block}
.card[data-state="done"]>header .skip,
.card[data-state="doubt"]>header .skip,
.card[data-state="flag"]>header .skip{display:none}
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
.flags{display:flex;gap:.4rem;align-items:baseline;flex-wrap:wrap}
.flag{font:inherit;font-size:.78rem;background:none;color:var(--muted);
  border:1px dashed var(--line);border-radius:3px;padding:.1rem .5rem;cursor:pointer}
.flag:hover,.flag:focus-visible{color:var(--bad);border-color:var(--bad)}
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
.card[data-state="flag"] .row,.card[data-state="skip"] .row{display:none}
.card[data-state="done"]{border-left:3px solid var(--done)}
.card[data-state="doubt"]{border-left:3px solid var(--doubt)}
.card[data-state="flag"]{border-left:3px solid var(--bad)}
.card[data-state="flag"] .chosen{color:var(--bad);font-size:.85rem}
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
  var FLAGS = {impure:'不同字混簇', truncated:'截斷',
               contaminated:'混入邊框/鄰字', not_text:'非文字'};
  var LSKEY = 'guji:' + BATCH;

  function lines(){ return log.textContent.match(/GUJI-EVENT .*/g) || []; }
  function events(){
    return lines().map(function(l){
      try { return JSON.parse(l.slice('GUJI-EVENT '.length)); }
      catch(e){ return null; }
    }).filter(Boolean); }
  function status(msg){
    var el = document.getElementById('save-status');
    if(el) el.textContent = msg; }

  // ── 持久化：经典 Artifact 无手势自动保存，必须显式 publish ──
  // 三层：files-publish（labels.jsonl 数据文件，本视图不重载）
  //     + localStorage 崩溃备份 + 页面底部可复制日志
  var nsPromise = (window.claude && window.claude.use)
    ? window.claude.use('artifact').catch(function(){ return null; })
    : Promise.resolve(null);
  var pubTimer = 0, disabled = false, unsaved = false;
  function saveLocal(){
    try { localStorage.setItem(LSKEY, log.textContent); } catch(e){} }
  function publishNow(){
    nsPromise.then(function(ns){
      if(!ns || disabled){
        status('自動儲存不可用：請複製底部日誌或點「下載」'); return; }
      status('儲存中…');
      ns.publish({'labels.jsonl': log.textContent}).then(function(){
        unsaved = false; status('已儲存 ' + lines().length + ' 條');
      }).catch(function(e){
        var c = e && e.code;
        if(c === 'rate_limited'){
          status('儲存排隊中…'); setTimeout(publishNow, 30000); }
        else if(c === 'upstream_error'){
          setTimeout(publishNow, 4000 + Math.random() * 3000); }
        else if(c === 'conflict'){ saveLocal(); }
        else { disabled = true;
          status('自動儲存不可用：請複製底部日誌或點「下載」'); }
      });
    }); }
  function schedulePublish(){
    unsaved = true; status('未儲存…');
    clearTimeout(pubTimer); pubTimer = setTimeout(publishNow, 3000); }
  window.addEventListener('beforeunload', function(){ saveLocal(); });

  function seqNext(){
    var n = parseInt(log.getAttribute('data-seq') || '0', 10) + 1;
    log.setAttribute('data-seq', String(n)); return n; }
  function emit(ev){
    if(ev.cluster && !ev.members){
      var card = cardOf(ev.cluster);
      var ms = card && card.getAttribute('data-members');
      if(ms) ev.members = ms.split(',');   // 簇 id 会变，成员实例 id 不变
    }
    ev.batch = BATCH; ev.seq = seqNext();
    ev.ts = new Date().toISOString().slice(0, 19) + '+00:00';
    log.textContent += 'GUJI-EVENT ' + JSON.stringify(ev) + '\\n';
    saveLocal(); schedulePublish(); progress(); }

  // ── 恢复：已发布的 labels.jsonl + localStorage 备份，按 seq 合并重放 ──
  function cardOf(cid){
    for(var i = 0, cs = list.children; i < cs.length; i++)
      if(cs[i].getAttribute && cs[i].getAttribute('data-cid') === cid)
        return cs[i];
    return null; }
  function applyVisual(ev){
    var card = ev.cluster ? cardOf(ev.cluster) : null;
    if(!card) return;
    var chosen = card.querySelector('[data-slot="chosen"]');
    if(ev.op === 'confirm'){
      card.setAttribute('data-state', 'done'); chosen.textContent = ev.char; }
    else if(ev.op === 'mark'){
      card.setAttribute('data-state', 'doubt'); chosen.textContent = '疑'; }
    else if(ev.op === 'flag'){
      if(ev.flag === 'clear'){
        card.setAttribute('data-state', 'open'); chosen.textContent = ''; }
      else { card.setAttribute('data-state', 'flag');
        chosen.textContent = FLAGS[ev.flag] || ev.flag; } } }
  function restore(){
    fetch('labels.jsonl')
      .then(function(r){ return r.ok ? r.text() : ''; })
      .catch(function(){ return ''; })
      .then(function(saved){
        var localTxt = '';
        try { localTxt = localStorage.getItem(LSKEY) || ''; } catch(e){}
        var seen = {}, merged = [], extra = 0;
        function add(l, isLocal){
          try { var ev = JSON.parse(l.slice('GUJI-EVENT '.length)); }
          catch(e){ return; }
          var key = ev.batch + '#' + ev.seq;
          if(seen[key]) return;
          seen[key] = 1; merged.push(l);
          if(isLocal) extra++; }
        (saved.match(/GUJI-EVENT .*/g) || []).forEach(function(l){ add(l, 0); });
        (localTxt.match(/GUJI-EVENT .*/g) || []).forEach(function(l){ add(l, 1); });
        if(merged.length){
          log.textContent = merged.join('\\n') + '\\n';
          var mx = 0;
          events().forEach(function(ev){
            if(ev.batch === BATCH && ev.seq > mx) mx = ev.seq; });
          log.setAttribute('data-seq', String(mx));
          events().forEach(applyVisual);
        }
        progress();
        if(extra) schedulePublish();
        else if(merged.length) status('已儲存 ' + merged.length + ' 條');
      }); }
  function progress(){
    var done = list.querySelectorAll(
      '[data-state="done"],[data-state="doubt"],[data-state="flag"]').length;
    var total = list.querySelectorAll('.card').length;
    document.getElementById('prog').textContent =
      done + ' / ' + total + ' 簇 · ' + lines().length + ' 條記錄'; }
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
      emit({op:'mark', instance: btn.getAttribute('data-inst'),
            cluster: card.getAttribute('data-cid'), flag:'uncertain'});
      card.querySelector('[data-slot="chosen"]').textContent = '疑';
      setState(card, 'doubt'); }
    else if(btn.classList.contains('flag')){
      emit({op:'flag', cluster: card.getAttribute('data-cid'),
            flag: btn.getAttribute('data-flag')});
      card.querySelector('[data-slot="chosen"]').textContent =
        btn.getAttribute('data-label');
      setState(card, 'flag'); }
    else if(btn.classList.contains('skip')) setState(card, 'skip');
    else if(btn.classList.contains('reopen')){
      if(card.getAttribute('data-state') === 'flag')
        emit({op:'flag', cluster: card.getAttribute('data-cid'), flag:'clear'});
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
  restore();

  // ── 导出：能力可用则存文件，不可用则退回「展开日志并全选」──
  // 按钮始终可见：之前仅在能力就绪时才显形，能力不可用的视图里
  // 用户看不到任何导出入口，等于没有兜底。
  var dlBtn = document.getElementById('dl');
  var dlNs = null;
  if(window.claude && window.claude.use){
    window.claude.use('downloads').then(function(dl){ dlNs = dl; })
      .catch(function(){}); }
  function selectLog(msg){
    var det = log.closest('details');
    if(det) det.open = true;
    log.scrollIntoView({block:'center'});
    try {
      var r = document.createRange(); r.selectNodeContents(log);
      var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
    } catch(e){}
    status(msg); }
  dlBtn.addEventListener('click', function(){
    var lines = (log.textContent.match(/GUJI-EVENT (.*)/g) || [])
      .map(function(l){ return l.slice('GUJI-EVENT '.length); }).join('\\n');
    if(!lines){ status('還沒有審查記錄'); return; }
    if(!dlNs){ selectLog('此處無法下載：日誌已全選，按 Ctrl/Cmd+C 複製'); return; }
    dlNs.save({filename: BATCH + '.labels.jsonl', data: lines})
      .then(function(){ status('已下載 ' + lines.split('\\n').length + ' 條'); })
      .catch(function(){
        selectLog('下載被拒絕：日誌已全選，按 Ctrl/Cmd+C 複製'); }); });
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
<span class="prog" id="save-status"></span>
<button type="button" data-f="all" data-on="1">全部</button>
<button type="button" data-f="open" data-on="0">未審</button>
<button type="button" data-f="done" data-on="0">已審</button>
<button type="button" id="dl">匯出審查記錄</button>
</header>
<main class="list" id="list" data-local-filter="all">
{cards}
</main>
<footer class="foot">
<p class="hint">點候選字確認；不在候選中則填「其他字」；拿不準點「存疑」；
切分或聚類有問題點「問題」行按鈕。每次操作後約 3 秒自動儲存
（右上角顯示狀態）；若顯示不可用，點「匯出審查記錄」——能下載就存檔，
不能下載會自動全選日誌，按 Ctrl/Cmd+C 複製貼回對話即可。</p>
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

_KNOWN_OPS = {"confirm", "relabel", "split", "merge", "mark", "flag"}


def extract_events(text: str) -> list[dict]:
    """从任意文本提取审查事件，两种行格式都认：

    - ``GUJI-EVENT {json}``（页面日志 / WebFetch 转写 / 粘贴片段）；
    - 裸 JSONL 行（「下載 labels.jsonl」导出的文件，无前缀）。

    无法解析的行静默跳过。
    """
    out = []
    for m in EVENT_RE.finditer(text):
        try:
            ev = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(ev, dict) and ev.get("op") in _KNOWN_OPS:
            out.append(ev)
    if out:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(ev, dict) and ev.get("op") in _KNOWN_OPS:
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
    # 批次页面导出后若重跑过聚类，簇 id 已变号——按事件携带的成员实例
    # 重绑到当前聚类，否则校验会全部判为「未知簇」
    parsed, n_remapped = remap_events(extract_events(text),
                                      session.cluster_of)
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
    return {"parsed": len(parsed), "new": new, "duplicate": dup,
            "remapped": n_remapped, "errors": errors}
