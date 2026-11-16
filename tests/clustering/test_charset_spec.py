# -*- coding: utf-8 -*-
"""`charset_spec` 的契约测试。

把 2026-09-17 那轮实测踩出来的几个坑钉成断言——它们都不是「显然」的，
每一条都是先写错了、被实测推翻才改对的。
"""

from types import SimpleNamespace

from open_guji_cv.clustering.charset_spec import (
    DEFAULT_ALLOW_BY_EDITION, DEFAULT_ESCALATE_THRESHOLD,
    base_charset, build_charsets, filter_candidates, is_simplified,
)


def test_base_ranges_sizes():
    """基集规模：改区段定义要在这里显式改，不能悄悄漂。"""
    assert len(base_charset("unicode-cjk-a")) == 27584      # 基本区 + 扩A
    assert len(base_charset("unicode-ext-b")) == 42720
    assert len(base_charset("unicode-cjk-ab")) == 70304


def test_base_charset_identity_is_stable():
    """同名两次取必须是**同一个元组对象**。

    `cnn_candidates._emb_index` 按 charset 的对象身份记忆化，身份不稳
    会让 7 万字的索引每页重建（实测一次 3.5 分钟）。
    """
    assert base_charset("unicode-cjk-a") is base_charset("unicode-cjk-a")


def test_variants_do_not_spill_into_base():
    """⚠️ 异体展开不得把升级档的字抬进基集。

    第一版直接把 `variants_of` 的产物并进基集：`unicode-cjk-a` 27,584 字
    展开后变成 46,942，其中 **17,584 个是扩B**——整个升级档被抬进基集，
    阶梯完全架空。
    """
    base, esc = build_charsets("unicode-cjk-a", "unicode-ext-b", None,
                               False, True, ())
    extb = [c for c in base if "\U00020000" <= c <= "\U0002A6DF"]
    assert not extb, f"基集里混进了 {len(extb)} 个扩B 字，阶梯会被架空"
    assert len(esc) > 40000
    # 基集 = 原区段 + 非扩B 的异体，略大于 27584 但远小于 46942
    assert 27584 <= len(base) < 32000


def test_build_charsets_disjoint():
    """升级档与基集不重叠——重叠会让同一个字在 RRF 里被算两次。"""
    base, esc = build_charsets("unicode-cjk-a", "unicode-ext-b", None,
                               False, True, ())
    assert not (set(base) & set(esc))


def test_is_simplified():
    """⚠️ 简体判据用 OpenCC 的 `s2t(ch) != ch`。

    原本打算用 `kirgkangxi.tsv`（康熙收字）当「不含简体」的白名单，
    **实测是错的**：国/学/体/这/说 全在那份表里且带康熙页码。
    """
    for ch in "国学体为无这说":
        assert is_simplified(ch), f"{ch} 应判为简体"
    for ch in "這說國學體甫鳥斲之人":
        assert not is_simplified(ch), f"{ch} 不该判为简体"
    # 扩B 罕见字不能误伤
    assert not is_simplified("\U000202C9")


def test_filter_candidates_shapes_and_keep():
    """三种候选形状都要吃；`keep` 无条件放行。"""
    class Hit:                     # 模拟 font_candidates.FontHit
        def __init__(self, char): self.char = char

    cands = [{"char": "國"}, {"char": "国"}]
    assert [c["char"] for c in filter_candidates(cands, "no-simplified")] == ["國"]

    tup = [("國", 0.9), ("国", 0.8)]
    assert [c[0] for c in filter_candidates(tup, "no-simplified")] == ["國"]

    hits = [Hit("國"), Hit("国")]
    assert [h.char for h in filter_candidates(hits, "no-simplified")] == ["國"]

    # keep 里的简体照样放行：本册语料是这本书自己的证据，优先于通用判据
    kept = filter_candidates(cands, "no-simplified", keep=frozenset("国"))
    assert [c["char"] for c in kept] == ["國", "国"]

    # none 模式原样返回
    assert filter_candidates(cands, "none") == cands


