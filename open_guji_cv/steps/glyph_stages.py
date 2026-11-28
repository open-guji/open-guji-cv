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
    5a.3  `groups.pair_clf`：形近字对的按书分类器（本书刻例上按对训的逻辑回归，吃 5a.1 已算好的嵌入）。书配置写了
          `pair` 才跑。near_group 的格、以及 5a.1 没拦但首位字在分类器文件里有对的格（同字异形的对不在形近字组表里），
          把文件里含首位字的对逐对问一遍，证据记进 `MatchRec.stage.pair`。只有 `pair.final` 开着、有分类器的各对都给了字
          且一致、其中有按册留出验收过的对（档 3）、且没有一对归文意时才定字（`via="pair:<对>"`，字可以不是 CNN 首位）。
          归文意的对（己已巳这类刻本混用的，或刻例够了仍分不开的）只记 `tier: context`。`final` 关着时判决层结论一格不变。
    5a.4… 以后的字形方法在 `STAGES` 里往后排，接口同 5a.2：吃 (`StageInput`, 证据 dict) → 可选的定字。

## 书级配置

    params:
      glyph_match:
        sim_model: {path: models/glyph_sim_qtw/model.pt, same: 0.90, low: 0.50}   # 必须开：5a.1 用整库 CNN 嵌入
        stages:
          route: {level: core, knn_min: 1.0}     # `near_route.RouteConfig` 的字段；book 不填＝三书的表并着用
          #       table: config/near_groups.json ＝本书自己的表（相对路径先找数据目录）；registry: false＝不按注册组拦
          final: [xb, di]                        # 本书实测够准、5a.2 可以直接定字的组（缺省空）
          shape: true                            # false＝不跑 5a.2（只分流）
          pair: {model: config/groups/pair_clf.json, final: false}   # 5a.3，不写不跑；model 相对路径先找数据目录；
          #       final: true＝档 3 的对可以在 5a 直接定字（缺省 false：只出证据）
          #       unsure: true＝判决层是 unsure 的格也出证据（前两名候选的对，只出证据不改判决；缺省 false）

`final` 名单按书、按实测给（人裁刻例上不看整理本的准确率，量法见 doc/design/形近字组-5a分流与第7步对接.md 第五节），
不从注册表推。各组的模板库、分类器可以按书另建：工作区 `config/groups/ids/<组>.json` 优先于仓里的（`ids_online.bank_path`）。

## 指纹

本模块、`near_route`、`shape_stage`、`groups.methods` 都**不进** `glyph_match` 的 `code_deps`；开着的书靠参数 `stages_sha`
（`stages_fingerprint`：这几个模块的代码哈希＋形近字组表＋`final` 组的模板库指纹；写了 `pair` 再加 `pair_clf`
的代码哈希、分类器文件哈希与 `final` 开关）判过期，不开的书不受影响。
代码哈希按 `composite_key` 查 `core/code_equiv.py` 的等价登记：把判法搬出这几个模块、产物逐字节不变时，
用 `scripts/code_equiv.py composite --base <改前>` 出登记行，开 stages 的书不过期（结构拆分 A4，11-28）。
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
    pair: str | None = None           # 5a.3 分类器文件（已解析成绝对路径）；None＝不跑
    pair_final: bool = False
    pair_unsure: bool = False         # 5a.3 也给判决层是 unsure 的格出证据（只出证据，不改判决）

    @classmethod
    def from_any(cls, v) -> "StagesConfig | None":
        if v in (None, False):
            return None
        from ..clustering.near_route import RouteConfig
        d = {} if v is True else dict(v)
        unknown = set(d) - {"route", "final", "shape", "pair"}
        if unknown:
            raise ValueError(f"glyph_match.stages 不认识的键：{sorted(unknown)}")
        r = dict(d.get("route") or {})
        bad = set(r) - {f.name for f in fields(RouteConfig)}
        if bad:
            raise ValueError(f"glyph_match.stages.route 不认识的键：{sorted(bad)}")
        if r.get("table"):
            r["table"] = _resolve(str(r["table"]))
        from ..groups.registry import FLOW_GROUPS
        final = frozenset(d.get("final") or ())
        if final - set(FLOW_GROUPS):
            raise ValueError(f"glyph_match.stages.final 里有没注册的字组：{sorted(final - set(FLOW_GROUPS))}")
        pr = d.get("pair")
        pair, pair_final, pair_unsure = None, False, False
        if pr not in (None, False):
            pr = {} if pr is True else dict(pr)
            if set(pr) - {"model", "final", "unsure"}:
                raise ValueError(f"glyph_match.stages.pair 不认识的键：{sorted(set(pr) - {'model', 'final', 'unsure'})}")
            from ..groups.pair_clf import REL_PATH
            pair, pair_final, pair_unsure = (_resolve(str(pr.get("model") or REL_PATH), "glyph_match.stages.pair.model"),
                                             bool(pr.get("final", False)), bool(pr.get("unsure", False)))
            if not Path(pair).is_file():
                raise ValueError(f"glyph_match.stages.pair.model 找不到：{pair}")
        return cls(route=RouteConfig(**r), final=final, shape=bool(d.get("shape", True)), pair=pair, pair_final=pair_final, pair_unsure=pair_unsure)


