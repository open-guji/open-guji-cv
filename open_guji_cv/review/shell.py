"""审查页壳的双传输包装。

**不重写 `scripts/_review_shell.py`**——它的令牌、自存、定点检查是踩出来的，
`.claude/skills/review-artifact/` 那套仍是出新页的正门。这里只做两件事：

1. `transport="artifact"`：原样交给现有壳，行为不变（自存到 Artifact，事后收割）；
2. `transport="server"`：在现有壳外面套一小段 JS，把每次裁决同时 `POST /api/events`
   到控制台。断网时进 localStorage 队列，恢复后补发——所以本地这条路和 Artifact
   那条路一样，不会丢裁决。

两种传输产出的裁决**格式相同**（都进 `#data` 的 verdicts），所以 server 模式的页面
也能被 `harvest` 读；反之 artifact 模式的页收割后走同一个 EventLog。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent

# 套在现有壳外面的一小段：把裁决同步到控制台。
# 契约：宿主壳把裁决写进 window.STATE.verdicts 并调用 window.onVerdict(id, v)（若存在）。
SERVER_SYNC_JS = """
(function(){
  var API = %(api)s, BATCH = %(batch)s, STEP = %(step)s, UNIT = %(unit)s, KIND = %(kind)s;
  var QKEY = 'guji-outbox:' + BATCH;
  function queue(){ try { return JSON.parse(localStorage.getItem(QKEY) || '[]'); } catch(e){ return []; } }
  function setQueue(q){ try { localStorage.setItem(QKEY, JSON.stringify(q)); } catch(e){} }
  function badge(txt, bad){
    var el = document.getElementById('sync-status');
    if(!el){ el = document.createElement('div'); el.id = 'sync-status';
      el.style.cssText = 'position:fixed;right:10px;bottom:10px;padding:3px 8px;border-radius:4px;font:12px var(--mono,monospace);z-index:99';
      document.body.appendChild(el); }
    el.textContent = txt;
    el.style.background = bad ? 'var(--zhu-soft,#f4e2de)' : 'var(--ok-soft,#dfebe2)';
    el.style.color = bad ? 'var(--zhu,#a8342a)' : 'var(--ok,#39684a)';
  }
  function flush(){
    var q = queue();
    if(!q.length){ badge('已同步'); return Promise.resolve(); }
    return fetch(API + '/api/events', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({batch: BATCH, step: STEP, unit: UNIT, kind: KIND, events: q})})
      .then(function(r){ if(!r.ok) throw new Error(r.status); setQueue([]); badge('已同步 ' + q.length + ' 条'); })
      .catch(function(e){ badge('待同步 ' + q.length + ' 条（' + e.message + '）', true); });
  }
  window.onVerdict = function(id, v, extra){
    var q = queue();
    q.push(Object.assign({id: id, verdict: v, t: Date.now()}, extra || {}));
    setQueue(q); flush();
  };
  addEventListener('online', flush);
  setInterval(flush, 20000);
  setTimeout(flush, 1500);
})();
"""


def _load_base_shell():
    """按需 import `scripts/_review_shell.py`（不是包，按路径加载）。"""
    import importlib.util
    path = REPO / "scripts" / "_review_shell.py"
    if not path.exists():
        raise FileNotFoundError(f"找不到审查壳: {path}")
    spec = importlib.util.spec_from_file_location("_review_shell", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_review_shell", mod)
    spec.loader.exec_module(mod)   # type: ignore[union-attr]
    return mod


def server_sync_js(batch: str, step: str, unit: str = "page", kind: str = "verdict",
                   api: str = "") -> str:
    return SERVER_SYNC_JS % {
        "api": json.dumps(api), "batch": json.dumps(batch), "step": json.dumps(step),
        "unit": json.dumps(unit), "kind": json.dumps(kind)}


def render(title: str, key: str, verdicts: dict, css: str, page_js: str, payload: dict,
           *, transport: str = "artifact", batch: str | None = None, step: str = "",
           unit: str = "page", kind: str = "verdict", api: str = "") -> str:
    """出一页审查页。参数与 `scripts/_review_shell.render` 一致，多了传输那几个。"""
    shell = _load_base_shell()
    js = page_js
    if transport == "server":
        js = page_js + "\n" + server_sync_js(batch or key, step, unit, kind, api)
    return shell.render(title, key, verdicts, css, js, payload)
