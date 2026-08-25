# -*- coding: utf-8 -*-
"""撤除笔宽归一的 golden 复核页（artifacts/README.md 台账里的「笔宽归一复核台」）。

    PYTHONPATH=. python scripts/build_norm_stroke_review.py \
        --dataset ../open-guji-dataset/char-normalization \
        --out artifacts/norm_stroke_review.html

改 normalize 会让 char-normalization 的 golden 全部失效，而那层是**人工目视门**
（README：「输出本身就错的绝不冻成 golden」）。本脚本把 37 张的
原图 / 现 golden / 新输出 三联并排出成审查页，裁决经页内「复制裁决」回流。
"""
import argparse, base64, json, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from open_guji_cv.clustering.normalize import normalize_patch  # noqa: E402
from open_guji_cv.clustering.normalize_eval import (  # noqa: E402
    binary_iou, pixel_diff_ratio, skeleton_nodes, to_binary)


def b64(img, scale=1):
    if scale != 1:
        img = cv2.resize(img, (img.shape[1] * scale, img.shape[0] * scale),
                         interpolation=cv2.INTER_NEAREST)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def collect(samples: Path) -> list[dict]:
    rows = []
    for d in sorted(p for p in samples.iterdir()
                    if p.is_dir() and (p / "expected.json").exists()):
        spec = json.loads((d / "expected.json").read_text(encoding="utf-8"))
        gray = cv2.imread(str(d / spec["input"]), cv2.IMREAD_GRAYSCALE)
        golden = to_binary(cv2.imread(str(d / spec["golden"]), cv2.IMREAD_GRAYSCALE))
        new = normalize_patch(gray, stroke_width=None)
        ge, _ = skeleton_nodes(golden)
        ne, _ = skeleton_nodes(new)
        tol = spec["tolerance"]
        pd, iou, ed = pixel_diff_ratio(golden, new), binary_iou(golden, new), abs(ne - ge)
        rows.append({
            "id": d.name, "iid": spec["instance_id"], "status": spec["status"],
            "tier": spec["tier"], "cue": spec.get("sampling_cue"),
            "char": spec.get("char"), "ink": spec.get("ink_ratio"),
            "defect": spec.get("defect"),
            "input": b64(gray), "golden": b64(golden * 255, 3), "new": b64(new * 255, 3),
            "pixel_diff": round(pd, 4), "iou": round(iou, 4),
            "endpoint_delta": ed, "tol": tol,
            "gate_pass": bool(pd <= tol["pixel_diff_ratio"]
                              and iou >= tol["binary_iou_min"]
                              and ed <= tol["skeleton_endpoint_delta_max"]),
            "ink_new": round(float(new.mean()), 4),
            "ink_old": round(float(golden.mean()), 4),
        })
    return rows


ap = argparse.ArgumentParser()
ap.add_argument("--dataset", default="../open-guji-dataset/char-normalization")
ap.add_argument("--out", default="artifacts/norm_stroke_review.html")
args = ap.parse_args()
rows = collect(Path(args.dataset) / "samples")
rows.sort(key=lambda r: (r["status"] != "verified", r["id"]))

