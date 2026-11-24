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

**格锚点后备键**（GM4／CV4 2026-11-24，裁定键长期方案③）：窗口键（含版本等价）都没中时，用「格号＋写裁定时这一页的 `cells_sha`
（`page_cells_sha`，Step3 切分 sha＋字块 sha，同 `bindings.page_state`）＋整理本对位字 `ref`」三样全对的裁定（`get_anchor`）。
只认 payload 里自带 `cells_sha` 的裁定：新裁定由写入方当场写；存量由 manager 回填，且只回填能证明是写裁定那一刻产物的。
命中返回副本，带 `ruling_key="anchor"`、`ruling_ver`。调用方还要核「裁定字在候选或＝ref」，其余护栏照旧。

事件 payload：`source="llm"`、`group`、`char`（组内字，或 None）、`other`（大模型认为组内字都不是）、`conf`(high/mid/low)、`why`（≤60 字）、
`model`、`prompt_ver`、`ctx{left,right,hash}`、`cell`、`tok{in,out,cache_read}`、`pending_reason`（问时这格的待审原因，缺省 unknown）。弃权（低把握、其他）也记，免得反复问。
"""
from __future__ import annotations

import hashlib
import sys
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


ANCHOR_MAX_WIN_DIFF = 3   # 格锚点命中时，裁定窗口与现窗口的编辑距离上限（GM4 审 #1832）


def edit_distance(a: str, b: str) -> int:
    """Levenshtein 距离（窗口 ≤20 字，直接 DP）。"""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


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


def merge_suffix_rows(rows: list[dict]) -> dict | None:
    """只差 `#模型` 后缀的几条裁定合成一条（最保守）：字（或「其他」）、子类、ref 各条须一致，不一致 → None；
    conf 取最低，`admit_ok` 取各条的「且」（GM4 审 #1830）。其余字段取最后一条。"""
    if not rows or len({(x.get("char"), bool(x.get("other")), x.get("subclass"), x.get("ref") or "") for x in rows}) != 1:
        return None
    lo = min(rows, key=lambda x: _CONF_RANK.get(x.get("conf"), 0))
    out = {**rows[-1], "conf": lo.get("conf")}
    if any("admit_ok" in x for x in rows):
        out["admit_ok"] = all(bool(x.get("admit_ok")) for x in rows)
    return out


#: seed_admit 消费的看图判／终审裁定（group=O）：提示词版本 → 收的子类（`_vis_ruling_pass` 从这里取；ctx-m1 的子类各书可在册配置
#: `vis_ruling_ctx_subclasses` 加，所以写入校验对 ctx-m1 不查子类）
VIS_RULING_GROUP = "O"
VIS_RULING_SPECS = (("vis-o1", frozenset({"A68", "B99", "D130", "L04"})), ("src-1", frozenset({"PUA", "GB"})), ("ctx-m1", frozenset({"Z", "N"})))
#: group=O 下另外认的版本：src-2＝格→私用码记录（`put_cell_code`）
_O_OTHER_VERS = frozenset({CELL_CODE_VER})


def group_prompt_vers() -> dict[str, str]:
    """各字组 L3 提示词的版本（仓内 `config/groups/<组>/prompt.md` 的 `ver`），fold 遍与在线 L3 按它查裁定。"""
    global _GROUP_VERS
    if _GROUP_VERS is None:
        from ..groups.ctx_l3 import load_prompt
        from ..groups.flow import rules_path
        from ..groups.registry import FLOW_GROUPS
        d = {}
        for g in FLOW_GROUPS:
            try:
                p = rules_path(g).with_name("prompt.md")
            except Exception:                      # noqa: BLE001 —— 没有 config_dir 的组
                continue
            if p.exists():
                v = load_prompt(p)[0].get("ver")
                if v:
                    d[g] = v
        _GROUP_VERS = d
    return _GROUP_VERS


_GROUP_VERS: dict | None = None


