"""C1 进库准入（`seed_admit`）各遍共用的小工具、常量与字块读取 `_page_patch`（CV4 整理 PR3c 2026-11-26 从 seed_admit.py 原样搬来）。

测试换字块读取一律 `monkeypatch.setattr(seed_admit_common, "_page_patch", …)`：各模块都经 `_C._page_patch` 调它。
"""

from __future__ import annotations

from .seed_admit_params import SeedAdmitParams  # noqa: F401  注解用

import logging
from dataclasses import dataclass
import re
from contextvars import ContextVar
from functools import lru_cache
from ..utils.image_io import imread as cv_imread
from ..utils.gap import is_gap
from ..utils.ji_yi_si import FAMILY as _JYS
from .seed_admit_params import _RARE_REF_COORD_MIN_COV


_log = logging.getLogger("open_guji_cv.steps.seed_admit")


def _demote(rec, by: str) -> None:
    """W5（GUJI-49）：后处理遍把**已放行**格降回待审之前，在 `evidence.demoted_from` 记下放行时的通道与降级遍
    （`{"channel": <放行时 channel>, "by": <遍名>}`，字段格式 Mila 10-14 代定、Eliot 如有异议 10-16 中午前提）。
    只在 `rec.admit` 为真时记（没放行过的格不是「降级」，不加键）；只追加 evidence 键，不改放行结果。
    **必须在 `rec.channel` 被置空之前调用。**"""
    if rec.admit:
        rec.evidence = {**(rec.evidence or {}), "demoted_from": {"channel": rec.channel, "by": by}}


_RARE_REF_HARD = ("occluded", "excluded", "near_form", "context_blank_cell", "context_tall_cell", "form_open", "approx_exemplar")


def _hard_blocked(doubts, guard, allow_near_form: bool = False) -> bool:
    """规则 A／影子升级共用的硬护栏：这些格任何新增通道都不碰。
    `allow_near_form`：规则 A 坐标对位那支放宽 `near_form`（`rare_ref_nf`，见 `_rare_ref_nf_ok`），其余照拦。"""
    return (guard in ("never_match", "conflict", "timeout")
            or any(d.startswith("护栏:") or (d in _RARE_REF_HARD and not (allow_near_form and d == "near_form"))
                   for d in doubts))


def _rare_ref_coord_ok(ref: str, lib_top: str | None, cands: list, doubts, topk: int,
                       are_variants, group_chars: frozenset[str], cov: float = 1.0,
                       min_cov: float = _RARE_REF_COORD_MIN_COV, group_top_ok: bool = False) -> bool:
    """规则 A 坐标对位那支（`SeedAdmitParams.rare_ref_coord`）比现役对位多的护栏。纯函数。
    `group_top_ok`（`rare_ref_coord_group_top`）：库首位在字组里不拦，坐标对位字在字组里仍拦。"""
    if not ref or is_gap(ref):                  # 空格位／逐列本生僻字占位：不知道是哪个字
        return False
    if cov < min_cov:
        return False
    if ref in group_chars or (lib_top and lib_top in group_chars and not group_top_ok):
        return False                            # 字组里的字归 group_flow 判
    if any(isinstance(d, str) and d.startswith(("group_flow", "shadow_veto")) for d in doubts or ()):
        return False
    forms = [c for c, _v in cands[:max(topk, 0)]]
    return not any(f != ref and are_variants(f, ref) for f in forms)


def _rare_ref_nf_ok(ref: str, cands: list, n_lib: int, max_n: int, strong_cov: float, are_variants,
                    cp_skip: frozenset = frozenset()) -> bool:
    """规则 A 坐标对位那支放宽 `near_form` 的条件（`rare_ref_nf`）。纯函数。BMP 字、库对该字没有判力（刻例 ≤ max_n）、
    候选里没有强对手（非该字且 cov ≥ strong_cov）、cov ≥ 0.80 的候选不是该字的异体、该字不在册 codepoints 里。"""
    if not ref or ord(ref[0]) >= 0x20000 or n_lib > max_n or ref in cp_skip:
        return False                       # cp_skip：册 codepoints 登记过的字（异体对码位未定，如 竄／𥨥，金标里错放都在这类）
    for ch, cov in cands:
        if ch == ref:
            continue
        if cov >= strong_cov or (cov >= 0.80 and are_variants(ch, ref)):
            return False
    return True


