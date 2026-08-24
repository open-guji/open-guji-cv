# -*- coding: utf-8 -*-
"""刻本字形库体检：形离群 + 竞争字 + OCR 异议 → 审查页人裁。

    # 体检（扫全库 + 报告 + 审查页）
    PYTHONPATH=. python scripts/audit_glyph_db.py run \
        --db output/glyph.db --out output/glyphdb_audit

    # 回收审查页事件（evict 撤库重审 / ok 白名单）
    PYTHONPATH=. python scripts/audit_glyph_db.py apply \
        --db output/glyph.db --events <events.txt>

判据与动作语义见 open_guji_cv/clustering/audit.py 模块注释；周期性
使用流程见 .claude/skills/glyphdb-audit/SKILL.md。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html as _html
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

from open_guji_cv.clustering.audit import (AuditEntry, apply_ocr,  # noqa: E402
                                           evict_instance, shape_audit)
from open_guji_cv.clustering.glyph_db import GlyphDB, _unpng  # noqa: E402
from open_guji_cv.clustering.review.persist_js import PERSIST_JS  # noqa: E402
from open_guji_cv.clustering.seed_queue import (STATUS_PENDING,  # noqa: E402
                                                SeedItem)
from open_guji_cv.clustering.variants import VariantMap  # noqa: E402


def load_entries(db: GlyphDB, vmap: VariantMap):
    """exemplars（库的检索面）→ AuditEntry 列表 + {iid: patch_png}。"""
    rows = db.conn.execute(
        """SELECT e.instance_id, g.char, d.data, i.patch_png, a.provenance
           FROM exemplars e
           JOIN glyphs g ON g.glyph_id = e.glyph_id
           JOIN derived d ON d.instance_id = e.instance_id AND d.kind='norm'
           JOIN instances i ON i.instance_id = e.instance_id
           LEFT JOIN admissions a ON a.instance_id = e.instance_id""").fetchall()
    entries, patches = [], {}
    for iid, ch, norm_png, patch_png, prov in rows:
        entries.append(AuditEntry(iid, ch, vmap.semantic(ch),
                                  _unpng(norm_png), prov))
        patches[iid] = patch_png
    return entries, patches


def run_ocr(patches: dict[str, bytes], only: set[str] | None = None):
    """RapidOCR top1 + s2t（与载体同源）。only 给了就只跑这些实例。"""
    import cv2
    import opencc
    from open_guji_cv.clustering.candidates import RapidOcrSource
    src = RapidOcrSource()
    src._ensure()
    cc = opencc.OpenCC("s2t")
    out: dict[str, tuple[str, float]] = {}
    for iid, png in patches.items():
        if only is not None and iid not in only:
            continue
        gray = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            continue
        topk = src.rec_topk(gray)
        if topk:
            ch, prob = topk[0]
            out[iid] = (cc.convert(ch)[:1] or ch, float(prob))
        else:
            out[iid] = ("", 0.0)
    return out


def _b64(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


FLAG_LABELS = {"rival": "形似他字", "outlier": "同字离群", "ocr": "OCR 异议"}


def render_html(findings, patches, batch_id: str, n_total: int,
                singles_ocr: list) -> str:
    cards = []
    for f in findings:
        tags = "".join(f'<span class="tag t-{t}">{FLAG_LABELS[t]}</span>'
                       for t in f.flags)
        figs = [f'<figure><img src="{_b64(patches[f.instance_id])}">'
                f'<figcaption>本例「{_html.escape(f.char)}」</figcaption></figure>']
        if f.same_peer and f.same_peer in patches:
            figs.append(
                f'<figure><img src="{_b64(patches[f.same_peer])}">'
                f'<figcaption>同字最近 cov {f.best_same:.2f}</figcaption></figure>')
        if f.other_peer and f.other_peer in patches:
            figs.append(
                f'<figure><img src="{_b64(patches[f.other_peer])}">'
                f'<figcaption>竞争「{_html.escape(f.other_char or "?")}」'
                f' cov {f.best_other:.2f}</figcaption></figure>')
        ocr_line = (f'<small class="near">OCR 读作「{_html.escape(f.ocr_char)}」'
                    f' {f.ocr_prob:.0%}</small>' if f.ocr_char else "")
        cards.append(f"""