def validate_payload(payload: dict, equiv: dict | None = None) -> tuple[list[str], list[str]]:
    """写裁定前的校验（GM4／CV4 2026-11-24，裁定键长期方案①）→ (错误, 提醒)。有错误就不该写：seed_admit 永远查不到它（白写）。

    认的版本（去掉 `#模型:effort` 后缀再比）：
    - group=O：`VIS_RULING_SPECS` 的三种（vis-o1、src-1、ctx-m1）与 src-2；
    - 其他字组：本组 `prompt.md` 的 `ver`（fold 遍、在线 L3 用它查）；
    - 任何组：看图 L4 缓存 `vis1:<字块哈希>`；
    - 版本等价表（`ver_equiv.yaml`）里登记给本组（或全组）的版本。
    提醒（不拦）：vis-o1／src-1 写了 `admit_ok` 却不是 seed_admit 收的子类——这条只当记录，不会放行。"""
    from ..groups.vis_llm import VER as L4_VER
    errs: list[str] = []
    warns: list[str] = []
    g, ver = payload.get("group"), payload.get("prompt_ver")
    if not g or not ver:
        return ["缺 group 或 prompt_ver"], warns
    b = base_ver(ver)
    ok = {v for v, _ in VIS_RULING_SPECS} | _O_OTHER_VERS if g == VIS_RULING_GROUP else set()
    gv = group_prompt_vers().get(g)
    if gv:
        ok.add(gv)
    for (eg, to), frs in ((equiv or {}).get("pairs") or {}).items():
        if eg in (g, "*"):
            ok.update([to, *frs])
    if b not in ok and not b.startswith(L4_VER + ":"):
        errs.append(f"组 {g} 的版本 {ver!r} seed_admit 不认（可用：{sorted(ok)}、{L4_VER}:<哈希>；"
                    f"换了提示词版本要写进 rulings/{EQUIV_FILE}）")
    elif g == VIS_RULING_GROUP and payload.get("admit_ok"):
        subs = dict(VIS_RULING_SPECS).get(b)
        if b != "ctx-m1" and subs is not None and payload.get("subclass") not in subs:
            warns.append(f"{b} 的子类 {payload.get('subclass')!r} 不在 seed_admit 收的 {sorted(subs)} 里，只当记录、不会放行")
    return errs, warns


validate = validate_payload          # 公共名（GM4 方案里叫 rulings.validate）


class RulingLog(EventLog):
    """裁定日志：同 `EventLog` 的格式与追加纪律，落 `<feedback>/rulings/`。

    `append` 先对 `ctx_ruling` 事件跑 `validate`：版本 seed_admit 不认的整批拒写（`BadRequest`），子类提醒打到 stderr。
    manager 终审、看图审、书仓脚本都直接 `RulingLog.append`，在这里挡住就都覆盖到（GM4／CV4 11-24）。
    管线自己写的（`RulingStore.put`／`put_cell_code`：在线 L3／L4 缓存，版本取自当前提示词，按构造就认）传 `validate=False`，
    免得校验口径与运行时差一点就让整页失败。"""

    def append(self, events, validate: bool = True) -> int:
        events = list(events)
        if not validate:
            return super().append(events)
        eq = load_ver_equiv(self.events_dir / EQUIV_FILE)
        bad = []
        for e in events:
            if e.kind != KIND:
                continue
            errs, warns = validate_payload(e.payload or {}, eq)
            bad += [f"{e.id}: {m}" for m in errs]
            for m in warns:
                print(f"⚠️  裁定 {e.id}: {m}", file=sys.stderr)
        if bad:
            from ..errors import BadRequest
            raise BadRequest("裁定拒写（seed_admit 查不到，写了也白写）：\n" + "\n".join(bad[:20])
                             + (f"\n……共 {len(bad)} 条" if len(bad) > 20 else ""))
        return super().append(events)

    @property
    def events_dir(self) -> Path:
        return self.root / "rulings"

    @property
    def consumed_dir(self) -> Path:
        return self.root / "rulings_consumed"