def _fold_hold(rec, ch) -> bool:
    """折叠组（`fold_ref_char: false` 等）已把这格归组、字等文意（`evidence.fold_pending`）：整理本字不算数，
    规则 A（rare_ref／rare_ref_sparse）不得拿整理本字在组内定字（殿本 vol41:55:4:19「六日僧道」应为曰，A24 11-08）。"""
    fp = (rec.evidence or {}).get("fold_pending")
    if not fp or not ch:
        return False
    from ..groups.registry import FLOW_GROUPS
    g = FLOW_GROUPS.get(fp.get("group"))
    return bool(g and ch in g.members)


def _is_hanzi(ch: str) -> bool:
    if not ch or len(ch) != 1:
        return False
    o = ord(ch)
    return (0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0x20000 <= o <= 0x3347F)


def _raw_same_char(m, mmap_raw: dict | None) -> str | None:
    """库判 same 的字：有退档前记录就看它（`consensus_fallback` 会把无参照格的共识 same 退成 unsure）。"""
    r = (mmap_raw or {}).get(m.id, m)
    return r.char if r.verdict == "same" else None


def _unbound_shifted(rec, h: dict, amap: dict) -> int | None:
    """`human_unbound_shift_ok` 的判据：旧人裁像是顺移到邻格的 → 顺移量；否则 None。"""
    if h.get("status") != "unanchored" or not h.get("char"):
        return None
    here = amap.get(rec.id)
    if not here or here[0] != rec.char or h["char"] == rec.char:
        return None
    head = rec.id.rpartition(":")[0]
    sub = rec.sub or ""
    for d in (-1, 1, -2, 2):
        nb = amap.get(f"{head}:{rec.slot + d}{sub}")
        if nb and nb[0] == h["char"]:
            return d
    return None


#: `review.cards` 的类别码（`_CLS_CODES`）照抄一份——那是控制台模块，进 `code_deps` 会让卡片 UI
#: 的改动也判本步过期。`tests/test_seed_admit_lanes.py` 逐类核两边判得一样。
_LANE_CLS_CODES = {
    "ref_conflict": {"context_vs_ref", "iron_vs_ref", "signal_conflict"},
    "near_form": {"near_form", "solo_confusable"},
    "variant": {"variant_indirect", "replace_form", "channel_off", "ref_lib_variant"},
    "replace_align": {"replace_align"},
}


_LANE_R1_CLASSES = frozenset({"replace_align", "ref_conflict", "near_form"})


#: 三通道都不碰的疑问：字块本身不成立（空白、近似例）或形未定。
_LANE_HARD = frozenset({"context_blank_cell", "context_tall_cell", "form_open", "approx_exemplar", "glyph_timeout",
                        # 字组流程复核时文意明确给了别的字（或解法互相冲突）而降审的格：待审补放通道不许再放回去
                        # （vol04：象彖复核降审的格被 coord_fallback 按整理本字又放行，降审白降）
                        "group_flow_disagree", "group_flow_conflict",
                        # 宽松档（`ruling_anchor_loose`）下 fold 按裁定给的字被影子降审：不许待审通道再按整理本字放回
                        # （20 册回放 vol49:179:9:4，裁定曰、影子日、coord_fallback 放回日；CV4 11-24）
                        "fold_ruling_vetoed",
                        # 补放时文意给了与整理本不同的字、没放成的格（`flow.group_flow_pass`）：同理不许按整理本字放回
                        "group_flow_ctx_contra",
                        # 库判 diff 拦下的 ref_lib 格：整理本字正是被库否掉的那个，补放通道不按它放回
                        "ref_lib_diff",
                        # match_ref 库判 diff 拦下的格（`match_ref_diff_guard`）：同理
                        "match_ref_diff",
                        # 坐标对位与现役对位不一致拦下的 ref_lib 格（`ref_lib_coord_dissent`）：同理
                        "ref_lib_coord_dissent",
                        # 坐标对位与 match_solo 系放行字不一致拦下的格（`solo_coord_dissent`）：同理
                        "solo_coord_dissent"})


