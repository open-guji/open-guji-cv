"""大模型的文意裁定（sheldon 2026-10-28）：L3 在线问过的格，答案存成裁定事件，下次直接用，不再问。

和人裁、看图结论（`vision.py`）同一个事件库、同一套格式与追加纪律，只是**来源是模型**：`kind="ctx_ruling"`、
`actor="model"`、`payload.source="llm"`，落 `<feedback>/rulings/<批次>.jsonl`（不进 `events/`——读人裁的地方几十处直接扫
`events/`，分目录是缺省安全；`events.counts_as_human` 也不认它）。同步走 `datastore.scope`（stream=rulings）。

**管线怎么用**（`groups/ctx_llm.judge`）：先 `RulingStore.get(组, 提示词版本, 前文, 后文)` 查，有就按它的结果走，
没有才调用大模型，问完 `put` 回来。人裁的字另走 `human_chars`，同一格有人裁就不会走到 L3。

**键是窗口内容，不是格号**：`(组, sha256(前文[-20:] | 后文[:20]))`，格号只记在 `payload.cell` 和 `target.key` 里给人看、
给审核页预填用。换图源重切后格号变了，同一上下文照样命中；同一上下文在别的册、别的页出现也共用一条（省钱）。
所以读口用 `raw=True`、不过换图源的页表 rev 判据——那条判据管的是“按格号取”的事件，这里不按格号取。
提示词换了版本（`prompt_ver`）才作废：同一窗口取版本相符的最新一条（`replay_key` 后到覆盖）；模型换了不作废，
要重问请换提示词版本或删事件。

**版本等价登记表**（GM4／CV4 2026-11-24，`<feedback>/rulings/ver_equiv.yaml`，随中心库同步；缺文件＝空表）：提示词换版后，旧版本写下的
裁定可登记为对新版本仍算数。只有 seed_admit 消费裁定的读口（`get_equiv`：`_vis_ruling_pass` 放行、fold 遍）用它；
`get`／`RulingCache.lookup`（在线问之前查缓存）仍按精确键——二审小组按「版本#模型:effort」分键存，通配会把不同成员的答案串起来。
格式见 `load_ver_equiv`。命中非精确键时，返回的 payload 是副本，多带 `ruling_key="ver_equiv"`、`ruling_ver`（实际命中的版本）。

事件 payload：`source="llm"`、`group`、`char`（组内字，或 None）、`other`（大模型认为组内字都不是）、`conf`(high/mid/low)、`why`（≤60 字）、
`model`、`prompt_ver`、`ctx{left,right,hash}`、`cell`、`tok{in,out,cache_read}`、`pending_reason`（问时这格的待审原因，缺省 unknown）。弃权（低把握、其他）也记，免得反复问。
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

import yaml

from .events import Event, EventLog, EventTarget, make_event, replay_key

KIND = "ctx_ruling"
SOURCE = "llm"
OTHER = "其他"
WIDTH = 20
CELL_CODE_VER = "src-2"      # 格→私用码记录（按格号取，不是窗口键）
EQUIV_FILE = "ver_equiv.yaml"
_CONF_RANK = {"high": 3, "mid": 2, "low": 1}


def base_ver(ver: str | None) -> str:
    """去掉 `#模型:effort` 后缀的提示词版本（`ctx-m1#claude-x:high` → `ctx-m1`）。"""
    return (ver or "").split("#", 1)[0]


def load_ver_equiv(path: str | Path) -> dict:
    """读版本等价表 → {"pairs": {(组|"*", 新版本): [旧版本, …]}, "model_suffix": bool}。文件不在 → 空表。

    ```yaml
    model_suffix: true          # 只差 `#模型` 后缀即等价（同一窗口各后缀的裁定须同字，conf 取最低）
    equiv:                      # 有向：查 to 没中时，用 from 写下的裁定；group 省略＝所有组
      - {group: O, from: ctx-m1-old, to: ctx-m1}
      - {from: ry-l2-2, to: rm-l2-1}
    ```
    多步登记（a→b、b→c）按传递闭包算。格式不对直接抛错，不静默当空表。"""
    p = Path(path)
    if not p.exists():
        return {"pairs": {}, "model_suffix": False}
    d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(d, dict):
        raise ValueError(f"{p}: 顶层须是映射")
    pairs: dict = {}
    for i, e in enumerate(d.get("equiv") or []):
        if not isinstance(e, dict) or not e.get("from") or not e.get("to"):
            raise ValueError(f"{p}: equiv[{i}] 须有 from、to")
        pairs.setdefault((str(e.get("group") or "*"), str(e["to"])), []).append(str(e["from"]))
    return {"pairs": pairs, "model_suffix": bool(d.get("model_suffix", False))}


class RulingLog(EventLog):
    """裁定日志：同 `EventLog` 的格式与追加纪律，落 `<feedback>/rulings/`。"""

    @property
    def events_dir(self) -> Path:
        return self.root / "rulings"

    @property
    def consumed_dir(self) -> Path:
        return self.root / "rulings_consumed"


def ctx_hash(left: str, right: str) -> str:
    s = (left or "")[-WIDTH:] + "|" + (right or "")[:WIDTH]
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:24]


def _book(cell: str | None) -> str | None:
    return cell.split(":", 1)[0] if cell and ":" in cell else None


class RulingStore:
    """读写裁定。`root` 缺省取 `default_feedback_root()`；没有 feedback 目录（没配工作区）时只在内存里记，不落盘。"""

    def __init__(self, root: str | Path | None = None, persist: bool = True):
        self.log = RulingLog(Path(root) if root else None)
        self.persist = persist
        self._idx: dict | None = None
        self._equiv: dict | None = None
        self._batch = f"llm-ctx-{time.strftime('%Y%m%d', time.gmtime())}"

    def _load(self) -> dict:
        if self._idx is None:
            idx: dict = {}
            if self.log.events_dir.exists():
                evs = [e for e in self.log.iter_all(raw=True) if e.kind == KIND]
                for e in sorted(evs, key=replay_key):             # 后到覆盖
                    p = e.payload
                    idx[(p.get("group"), (p.get("ctx") or {}).get("hash"), p.get("prompt_ver"))] = p
            self._idx = idx
        return self._idx

    def get(self, group: str, prompt_ver: str, left: str, right: str) -> dict | None:
        """→ 裁定 payload（含 char/conf/why/model/tok），没有 → None。"""
        return self._load().get((group, ctx_hash(left, right), prompt_ver))

    def ver_equiv(self) -> dict:
        """版本等价表（`<feedback>/rulings/ver_equiv.yaml`，见 `load_ver_equiv`）；只读一次。"""
        if self._equiv is None:
            self._equiv = load_ver_equiv(self.log.events_dir / EQUIV_FILE)
        return self._equiv

    def equiv_vers(self, group: str, ver: str) -> list[str]:
        """`ver` 的等价旧版本（不含自己），按登记先后、传递闭包，先本组后通配组。"""
        pairs = self.ver_equiv()["pairs"]
        out: list[str] = []
        todo = [ver]
        while todo:
            v = todo.pop(0)
            for g in (group, "*"):
                for x in pairs.get((g, v), ()):
                    if x != ver and x not in out:
                        out.append(x)
                        todo.append(x)
        return out

    def _by_base(self) -> dict:
        """(组, 窗口哈希, 去后缀版本) → [payload, …]（`model_suffix` 通配用）。"""
        if getattr(self, "_bidx", None) is None:
            b: dict = {}
            for (g, h, v), pl in self._load().items():
                b.setdefault((g, h, base_ver(v)), []).append(pl)
            self._bidx = b
        return self._bidx

    def _suffix_hit(self, group: str, ver: str, h: str) -> dict | None:
        """只差 `#模型` 后缀的裁定：各后缀须同字（或同为「其他」），不同 → 不算；conf 取最低。"""
        rows = [x for x in self._by_base().get((group, h, base_ver(ver)), ()) if x.get("prompt_ver") != ver]
        if not rows or len({(x.get("char"), bool(x.get("other"))) for x in rows}) != 1:
            return None
        lo = min(rows, key=lambda x: _CONF_RANK.get(x.get("conf"), 0))
        return {**rows[-1], "conf": lo.get("conf")}

    def get_equiv(self, group: str, prompt_ver: str, left: str, right: str) -> dict | None:
        """同 `get`，精确键没中再按版本等价表查（登记的旧版本，再「只差模型后缀」）。非精确命中 → payload 副本，
        带 `ruling_key="ver_equiv"`、`ruling_ver`（实际命中的版本）。没有等价表时与 `get` 完全相同。"""
        h = ctx_hash(left, right)
        idx = self._load()
        v = idx.get((group, h, prompt_ver))
        if v is not None:
            return v
        eq = self.ver_equiv()
        if not eq["pairs"] and not eq["model_suffix"]:
            return None
        for ver in [prompt_ver, *self.equiv_vers(group, prompt_ver)]:
            x = idx.get((group, h, ver)) if ver != prompt_ver else None
            if x is None and eq["model_suffix"]:
                x = self._suffix_hit(group, ver, h)
            if x is not None:
                return {**x, "ruling_key": "ver_equiv", "ruling_ver": x.get("prompt_ver")}
        return None

    def cell_codes(self) -> dict[str, dict]:
        """格号 → 这一格在新图源文本层里的私用码记录（`prompt_ver="src-2"`，`put_cell_code` 写的）。

        和窗口键的裁定不同，这里**按格号取**：「码表字对不对」要按码判，而格→码的对应靠离线对页文本一次算好（管线里没有文本层），
        不能再绕窗口。格号换图源重切后会变，所以每条带 `ref`（当时这格的整理本对位字），用的时候要核对 `ref` 没变才算数。
        后到覆盖（`replay_key`）。"""
        if getattr(self, "_cc", None) is None:
            cc: dict[str, dict] = {}
            if self.log.events_dir.exists():
                evs = [e for e in self.log.iter_all(raw=True) if e.kind == KIND and (e.payload or {}).get("prompt_ver") == CELL_CODE_VER]
                for e in sorted(evs, key=replay_key):
                    p = e.payload
                    if p.get("cell") and p.get("code"):
                        cc[p["cell"]] = p
            self._cc = cc
        return self._cc

    def put_cell_code(self, cell: str, code: str, *, ref: str = "", anch: int = 0, page_match: float = 0.0, src: str = "") -> dict:
        """记一格的私用码（离线对页文本算出，见 research/a24/pua_src/build_cell_codes.py）。`code` 写 `F1001`（U+F1001 去掉前缀）。"""
        payload = {"source": "src_text", "group": "O", "prompt_ver": CELL_CODE_VER, "cell": cell, "code": code, "ref": ref or "",
                   "anch": int(anch), "page_match": round(float(page_match), 3), "src": src}
        self.cell_codes()[cell] = payload
        if self.persist:
            seq = max((e.seq for e in self.log.read(self._batch + "-cellcode", raw=True)), default=0) + 1
            ev = make_event(self._batch + "-cellcode", seq, KIND, EventTarget(step="seed_admit", unit="cell", key=cell, book=_book(cell)),
                            payload, actor="model")
            self.log.append([ev])
        return payload

    def put(self, group: str, prompt_ver: str, left: str, right: str, *, char, conf, why: str, model: str,
            cell: str | None = None, tok: dict | None = None, pending_reason: str | None = None) -> dict:
        left, right = (left or "")[-WIDTH:], (right or "")[:WIDTH]
        other = char == OTHER                      # “组内字都不是”：char 留空、other=True（字形字段只收单字）
        payload = {"source": SOURCE, "group": group, "char": None if other else char, "other": other, "conf": conf, "why": (why or "")[:60],
                   "model": model, "prompt_ver": prompt_ver, "cell": cell, "tok": tok or {},
                   "ctx": {"left": left, "right": right, "hash": ctx_hash(left, right)},
                   "pending_reason": pending_reason or "unknown"}   # 问的时候这格的待审原因（doc/design/待审原因PendingReason.md），不知道记 unknown
        self._load()[(group, payload["ctx"]["hash"], prompt_ver)] = payload
        self._bidx = None
        if self.persist:
            seq = max((e.seq for e in self.log.read(self._batch, raw=True)), default=0) + 1
            key = cell or f"ctx:{payload['ctx']['hash']}"
            ev = make_event(self._batch, seq, KIND, EventTarget(step="seed_admit", unit="cell", key=key,
                                                                book=_book(cell)), payload, actor="model")
            self.log.append([ev])
        return payload


class RulingCache:
    """`groups.ctx_llm.judge` 的缓存接口（lookup／store）接到裁定库上。"""

    def __init__(self, store: RulingStore):
        self.store_ = store

    def lookup(self, group, prompt_ver, model, left, right):
        p = self.store_.get(group, prompt_ver, left, right)
        if p is None:
            return None
        return {"char": OTHER if p.get("other") else p.get("char"), "conf": p.get("conf"), "why": p.get("why"), "model": p.get("model"),
                "tok": p.get("tok") or {}}

    def store(self, group, prompt_ver, model, left, right, e: dict, cell=None) -> None:
        self.store_.put(group, prompt_ver, left, right, char=e.get("char"), conf=e.get("conf"), why=e.get("why") or "",
                        model=e.get("model") or model, cell=cell, tok=e.get("tok"), pending_reason=e.get("pending_reason"))
