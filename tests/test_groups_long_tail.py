# -*- coding: utf-8 -*-
"""未覆盖形近字长尾（2026-10-21）：子于 zy、山由出 sy 走整字岭回归。一对多（三类以上）判法用自造字块；真模板库只验格式与登记，不读真书。"""
from __future__ import annotations

import numpy as np

from open_guji_cv.groups import ids_online as O
from open_guji_cv.groups import ids_whole as W
from open_guji_cv.groups.registry import GROUPS

SPEC3 = O.IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.3, min_class=4, whole="hog", lam=1.0, size=32)


def _glyph(kind: str, k: int = 0) -> np.ndarray:
    """三种造字：同一个方框外形（归一取外框后不丢差别），框里分别是竖、横、斜；k 微移位置当抖动。"""
    g = np.full((90, 80), 255, np.uint8)
    g[10 + k:80 + k, 15:65] = 0
    g[16 + k:74 + k, 21:59] = 255
    if kind == "v":
        g[16 + k:74 + k, 36:44] = 0
    elif kind == "h":
        g[40 + k:50 + k, 21:59] = 0
    else:
        for i in range(36):
            g[20 + i + k:26 + i + k, 24 + i:30 + i] = 0
    return g


def _bank3(n=8):
    cells = [(f, _glyph(kind, k % 3 - 1), f"vol{k % 4 + 1:02d}", f"{f}{k}")
             for f, kind in (("山", "v"), ("由", "h"), ("出", "d")) for k in range(n)]
    d = W.build("sy", cells, 32)
    return d, {k: [O._dec(s, 32) for s in v] for k, v in d["templates"].items()}


def test_multiclass_ridge_picks_class_and_margin_is_gap():
    d, bank = _bank3()
    for f, kind in (("山", "v"), ("由", "h"), ("出", "d")):
        ch, m, sc = W.score(_glyph(kind), bank, "hog", (0, 1, 0, 1), 1.0, 32)
        assert ch == f and m > 0.3 and set(sc) == {"出", "山", "由"}
        assert np.isclose(m, sorted(sc.values())[-1] - sorted(sc.values())[-2])


def test_multiclass_judge_and_leave_one_book_out():
    d, bank = _bank3()
    v = O.judge_with("sy", _glyph("h"), bank, SPEC3)
    assert v.char == "由" and v.why == "agree"
    # 组外字进库：判成它 → 弃权（abstain:slot），不硬判进组
    bank["曲"] = bank["山"]
    assert O.judge_with("sy", _glyph("v"), {**bank, "山": bank["由"]}, SPEC3).char is None
    saved = O.SPECS.get("sy")
    O.SPECS["sy"] = SPEC3
    try:
        r = W.evaluate("sy", d, margins=(0.0,))
    finally:
        O.SPECS["sy"] = saved
    assert r["cells"] == 24 and r["by_margin"][0.0]["wrong"] == 0


def test_two_class_path_unchanged_shape():
    """两类仍是单个权重向量：返回的 `{字: 判别值}` 两项互为相反数。"""
    cells = [(f, _glyph(kind, k % 3 - 1), f"vol{k % 4 + 1:02d}", f"{f}{k}") for f, kind in (("子", "v"), ("于", "h")) for k in range(8)]
    d = W.build("zy", cells, 32)
    bank = {k: [O._dec(s, 32) for s in v] for k, v in d["templates"].items()}
    ch, m, sc = W.score(_glyph("h"), bank, "hog", (0, 1, 0, 1), 1.0, 32)
    assert ch == "于" and np.isclose(sc["子"], -sc["于"])


