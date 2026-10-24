# -*- coding: utf-8 -*-
"""己/已/巳 词组分类器（overview#443，Z-jys）：`utils/ji_yi_si_clf` + `seed_admit.ji_yi_si_clf`。自造数据。"""
from __future__ import annotations

import importlib.util
import itertools
import json
from pathlib import Path

import open_guji_cv.steps  # noqa: F401
import open_guji_cv.utils.ji_yi_si_clf as clf
from helpers import make_book, page_align_ref, page_match, write_product
from open_guji_cv.core.step import STEPS, RunContext
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps.seed_admit import SeedAdmitParams

BOOK, PAGE, COL = "tbook", 1, 1


# ---- 规则路（纯函数）：每条规则 ≥2 正例 ≥1 反例 ----
def test_ganzhi_prev_gan():
    assert clf.classify("康熙癸", "年")[0] == "巳"
    assert clf.classify("乙", "")[0] == "巳"


def test_ganzhi_prev_ji_is_not_gan():
    # 前字是「己」（可能刚被放行成「自己」的己）：不当天干判巳
    assert clf.classify("自己", "經")[0] == "已"          # 自己＋已經
    assert clf.classify("克己", "矣")[0] == "已"
    assert clf.classify("克己", "")[0] is None            # 不得是「巳」
    assert clf.classify("康熙己", "年")[0] is None


def test_ganzhi_chen_si_jian():
    assert clf.classify("辰", "間")[0] == "巳"
    assert clf.classify("寅", "間")[0] is None            # 只认辰巳間，其他地支＋間不判
    assert clf.classify("午", "間")[0] is None
    assert clf.classify("某", "間")[0] is None


def test_ganzhi_next_zhi():
    assert clf.classify("順治", "丑")[0] == "己"
    assert clf.classify("某", "酉")[0] == "己"
    assert clf.classify("而", "未嘗")[0] is None           # 「而◎未嘗」：未 需日期语境，不当干支；「而◎」接谓语也不判（10-24 收窄）
    assert clf.classify("康熙", "未")[0] == "己"           # 年号末字 → 日期语境


def test_ji_self():
    assert clf.classify("斷以", "意")[0] == "己"
    assert clf.classify("參以", "見")[0] == "己"
    assert clf.classify("克", "復禮")[0] == "己"
    assert clf.classify("據爲", "有")[0] == "己"
    assert clf.classify("某", "見於")[0] is None            # 「已見」不是「己見」：前字不在 gate 里，不判


def test_yi_function_words():
    assert clf.classify("不過如此而", "矣")[0] == "已"
    assert clf.classify("業", "")[0] == "已"
    assert clf.classify("不", "")[0] is None
    assert clf.classify("不得", "")[0] == "已"
    assert clf.classify("某書", "經")[0] == "已"
    assert clf.classify("自", "經")[0] == "己"              # 自己 压过 已經


def test_yi_verb_time_next():
    # 已＋動詞/時間词（语料筛出，见 mine_yi_rules.py）
    assert clf.classify("某書", "久")[0] == "已"
    assert clf.classify("某書", "定")[0] == "已"
    assert clf.classify("田", "墾")[0] == "已"
    assert clf.classify("某", "畢")[0] == "已"
    assert clf.classify("某", "譏")[0] is None            # 语料里「譏」样本不足，不判
    assert clf.classify("自", "久")[0] == "己"            # 自己 压过 已久


def test_yi_ran():
    assert clf.classify("某", "然")[0] == "已"
    assert clf.classify("某", "然其")[0] == "已"
    assert clf.classify("無諸", "然後非諸人")[0] is None   # 「己|然後」：句读被吞，不判
    assert clf.classify("克", "然後")[0] == "己"           # 克己 + 然後


def test_yi_prev_time_words():
    assert clf.classify("既", "")[0] == "已"
    assert clf.classify("前", "有")[0] == "已"
    assert clf.classify("勝凡他人所", "言者")[0] == "已"   # 所已言
    assert clf.classify("五品", "上")[0] == "已"
    assert clf.classify("中書", "未召試")[0] is None       # 「書＋已」已剔除：中書己未
    assert clf.classify("前", "未")[0] is None             # 后字是地支留给干支规则
    assert clf.classify("既", "意")[0] == "己"             # 己意 优先


