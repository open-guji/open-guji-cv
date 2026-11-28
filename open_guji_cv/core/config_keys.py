"""配置键的归层登记（整改清单 X5，CV0 2026-11-28）：每个键允许写在哪几层、推荐写在哪层。

六层：全局（代码缺省、cv ``config/``）、组、书（``config/book_defaults.yaml``）、册（``books/<册>.yaml``）、
页（人裁、页型，不放开关）、运行（``--override``／``GUJI_BOOK_OVERRIDE``）。本表只管能写进 yaml 的五层里
「组、书、册、运行」四层。

**一期只警告、不拦**：真拦的规矩仍在 ``core/book_config.py``（``FORBIDDEN_IN_DEFAULTS``、``FORBIDDEN_IN_GROUP``…），
本表把它们一并登记，测试守着两边不打架（``tests/test_config_keys.py``）。警告出现在 ``guji-cv book show``。

没登记的键不报：缺省「书、册、运行都许、推荐书」。Step 参数按 ``<step>.<field>`` 登在 ``PARAM_RULES``。
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

GROUP, BOOK, VOLUME, RUN = "组", "书", "册", "运行"
LAYERS = (GROUP, BOOK, VOLUME, RUN)


@dataclass(frozen=True)
class KeyRule:
    allowed: frozenset
    recommended: frozenset
    note: str = ""


def _r(allowed: str, recommended: str, note: str = "") -> KeyRule:
    return KeyRule(frozenset(allowed.split()), frozenset(recommended.split()), note)


_PIN_NOTE = "钉子：书层写缺省、个别册另钉；组里不许"
_ID_NOTE = "书的身份"
_VOL_NOTE = "册的身份"
_MEASURED_NOTE = "实测的版式先验，换册要重标"

#: 顶层键
KEY_RULES: dict[str, KeyRule] = {
    "groups": _r("书", "书", "归哪个组是书的事"),
    # 书身份
    **{k: _r("书 册", "书", _ID_NOTE) for k in ("book_id", "book_title", "book_edition", "volume_width",
                                              "chapter_width", "seg_set", "edition")},
    # 册身份
    **{k: _r("册", "册", _VOL_NOTE) for k in ("id", "title", "raw_dir", "raw_pattern", "pages", "sets",
                                            "freeze", "gaps", "volume")},
    # 实测先验
    **{k: _r("册 运行", "册", _MEASURED_NOTE) for k in ("bottom_gap", "period_prior", "frame_height", "col_pitch",
                                                     "outer_shift", "outer_gap", "preclean", "page_split",
                                                     "dev_set", "layout_hints", "page_kinds")},
    # 钉子
    "corpus": _r("书 册 运行", "册", "语料总号每册各编；写书层靠 unresolved_pins 兜底"),
    **{k: _r("书 册 运行", "书 册", _PIN_NOTE) for k in ("glyph_pin", "model", "code", "pua_table_pin",
                                                    "cv_version", "pin")},
    "references": _r("书 册 运行", "书 册", "参校本；个别册另写可以"),
    "codepoints": _r("书 册 运行", "册 运行", "书级码位写 config/codepoints.yaml，别写进 book_defaults"),
    "src_w": _r("书 册", "书", "书影宽"),
    "cos_iou_min": _r("书 册", "书", "书影墨迹 IoU 线"),
    # 版式：同一刻本／写本一致，推荐进组
    **{k: _r("组 书 册 运行", "组 书", "版式；同一版式的书推荐进组") for k in ("expected_cols", "chars_per_line",
                                                                       "side_frame", "frame_layers")},
}

#: Step 参数（``<step>.<field>``）
_FOLLOW = "字对随书，组里不许"
PARAM_RULES: dict[str, KeyRule] = {
    **{f"char_decide.{k}": _r("书 册 运行", "书", _FOLLOW) for k in ("follow_ref", "follow_ref_seen", "pua_rules")},
    "align_ref.page_pins": _r("书 册 运行", "书", "页钉文件随书"),
    "align_ref.coord_title_formula": _r("书 册 运行", "书", "书名行公式随书"),
    "row_segment.layout_prior": _r("书 册 运行", "书 册", "版式先验文件随书"),
    "row_segment.roster_ref_corpus": _r("书 册 运行", "书", "随书"),
    "row_segment.roster_ref_pins": _r("书 册 运行", "书", "随书"),
    # 对位：同版式通用，推荐进组（史記 42 册逐册抄过）
    **{f"align_ref.{k}": _r("组 书 册 运行", "组 书", "对位开关；推荐进组")
       for k in ("alt_select", "coord_circle_ext", "coord_consensus_not_same", "coord_dp", "coord_dp_flat",
                 "coord_dp_skip_cost", "coord_legacy_line_guard", "coord_ref_hint", "coord_relaxed",
                 "coord_title_trust")},
    # 5a：CV3 11-28，不改全局缺省，写进组
    **{f"glyph_match.{k}": _r("组 书 册 运行", "组 书", "5a；CV3 定写进组")
       for k in ("knn_k", "knn_per_char", "knn_per_char_top", "consensus_cov", "consensus_margin",
                 "consensus_min_confirmed")},
}

#: 必须写在同一层的键（CV3 11-28：相似度模型与配对分类器配套）
SAME_LAYER_GROUPS: tuple[tuple[str, ...], ...] = (
    ("glyph_match.sim_model", "glyph_match.pair_clf"),
)

#: Step 旧名 → 现名（登记表只按现名登）
_STEP_ALIAS = {"seed_admit": "char_decide"}

#: 收敛提示：同一键同一值写在至少这么多比例的册里，提示收进书（或组）
CONVERGE_RATIO = 0.9


def layer_of(name: str) -> str | None:
    """``book_config.layers()`` 的层名 → 本表的层。"""
    if name.startswith("组 "):
        return GROUP
    return {"基础配置": BOOK, "册 yaml": VOLUME, "运行覆盖": RUN}.get(name)


def rule_for(key: str) -> KeyRule | None:
    return PARAM_RULES.get(key) if "." in key else KEY_RULES.get(key)


def _items(d: dict):
    """顶层键与 ``params.<step>.<field>``（后者报成 ``<step>.<field>``）。"""
    for k, v in d.items():
        if k == "params" and isinstance(v, dict):
            for step, fields in v.items():
                if isinstance(fields, dict):
                    for f in fields:
                        yield f"{_STEP_ALIAS.get(step, step)}.{f}"
        else:
            yield k


def check(named_layers: list[tuple[str, dict]]) -> list[str]:
    """逐层查写错层（不在允许层）、写在不推荐的层、配套键不同层；返回警告句子。"""
    out: list[str] = []
    seen_layer: dict[str, str] = {}
    for name, d in named_layers:
        ly = layer_of(name)
        if ly is None or not isinstance(d, dict):
            continue
        for key in _items(d):
            seen_layer[key] = ly
            r = rule_for(key)
            if r is None:
                continue
            if ly not in r.allowed:
                out.append(f"{name}：{key} 不该写在{ly}层（允许 {'、'.join(sorted(r.allowed, key=LAYERS.index))}；{r.note}）")
            elif ly not in r.recommended:
                out.append(f"{name}：{key} 推荐写在 {'、'.join(sorted(r.recommended, key=LAYERS.index))} 层（{r.note}）")
    for grp in SAME_LAYER_GROUPS:
        lys = {seen_layer[k] for k in grp if k in seen_layer}
        if len(lys) > 1:
            out.append(f"{'、'.join(grp)} 要写在同一层，现在分在 {'、'.join(sorted(lys, key=LAYERS.index))}")
    return out


def check_book(book_yaml: Path | str) -> list[str]:
    """某册各层的归层警告（含基础配置与组）。"""
    from .book_config import layers
    return check(layers(Path(book_yaml)))


def converge_hints(books_dir: Path | str, ratio: float = CONVERGE_RATIO) -> list[str]:
    """同一键同一值写在 ≥ ``ratio`` 的册 yaml 里：提示收进书（或组）。身份键与实测键不提示。"""
    import yaml
    files = sorted(Path(books_dir).glob("*.yaml"))
    if len(files) < 2:
        return []
    cnt: Counter = Counter()
    for f in files:
        d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        flat = {}
        for k, v in d.items():
            if k == "params" and isinstance(v, dict):
                for step, fields in v.items():
                    if isinstance(fields, dict):
                        for fk, fv in fields.items():
                            flat[f"{_STEP_ALIAS.get(step, step)}.{fk}"] = fv
            else:
                flat[k] = v
        for k, v in flat.items():
            r = rule_for(k)
            if r is not None and BOOK not in r.allowed:
                continue
            cnt[(k, json.dumps(v, ensure_ascii=False, sort_keys=True, default=str))] += 1
    need = max(2, int(len(files) * ratio + 0.999))
    return [f"{k} = {v if len(v) <= 60 else v[:57] + '…'} 写在 {c}/{len(files)} 册里，可收进书（或组）"
            for (k, v), c in sorted(cnt.items()) if c >= need]