HTML = """<title>笔宽归一复核台</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&family=Noto+Serif+SC:wght@500;700&display=swap">
<style>
:root{
  --ground:#FBFAF8; --surface:#FFFFFF; --sunk:#F3F0E9;
  --ink:#16150F; --muted:#6E6A5F; --faint:#96917F;
  --rule:#E2DED4; --rule-strong:#CFC9BA;
  --flag:#A8322A; --flag-soft:#F6E7E4;
  --ok:#3F6B4A; --ok-soft:#E5EEE6;
  --shadow:0 1px 2px rgba(22,21,15,.06),0 8px 24px -16px rgba(22,21,15,.18);
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --ground:#14140F; --surface:#1D1C16; --sunk:#232219;
    --ink:#EDEAE0; --muted:#A8A395; --faint:#7C7768;
    --rule:#34322A; --rule-strong:#4A473C;
    --flag:#E0705F; --flag-soft:#3A211D;
    --ok:#7FB08C; --ok-soft:#1E2A21;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px -16px rgba(0,0,0,.7);
  }
}
:root[data-theme="dark"]{
  --ground:#14140F; --surface:#1D1C16; --sunk:#232219;
  --ink:#EDEAE0; --muted:#A8A395; --faint:#7C7768;
  --rule:#34322A; --rule-strong:#4A473C;
  --flag:#E0705F; --flag-soft:#3A211D;
  --ok:#7FB08C; --ok-soft:#1E2A21;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px -16px rgba(0,0,0,.7);
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:"IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  font-size:15px; line-height:1.6; -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1180px; margin:0 auto; padding:0 24px 96px}
header.intro{padding:56px 0 28px; border-bottom:1px solid var(--rule)}
h1{
  font-family:"Noto Serif SC",Georgia,serif; font-weight:700;
  font-size:clamp(28px,4vw,40px); line-height:1.2; margin:0 0 12px;
  text-wrap:balance; letter-spacing:-.01em;
}
.lede{max-width:62ch; color:var(--muted); margin:0 0 20px}
.lede strong{color:var(--ink); font-weight:600}
.ask{
  background:var(--sunk); border:1px solid var(--rule); border-radius:10px;
  padding:16px 18px; max-width:62ch; margin:0;
}
.ask b{font-family:"Noto Serif SC",Georgia,serif}
.meta-line{
  display:flex; flex-wrap:wrap; gap:8px 20px; margin-top:20px;
  font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:12.5px; color:var(--faint);
}
.bar{
  position:sticky; top:0; z-index:20; background:var(--ground);
  border-bottom:1px solid var(--rule); padding:12px 0;
  display:flex; flex-wrap:wrap; align-items:center; gap:10px 18px;
}
.counts{display:flex; gap:14px; font-family:"IBM Plex Mono",monospace; font-size:13px}
.counts span{color:var(--muted)} .counts b{color:var(--ink); font-variant-numeric:tabular-nums}
.spacer{flex:1 1 auto}
button{
  font:inherit; font-size:13px; color:var(--ink); background:var(--surface);
  border:1px solid var(--rule-strong); border-radius:7px; padding:6px 13px;
  cursor:pointer; transition:background .12s,border-color .12s;
}
button:hover{background:var(--sunk)}
button:focus-visible{outline:2px solid var(--ink); outline-offset:2px}
button[aria-pressed="true"]{background:var(--ink); color:var(--ground); border-color:var(--ink)}
.seg{display:flex; gap:6px}
h2.group{
  font-family:"Noto Serif SC",Georgia,serif; font-size:19px; font-weight:700;
  margin:44px 0 4px; display:flex; align-items:baseline; gap:12px;
}
h2.group small{font-family:"IBM Plex Mono",monospace; font-size:12px; font-weight:400; color:var(--faint)}
.group-note{color:var(--muted); font-size:13.5px; margin:0 0 18px; max-width:64ch}
.rows{display:flex; flex-direction:column; gap:14px}
.row{
  background:var(--surface); border:1px solid var(--rule); border-radius:12px;
  box-shadow:var(--shadow); overflow:hidden;
  display:grid; grid-template-columns:168px 1fr 220px; align-items:stretch;
}
.row[data-mark="ok"]{border-color:var(--ok)}
.row[data-mark="bad"]{border-color:var(--flag)}
.idcol{padding:16px 14px; border-right:1px solid var(--rule); background:var(--sunk); min-width:0}
.sid{font-family:"IBM Plex Mono",monospace; font-size:17px; font-weight:500; letter-spacing:.02em}
.iid{font-family:"IBM Plex Mono",monospace; font-size:11px; color:var(--faint); word-break:break-all; margin-top:2px}
.chips{display:flex; flex-wrap:wrap; gap:5px; margin-top:10px}
.chip{
  font-size:11px; letter-spacing:.04em; text-transform:uppercase;
  padding:2px 7px; border-radius:5px; background:var(--ground);
  border:1px solid var(--rule); color:var(--muted);
}
.chip.defect{background:var(--flag-soft); border-color:var(--flag); color:var(--flag)}
.plates{display:flex; gap:0; align-items:stretch; overflow-x:auto}
.plate{
  flex:0 0 auto; padding:14px 16px; display:flex; flex-direction:column;
  align-items:center; gap:8px; border-right:1px solid var(--rule);
}
.plate:last-child{border-right:none}
.plate.new{background:var(--sunk)}
.plate-label{
  font-size:11px; letter-spacing:.06em; text-transform:uppercase; color:var(--faint);
  display:flex; align-items:center; gap:6px;
}
.plate.new .plate-label{color:var(--ink); font-weight:600}
.plate img{
  display:block; image-rendering:pixelated; background:#fff;
  border:1px solid var(--rule-strong); border-radius:3px;
}
.plate img.norm{width:150px; height:150px}
.plate img.src{height:150px; width:auto; max-width:170px}
.arrow{
  align-self:center; color:var(--faint); font-size:17px; padding:0 2px;
  font-family:"IBM Plex Mono",monospace;
}
.judge{
  padding:14px 16px; border-left:1px solid var(--rule);
  display:flex; flex-direction:column; gap:10px; justify-content:space-between;
}
.nums{font-family:"IBM Plex Mono",monospace; font-size:12px; color:var(--muted); display:grid; gap:3px}
.nums div{display:flex; justify-content:space-between; gap:10px}
.nums b{color:var(--ink); font-weight:500; font-variant-numeric:tabular-nums}
.nums .over{color:var(--flag)}
.acts{display:flex; gap:7px}
.acts button{flex:1}
.acts button.ok[aria-pressed="true"]{background:var(--ok); border-color:var(--ok); color:#fff}
.acts button.bad[aria-pressed="true"]{background:var(--flag); border-color:var(--flag); color:#fff}
.toast{
  position:fixed; left:50%; bottom:28px; transform:translateX(-50%);
  background:var(--ink); color:var(--ground); padding:9px 18px; border-radius:8px;
  font-size:13px; opacity:0; pointer-events:none; transition:opacity .2s;
}
.toast.on{opacity:1}
footer{margin-top:56px; padding-top:20px; border-top:1px solid var(--rule); color:var(--faint); font-size:12.5px}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
@media (max-width:900px){
  .row{grid-template-columns:1fr}
  .idcol{border-right:none; border-bottom:1px solid var(--rule)}
  .judge{border-left:none; border-top:1px solid var(--rule)}
}
</style>

<div class="wrap">
<header class="intro">
  <h1>笔宽归一复核台</h1>
  <p class="lede">归一化打算<strong>撤掉笔宽归一</strong>（骨架化 + 统一膨胀到 3px）。这一步当年是为刚性 F1 判据抗着墨浓淡的，现在的软覆盖判据本来就不吃这一套，它反而把 已/巳 那类开口糊死。撤掉后 triplets hard 排序 0.684 → 0.763，阈值集主指标 recall 0.0807 → 0.1130。</p>
  <div class="ask">
    <b>要你判的不是「新旧一不一样」</b>——那必然不一样，37 张全部出容差，这是设计使然。要判的是：<b>右边那张（新输出）是不是这个字的正确归一化</b>。笔画该在的都在、不该连的没连、不该断的没断，就算过。
  </div>
  <div class="meta-line">
    <span>char-normalization · 37 样本</span>
    <span>当前实现逐位复现 golden 37/37</span>
    <span>墨量占比中位 0.168 → 0.190</span>
  </div>
</header>

<div class="bar">
  <div class="counts">
    <span>待定 <b id="c-pend">0</b></span>
    <span>可以 <b id="c-ok">0</b></span>
    <span>有问题 <b id="c-bad">0</b></span>
  </div>
  <div class="spacer"></div>
  <div class="seg">
    <button data-filter="all" aria-pressed="true">全部</button>
    <button data-filter="pending" aria-pressed="false">只看待定</button>
    <button data-filter="bad" aria-pressed="false">只看有问题</button>
  </div>
  <button id="copy">复制裁决</button>
</div>

<div id="groups"></div>

<footer>
  三个容差指标（像素差 / IoU / 骨架端点差）只是参考——它们量的是「与旧 golden 的距离」，
  而这次旧 golden 本来就要被替换。以目视为准。
</footer>
</div>
<div class="toast" id="toast"></div>

<script type="application/json" id="data">__DATA__</script>
<script>
const ROWS = JSON.parse(document.getElementById('data').textContent);
const KEY = 'norm-review-v1';
let marks = {};
try { marks = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (e) { marks = {}; }
function save(){ try { localStorage.setItem(KEY, JSON.stringify(marks)); } catch (e) {} }

const GROUPS = [
  {key:'verified', title:'verified · 严格回归门',
   note:'这 33 张的 golden 是逐张目视确认过的正确输出，回归门必须全过。你确认之后我才会用新输出重冻。'},
  {key:'known_defect', title:'known_defect · 只记录行为',
   note:'这 4 张当前输出本身就有缺陷（笔画被吃 / 残留没去掉），按规矩绝不冻成 golden。看新输出是不是把缺陷修好了。'},
];

function esc(s){ return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

function metricRow(label, val, over){
  return `<div><span>${label}</span><b class="${over?'over':''}">${val}</b></div>`;
}

function rowHTML(r){
  const t = r.tol;
  const chips = [
    `<span class="chip">${esc(r.tier)}</span>`,
    r.cue ? `<span class="chip">${esc(r.cue)}</span>` : '',
    r.char ? `<span class="chip">${esc(r.char)}</span>` : '',
    r.defect ? `<span class="chip defect">${esc(r.defect)}</span>` : '',
  ].join('');
  return `<article class="row" data-id="${r.id}" data-group="${r.status}" data-mark="${marks[r.id]||''}">
    <div class="idcol">
      <div class="sid">${esc(r.id)}</div>
      <div class="iid">${esc(r.iid)}</div>
      <div class="chips">${chips}</div>
    </div>
    <div class="plates">
      <div class="plate"><div class="plate-label">原始图块</div><img class="src" src="${r.input}" alt="样本 ${esc(r.id)} 的原始灰度图块"></div>
      <div class="arrow">→</div>
      <div class="plate"><div class="plate-label">现 golden · 笔宽 3px</div><img class="norm" src="${r.golden}" alt="样本 ${esc(r.id)} 当前冻结的归一化输出"></div>
      <div class="plate new"><div class="plate-label">新输出 · 不做笔宽归一</div><img class="norm" src="${r.new}" alt="样本 ${esc(r.id)} 撤除笔宽归一后的输出"></div>
    </div>
    <div class="judge">
      <div class="nums">
        ${metricRow('像素差', r.pixel_diff, r.pixel_diff > t.pixel_diff_ratio)}
        ${metricRow('IoU', r.iou, r.iou < t.binary_iou_min)}
        ${metricRow('骨架端点差', r.endpoint_delta, r.endpoint_delta > t.skeleton_endpoint_delta_max)}
        ${metricRow('墨量 旧→新', r.ink_old + ' → ' + r.ink_new, false)}
      </div>
      <div class="acts">
        <button class="ok" data-act="ok" aria-pressed="${marks[r.id]==='ok'}">可以</button>
        <button class="bad" data-act="bad" aria-pressed="${marks[r.id]==='bad'}">有问题</button>
      </div>
    </div>
  </article>`;
}

document.getElementById('groups').innerHTML = GROUPS.map(g => {
  const rs = ROWS.filter(r => r.status === g.key);
  if (!rs.length) return '';
  return `<h2 class="group">${esc(g.title)}<small>${rs.length} 张</small></h2>
    <p class="group-note">${esc(g.note)}</p>
    <div class="rows">${rs.map(rowHTML).join('')}</div>`;
}).join('');

function refresh(){
  let ok=0, bad=0;
  ROWS.forEach(r => { if (marks[r.id]==='ok') ok++; else if (marks[r.id]==='bad') bad++; });
  document.getElementById('c-ok').textContent = ok;
  document.getElementById('c-bad').textContent = bad;
  document.getElementById('c-pend').textContent = ROWS.length - ok - bad;
}
refresh();

document.getElementById('groups').addEventListener('click', e => {
  const btn = e.target.closest('button[data-act]');
  if (!btn) return;
  const row = btn.closest('.row'), id = row.dataset.id, act = btn.dataset.act;
  marks[id] = (marks[id] === act) ? '' : act;
  if (!marks[id]) delete marks[id];
  row.dataset.mark = marks[id] || '';
  row.querySelectorAll('button[data-act]').forEach(b =>
    b.setAttribute('aria-pressed', String(marks[id] === b.dataset.act)));
  save(); refresh(); applyFilter();
});

let filter = 'all';
function applyFilter(){
  document.querySelectorAll('.row').forEach(row => {
    const m = marks[row.dataset.id] || '';
    const show = filter === 'all' || (filter === 'pending' && !m) || (filter === 'bad' && m === 'bad');
    row.style.display = show ? '' : 'none';
  });
}
document.querySelectorAll('button[data-filter]').forEach(b => b.addEventListener('click', () => {
  filter = b.dataset.filter;
  document.querySelectorAll('button[data-filter]').forEach(o =>
    o.setAttribute('aria-pressed', String(o === b)));
  applyFilter();
}));

const toast = document.getElementById('toast');
function say(msg){ toast.textContent = msg; toast.classList.add('on'); setTimeout(() => toast.classList.remove('on'), 1900); }

document.getElementById('copy').addEventListener('click', async () => {
  const bad = ROWS.filter(r => marks[r.id]==='bad').map(r => r.id);
  const ok  = ROWS.filter(r => marks[r.id]==='ok').map(r => r.id);
  const pend= ROWS.filter(r => !marks[r.id]).map(r => r.id);
  const text = JSON.stringify({可以: ok, 有问题: bad, 待定: pend}, null, 1);
  try { await navigator.clipboard.writeText(text); say('裁决已复制，贴回对话即可'); }
  catch (e) { say('复制失败，请手动选中下方 JSON'); console.log(text); }
});
</script>
"""
out = Path(args.out)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(HTML.replace("__DATA__", json.dumps(rows, ensure_ascii=False)),
               encoding="utf-8")
n_ok = sum(r["gate_pass"] for r in rows)
print(f"写出 {out}  {out.stat().st_size / 1e6:.2f} MB")
print(f"样本 {len(rows)}（verified {sum(r['status'] == 'verified' for r in rows)}）"
      f"  新输出仍能过回归门的 {n_ok}/{len(rows)}")
