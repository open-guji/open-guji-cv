# -*- coding: utf-8 -*-
"""对勘：整理本里没有的段（校勘按语、卷末题）不参与比对（2026-09-22）。

bxgb p56 卷末有一段 68 字校勘按语，整理本（文集本）不收。8-gram 锚定拿整页
170 字投票，前 5 字命中了别处，整页按那个偏移对齐，后面 160 字逐字全错，
报成 61 条差异——**图与转写都没错**，是「有按语的页 × 删了按语的整理本」
这件事本身不成立。

⚠️ 钉住那次踩过的坑：判据起初对**每一列**做「整列在不在证人里」，
结果摘掉 302 段 6,167 字**正文**（字位 18,237→12,138、刻本多 37→930）。
正文列在整理本里是连续文本，但有分页、有异体、有个别识别错，「整列原样
连续命中」正文本来就满足不了。卷末题的特征是**位置在末列**且**自成一体**，
不是「长得不像正文」。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_collation_report import witness_absent_runs  # noqa: E402


def _slots(spec):
    """spec: [(col, slot, sub, char), …] → page_slots 那样的字典表。"""
    return [{"id": f"b:1:{c}:{s}{sub}", "col": c, "slot": s, "sub": sub, "char": ch}
            for c, s, sub, ch in spec]


def test_jiazhu_absent_from_witness_is_picked_up():
    note = "案上卷乾道五年十月二十一日行三十里飯黃碧二十八里宿和尚店"
    slots = _slots([(1, i + 1, "", ch) for i, ch in enumerate("接晚過黃壁")]
                   + [(1, i + 6, "a", ch) for i, ch in enumerate(note)])
    out = witness_absent_runs(slots, "接晚過黃壁六日丁巳雨過縉雲")
    assert len(out) == 1 and out[0]["kind"] == "夾注"
    assert out[0]["n"] == len(note)


def test_jiazhu_present_in_witness_is_left_alone():
    """整理本里有的夾注照常比对——全书四段里三段是这种。"""
    note = "張說張掄宋鈞宋直溫康諝王抃"
    slots = _slots([(1, i + 1, "a", ch) for i, ch in enumerate(note)])
    assert witness_absent_runs(slots, "前文" + note + "後文") == []


def test_short_jiazhu_is_not_probed():
    """「並六十陌」这类三五字的注，碰巧命中/落空都不说明问题，不查。"""
    slots = _slots([(1, i + 1, "a", ch) for i, ch in enumerate("並六十陌")])
    assert witness_absent_runs(slots, "毫不相干的证人文本") == []


def test_colophon_in_last_column_is_picked_up():
    slots = _slots([(1, i + 1, "", ch) for i, ch in enumerate("喜可知也")]
                   + [(13, i + 1, "", ch) for i, ch in enumerate("北行日錄下完")])
    out = witness_absent_runs(slots, "喜可知也攻媿先生文集卷第一百二十")
    assert len(out) == 1 and out[0]["kind"] == "卷末题" and out[0]["col"] == 13


def test_body_columns_are_never_dropped():
    """正文列绝不能被摘掉——那次把 6,167 字正文吃掉就是这里没守住。

    证人里**没有**这一列的原样连续串（模拟分页/异体/个别识别错），
    但它是正文列（不在末列、且长），必须留下。
    """
    body = "雲縣少候仁甫即行道經放生潭山水秀發策杖縱觀"
    slots = _slots([(2, i + 1, "", ch) for i, ch in enumerate(body)]
                   + [(3, i + 1, "", ch) for i, ch in enumerate("以侯名雙頭巖白巖烏嚴皆奇偉")])
    # 证人里两列都查不到原样串
    out = witness_absent_runs(slots, "毫不相干的证人文本" * 5)
    assert all(o["kind"] != "夾注" for o in out)
    # 末列若够短会被当卷末题，但第 2 列（正文）一定不能被摘
    assert not any(o["col"] == 2 for o in out), "正文列被摘掉了"


def test_long_last_column_is_not_a_colophon():
    """末列写满 21 字是正文没写完，不是题。"""
    long_col = "秀潤鳥巖下有石室端植如門渡溪入仙都玉虛宮路"
    slots = _slots([(13, i + 1, "", ch) for i, ch in enumerate(long_col)])
    assert witness_absent_runs(slots, "毫不相干") == []


def test_variant_normalized_before_probing():
    """按异体归一层比：整理本作「北行日録」而刻本刻「北行日錄」。"""
    slots = _slots([(9, i + 1, "", ch) for i, ch in enumerate("北行日錄上")])
    # 证人用「録」，原串比对会误判成「证人里没有」
    assert witness_absent_runs(slots, "攻媿先生文集卷第一百十九北行日録上時待次") == []


def test_colophon_at_front_is_picked_up():
    """卷端题（撰人题）同卷末题：bxgb p3 第 2 列「宋樓鑰𢰅」。

    整理本（文集本）作「四明樓鑰大防」并接生平，逐字比会把 4 个格配成
    宋→州、樓→教、鑰→授、𢰅→隨 四条假「改」外加一条 16 字 missing——
    **一处体例差异报成五条**。
    """
    slots = _slots([(1, i + 1, "", ch) for i, ch in enumerate("北行日錄上")]
                   + [(2, i + 1, "", ch) for i, ch in enumerate("宋樓鑰𢰅")]
                   + [(3, i + 1, "", ch) for i, ch in enumerate("乾道五年己丑十月九日辛卯邸報仲舅侍郎")])
    out = witness_absent_runs(slots, "四明樓鑰大防北行日録上時待次溫州教授隨侍充公守括蒼"
                                     "乾道五年己丑十月九日辛卯邸報仲舅侍郎充賀正")
    assert [o["kind"] for o in out] == ["卷端题"] and out[0]["col"] == 2


def test_one_unmatched_char_does_not_drop_a_body_column():
    """整串精确匹配没有容错——p24 第 1 列正文只因整理本作「廪」而刻本刻「廩」
    （异体表没收这一对）就被误摘。判据必须容得下个别字对不上。"""
    body = "此也有滑臺本鄭之廩延"
    slots = _slots([(1, i + 1, "", ch) for i, ch in enumerate(body)]
                   + [(2, i + 1, "", ch) for i, ch in enumerate("十四日乙未晴五更車行二十五里至濬州")])
    witness = "酈生所謂守白馬之津皆此也有滑臺本鄭之廪延十四日乙未晴五更車行二十五里至濬州城外"
    assert not any(o["col"] == 1 for o in witness_absent_runs(slots, witness)), "正文列被误摘"


def test_note_quoting_the_witness_is_still_absent():
    """按语会**大段引用**原文——按「k-gram 出现过吗」算命中率接近 1，会被放过去。
    判据得看它们**连不连在一处**：引文散落各处，没有一个连续区间装得下整段。"""
    note = ("案上卷乾道五年十月二十一日行三十里飯黃碧二十八里宿和尚店去李溪猶二里"
            "此云過永康數里飯至李溪晚過黃壁")
    slots = _slots([(1, i + 1, "a", ch) for i, ch in enumerate(note)])
    witness = ("小憩而行三十里飯黃碧村醪醇釅不殊家釀二十八里宿和尚店去李溪猶二里會倅廳一兵"
               + "中间隔着很长很长的正文" * 40
               + "五日丙辰晴過永康數里飯至李溪遇承局持家書來接晚過黃壁六日丁巳雨")
    out = witness_absent_runs(slots, witness)
    assert len(out) == 1 and out[0]["kind"] == "夾注"