def test_keben_defaults_to_no_simplified():
    """刻本默认开简体否决——刻本不可能印简体，而 s2t/异体扩展会塞进来。"""
    assert DEFAULT_ALLOW_BY_EDITION["keben"] == "no-simplified"
    assert DEFAULT_ALLOW_BY_EDITION["modern_body"] == "none"


def test_escalate_threshold_is_calibrated_value():
    """0.85 是北行 383 条裁决上标出来的甜点（top-10 96.3%）。

    换 `base` 要重标，改这个常量必须同时改 `charset_spec` 模块头那张表。
    """
    assert DEFAULT_ESCALATE_THRESHOLD == 0.85


def test_symbols_join_base_only_when_switched_on(monkeypatch):
    """特殊符号设计 S3：`font.charset.symbols: true` 才把符号表并进基集；extra 里的符号绕过 `_cjk` 过滤，
    不开的书字表逐字不变。"""
    import open_guji_cv.core.book as book_mod
    from open_guji_cv.clustering.charset_spec import spec_for_book
    from open_guji_cv.hanzi.symbols import symbols

    def fake(cfg):
        return lambda _b: SimpleNamespace(font={"charset": cfg}, edition="keben")
    monkeypatch.setattr(book_mod, "load_book", fake({"symbols": True, "extra": ["甫"]}))
    spec = spec_for_book("x")
    assert spec["extra"][0] == "甫" and set(symbols()) <= set(spec["extra"])
    monkeypatch.setattr(book_mod, "load_book", fake({"extra": ["甫"]}))
    assert spec_for_book("x")["extra"] == ["甫"]

    on, esc_on = build_charsets("unicode-cjk-a", "unicode-ext-b", None, False, True, tuple(symbols()))
    off, esc_off = build_charsets("unicode-cjk-a", "unicode-ext-b", None, False, True, ())
    assert set(on) - set(off) == set(symbols())
    assert not any(c in symbols() for c in off) and esc_on == esc_off


def test_ext_g_and_beyond_reachable_but_not_in_default_base():
    """扩G／H／J（U+30000 起）2026-11-16 起进得了字表，但缺省配置下两张字表逐字不变。

    原先 `_cjk` 上界是 U+2FFFF，这三区 13,429 字一律被滤掉：殿本人裁金标的 𰜹 𱁪 𲄳 怎么配都进不了候选池。
    放开后有三条路进字表：册配置 `extra`、升级档 `unicode-ext-all`、文件型基集 `unicode-all`。
    缺省配置（基本区＋扩A，升级档扩B）不走这三条路：异体展开撞上的 992 个扩G／H 字照旧不收，
    不然所有书的基集都要变、候选整体漂移，而 `charset_spec` 不在 Step5-b 的代码指纹里，产物不会判过期。
    """
    gold = "\U00030739\U0003106A\U00032133"          # 𰜹 𱁪 𲄳
    tip = "\U00030000"

    assert len(base_charset("unicode-ext-all")) == 74400
    assert len(base_charset("unicode-all")) == 101996   # 原先 88,567：文件里的扩G／H／J 被滤掉了

    base, esc = build_charsets("unicode-cjk-a", "unicode-ext-b", None, False, True, ())
    assert not [c for c in base + esc if c >= tip]
    assert len(esc) == 42720

    base_x, esc_x = build_charsets("unicode-cjk-a", "unicode-ext-b", None, False, True, tuple(gold))
    assert set(gold) <= set(base_x) and not [c for c in esc_x if c >= tip]
    assert set(base_x) - set(base) == set(gold)         # 这三个字没有异体边，只多它们自己

    base_a, esc_a = build_charsets("unicode-cjk-a", "unicode-ext-all", None, False, True, ())
    assert set(gold) <= set(esc_a)
    assert not [c for c in base_a if c >= tip], "扩G 以后的异体产物应归升级档，不进基集"
    assert not (set(base_a) & set(esc_a))
    assert set(esc) <= set(esc_a)
    # 区间止于已编码的末位：和 Unicode 全集里第二、三辅助平面的字逐字相同，不带没编码的码位
    assert set(base_charset("unicode-ext-all")) == {
        c for c in base_charset("unicode-all") if c >= "\U00020000"}
