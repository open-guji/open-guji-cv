# -*- coding: utf-8 -*-
"""第 5 步库匹配之后的分段判定：5a.1 分流 → 5a.2 形近字组字形方法 → 5a.3…（2026-11-16 Sheldon 定结构）。

`glyph_match` 的参数 `stages` 开了才走（缺省 None：不 import 本模块，产物与参数指纹逐字节不变）。只处理判决层
判成 **same** 的格（要放行的格才值得再问一遍；unsure／diff 本来就交后面的步骤）。

    5a.1  `clustering.near_route`：首位字落形近字组表或属于注册字组 → `guard="near_group"`；近邻一致度不满 → `guard="weak_knn"`。
          两种都把 same 降成 unsure，交后面的步骤（第 7 步按字组判、和整理本互证）。
    5a.2  `groups.shape_stage`：near_group 的格按首位字所属注册组的字形方法判一遍，证据记进 `MatchRec.stage`。
          **只有书级名单 `final` 里的组**、且给字的各组一致时才在这里定字（verdict 回到 same，`via="shape:<组>"`，
          字可以不是 CNN 首位字）。名单缺省空：全部只出证据、不放行。
    5a.3… 以后的字形方法在 `STAGES` 里往后排，接口同 5a.2：吃 (`StageInput`, 证据 dict) → 可选的定字。

## 书级配置

    params:
      glyph_match:
        sim_model: {path: models/glyph_sim_qtw/model.pt, same: 0.90, low: 0.50}   # 必须开：5a.1 用整库 CNN 嵌入
        stages:
          route: {level: core, knn_min: 1.0}     # `near_route.RouteConfig` 的字段；book 不填＝三书的表并着用
          final: [xb, di]                        # 本书实测够准、5a.2 可以直接定字的组（缺省空）
          shape: true                            # false＝不跑 5a.2（只分流）

`final` 名单按书、按实测给（人裁刻例上不看整理本的准确率，量法见 doc/design/形近字组-5a分流与第7步对接.md 第五节），
不从注册表推。各组的模板库、分类器可以按书另建：工作区 `config/groups/ids/<组>.json` 优先于仓里的（`ids_online.bank_path`）。

## 指纹

本模块、`near_route`、`shape_stage`、`groups.methods` 都**不进** `glyph_match` 的 `code_deps`；开着的书靠参数 `stages_sha`
（`stages_fingerprint`：这几个模块的代码哈希＋形近字组表＋`final` 组的模板库指纹）判过期，不开的书不受影响。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Callable

import numpy as np

FONT_PREFIX = "font:"


@dataclass(frozen=True)
class StagesConfig:
    route: Any = None                 # near_route.RouteConfig
    final: frozenset = frozenset()
    shape: bool = True

    @classmethod
    def from_any(cls, v) -> "StagesConfig | None":
        if v in (None, False):
            return None
        from ..clustering.near_route import RouteConfig
        d = {} if v is True else dict(v)
        unknown = set(d) - {"route", "final", "shape"}
        if unknown:
            raise ValueError(f"glyph_match.stages 不认识的键：{sorted(unknown)}")
        r = dict(d.get("route") or {})
        bad = set(r) - {f.name for f in fields(RouteConfig)}
        if bad:
            raise ValueError(f"glyph_match.stages.route 不认识的键：{sorted(bad)}")
        from ..groups.registry import FLOW_GROUPS
        final = frozenset(d.get("final") or ())
        if final - set(FLOW_GROUPS):
            raise ValueError(f"glyph_match.stages.final 里有没注册的字组：{sorted(final - set(FLOW_GROUPS))}")
        return cls(route=RouteConfig(**r), final=final, shape=bool(d.get("shape", True)))


def _code_sha(*mods: str) -> str:
    import importlib.util
    from ..core.engine import code_only_text
    h = hashlib.sha256()
    for m in mods:
        p = Path(importlib.util.find_spec(m).origin)
        h.update(code_only_text(p.read_text(encoding="utf-8")).encode("utf-8"))
    return h.hexdigest()[:16]


def stages_fingerprint(v) -> str:
    """开着 `stages` 时进参数指纹的值；没开返回空串。"""
    cfg = StagesConfig.from_any(v)
    if cfg is None:
        return ""
    from ..clustering import near_route
    from ..groups import ids_online
    tab = Path(cfg.route.table) if cfg.route.table else near_route.TABLE
    t = hashlib.sha256(tab.read_bytes()).hexdigest()[:16] if tab.exists() else "none"
    code = _code_sha("open_guji_cv.steps.glyph_stages", "open_guji_cv.clustering.near_route", "open_guji_cv.groups.shape_stage",
                     "open_guji_cv.groups.methods", "open_guji_cv.groups.ids_online", "open_guji_cv.groups.registry")
    bank = hashlib.sha256(ids_online.fingerprint(cfg.final).encode("utf-8")).hexdigest()[:12] if cfg.final and cfg.shape else ""
    return f"{code}:{t}" + (f":{bank}" if bank else "")


@dataclass
class StageInput:
    cell_id: str
    top: str                          # 5a.1 的首位字（整库 CNN 最像的字）
    groups: tuple                     # 首位字所属的注册字组
    cands: list                       # 库候选 [(字, 分)]
    gray: Any                         # 第 4 步的灰度字块（没归一的）


@dataclass(frozen=True)
class StageOut:
    """一格过完各段的结果。`verdict` 为 None＝各段都不改判决层的结论。"""
    verdict: str | None = None
    char: str | None = None
    guard: str | None = None
    via: str | None = None
    stage: dict | None = None         # 落进 `MatchRec.stage` 的证据


def stage_shape(inp: StageInput, cfg: StagesConfig, flow_cfg) -> tuple[dict, str | None, str | None]:
    """5a.2：首位字所属各组的字形方法各判一遍 → (证据, 定的字或 None, 定字的组)。
    定字条件：给了字的组全一致，且其中至少一组在书级 `final` 名单里。"""
    from ..groups import shape_stage
    rows, picked, finals = [], set(), []
    for g in inp.groups:
        v = shape_stage.judge(g, inp.cell_id, inp.cands, lambda _c: inp.gray, flow_cfg)
        if v.why == "no_method":
            continue
        rows.append({"group": g, "char": v.char, "why": v.why,
                     "solvers": [[n, c, round(float(cf), 4) if cf is not None else None, w] for n, c, cf, w in v.solvers]})
        if v.char is not None:
            picked.add(v.char)
            if g in cfg.final:
                finals.append(g)
    ev = {"shape": rows} if rows else {}
    if len(picked) == 1 and finals:
        return ev, next(iter(picked)), finals[0]
    return ev, None, None


# 5a.2 起的各段，按顺序跑；前一段定了字就不往后。加新段：写一个同签名的函数排进来。
STAGES: tuple[tuple[str, Callable], ...] = (("5a.2", stage_shape),)


class Stages:
    """绑定一个匹配器（要开着 `sim_model`）。整库嵌入只算刻本库那部分（不含字体域），按匹配器缓存。"""

    def __init__(self, matcher, cfg: StagesConfig):
        from ..clustering.near_route import Router
        from ..clustering.sim_cnn import embed, load_calib
        from ..groups.flow import FlowConfig
        v = getattr(matcher, "_verify", None)
        if not hasattr(v, "net"):
            raise ValueError("glyph_match.stages 要先开 sim_model（5a.1 用整库 CNN 嵌入）")
        self.cfg, self._m, self._net, self._embed = cfg, matcher, v.net, embed
        self._rows = [j for j, iid in enumerate(matcher._ids) if not str(iid).startswith(FONT_PREFIX)]
        self._pos = {j: k for k, j in enumerate(self._rows)}
        E = embed(v.net, [matcher._patches[j] for j in self._rows])
        self.router = Router(E, [matcher._chars[j] for j in self._rows], cfg.route, load_calib(v.cfg.path))
        from ..groups.registry import FLOW_GROUPS
        self._flow_cfg = FlowConfig(groups=tuple(FLOW_GROUPS))

    def apply(self, verdict: str, m, norm: np.ndarray, gray, cell_id: str, exclude_id: str | None) -> StageOut:
        if verdict != "same":
            return StageOut()
        ex = [self._pos[j] for j in (self._m._same_cell_rows(exclude_id) if exclude_id is not None else ()) if j in self._pos]
        r = self.router.decide(self._embed(self._net, [norm])[0], ex)
        if r.reason is None or r.reason == "empty":
            return StageOut()
        ev: dict = {"route": r.reason, "top": r.top, "knn": round(r.knn, 3)}
        if r.reason == "weak":
            return StageOut("unsure", None, "weak_knn", None, ev)
        if r.partners:
            ev["partners"] = list(r.partners)
        if r.groups:
            ev["groups"] = list(r.groups)
        if self.cfg.shape and r.groups:
            inp = StageInput(cell_id, r.top, r.groups, list(m.candidates), gray)
            for name, fn in STAGES:
                e, char, gid = fn(inp, self.cfg, self._flow_cfg)
                ev.update(e)
                if char is not None:
                    ev["final"] = name
                    return StageOut("same", char, None, f"shape:{gid}", ev)
        return StageOut("unsure", None, "near_group", None, ev)