def test_long_tail_groups_registered_and_banks_match():
    for g, members, extra in (("zy", "子于", "干"), ("sy", "山由出", "曲")):
        spec = GROUPS[g]
        # zy 另有陪衬 亍（形近护栏 N 类，A24 10-26：分差内的 亍 挡住于千子；不进模板库）
        assert spec.kind == "near_form" and spec.flow.tolerate - frozenset("亍") == frozenset(extra)
        if g == "sy":
            assert spec.members == frozenset(members) and spec.flow.solvers == ("ids",) and not spec.flow.review
        else:   # 2026-10-24 zy 扩成 于千子干（并入 qg）：文意在前，子于整字 HOG 当第二路（`Only` 限 子于干 入口、只给 子于）
            assert spec.members == frozenset("于千子干") and spec.flow.solvers == ("ctx", "ids") and spec.flow.review
        sp = O.SPECS[g]
        assert sp.whole == "hog" and O.has_bank(g), g
        bank = O.load_bank(O.bank_path(g))
        assert set(bank) == set(members) | {extra}, g      # 组外的陪衬字进库，判成它就弃权
        assert all(len(v) >= sp.min_class for v in bank.values()), g
        assert all(t.shape == (sp.size, sp.size) for v in bank.values() for t in v), g
        assert O.bank_path(g).stat().st_size < 1_000_000, g  # 过 1MB 要改走 R2


def test_non_member_template_class_abstains_with_slot():
    d, bank = _bank3()
    bank2 = {"山": bank["山"], "由": bank["由"], "曲": bank["出"]}    # 「出」的图在库里叫曲（组外字）
    v = O.judge_with("sy", _glyph("d"), bank2, SPEC3)
    assert v.char is None and v.why == "abstain:slot"


def test_second_batch_registered_and_banks_load():
    """宋朱未 sz、各名 gm、心必 xb（2026-10-22）：整字字形判；模板库格式对、类别齐、小于 1MB。"""
    from pathlib import Path
    import json
    root = Path(__file__).resolve().parent.parent
    for gid, members, extra in (("sz", "宋朱未", "末"), ("gm", "各名", ""), ("xb", "心必", "")):
        g = GROUPS[gid]
        assert set(g.members) == set(members) and g.flow.solvers == ("ids",)
        assert O.SPECS[gid].whole == "hog"
        p = root / g.config_dir / "ids_bank.json"
        assert p.stat().st_size < 1_000_000
        d = json.loads(p.read_text(encoding="utf-8"))
        assert set(members + extra) <= set(d["templates"])
    assert "wm" in GROUPS["sz"].overlaps and "sz" in GROUPS["wm"].overlaps


def test_wide_shape_pairs_registered_and_banks_load():
    """衛衞 weiw、刪删 shan、扺抵 di（2026-10-22，字形判法扩面）：取框 HOG；模板库格式对、两形都在、小于 1MB。"""
    from pathlib import Path
    import json
    root = Path(__file__).resolve().parent.parent
    for gid, members in (("weiw", "衛衞"), ("shan", "刪删"), ("di", "扺抵")):
        g = GROUPS[gid]
        assert set(g.members) == set(members) and g.flow.solvers == ("ids",)
        sp = O.SPECS[gid]
        assert sp.whole == "hog" and sp.region[3] == 1.0 and sp.region != (0.0, 1.0, 0.0, 1.0)
        p = root / g.config_dir / "ids_bank.json"
        assert p.stat().st_size < 1_000_000
        d = json.loads(p.read_text(encoding="utf-8"))
        assert set(members) <= set(d["templates"]) and d["size"] == sp.size


def test_qin_is_flow_only_and_bank_loads():
    """禽會俞命舍 qin（2026-10-22）：只进字组流程表，不进 `GROUPS`（常用字，进了会改 glyph_match／rare_ref_coord 的全局行为）；与 zh 共用「會」。"""
    from pathlib import Path
    import json
    from open_guji_cv.groups.registry import FLOW_GROUPS, SHAPE_GROUPS
    assert "qin" in SHAPE_GROUPS and "qin" in FLOW_GROUPS and "qin" not in GROUPS
    assert set(FLOW_GROUPS["qin"].members) == set("禽會俞命舍")
    assert "zh" in FLOW_GROUPS["qin"].overlaps and "qin" in GROUPS["zh"].overlaps
    sp = O.SPECS["qin"]
    root = Path(__file__).resolve().parent.parent
    p = root / FLOW_GROUPS["qin"].config_dir / "ids_bank.json"
    assert p.stat().st_size < 1_000_000
    d = json.loads(p.read_text(encoding="utf-8"))
    assert set("禽會俞命舍曾合愈") <= set(d["templates"]) and d["size"] == sp.size
    assert O.has_bank("qin")