#: R1/R4 另外不碰的：context 乱码护栏拦下过格的**整列**（overview#427：列切窄、整列字块是
#: 笔画残边，证人字再齐也对不上图——vol04 p217c3 只有 2 格带这个码，同列其余 4 格看图同样是乱码）。
_LANE_GARBLE = frozenset({"ctx_garble_shape", "ctx_garble_rare"})


#: `lane_keep_ref_review` 开着时 R1/R4/R5 不碰的：护栏已拿整理本字比过、判定该人看的格。
_LANE_REF_REVIEW = frozenset({"ctx_guard_ref", "group_flow_ref_dissent", "group_flow_coord_dissent"})


def _lane_class(doubts, evidence: dict | None, char, ref_char, lib_top) -> str:
    """待审格归哪一类——`review.cards.card_class` 的镜像（见 `_LANE_CLS_CODES`）。"""
    ds = [d for d in (doubts or []) if isinstance(d, str)]
    codes = {d for d in ds if re.match(r"^[a-z][a-z0-9_]*$", d)}
    ev = evidence or {}
    if "occluded" in codes or ev.get("occluded"):
        return "occluded"
    if ev.get("ji_yi_si") or any(c and c in _JYS for c in (char, ref_char, lib_top)):
        return "ji_yi_si"
    if "form_open" in codes:
        return "form_open"
    for k in ("ref_conflict", "near_form"):
        if codes & _LANE_CLS_CODES[k]:
            return k
    if any(d.startswith("库里没有") for d in ds):
        return "lib_miss"
    for k in ("variant", "replace_align"):
        if codes & _LANE_CLS_CODES[k]:
            return k
    return "other"


def _group_img_dissent(group: dict | None, char: str, min_p: float) -> dict | None:
    """`lane_group_img_veto` 的判据，纯函数：字组流程里**图像判官**（solver 名以 `_img` 结尾，现只有人入八组的
    `rr_img`）给了字、与要放的字不同、自己那个字的概率 ≥ `min_p` → {solver, img, p}；否则 None。
    group 缺、判官弃权、没给概率、或判官同意要放的字 → None（不拦）。"""
    for s in (group or {}).get("solvers") or []:
        name, ch = str(s.get("solver") or ""), s.get("char")
        if not name.endswith("_img") or not ch or ch == char:
            continue
        pr = (s.get("probs") or {}).get(ch)
        if pr is not None and float(pr) >= min_p:
            return {"solver": name, "img": ch, "p": round(float(pr), 3)}
    return None


def _parse_pua_rules(spec: str) -> dict[str, str]:
    """`pua_rules` → {库首位字: 录入字}。纯函数；空项、多字项跳过。"""
    out: dict[str, str] = {}
    for item in (spec or "").split(","):
        item = item.strip()
        if not item:
            continue
        lib, _, to = item.partition("=")
        lib, to = lib.strip(), (to.strip() or lib.strip())
        if len(lib) == 1 and len(to) == 1:
            out[lib] = to
    return out


#: `reference_trust` 各项的书无关默认：字形路 ids 反对、字＝参校字时不降审的组（看图核对过的写本形错判与同义异体）；
#: 解法全弃权时按参校本走的组；字组补放字形路给参校字就放的组；库首位放行的 cov 下限与对手差。
REFERENCE_TRUST_COV = 0.90


REFERENCE_TRUST_GAP = 0.005


#: `reference_trust` 的库首位放行不碰的字：有专门解法（字组流程）的几族——日曰目、己已巳、入人八、一二。
def _is_han(c) -> bool:
    """整理本字是不是汉字（CJK 各区、兼容区、私用区——私用码是整理本里的造字，仍算字）。缅文、拉丁、符号等 → False：
    这类对位多半是对位错位或版面符号，不能拿来当「整理本字」放行（史記 r12，03:114:2:20 参校字 ခ、库首位 六）。"""
    if not c or len(c) != 1:
        return False
    o = ord(c)
    return (0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0x20000 <= o <= 0x3FFFF
            or 0xE000 <= o <= 0xF8FF or 0xF0000 <= o <= 0x10FFFF or 0x2E80 <= o <= 0x2FDF)