<div class="card" data-iid="{_html.escape(f.instance_id)}">
 <header><span class="iid">{_html.escape(f.instance_id)}</span>
  <b style="font-size:1.3rem">{_html.escape(f.char)}</b>{tags}
  <span class="tag" data-slot="done"></span></header>
 <div class="row"><div class="imgs">{''.join(figs)}</div>
  <div class="main">{ocr_line}
   <div class="cands">
    <button type="button" class="act" data-op="evict">撤库重审 <kbd>X</kbd></button>
    <button type="button" class="act ok" data-op="ok">没问题 <kbd>O</kbd></button>
   </div></div></div>
</div>""")
    singles = "".join(
        f'<div class="single"><img src="{_b64(patches[iid])}">'
        f'<span>{_html.escape(ch)} → OCR「{_html.escape(oc)}」{p:.0%}</span>'
        f'<button type="button" class="act mini" data-op="evict" data-iid='
        f'"{_html.escape(iid)}">撤</button>'
        f'<button type="button" class="act mini ok" data-op="ok" data-iid='
        f'"{_html.escape(iid)}">可</button></div>'
        for iid, ch, oc, p in singles_ocr)
    consts = (f'var BATCH = {json.dumps(batch_id)};')
    return f"""<title>字形库体检 · {batch_id.split('-')[-1]}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{{--paper:#faf6ee;--card:#fffdf8;--ink:#2b2620;--muted:#8a7f6e;
 --line:#e3dbc9;--seal:#a63b2a;--seal-ink:#fff6ee;--done:#3d7a4f;
 --doubt:#8a6d1f;--bad:#8a4238;--imgbg:#fff}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{
 --paper:#1d1a15;--card:#26221b;--ink:#e8e0d0;--muted:#9a8f7c;
 --line:#3a342a;--seal:#d0715e;--seal-ink:#2b1512;--done:#7fba8f;
 --doubt:#cfae4e;--bad:#cf8377;--imgbg:#efe9dd}}}}
:root[data-theme="dark"]{{--paper:#1d1a15;--card:#26221b;--ink:#e8e0d0;
 --muted:#9a8f7c;--line:#3a342a;--seal:#d0715e;--seal-ink:#2b1512;
 --done:#7fba8f;--doubt:#cfae4e;--bad:#cf8377;--imgbg:#efe9dd}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--paper);color:var(--ink);line-height:1.5;
 font-family:"Noto Serif TC","Songti TC","SimSun",serif}}
.top{{position:sticky;top:0;z-index:5;background:var(--paper);
 border-bottom:1px solid var(--line);padding:.6rem 1rem;display:flex;
 flex-wrap:wrap;gap:.5rem 1.1rem;align-items:baseline}}
.top h1{{font-size:1.05rem;margin:0}}.prog{{color:var(--muted)}}
#save-status[data-bad="1"]{{color:var(--seal-ink);background:var(--bad);
 padding:.1rem .5rem;border-radius:3px;font-size:.8rem}}
#copybar[data-pending="1"]{{background:var(--doubt);color:var(--seal-ink)}}
.top button{{font:inherit;font-size:.85rem;background:none;color:var(--ink);
 border:1px solid var(--line);border-radius:3px;padding:.15rem .6rem;cursor:pointer}}
.list{{max-width:56rem;margin:0 auto;padding:1rem;display:flex;
 flex-direction:column;gap:.8rem}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:4px}}
.card.active{{border-color:var(--seal);box-shadow:0 0 0 1px var(--seal)}}
.card>header{{display:flex;gap:.7rem;align-items:baseline;flex-wrap:wrap;
 padding:.4rem .8rem;border-bottom:1px solid var(--line)}}