def _resolve(path: str, what: str = "glyph_match.stages.route.table") -> str:
    """书自己的文件（形近字组表、5a.3 分类器）：相对路径先找数据目录（随中心库走，如 `config/near_groups.json`），再找工作区、仓根。"""
    from ..core.workspace import REPO_ROOT, data_root, workspace_root
    q = Path(path).expanduser()
    if q.is_absolute():
        return str(q)
    for base in (data_root(), workspace_root(), REPO_ROOT):
        if base is not None and (base / q).exists():
            return str(base / q)
    raise ValueError(f"{what} 找不到：{path}（数据目录、工作区、仓根都没有）")


#: 5a 各段进 `stages_sha` 的模块（次序进哈希，别动）
STAGES_CODE_MODS = ("open_guji_cv.steps.glyph_stages", "open_guji_cv.clustering.near_route", "open_guji_cv.groups.shape_stage",
                    "open_guji_cv.groups.methods", "open_guji_cv.groups.ids_online", "open_guji_cv.groups.registry")
PAIR_CODE_MODS = ("open_guji_cv.groups.pair_clf",)


def composite_key(mods) -> str:
    """几个模块合算的代码哈希在 `core/code_equiv.py::ENTRIES` 里登记等价时用的 `module` 名。"""
    return "composite:" + "+".join(mods)


def composite_hash(mods, read: Callable[[str], str]) -> str:
    """几个模块「只认代码」文本串起来的 sha256（全长、未经等价换算）；`read(模块名)` 给源码。"""
    from ..core.engine import code_only_text
    h = hashlib.sha256()
    for m in mods:
        h.update(code_only_text(read(m)).encode("utf-8"))
    return h.hexdigest()


def _read_module(m: str) -> str:
    import importlib.util
    return Path(importlib.util.find_spec(m).origin).read_text(encoding="utf-8")


def _code_sha(*mods: str) -> str:
    """几个模块合算的代码哈希（前 16 位）。按 `composite_key(mods)` 查等价登记：搬家、改写但产物逐字节不变的改动
    登记后换回旧值，开 `stages` 的书不过期（结构拆分 A4，11-28；登记行用 `scripts/code_equiv.py composite` 出）。"""
    from ..core.code_equiv import canonical
    return canonical(composite_key(mods), composite_hash(mods, _read_module))[:16]


def stages_fingerprint(v) -> str:
    """开着 `stages` 时进参数指纹的值；没开返回空串。"""
    cfg = StagesConfig.from_any(v)
    if cfg is None:
        return ""
    from ..clustering import near_route
    from ..groups import ids_online
    tab = Path(cfg.route.table) if cfg.route.table else near_route.TABLE
    t = hashlib.sha256(tab.read_bytes()).hexdigest()[:16] if tab.exists() else "none"
    code = _code_sha(*STAGES_CODE_MODS)
    bank = hashlib.sha256(ids_online.fingerprint(cfg.final).encode("utf-8")).hexdigest()[:12] if cfg.final and cfg.shape else ""
    out = f"{code}:{t}" + (f":{bank}" if bank else "")
    if cfg.pair:
        from ..groups import pair_clf
        out += f":pair={_code_sha(*PAIR_CODE_MODS)}.{pair_clf.fingerprint(cfg.pair)}.{int(cfg.pair_final)}{'.u' if cfg.pair_unsure else ''}"
    return out


@dataclass
class StageInput:
    cell_id: str
    top: str                          # 5a.1 的首位字（整库 CNN 最像的字）
    groups: tuple                     # 首位字所属的注册字组
    cands: list                       # 库候选 [(字, 分)]
    gray: Any                         # 第 4 步的灰度字块（没归一的）
    emb: Any = None                   # 5a.1 算好的相似度嵌入
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


def stage_pair(inp: StageInput, cfg: StagesConfig, flow_cfg) -> tuple[dict, str | None, str | None]:
    """5a.3：按书的形近字对分类器 → (证据, 定的字或 None, 定字的对)。没配 `pair` 或这一格没有相关的对时不出证据。"""
    if not cfg.pair or inp.emb is None:
        return {}, None, None
    from ..groups import pair_clf
    model = pair_clf.load(cfg.pair)
    rows, char, key = pair_clf.decide(model, inp.top, inp.emb, cfg.pair_final)
    return ({"pair": rows} if rows else {}), char, key