_REF_LIB_COORD_SKIP = frozenset("日曰目己已巳入人八一二")


#: `ref_lib_coord` 认的疑问（白名单，别的一律不碰）：库不确定／上下文不足、整理本护栏、字组只弃权或只有分歧、人裁绑丢（另判）。
_REF_LIB_COORD_DOUBTS = ("库 unsure", "库 same 但准入被拦", "上下文 margin 不足", "near_form", "ctx_guard_ref",
                         "context_variant_form", "group_flow_abstain", "group_flow_joint", "group_flow_ref_dissent",
                         "group_flow_coord_dissent", "human_unbound", "lane_coord_fallback", "context_page_end")


#: `ref_topk_follow`：整理本字在库前 5 名候选里、与首位 cov 差不超过这个数才按整理本放。
REFERENCE_TRUST_TOPK_GAP = 0.05


def _parse_follow_ref(spec: str) -> dict[str, str]:
    """`follow_ref` → {整理本形: 库里另一形}。纯函数；空项、不是「单字=单字」的项跳过。"""
    out: dict[str, str] = {}
    for item in (spec or "").split(","):
        a, _, b = item.strip().partition("=")
        a, b = a.strip(), b.strip()
        if len(a) == 1 and len(b) == 1 and a != b:
            out[a] = b
    return out


#: `follow_ref_seen` 仍然不碰的硬疑问：遮挡／排除、乱码、字组解法或文意明确给了别的字（不是弃权）、库判 diff 的 ref_lib 格
_SEEN_HARD = frozenset({"excluded", "occluded"}) | _LANE_HARD | _LANE_GARBLE


def _parse_follow_ref_seen(spec: str) -> dict[str, frozenset]:
    """`follow_ref_seen` → {整理本形: {库里的另几形}}（同一整理本形可以对多个，如 永=氷,永=未）。"""
    out: dict[str, set] = {}
    for item in (spec or "").split(","):
        a, _, b = item.strip().partition("=")
        a, b = a.strip(), b.strip()
        if len(a) == 1 and len(b) == 1 and a != b:
            out.setdefault(a, set()).add(b)
    return {k: frozenset(v) for k, v in out.items()}


class _RivalFacts:
    """交给书级钩子 `follow_ref_hooks.rival_skip` 的关系层查询（书级代码不许 import cv 内部模块，事实由这里给）。

    `facts(a, b)` → `_PairFacts`；`facts.semantic(ch)` → 同义归并后的字（`follow_ref_variants` 的 vmap，没开时原字）。"""
    __slots__ = ("_vmap",)

    def __init__(self, vmap):
        self._vmap = vmap

    def semantic(self, ch: str) -> str:
        return self._vmap.semantic(ch) if self._vmap is not None else ch

    def __call__(self, a: str, b: str) -> "_PairFacts":
        return _pair_facts(a, b, self.semantic(a) == self.semantic(b))


@dataclass(frozen=True)
class _PairFacts:
    """一对字的关系层事实（只读）。

    - `same_semantic`：同义归并后相同（`follow_ref_variants` 的 vmap）；
    - `tier`／`sources`／`n_bridge`／`never_only`／`is_variant`：边表 `variants.variant_edge`（T1 纯异体、T2 互通·一对多、
      T3 通假·形近·简繁、None 无边；`n_bridge` 异体字典来源数）；
    - `never`：人工审定永不并组（`config/variants/never_group.json`）；
    - `edge_excluded`：本书假边表（`config/variants/edge_pair_exclude.tsv`）；
    - `groups`：两字同在的字组 `((组 id, kind), …)`，kind＝"variant"｜"near_form"（`groups.registry.FLOW_GROUPS`）。"""
    same_semantic: bool
    tier: str | None
    sources: tuple
    n_bridge: int
    never_only: bool
    is_variant: bool
    never: bool
    edge_excluded: bool
    groups: tuple