.iid{{font-family:ui-monospace,monospace;font-size:.75rem;color:var(--muted)}}
.row{{display:flex;gap:1.1rem;padding:.8rem;flex-wrap:wrap}}
.imgs{{display:flex;gap:.6rem}}
.imgs figure{{margin:0;text-align:center}}
.imgs img{{width:6.5rem;height:6.5rem;object-fit:contain;background:var(--imgbg);
 border:1px solid var(--line);border-radius:2px}}
.imgs figcaption{{font-size:.72rem;color:var(--muted)}}
.main{{flex:1;min-width:14rem;display:flex;flex-direction:column;gap:.6rem}}
.cands{{display:flex;gap:.45rem}}
.act{{font:inherit;border:1px solid var(--line);background:none;color:var(--ink);
 border-radius:3px;padding:.25rem .7rem;cursor:pointer}}
.act:hover{{border-color:var(--seal)}}
.act.ok{{color:var(--done)}}
.tag{{font-size:.68rem;border:1px solid var(--line);border-radius:3px;
 padding:0 .35em;color:var(--muted)}}
.t-rival{{color:var(--bad);border-color:var(--bad)}}
.t-outlier{{color:var(--doubt);border-color:var(--doubt)}}
.t-ocr{{color:var(--seal)}}
.near{{color:var(--muted)}}
.card[data-state="done"] .row{{display:none}}
.singles{{max-width:56rem;margin:0 auto;padding:0 1rem 2rem;display:flex;
 flex-wrap:wrap;gap:.5rem}}
.single{{display:flex;align-items:center;gap:.4rem;border:1px solid var(--line);
 border-radius:3px;padding:.25rem .5rem;background:var(--card);font-size:.8rem}}
.single img{{width:3rem;height:3rem;object-fit:contain;background:var(--imgbg)}}
.act.mini{{padding:.05rem .4rem;font-size:.75rem}}
kbd{{font-family:ui-monospace,monospace;font-size:.68rem;color:var(--muted);
 border:1px solid var(--line);border-radius:3px;padding:0 .3em}}
.log{{display:none}}
h2{{max-width:56rem;margin:1rem auto .3rem;padding:0 1rem;font-size:.95rem}}
.note{{max-width:56rem;margin:0 auto;padding:0 1rem;color:var(--muted);
 font-size:.8rem}}
</style>
<div class="top"><h1>字形库体检</h1>
 <span class="prog" id="prog"></span>
 <span id="save-status"></span>
 <button type="button" id="copybar">复制事件</button>
 <button type="button" id="dlbar">下载</button>