def test_ji_prev_narrowed():
    # 人名／书名／固定词尾后的「已」不能因前字在旧表里就判成己
    assert clf.classify("然歐陽修", "稱今但存")[0] is None       # 歐陽修已稱
    assert clf.classify("有周易說異", "著錄是編")[0] == "已"      # 說異已著錄（后字「著」→ 已＋動詞）
    assert clf.classify("現在", "有")[0] is None                   # 現在已有
    assert clf.classify("自", "性徹入")[0] == "己"                 # 自己：保留
    assert clf.classify("捨", "從人")[0] == "己"


def test_er_yi_exception_title():
    # 书名《己易》被「而已」规则误伤（vol05:36:6:15）→ 弃权
    assert clf.classify("名徒生轇轕而", "易芥八卷")[0] is None


def test_out_of_volume_fixes_1024():
    # vol11–20 册外回测（A24，2026-10-24）查出的错判，改后弃权或改判
    assert clf.classify("旬之外卜乙丁", "辛癸等柔日")[0] is None      # 天干列举：不是地支巳
    assert clf.classify("甲辰乙", "丙午")[0] == "巳"                 # 干支连写照旧（乙巳丙午）
    assert clf.classify("司馬光曰古律", "亡")[0] == "已"             # 律 不再当「律己」；已亡 照判
    assert clf.classify("非相生之律", "屬乖舛")[0] is None
    assert clf.classify("復古之學艱苦之由", "得大槩")[0] is None       # 由 不再当「由己」
    assert clf.classify("謂虞帝恭", "無爲")[0] == "己"               # 恭己
    assert clf.classify("之說謂自子至", "前六辰")[0] is None          # 至巳前：时辰，不是已前
    assert clf.classify("某", "前")[0] == "已"                       # 已前 照判
    assert clf.classify("女爲悅己者容", "下脫者字")[0] is None        # 校勘语「己下脫」
    assert clf.classify("某", "下")[0] == "已"


def test_er_yi_narrowed_1024():
    assert clf.classify("不過如此而", "")[0] == "已"
    assert clf.classify("徒好立異而", "矣")[0] == "已"
    assert clf.classify("同乎人而", "不以富爲累")[0] is None          # 而己不以…：交文意表
    assert clf.classify("爲十翼而", "又翼孔子")[0] is None
    assert clf.classify("不杖衰而", "與之無服")[0] is None
    assert clf.classify("不杖衰而", "經")[0] is None                 # 已經类规则也不接手


def test_unknown_blocks():
    assert clf.classify("□", "□")[0] is None
    assert clf.classify("而□", "□")[0] is None             # 紧邻是未知字，不越过去


def test_research_rules_parity():
    """research 里的研究版规则与管线内定型版逐上下文一致（除 research 版没加的例外已同步）。"""
    p = Path(__file__).resolve().parents[1] / "research/char_groups/jys/rules.py"
    spec = importlib.util.spec_from_file_location("jys_rules_research", p)
    rs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rs)
    chars = "癸子丑未自克以而業得不意見說經矣有爲間月康熙某久然既前所品書後定畢"
    for l, r in itertools.product(chars, repeat=2):
        for pre in ("", "不"):
            assert clf.classify(pre + l, r)[0] == rs.classify(pre + l, r)[0], (pre + l, r)


# ---- 答案表 ----
def test_ctx_key_cuts_at_unknown():
    assert clf.ctx_key("甲□乙丙", "丁□戊") == clf.ctx_key("乙丙", "丁")


# ---- seed_admit 接线 ----
def _ctx(tmp_path, monkeypatch, params):
    products, cache = tmp_path / "products", tmp_path / "cache"
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(products))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(cache))
    return RunContext(make_book(BOOK), ProductStore(products), ImageCache(cache),
                      params={"seed_admit": params}, log=lambda s: None)


def _run(ctx, left, right, ref):
    recs = [
        dict(slot=1, verdict="same", cov=1.0, wmax=0.0, char=left, candidates=[(left, 1.0)]),
        dict(slot=2, verdict="unsure", cov=0.5, wmax=0.0, candidates=[("巳", 0.5), ("已", 0.4)]),
        dict(slot=3, verdict="same", cov=1.0, wmax=0.0, char=right, candidates=[(right, 1.0)]),
    ]
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, recs=recs, col=COL))
    write_product(ctx, "align_ref", PAGE, align_ref=page_align_ref(
        PAGE, BOOK, recs=[dict(slot=1, align_char=left), dict(slot=2, align_char=ref),
                          dict(slot=3, align_char=right)], col=COL))
    sa = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"]
    return {r.slot: r for cc in sa.columns for r in cc.chars}[2]