@lru_cache(maxsize=65536)
def _pair_facts(a: str, b: str, same_semantic: bool) -> _PairFacts:
    from ..variants import variant_edge
    from ..groups.registry import FLOW_GROUPS
    e = variant_edge(a, b)
    groups = tuple(sorted((gid, getattr(g, "kind", "") or "") for gid, g in FLOW_GROUPS.items()
                          if a in g.members and b in g.members))
    return _PairFacts(same_semantic=same_semantic, tier=e.tier, sources=tuple(e.sources), n_bridge=e.n_bridge,
                      never_only=e.never_only, is_variant=e.is_variant, never=frozenset((a, b)) in _never_pairs(),
                      edge_excluded=_edge_pair_excluded(a, b), groups=groups)


@lru_cache(maxsize=1)
def _never_pairs() -> frozenset:
    from ..clustering.variants import never_group_pairs
    return never_group_pairs()


def _blind_ref_behind(m, co: str, top_cov: float, gap: float) -> bool:
    """库首位 cov ≥ top_cov，参校字 co 在候选里且比首位低 ≥ gap（`lane_coord_blind_guard`）。"""
    cs = list(getattr(m, "candidates", None) or [])
    if not cs or float(cs[0][1]) < top_cov:
        return False
    sc = next((float(v) for c, v in cs if c == co), None)
    return sc is not None and float(cs[0][1]) - sc >= gap


def _coord_codepoint_norm(p: "SeedAdmitParams", m, lib: str, co: str, canon) -> str | None:
    """`lane_coord_codepoint_variant`：库首位 `lib` 与坐标对位字 `co` 在本书 codepoints 里归一到同一码位、
    首位不是 diff、归一后不同字的最强候选比首位低 `lane_coord_codepoint_gap` 以上 → 归一后的码位，否则 None。"""
    if canon is None or canon(lib) != canon(co):
        return None
    cands = list(getattr(m, "candidates", None) or []) if m is not None else []
    if not cands or cands[0][0] != lib or getattr(m, "verdict", None) == "diff":
        return None
    top = float(cands[0][1])
    rival = max((float(c) for ch, c in cands[1:] if canon(ch) != canon(lib)), default=0.0)
    if top - rival < p.lane_coord_codepoint_gap:
        return None
    return canon(lib)


def _seal_variant_norm(char: str, form: str, canon) -> tuple[str, str] | None:
    """`lane_seal_codepoint_variant`：`char`、`form` 两形本书已定归一时 → (放行字, 依据)，否则 None。

    依据 `codepoint`：本书 `codepoints:` 把两形归到同一码位，放该码位；`provisional`：两形同在一个暂归一组
    （`groups.registry.PROVISIONAL`），放组定的字。"""
    if canon is not None and canon(char) == canon(form):
        return canon(char), "codepoint"
    from ..groups.registry import PROVISIONAL
    for pv in PROVISIONAL.values():
        if char in pv.forms and form in pv.forms:
            return pv.to, "provisional"
    return None


def _seal_lib_same(m, char: str | None, min_cov: float) -> bool:
    """库首位＝默认字且覆盖度 ≥ min_cov（`occluded_variant_first` ①）。"""
    top = m.candidates[0] if m and m.candidates else None
    return bool(top and char and top[0] == char and float(top[1]) >= min_cov
                and getattr(m, "verdict", None) != "diff")


def _seal_page_shifted(out: list, mmap: dict, min_cov: float = 0.9, min_hits: int = 3) -> bool:
    """`lane_seal_shift_guard`：本页印章格的默认字是否整体错了一格。

    每列按格号排（夹注半格不算），字形库首位（覆盖度 ≥ `min_cov`）分别与本格、下一格、上一格的默认字比；
    错一格吻合的次数 ≥ `min_hits` 且多过对齐吻合 → 错位。人裁格不算（字是人定的，不是默认字）。"""
    aligned = nxt = prv = 0
    for col in out:
        rs = sorted((r for r in (col.chars or []) if (r.evidence or {}).get("occluded") and not r.sub
                     and r.channel != "human" and r.provenance != "human"), key=lambda r: max(r.slot, 0))
        for i, r in enumerate(rs):
            m = mmap.get(r.id)
            top = m.candidates[0] if m and m.candidates else None
            if not top or top[1] < min_cov:
                continue
            aligned += top[0] == r.char
            nxt += i + 1 < len(rs) and rs[i + 1].char == top[0]
            prv += i > 0 and rs[i - 1].char == top[0]
    shifted = max(nxt, prv)
    return shifted >= min_hits and shifted > aligned