</div>
<h2>可疑刻例（多例字，{len(findings)} 条 / 全库 {n_total}）</h2>
<p class="note">X 撤库重审（回审查队列重新裁决），O 没问题（进白名单，
下轮不再出）。J/K 上下张。三路信号都只是怀疑，以你的眼睛为准。</p>
<div class="list" id="list">{''.join(cards)}</div>
<h2>单例字 OCR 异议（{len(singles_ocr)} 条，无同字参照，仅供扫一眼）</h2>
<div class="singles">{singles}</div>
<pre class="log" id="guji-log" data-seq="0" data-batch="{_html.escape(batch_id)}"></pre>
<script>
(function(){{
  {consts}
  function progress(){{
    var l = document.getElementById('list');
    var done = l.querySelectorAll('.card[data-state="done"]').length;
    document.getElementById('prog').textContent =
      done + '/' + l.querySelectorAll('.card').length;
  }}
  function cardOf(iid){{
    var c = null;
    document.getElementById('list').querySelectorAll('.card')
      .forEach(function(x){{ if(x.dataset.iid === iid) c = x; }});
    return c;
  }}
  function setActive(card){{
    document.getElementById('list').querySelectorAll('.card.active')
      .forEach(function(x){{ x.classList.remove('active'); }});
    if(card){{ card.classList.add('active');
      card.scrollIntoView({{block:'center'}}); }}
  }}
  {PERSIST_JS}
  function applyVisual(ev){{
    var card = cardOf(ev.instance_id);
    if(card){{
      card.dataset.state = 'done';
      var slot = card.querySelector('[data-slot="done"]');
      if(slot) slot.textContent = (ev.op === 'evict' ? '已撤库 ✗' : '没问题 ✓');
      return;
    }}
    var b = document.querySelector(
      '.single .act[data-iid="' + ev.instance_id + '"]');
    if(b) b.closest('.single').style.opacity = '0.45';
  }}
  function act(iid, op){{
    emit({{op: op, instance_id: iid}});
    applyVisual({{op: op, instance_id: iid}});
    var card = cardOf(iid);
    if(card && card.nextElementSibling) setActive(card.nextElementSibling);
  }}
  document.addEventListener('click', function(ev){{
    var b = ev.target.closest('.act');
    if(!b) return;
    var iid = b.dataset.iid ||
      (b.closest('.card') && b.closest('.card').dataset.iid);
    if(iid) act(iid, b.dataset.op);
  }});
  document.addEventListener('keydown', function(ev){{
    if(ev.target.tagName === 'INPUT') return;
    var l = document.getElementById('list');
    var cur = l.querySelector('.card.active') ||
              l.querySelector('.card:not([data-state="done"])');
    if(!cur) return;
    var k = ev.key.toLowerCase();
    if(k === 'x') act(cur.dataset.iid, 'evict');
    else if(k === 'o') act(cur.dataset.iid, 'ok');
    else if(k === 'j') setActive(cur.nextElementSibling || cur);
    else if(k === 'k') setActive(cur.previousElementSibling || cur);
    else return;
    ev.preventDefault();
  }});
  function restore(){{
    events().forEach(applyVisual);
    restoreView();
  }}
  document.getElementById('copybar').addEventListener('click', function(){{
    var text = lines().join('\\n');
    if(!text){{ status('还没有裁决记录'); return; }}
    var n = lines().length;
    if(navigator.clipboard && navigator.clipboard.writeText){{
      navigator.clipboard.writeText(text).then(function(){{
        markExported(n); status('已复制 ' + n + ' 条，贴回对话即可');
      }}).catch(function(){{ status('复制失败，请手动全选日志', true); }});
    }}
  }});
  restore();
  progress();
  refreshBar();
  if(!document.querySelector('.card.active'))
    setActive(document.querySelector('#list .card:not([data-state="done"])'));
}})();
</script>"""


def cmd_run(args) -> None:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ok_path = out_dir / "audit_ok.json"
    whitelist = set(json.loads(ok_path.read_text(encoding="utf-8"))) \
        if ok_path.exists() else set()

    vmap = VariantMap.load()
    db = GlyphDB(args.db)
    try:
        entries, patches = load_entries(db, vmap)
    finally:
        db.close()
    print(f"库内刻例 {len(entries)}，白名单 {len(whitelist)}")

    findings = shape_audit(entries)
    sem = {e.instance_id: e.semantic for e in entries}
    singles = [e.instance_id for e in entries
               if findings[e.instance_id].best_same < 0]

    readings = {}
    if not args.no_ocr:
        readings = run_ocr(patches)
        apply_ocr(findings, readings, vmap.semantic)

    flagged = [f for f in findings.values()
               if f.flags and f.instance_id not in whitelist
               and f.best_same >= 0]
    flagged.sort(key=lambda f: (-f.score, -f.best_other, f.best_same))
    singles_ocr = []
    for iid in singles:
        if iid in whitelist:
            continue
        ch, prob = readings.get(iid, ("", 0.0))
        f = findings[iid]
        if "ocr" in f.flags:
            singles_ocr.append((iid, f.char, ch, prob))

    report = {
        "n_exemplars": len(entries),
        "n_flagged": len(flagged),
        "n_singleton": len(singles),
        "n_singleton_ocr": len(singles_ocr),
        "whitelisted": len(whitelist),
        "flagged": [{
            "instance_id": f.instance_id, "char": f.char, "flags": f.flags,
            "best_same": round(f.best_same, 4), "same_peer": f.same_peer,
            "best_other": round(f.best_other, 4), "other_char": f.other_char,
            "other_peer": f.other_peer, "ocr": [f.ocr_char, round(f.ocr_prob, 3)],
        } for f in flagged],
        "singleton_ocr": [{"instance_id": i, "char": c, "ocr": [o, round(p, 3)]}
                          for i, c, o, p in singles_ocr],
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    batch_id = "glyphdb-audit-" + hashlib.md5(
        json.dumps(sorted(f.instance_id for f in flagged)).encode()
    ).hexdigest()[:8]
    need = {f.instance_id for f in flagged} | {i for i, *_ in singles_ocr}
    for f in flagged:
        need |= {p for p in (f.same_peer, f.other_peer) if p}
    (out_dir / "review.html").write_text(
        render_html(flagged, {k: v for k, v in patches.items() if k in need},
                    batch_id, len(entries), singles_ocr), encoding="utf-8")
    print(json.dumps({k: report[k] for k in
                      ("n_exemplars", "n_flagged", "n_singleton",
                       "n_singleton_ocr", "whitelisted")}, ensure_ascii=False))
    print(f"报告 {out_dir/'report.json'}\n审查页 {out_dir/'review.html'}")


PREFIX = "GUJI-SEED-EVENT"        # 与 persist_js 同前缀，op 空间不同


def cmd_apply(args) -> None:
    out_dir = Path(args.out)
    ok_path = out_dir / "audit_ok.json"
    whitelist = set(json.loads(ok_path.read_text(encoding="utf-8"))) \
        if ok_path.exists() else set()
    last: dict[str, dict] = {}
    for line in Path(args.events).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith(PREFIX):
            continue
        try:
            ev = json.loads(line[len(PREFIX):].strip())
        except json.JSONDecodeError:
            continue
        if ev.get("op") in ("evict", "ok") and ev.get("instance_id"):
            cur = last.get(ev["instance_id"])
            if cur is None or (ev.get("seq") or 0) >= (cur.get("seq") or 0):
                last[ev["instance_id"]] = ev

    db = GlyphDB(args.db)
    n = {"evicted": 0, "ok": 0, "reopened": 0, "missing": 0}
    try:
        for iid, ev in sorted(last.items()):
            if ev["op"] == "ok":
                whitelist.add(iid)
                n["ok"] += 1
                continue
            ch = evict_instance(db, iid)
            if ch is None:
                n["missing"] += 1
                continue
            n["evicted"] += 1
            book = iid.split(":")[0]
            qp = Path(args.output) / book / "phase9_seed" / "queue.jsonl"
            if qp.exists():
                rows = [SeedItem.from_json(l) for l in
                        qp.read_text(encoding="utf-8").splitlines() if l.strip()]
                for it in rows:
                    if it.instance_id == iid:
                        it.status = STATUS_PENDING
                        it.decided_char = None
                        it.provenance = None
                        it.note = "audit_evict"
                        n["reopened"] += 1
                qp.write_text("".join(it.to_json() + "\n" for it in rows),
                              encoding="utf-8")
    finally:
        db.close()
    ok_path.parent.mkdir(parents=True, exist_ok=True)
    ok_path.write_text(json.dumps(sorted(whitelist), ensure_ascii=False,
                                  indent=1), encoding="utf-8")
    print(json.dumps(n, ensure_ascii=False))
    if n["reopened"]:
        print("撤库实例已退回审查队列；重新导出对应页并 seed-ingest 其裁决，"
              "progress 的 pending 数会在下次导出时刷新。")


def main() -> None:
    ap = argparse.ArgumentParser(description="刻本字形库体检")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run", help="扫全库 + 报告 + 审查页")
    p_run.add_argument("--db", default="output/glyph.db")
    p_run.add_argument("--out", default="output/glyphdb_audit")
    p_run.add_argument("--no-ocr", action="store_true")
    p_run.set_defaults(fn=cmd_run)
    p_ap = sub.add_parser("apply", help="回收审查页事件")
    p_ap.add_argument("--db", default="output/glyph.db")
    p_ap.add_argument("--out", default="output/glyphdb_audit")
    p_ap.add_argument("--output", default="output", help="书输出根目录（找队列用）")
    p_ap.add_argument("--events", required=True)
    p_ap.set_defaults(fn=cmd_apply)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
