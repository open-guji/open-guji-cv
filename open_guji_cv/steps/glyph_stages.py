# -*- coding: utf-8 -*-
"""第 5 步库匹配之后的分段判定：5a.1 分流 → 5a.2 形近字组字形方法 → 5a.3…（2026-11-16 Sheldon 定结构）。

`glyph_match` 的参数 `stages` 开了才走（缺省 None：不 import 本模块，产物与参数指纹逐字节不变）。只处理判决层
判成 **same** 的格（要放行的格才值得再问一遍；unsure／diff 本来就交后面的步骤）。

    5a.1  `clustering.near_route`：首位字落形近字组表或属于注册字组（near_group）、近邻一致度不满（weak_knn）的格，
          same 降成 unsure，**落法并进匹配器现有的两种护栏**，后面的步骤不用改就接得住：
          - near_group → `guard="never_match"`，表里的对家（库里有的）补进候选（分 0.0，同匹配器护栏 1 的做法）。
            下游照「形近护栏格」走：纯字形单独放行的通道一律不放；整理本与库首位一致的 `match_ref` 照放；
            第 7 步 `group_flow`、`near_knn`、`nm_5b` 这些专管形近格的判法照常接手；上下文在候选（含对家）里重排。
          - weak_knn → `guard="conflict"`，前 k 名里分最高的别的字补进候选（同匹配器护栏 2：近邻里有两个字）。
          `MatchRec.stage.route` 记真实来由（`near_group`／`weak_knn`），统计时和匹配器自己判的护栏分得开。
    5a.2  `groups.shape_stage`：near_group 的格按首位字所属注册组的字形方法判一遍，证据记进 `MatchRec.stage`。
          **只有书级名单 `final` 里的组**、且给字的各组一致时才在这里定字（verdict 回到 same，`via="shape:<组>"`，
          字可以不是 CNN 首位字）。名单缺省空：全部只出证据、不放行。
    5a.3  `groups.near_knn`（2026-11-16 夜）：前一段没定字的 near_group 格，用**本书刻形近邻库**（第 7 步配着整理本用的
          同一份 `config/groups/near_knn.json`）在 {首位字, 表里对家} 里判，不给整理本；证据记进 `stage.knn3`。
          近邻给的就是首位字、距离比 < `ratio_max`、且字对在书级名单 `knn.final` 里才定字（`via="shape:near_knn"`）。
          一二（特征会去掉贴边的细短横）、戸尸户（区别只在一点）实测有真错，别进名单。没有近邻库的书这一段不跑。
    5a.4… 以后的字形方法在 `STAGES` 里往后排，接口同上：吃 (`StageInput`, 配置) → (证据, 可选的定字, 来由)。

## 书级配置

    params:
      glyph_match:
        sim_model: {path: models/glyph_sim_qtw/model.pt, same: 0.90, low: 0.50}   # 必须开：5a.1 用整库 CNN 嵌入
        stages:
          route: {level: core, knn_min: 1.0}     # `near_route.RouteConfig` 的字段；book 不填＝三书的表并着用
          final: [xb, di]                        # 本书实测够准、5a.2 可以直接定字的组（缺省空）
          shape: true                            # false＝不跑 5a.2（只分流）
          knn: {final: ["其具", "中申"], ratio_max: 0.55}   # 5a.3；不写＝不跑。final 每项是一串字，缺省空（只出证据）

`final` 名单按书、按实测给（人裁刻例上不看整理本的准确率，量法见 doc/design/形近字组-5a分流与第7步对接.md 第五节），
不从注册表推。各组的模板库、分类器可以按书另建：工作区 `config/groups/ids/<组>.json` 优先于仓里的（`ids_online.bank_path`）。

## 指纹

本模块、`near_route`、`shape_stage`、`groups.methods` 都**不进** `glyph_match` 的 `code_deps`；开着的书靠参数 `stages_sha`
（`stages_fingerprint`：这几个模块的代码哈希＋形近字组表＋`final` 组的模板库指纹；开了 `knn` 再加 `near_knn`、
`rr_shape` 的代码哈希与近邻库文件指纹）判过期，不开的书不受影响。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Callable

import numpy as np

FONT_PREFIX = "font:"


@dataclass(frozen=True)
class KnnConfig:
    """5a.3：本书刻形近邻库（`groups.near_knn`，第 7 步配着整理本用的同一份）在 {首位字, 表里对家} 里判，不给整理本。"""
    path: str = ""                    # 留空＝数据目录 config/groups/near_knn.json；找不到＝这一段不跑
    final: frozenset = frozenset()    # 书级名单：每项是一串字（如 "其具"），首位字和用到的候选全在同一项里才许定字
    ratio_max: float = 0.55           # 定字要的距离比（比库里放行用的 0.6 紧；全唐文 020：<0.6 错 1、<0.55 零错）

    def resolved(self) -> str:
        from ..core.workspace import REPO_ROOT, data_root, workspace_root
        if self.path:
            q = Path(self.path).expanduser()
            if q.is_absolute():
                return str(q)
            for base in (data_root(), workspace_root(), REPO_ROOT):
                if base is not None and (base / q).exists():
                    return str(base / q)
            return str(q)
        q = (data_root() or REPO_ROOT) / "config" / "groups" / "near_knn.json"
        return str(q) if q.exists() else ""


@dataclass(frozen=True)
class StagesConfig:
    route: Any = None                 # near_route.RouteConfig
    final: frozenset = frozenset()
    shape: bool = True
    knn: "KnnConfig | None" = None    # 5a.3 本书刻形近邻；None＝不跑

    @classmethod
    def from_any(cls, v) -> "StagesConfig | None":
        if v in (None, False):
            return None
        from ..clustering.near_route import RouteConfig
        d = {} if v is True else dict(v)
        unknown = set(d) - {"route", "final", "shape", "knn"}
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
        knn = None
        if d.get("knn"):
            k = {} if d["knn"] is True else dict(d["knn"])
            badk = set(k) - {"path", "final", "ratio_max"}
            if badk:
                raise ValueError(f"glyph_match.stages.knn 不认识的键：{sorted(badk)}")
            knn = KnnConfig(path=str(k.get("path") or ""), final=frozenset(str(s) for s in (k.get("final") or ())),
                            ratio_max=float(k.get("ratio_max", 0.55)))
        return cls(route=RouteConfig(**r), final=final, shape=bool(d.get("shape", True)), knn=knn)


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
    out = f"{code}:{t}" + (f":{bank}" if bank else "")
    if cfg.knn is not None:           # 没开 5a.3 时指纹与原来逐字相同
        from ..groups import near_knn
        out += f":nk{_code_sha('open_guji_cv.groups.near_knn', 'open_guji_cv.groups.rr_shape')}.{near_knn.fingerprint(cfg.knn.resolved()) or 'none'}"
    return out


@dataclass
class StageInput:
    cell_id: str
    top: str                          # 5a.1 的首位字（整库 CNN 最像的字）
    groups: tuple                     # 首位字所属的注册字组
    cands: list                       # 库候选 [(字, 分)]
    gray: Any                         # 第 4 步的灰度字块（没归一的）
    partners: tuple = ()              # 形近字组表里首位字的对家


@dataclass(frozen=True)
class StageOut:
    """一格过完各段的结果。`verdict` 为 None＝各段都不改判决层的结论。"""
    verdict: str | None = None
    char: str | None = None
    guard: str | None = None
    via: str | None = None
    stage: dict | None = None         # 落进 `MatchRec.stage` 的证据
    candidates: list | None = None    # 改了候选时给（对家、对手补进来）；None＝候选不动


def stage_shape(inp: StageInput, cfg: StagesConfig, flow_cfg) -> tuple[dict, str | None, str | None]:
    """5a.2：首位字所属各组的字形方法各判一遍 → (证据, 定的字或 None, 定字的来由：组名)。
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