#: 入人八 刻形判法不碰的格：看不到字、排除、空格／瘦高格、开放字形、近似刻例、超时
_RR_SHAPE_HARD = frozenset({"occluded", "excluded", "context_blank_cell", "context_tall_cell", "form_open",
                            "approx_exemplar", "glyph_timeout"})


_RR = frozenset("人入八")


_VIS_RULING_HARD = frozenset({"occluded", "excluded", "glyph_timeout"})


_IRREGULAR_SOURCES = frozenset({"twedu", "local:keben"})


@lru_cache(maxsize=None)
def _ref_regulars(ref: str) -> tuple[str, ...]:
    """整理本字是异体写法时它的正字（`_IRREGULAR_SOURCES` 指认的），不是异体写法 → 空。"""
    from ..variants import _graph
    return tuple(r for r, tags in _graph().regulars_of(ref) if set(tags) & _IRREGULAR_SOURCES)


def _irregular_ref_gap(machine: str, ref: str, cands) -> float | None:
    """`p_ref_irregular_gap` 判据：整理本字是异体写法时，机器字 cov 减去「整理本字及其正字」在库候选里的最高 cov。
    整理本字不是异体写法、机器字不在候选里、整理本字族一个都不在候选里、机器字与整理本字有直接异体边 → `None`。"""
    regs = _ref_regulars(ref)
    if not regs or _direct_variant_edge(machine, ref):
        return None
    sc = {c: float(v) for c, v in (cands or [])}
    fam = [sc[c] for c in (ref, *regs) if c in sc and c != machine]
    if machine not in sc or not fam or machine in regs:
        return None
    return sc[machine] - max(fam)


_WU = frozenset("嗚鳴")


_HOU = frozenset("候𠋫")


@lru_cache(maxsize=8)
def _shape_variant_pairs(path: str, fp: str = "") -> frozenset:
    """归属表里刻形且同字异形的对（`attr: shape`、`variant: true`）→ {frozenset({a, b})}。"""
    from ..groups import pair_attr
    return frozenset(frozenset(k) for k, v in pair_attr.load(path).items() if v.get("attr") == "shape" and v.get("variant"))


def _shape_first_ok(p, m, a, b, form) -> bool:
    """`lane_shape_first` 的闸：(a, b) 是表里刻形同字异形，且第 5 步 5a.3 对这一对有终判档（tier ≥3）的证据、倾向正是要放的刻形 `form`。
    库首位覆盖度分不开极近的对（奥奧：020 册 cov 0.99 仍错 2/6），只有分类器证明分得开的对才放。"""
    if not p.lane_shape_first or frozenset((a, b)) not in _shape_variant_pairs(p.lane_shape_first, p.lane_shape_first_fingerprint):
        return False
    rows = (getattr(m, "stage", None) or {}).get("pair") or []
    return any(set(r.get("pair") or "") == {a, b} and (r.get("tier") or 0) >= 3 and r.get("lean") == form for r in rows)


def _shape_first_lib(p, m, lib, ref):
    """`lane_shape_first` 的 lib_variant 放宽：(库首位, 整理本字) 过 `_shape_first_ok`、库首位覆盖度 ≥ `lane_lib_veto` → 返回覆盖度，否则 None。"""
    if not (p.lane_shape_first and p.lane_lib_veto and lib and ref and lib != ref):
        return None
    top = (m.candidates[0] if m and m.candidates else None)
    if top and top[0] == lib and float(top[1]) >= p.lane_lib_veto and _shape_first_ok(p, m, lib, ref, lib):
        return round(float(top[1]), 4)
    return None


_NEAR_CODES = frozenset({"near_form", "solo_confusable", "iron_confusable_ref"})