# 5a.2 起的各段，按顺序跑；前一段定了字就不往后。加新段：写一个同签名的函数排进来。
# 第三项是 `via` 的前缀；第四项说这一段要不要首位字属于注册字组才跑。
STAGES: tuple[tuple[str, Callable, str, bool], ...] = (("5a.2", stage_shape, "shape", True), ("5a.3", stage_pair, "pair", False))


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
        if cfg.pair:
            from ..groups import pair_clf
            pair_clf.check_sim_model(pair_clf.load(cfg.pair), v.cfg.path)
        self._rows = [j for j, iid in enumerate(matcher._ids) if not str(iid).startswith(FONT_PREFIX)]
        self._pos = {j: k for k, j in enumerate(self._rows)}
        # 整库嵌入用精验器已经算好（或它头一次用时也要算）的那份，不另算一遍
        E = v._lib()[self._rows] if len(self._rows) != len(matcher._ids) else v._lib()
        self._lib_chars = frozenset(matcher._chars)
        self.router = Router(E, [matcher._chars[j] for j in self._rows], cfg.route, load_calib(v.cfg.path))
        from ..groups.registry import FLOW_GROUPS
        self._flow_cfg = FlowConfig(groups=tuple(FLOW_GROUPS))

    def apply(self, verdict: str, m, norm: np.ndarray, gray, cell_id: str, exclude_id: str | None) -> StageOut:
        if verdict == "unsure" and self.cfg.pair and self.cfg.pair_unsure:
            return self._pair_unsure(m, norm, cell_id, gray)
        if verdict != "same":
            return StageOut()
        ex = [self._pos[j] for j in (self._m._same_cell_rows(exclude_id) if exclude_id is not None else ()) if j in self._pos]
        emb = self._embed(self._net, [norm])[0]
        r = self.router.decide(emb, ex)
        if r.reason == "empty":
            return StageOut()
        if r.reason is None:
            return self._pair_only(r.top, m, emb, cell_id, gray)
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
        inp = StageInput(cell_id, r.top, r.groups or (), list(m.candidates), gray, emb, tuple(r.partners or ()))
        for name, fn, via, need_groups in STAGES:
            if need_groups and not (self.cfg.shape and r.groups):
                continue
            e, char, gid = fn(inp, self.cfg, self._flow_cfg)
            ev.update(e)
            if char is not None:
                ev["final"] = name
                return StageOut("same", char, None, f"{via}:{gid}", ev)
        return StageOut("unsure", None, "never_match", None, ev, _ranked(cands))


    def _pair_unsure(self, m, norm: np.ndarray, cell_id: str, gray) -> StageOut:
        """判决层是 unsure 的格（2026-11-19，统一方案第 2 步）：库候选前两名各自在本书分类器里的对都问一遍，只出证据
        （`stage.pair`，每行带 `cand`＝是哪个候选的对），**不改判决、不改候选、不定字**。第 7 步读这份证据。
        020 册 841 个基准格里 638 格在第 5 步是 unsure，形近对的格多数本来就交第 7 步，只给 same 格出证据碰不到它们。"""
        from ..groups import pair_clf
        tops = []
        for c, _s in list(m.candidates)[:2]:
            if c not in tops:
                tops.append(c)
        model = pair_clf.load(self.cfg.pair)
        if not any(pair_clf.pairs_for(model, c) for c in tops):
            return StageOut()
        emb = self._embed(self._net, [norm])[0]
        rows, seen = [], set()
        for rank, c in enumerate(tops, 1):
            for r in pair_clf.decide(model, c, emb, False)[0]:
                if r["pair"] in seen:
                    continue
                seen.add(r["pair"])
                rows.append({**r, "cand": c, "rank": rank})
        return StageOut(stage={"pair": rows, "on": "unsure"}) if rows else StageOut()

    def _pair_only(self, top, m, emb, cell_id, gray) -> StageOut:
        """5a.1 没拦的格（照常放行的）：首位字在本书分类器里有对的，5a.3 照样问一遍。同字异形的对（淸清、眞真）
        不在形近字组表里，CNN 首位又常是库里刻例多的那一形，只有这里能按刻形改过来。只在定了字且不是首位字时改判决；
        其余只留证据。"""
        if not self.cfg.pair or top is None:
            return StageOut()
        e, char, key = stage_pair(StageInput(cell_id, top, (), list(m.candidates), gray, emb), self.cfg, self._flow_cfg)
        if not e:
            return StageOut()
        if char is None or char == top:
            return StageOut(stage=e)
        return StageOut("same", char, None, f"pair:{key}", {"top": top, **e, "final": "5a.3"})


def _ranked(cands: dict) -> list:
    """候选按分降序；同分保持插入序（对家按码位序补在后面），产物可复现。"""
    return sorted(cands.items(), key=lambda t: -t[1])
