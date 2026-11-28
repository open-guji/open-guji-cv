"""第三步看图大模型 `glyph_vis` 的答案缓存（2026-11-28，CV3；接口草案 CV4 审定，目录 GM3／GM4 定）。

**只当证据，不是人裁、不算钉**：`kind="vis_glyph"`、`actor="model"`、`payload.source="llm"`；`events.event_level` 给 None
（`counts_as_pin` 假）；裁定库 `RulingStore` 只收 `ctx_ruling`，不会混进它的窗口键索引。

## 目录

`<feedback>/vis_glyph/<批次>.jsonl`（**单开目录，不进 `rulings/`**，GM4 2026-11-28 定：钉旧 cv 的书读 `rulings/` 时
`Event.kind` 是 Literal，认不得新 kind 会读崩）。目录名只在 `SUBDIR` 一处定义。同 `EventLog` 的事件格式与追加纪律。
随中心库同步要 manager 侧把这个目录登记进同步口径（`datastore.scope.classify`），在那之前只在本机。

## 事件

- `target`：`{step: "glyph_vis", unit: "glyph_img", key: <img_sha>}`——按图寻址，**不按格号**（不进格级人裁的各种闸：
  换图源 rev 闸在 `core.event_files.GATE_EXEMPT_KINDS` 里豁免、manager 推库「缺 u」闸只看 unit=cell 与 ctx_ruling）；
- `payload`：`{source: "llm", img_sha, img_shape, patch, prompt, prompt_sha, cands, char, other, conf, why, model, tok, cell, legacy}`，
  rekey 来的另有 `source_event`；`cell` 只给人看、给审核页预填，不进键。

## 键与读法

`(img_sha, prompt_sha, cands_key, model)`，四样全对才命中（候选变了、模型不同都不命中，**不做回退**）。`model` 是书配置值；
对话看图判写 `session:<名>`，读时要书配置 `accept_models` 显式列出才认。后到覆盖（`replay_key`）。
弃权（low、其他）也记，免得反复问；出错、拒答不记。

`legacy=true`（`scripts/rekey_vis1_to_glyph_vis.py` 从第四步 vis1 旧缓存转来的，看过前后文）另建按 `img_sha` 的索引，
只在 `accept_legacy` 开时读（仅供 A/B）：旧答案是按「组＋共字组」问的，候选集合与第三步对不上，所以不比候选键，
由调用方核答案字在本次候选里。

`cache_pin()`：本目录全部 `vis_glyph` 事件（id＋ts）的哈希，产物页头记它，只记录、不进指纹（导一批新答案后从 `glyph_vis` 起 force）。
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from .events import EventLog, EventTarget, make_event, replay_key

KIND = "vis_glyph"
#: 缓存目录（相对 feedback 根）。**只在这里定义**；manager 同步口径、rekey 脚本都从这里取
SUBDIR = "vis_glyph"
SOURCE = "llm"
TARGET_UNIT = "glyph_img"
LEGACY_PROMPT = "vis1-legacy"


def default_root() -> Path:
    from .events import default_feedback_root
    return default_feedback_root()


class VisGlyphLog(EventLog):
    """`<feedback>/vis_glyph/` 的事件日志（同 `EventLog` 的格式与追加纪律）。"""

    @property
    def events_dir(self) -> Path:
        return self.root / SUBDIR

    @property
    def consumed_dir(self) -> Path:
        return self.root / f"{SUBDIR}_consumed"


def cands_key(cands) -> str:
    from ..groups.vis_img import cands_key as _ck
    return _ck(cands)


class VisGlyphStore:
    """读写看图缓存。`root` 是 feedback 根（缺省 `default_feedback_root()`）；`persist=False` 只在内存里记。"""

    def __init__(self, root: str | Path | None = None, persist: bool = True):
        self.log = VisGlyphLog(Path(root) if root else None)
        self.persist = persist
        self._idx: dict | None = None
        self._legacy: dict = {}
        self._pin: list[str] = []
        self._sources: set[str] = set()

    @property
    def dir(self) -> Path:
        return self.log.events_dir

    def _load(self) -> dict:
        if self._idx is None:
            idx: dict = {}
            leg: dict = {}
            pin: list[str] = []
            if self.log.events_dir.exists():
                evs = [e for e in self.log.iter_all(raw=True) if e.kind == KIND]
                for e in sorted(evs, key=replay_key):           # 后到覆盖
                    p = e.payload or {}
                    pin.append(f"{e.id}|{e.ts}")
                    if p.get("legacy"):
                        leg[p.get("img_sha")] = p
                        if p.get("source_event"):
                            self._sources.add(p["source_event"])
                    else:
                        idx[(p.get("img_sha"), p.get("prompt_sha"), cands_key(p.get("cands") or ()), p.get("model") or "")] = p
            self._idx, self._legacy, self._pin = idx, leg, pin
        return self._idx

    def lookup(self, img_sha: str, prompt_sha: str, cands, models) -> dict | None:
        """`models` 按序试（书配置 `model` 在前，再 `accept_models`），第一个命中的返回；空串跳过。"""
        idx = self._load()
        ck = cands_key(cands)
        for m in models:
            if m:
                p = idx.get((img_sha, prompt_sha, ck, m))
                if p is not None:
                    return p
        return None

    def lookup_legacy(self, img_sha: str) -> dict | None:
        self._load()
        return self._legacy.get(img_sha)

    def legacy_sources(self) -> set[str]:
        """rekey 转过的原 vis1 事件 id（rekey 脚本靠它跳过已转的）。"""
        self._load()
        return set(self._sources)

    def cache_pin(self) -> str:
        self._load()
        if not self._pin:
            return ""
        return hashlib.sha256("\n".join(sorted(self._pin)).encode("utf-8")).hexdigest()[:16]

    def put(self, *, img_sha: str, img_shape, patch: str, prompt: str, prompt_sha: str, cands, char, conf: str, why: str,
            model: str, tok: dict | None = None, cell: str | None = None, legacy: bool = False,
            source_event: str | None = None, batch: str | None = None) -> dict:
        """写一条答案（`char` 是「其他」时 char 留空、other=True）。返回 payload。"""
        from ..groups.vis_img import OTHER, sort_cands
        other = char == OTHER
        payload = {"source": SOURCE, "img_sha": img_sha, "img_shape": [int(x) for x in img_shape][:2], "patch": patch,
                   "prompt": prompt, "prompt_sha": prompt_sha, "cands": sort_cands(cands),
                   "char": None if other else char, "other": other, "conf": conf, "why": (why or "")[:60],
                   "model": model, "tok": tok or {}, "cell": cell, "legacy": bool(legacy)}
        if source_event:
            payload["source_event"] = source_event
        self._load()
        if legacy:
            self._legacy[img_sha] = payload
            if source_event:
                self._sources.add(source_event)
        else:
            self._idx[(img_sha, prompt_sha, cands_key(cands), model or "")] = payload
        if self.persist:
            b = batch or f"glyph-vis-{time.strftime('%Y%m%d', time.gmtime())}"
            seq = max((e.seq for e in self.log.read(b, raw=True)), default=0) + 1
            ev = make_event(b, seq, KIND, EventTarget(step="glyph_vis", unit=TARGET_UNIT, key=img_sha), payload, actor="model")
            self.log.append([ev])
            self._pin.append(f"{ev.id}|{ev.ts}")
        return payload


def answer_of(p: dict) -> str | None:
    """payload → 答案字（「其他」给 `OTHER`）。"""
    from ..groups.vis_img import OTHER
    return OTHER if p.get("other") else p.get("char")


_STORES: dict[str, tuple[tuple, VisGlyphStore]] = {}


def open_store(root: str | Path | None = None) -> VisGlyphStore:
    """按目录内文件（名、大小、mtime）记住解析结果；文件变了重读。管线每页调一次。"""
    st = VisGlyphStore(root)
    d = st.dir
    paths = [st.log.batch_path(b) for b in st.log.batches()]
    sig = tuple(sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in paths))
    k = str(d)
    hit = _STORES.get(k)
    if hit is not None and hit[0] == sig:
        return hit[1]
    _STORES[k] = (sig, st)
    return st