#: seed_admit 跑一页时（且这一页有换备选切法的列）：(册 id, AltView)；`_page_patch` 按册 id 取图时用
_ALT_SCOPE: "ContextVar[tuple[str, object] | None]" = ContextVar("seed_admit_alt_scope", default=None)


class PatchUnavailable(RuntimeError):
    """本页字块读不到也再生不出来——这一页停下，不降级（overview#407）。"""


def _page_patch(src, page: int, col: int, slot, sub):
    """读**本页**一格的字块，读不到就抛 `PatchUnavailable`。

    `src` 是 `RunContext`（管线里）就走 `ctx.image`：验页戳、缓存没有就现算；
    是册 id 字符串（离线审计脚本）就只查缓存。2026-10-05 前这四处（铁证尺度 / 铁证判定 /
    CNN 背书 / 组内检索）都是 `ImageCache().get()` 不验戳不再生、没图 `return None`——
    缓存缺了或读不出来，铁证与 CNN 两路就**悄悄关掉**，放行结果变了而状态显示正常。
    """
    import cv2

    key = f"p{page:04d}c{col:02d}s{slot}{sub or ''}"
    if not hasattr(src, "image"):
        # 按册 id 取图（组内检索、铁证尺度等）：本页换过备选切法的列要换键（`products.alt_view`）
        scope = _ALT_SCOPE.get()
        if scope is not None and scope[0] == src:
            from ..products.alt_view import alt_patch_key
            key = alt_patch_key(key, scope[1].alt_cols(page))
        elif scope is None:                 # 离线审计脚本：读产物仓里的 align_ref
            from ..products.alt_view import resolve_patch_key
            key = resolve_patch_key(src, key)
    try:
        if hasattr(src, "image"):
            return src.image("char_patch", key)
        from ..products.cache import ImageCache
        path = ImageCache().get(src, "char_patch", key)
        if path is None:
            raise FileNotFoundError(f"缓存里没有 {src}/char_patch/{key}")
        return cv_imread(str(path), cv2.IMREAD_GRAYSCALE, strict=True)
    except Exception as e:                  # noqa: BLE001 —— 换成带页号与键的错误再抛，不吞
        raise PatchUnavailable(f"p{page} 字块 {key} 读不到: {type(e).__name__}: {e}") from e


def _is_consensus_same(r) -> bool:
    return r.verdict == "same" and str(getattr(r, "via", None) or "").startswith("consensus")


def _lane_variant_rank(hook, lane: str, char: str, cur: str | None, m, topk: int, variant_pair,
                       lib: str | None) -> tuple[str, list] | None:
    """调书级钩子 `variant_rank`：把 `char` 的异体在现字（名次 0）与库前 `topk` 名（名次 1…）里各排第几告诉它。
    → (放行字, [[名次, 异体, cov|None], …])；钩子不放 → None。"""
    cands = [(c, round(float(v), 4)) for c, v in ((m.candidates or [])[:max(topk, 0)] if m else [])]
    forms = ([[0, cur, None]] if cur and variant_pair(cur, char) else []) + [
        [i, c, v] for i, (c, v) in enumerate(cands, 1) if variant_pair(c, char)]
    if not forms:
        return None
    vr = hook(lane=lane, char=char, forms=tuple(tuple(f) for f in forms), cur=cur, cands=tuple(cands), lib=lib)
    return (vr, forms) if vr else None


def _edge_pair_excluded(a: str, b: str) -> bool:
    """`a`／`b` 这一对在本书假边表 `edge_pair_exclude.tsv` 里（`replace_form_edge_exclude`）。"""
    from ..groups.edge_pairs import _exclude
    return frozenset((a, b)) in _exclude()


def _direct_variant_edge(a: str, b: str) -> bool:
    """关系层（`variants.json`）里 a、b 之间有没有**直接**异体边，方向不论。

    只收 kSpoofingVariant（形近易混）/ hydzd-borrowed（通假）的边不算——那两个
    来源永不当异体用（`variants.NEVER_SOURCES`）。"""
    from ..variants import NEVER_SOURCES, _graph
    return bool(set(_graph().sources_of(a, b)) - NEVER_SOURCES)