def test_shape_pairs_flow_only_and_banks_load():
    """尙尚 shang、蓋葢 gai、䟦跋 ba、凖準 zhun、宻密 mi、撰𢰅 zhuan（2026-10-24，异体按刻形拆判）：只进字组流程表；复核时按刻形改码位；模板库两形都在、小于 1MB；
    库里的模板拿回去判，判回自己的字（库与判法参数对得上）。"""
    from pathlib import Path
    import json
    import numpy as np
    from open_guji_cv.groups.registry import FLOW_GROUPS, SHAPE_GROUPS
    root = Path(__file__).resolve().parent.parent
    for gid, members in (("shang", "尙尚"), ("gai", "蓋葢"), ("ba", "䟦跋"), ("zhun", "凖準"), ("mi", "宻密"), ("zhuan", "撰𢰅")):
        assert gid in SHAPE_GROUPS and gid not in GROUPS
        g = FLOW_GROUPS[gid]
        assert set(g.members) == set(members) and g.flow.solvers == ("ids",)
        assert g.flow.review and g.flow.review_fix
        sp = O.SPECS[gid]
        p = root / g.config_dir / "ids_bank.json"
        assert p.stat().st_size < 1_000_000
        d = json.loads(p.read_text(encoding="utf-8"))
        assert set(members) <= set(d["templates"]) and d["size"] == sp.size   # 陪衬也进库（shang：同會何問…）
        bank = O.load_bank(p)
        for ch in members:
            t = (np.asarray(bank[ch][0]) * 255).astype(np.uint8)
            v = O._judge_whole(255 - t, bank, sp, g.members)
            assert v.char == ch, (gid, ch, v.why)


def test_give_restricts_which_members_get_a_char():
    """`IdsSpec.give`（2026-10-24，广宀族）：判成成员但不在 give 里 → 弃权 abstain:not_given；在 give 里照常给字。"""
    from dataclasses import replace
    d, bank = _bank3()
    sp = replace(SPEC3, give="由")
    assert O._judge_whole(_glyph("h"), bank, sp, frozenset("山由出")).char == "由"
    v = O._judge_whole(_glyph("v"), bank, sp, frozenset("山由出"))
    assert v.char is None and v.why == "abstain:not_given" and v.extra["form"] == "山"


def test_guang_flow_only_gives_only_bin_variants():
    """广宀族 guang（2026-10-24）：只进字组流程表；只给 賔賓（實廣宸 只当入口）；陪衬都在模板库里有类；补放＋复核降审（不改字）；模板库 <1MB、
    库里的模板拿回去判：賔／賓 多数判回自己，别的类一个也不给成 賔／賓。"""
    from pathlib import Path
    import json
    from open_guji_cv.groups.registry import FLOW_GROUPS, SHAPE_GROUPS
    assert "guang" in SHAPE_GROUPS and "guang" not in GROUPS
    g = FLOW_GROUPS["guang"]
    assert set(g.members) == set("廣實賔賓宸") and g.flow.solvers == ("ids",)
    assert g.flow.review and not g.flow.review_fix
    sp = O.SPECS["guang"]
    assert sp.give == "賔賓" and set(sp.give) <= set(g.members)
    p = Path(__file__).resolve().parent.parent / g.config_dir / "ids_bank.json"
    assert p.stat().st_size < 1_000_000
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["size"] == sp.size and set(g.members) | set(g.flow.tolerate) | {"〇"} == set(d["templates"])
    bank = O.load_bank(p)
    for f, ts in bank.items():
        got = [O._judge_whole(255 - (np.asarray(t) * 255).astype(np.uint8), bank, sp, g.members).char for t in ts]
        if f in "賔賓":
            assert set(got) <= {f, None} and got.count(f) >= 0.8 * len(got), (f, got.count(f), len(got))
        else:
            assert set(got) == {None}, f