def stage_knn(inp: StageInput, cfg: StagesConfig, flow_cfg) -> tuple[dict, str | None, str | None]:
    """5a.3：本书刻形近邻在 {首位字, 对家}（没有对家时取所属组的成员）里判 → (证据, 定的字或 None, 定字的来由)。
    定字条件：近邻给的字就是 5a 首位字（两路字形证人一致）、距离比 < `ratio_max`、首位字和用到的候选全在书级名单的同一项里。"""
    k = cfg.knn
    path = k.resolved() if k is not None else ""
    if not path:
        return {}, None, None
    from ..groups import near_knn, rr_shape
    cands = [inp.top, *inp.partners]
    if len(cands) < 2:
        from ..groups.registry import FLOW_GROUPS
        for g in inp.groups:
            cands += sorted(FLOW_GROUPS[g].members - set(cands))
    r = near_knn.judge_feat(rr_shape.features(inp.gray)[0], near_knn.load(path), cands)
    ev = {"knn3": {x: r[x] for x in ("char", "why", "votes", "ratio", "cands") if x in r}}
    used = set(r.get("cands") or ())
    if (r.get("char") == inp.top and r.get("ratio", 1.0) < k.ratio_max
            and any(used <= set(item) for item in k.final)):
        return ev, inp.top, "near_knn"
    return ev, None, None