def ctx_hash(left: str, right: str) -> str:
    s = (left or "")[-WIDTH:] + "|" + (right or "")[:WIDTH]
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:24]


def page_cells_sha(book: str, page: int, store) -> str | None:
    """格锚点用的本页产物戳：`bindings.page_state` 的两份 sha（Step3 切分＋字块）用「+」连起来；切分 sha 取不到 → None。
    写裁定的一方（manager 终审、看图审、书仓脚本）写 `payload.cells_sha` 时须用同一个函数，读写口径才一致。"""
    from .bindings import page_state
    cells, patch = page_state(book, page, store)
    return f"{cells}+{patch or ''}" if cells else None


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
            anc: dict = {}
            if self.log.events_dir.exists():
                evs = [e for e in self.log.iter_all(raw=True) if e.kind == KIND]
                for e in sorted(evs, key=replay_key):             # 后到覆盖
                    p = e.payload
                    idx[(p.get("group"), (p.get("ctx") or {}).get("hash"), p.get("prompt_ver"))] = p
                    if p.get("cells_sha") and p.get("cell"):
                        k = (p.get("group"), p["cell"], p["cells_sha"])
                        rows = anc.setdefault(k, {})
                        rows.pop(p.get("prompt_ver"), None)       # 同版本后到覆盖，且排到最后
                        rows[p.get("prompt_ver")] = p
            self._idx = idx
            self._anc = anc
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
        """只差 `#模型` 后缀的裁定，按 `merge_suffix_rows` 合成一条。"""
        return merge_suffix_rows([x for x in self._by_base().get((group, h, base_ver(ver)), ()) if x.get("prompt_ver") != ver])

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

    def has_anchors(self) -> bool:
        """裁定库里有没有带 `cells_sha` 的裁定（没有就不必算本页 cells_sha）。"""
        self._load()
        return bool(self._anc)

    def get_anchor(self, group: str, prompt_ver: str, cell: str, cells_sha: str | None, ref: str | None,
                   left: str | None = None, right: str | None = None) -> dict | None:
        """格锚点后备键：格号＋写裁定时的 `cells_sha`＋整理本对位字 `ref` 全对、版本是 `prompt_ver` 或其等价版本
        （登记表与「只差模型后缀」同 `get_equiv`；多条时取先命中的版本，同一版本后到覆盖；只差后缀的各条按 `merge_suffix_rows` 合并）。
        窗口护栏（GM4 审 #1832）：大模型当时按裁定里的窗口判文意，现窗口（`left`／`right`）与它的编辑距离（前后两段相加）
        须 ≤ `ANCHOR_MAX_WIN_DIFF`，超了或裁定没记窗口都弃权；`window_diff` 记进返回的副本。
        → payload 副本（`ruling_key="anchor"`、`ruling_ver`、`window_diff`）｜None。"""
        if not cell or not cells_sha:
            return None
        self._load()
        rows = self._anc.get((group, cell, cells_sha))
        if not rows:
            return None
        ref = ref or ""
        rows = {v: p for v, p in rows.items() if (p.get("ref") or "") == ref}
        if not rows:
            return None
        eq = self.ver_equiv()
        for ver in [prompt_ver, *self.equiv_vers(group, prompt_ver)]:
            x = rows.get(ver)
            if x is None and eq["model_suffix"]:
                x = merge_suffix_rows([p for v, p in rows.items() if v != ver and base_ver(v) == base_ver(ver)])
            if x is not None:
                c = x.get("ctx") or {}
                if "left" not in c or "right" not in c:
                    return None
                d = edit_distance(c["left"][-WIDTH:], (left or "")[-WIDTH:]) + edit_distance(c["right"][:WIDTH], (right or "")[:WIDTH])
                if d > ANCHOR_MAX_WIN_DIFF:
                    return None
                return {**x, "ruling_key": "anchor", "ruling_ver": x.get("prompt_ver"), "window_diff": d}
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
            self.log.append([ev], validate=False)
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
            self.log.append([ev], validate=False)
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
