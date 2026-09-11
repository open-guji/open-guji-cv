# -*- coding: utf-8 -*-
"""C1 进库准入包壳。

守住 glyph_db_first_design §7.3 的四条原则里跟这一步有关的两条：
OCR 置信度不参与自动判断；库匹配按 cov 分档、0.99 是拐点。
"""

from __future__ import annotations

from pathlib import Path

import pytest

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core.book import load_book
from open_guji_cv.core.spec import page_key
from open_guji_cv.core.step import KINDS, STEPS
from open_guji_cv.products.store import ProductStore

REPO = Path(__file__).resolve().parent.parent


def _ws_raw():
    """原图根：优先 GUJI_WORKSPACE（数据已迁 siku-zongmu-workspace），
    没设则退回仓根——引擎自带的小样本仍在仓内。"""
    from open_guji_cv.core.workspace import raw_root
    return raw_root()
RAW = _ws_raw() / "data_full" / "zongmu"
needs_raw = pytest.mark.skipif(not RAW.exists(), reason="需要 data_full/zongmu 原图")


def test_registered():
    assert "admit_decide" in STEPS and "admit_decide" in KINDS
    assert "db" in STEPS["admit_decide"].spec.needs


@needs_raw
def test_auto_admissions_always_carry_a_channel_and_a_char():
    """自动进库的必须说清走的哪条通道、进的哪个字——不许有匿名准入。"""
    store = ProductStore()
    seen = 0
    for pg in load_book("vol01").dev_set[:6]:
        d = store.read("vol01", "admit_decide", page_key(pg), "admit_decide")
        if d is None:
            continue
        for cc in d.columns:
            for r in cc.chars:
                if not r.admit:
                    continue
                seen += 1
                assert r.channel, f"{r.id} 自动进库却没有通道名"
                assert r.char, f"{r.id} 自动进库却没有字"
                # human 是 2026-09-06 加的最高优先级通道：人裁过的位一票定案，
                # 任何自动通道都不许改写（admit_decide v1.4）
                assert r.provenance in ("match", "context", "align", "human"), \
                    f"{r.id} provenance 不合法：{r.provenance}"
    if not seen:
        pytest.skip("还没跑过 admit_decide")


@needs_raw
def test_match_solo_requires_the_cov_cutoff():
    """match_solo 通道的 cov 必须够 0.99——那是实测拐点，不是拍的。

    库匹配按 cov 分档的准确率：same 100% / ≥0.99 100% / ≥0.98 95.2% /
    ≥0.95 68.5% / <0.95 10.2%（529 条人审回放）。
    """
    store = ProductStore()
    checked = 0
    for pg in load_book("vol01").dev_set[:6]:
        a = store.read("vol01", "admit_decide", page_key(pg), "admit_decide")
        if a is None:
            continue
        for cc in a.columns:
            for r in cc.chars:
                if r.channel != "match_solo":
                    continue
                cov = r.evidence.get("cov", 0.0)
                assert cov >= 0.99, f"{r.id} 走 match_solo 但 cov 只有 {cov}"
                checked += 1
    if not checked:
        pytest.skip("没有 match_solo 记录")


@needs_raw
def test_review_items_say_why():
    """落回人审的要写明疑问——审查页靠它给人看「为什么拿不准」。"""
    store = ProductStore()
    seen = 0
    for pg in load_book("vol01").dev_set[:6]:
        d = store.read("vol01", "admit_decide", page_key(pg), "admit_decide")
        if d is None:
            continue
        for cc in d.columns:
            for r in cc.chars:
                if r.admit:
                    continue
                seen += 1
                assert r.doubts, f"{r.id} 落回人审却没说原因"
    if not seen:
        pytest.skip("这几页全自动了")


@needs_raw
def test_counts_add_up():
    store = ProductStore()
    for pg in load_book("vol01").dev_set[:4]:
        d = store.read("vol01", "admit_decide", page_key(pg), "admit_decide")
        if d is None:
            continue
        n = sum(len(cc.chars) for cc in d.columns if cc.ok)
        # 排除名单里的格既不自动也不人审（admit_decide v1.3 的 n_excluded），三者之和才是全部
        assert d.n_auto + d.n_review + d.n_excluded == n, \
            f"p{pg} 计数对不上：{d.n_auto}+{d.n_review}+{d.n_excluded} != {n}"


def test_human_shapes_only_takes_v2_ids(tmp_path):
    """人裁表只认 `v2:` 前缀——v1 的 id 是另一个命名空间，混进来会整列错位。

    实测教训（2026-09-06）：库里 1,925 条人裁有 1,021 条是 v1 的
    `book:page:col:idx`，与 v2 的 `book:page:col:slot` 长得一样但不是同一格。
    第一版不加区分地收，vol01 判据 A 当场从 100% 掉到 94.70%
    （vol01:4:1:10 判「編」而金标「三」）。
    """
    import sqlite3

    from open_guji_cv.steps.admit_decide import _human_shapes

    db = tmp_path / "g.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE admissions (instance_id TEXT PRIMARY KEY, char TEXT, provenance TEXT);
        CREATE TABLE exemplars (glyph_id INTEGER, instance_id TEXT);
        CREATE TABLE glyphs (glyph_id INTEGER PRIMARY KEY, char TEXT);
    """)
    conn.execute("INSERT INTO glyphs VALUES (1, '曾')")
    conn.execute("INSERT INTO glyphs VALUES (2, '三')")
    # v2 的：该收
    conn.execute("INSERT INTO admissions VALUES ('v2:vol01:4:1:10', '曾', 'human')")
    conn.execute("INSERT INTO exemplars VALUES (1, 'v2:vol01:4:1:10')")
    # v1 的（无前缀）：绝不能收，它的 4:1:10 指的不是同一格
    conn.execute("INSERT INTO admissions VALUES ('vol01:4:1:10', '三', 'human')")
    conn.execute("INSERT INTO exemplars VALUES (2, 'vol01:4:1:10')")
    # 非人裁的：不收
    conn.execute("INSERT INTO admissions VALUES ('v2:vol01:9:9:9', '三', 'match')")
    conn.execute("INSERT INTO exemplars VALUES (2, 'v2:vol01:9:9:9')")
    conn.commit()
    conn.close()

    got = _human_shapes(str(db))
    assert got == {"vol01:4:1:10": "曾"}, got