# 5a.2 起的各段，按顺序跑；前一段定了字就不往后。加新段：写一个同签名的函数排进来。
# 每项（段名, 函数, 这一格要不要跑）；函数返回 (证据, 定的字或 None, 来由)，来由写进 `via`。
STAGES: tuple[tuple[str, Callable, Callable], ...] = (
    ("5a.2", stage_shape, lambda cfg, inp: cfg.shape and bool(inp.groups)),
    ("5a.3", stage_knn, lambda cfg, inp: cfg.knn is not None),
)


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
        # 整库嵌入用精验器已经算好（或它头一次用时也要算）的那份，不另算一遍
        E = v._lib()[self._rows] if len(self._rows) != len(matcher._ids) else v._lib()
        self._lib_chars = frozenset(matcher._chars)
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
        ev: dict = {"route": "weak_knn" if r.reason == "weak" else r.reason, "top": r.top, "knn": round(r.knn, 3)}
        cands = dict(m.candidates)
        if r.reason == "weak":
            if r.rival is not None:
                ev["rival"] = [r.rival[0], round(r.rival[1], 4)]
                # 对手只是「带进候选」，不许排到首位字前面：候选里的分可能是融合分（`sim_model.fuse`），
                # 对手的分是纯 CNN 分，两个尺度直接比会把对手顶成首位（全唐文 020 整册对比：碑→裨、遽→蘧）。
                if r.rival[0] not in cands:
                    best = max(cands.values(), default=r.rival[1])
                    cands[r.rival[0]] = round(min(r.rival[1], best - 1e-4), 4)
            return StageOut("unsure", None, "conflict", None, ev, _ranked(cands))
        if r.partners:
            ev["partners"] = list(r.partners)
            for c in sorted(set(r.partners) & self._lib_chars):
                cands.setdefault(c, 0.0)
        if r.groups:
            ev["groups"] = list(r.groups)
        inp = StageInput(cell_id, r.top, tuple(r.groups or ()), list(m.candidates), gray, tuple(r.partners or ()))
        for name, fn, wanted in STAGES:
            if not wanted(self.cfg, inp):
                continue
            e, char, why = fn(inp, self.cfg, self._flow_cfg)
            ev.update(e)
            if char is not None:
                ev["final"] = name
                return StageOut("same", char, None, f"shape:{why}", ev)
        return StageOut("unsure", None, "never_match", None, ev, _ranked(cands))


def _ranked(cands: dict) -> list:
    """候选按分降序；同分保持插入序（对家按码位序补在后面），产物可复现。"""
    return sorted(cands.items(), key=lambda t: -t[1])
