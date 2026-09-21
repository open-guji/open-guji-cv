# -*- coding: utf-8 -*-
"""C1 进库准入包壳。

守住 glyph_db_first_design §7.3 的四条原则里跟这一步有关的两条：
OCR 置信度不参与自动判断；库匹配按 cov 分档、0.99 是拐点。

2026-09-20 重写：原先四条都在扫 vol01 dev_set 前六页的 `seed_admit` 产物，
碰上什么形态就断言什么，碰不上就 skip——`test_match_solo_requires_the_cov_cutoff`
因此**只在这次跑批恰好产出过 match_solo 记录时**才真的执行到，云端一次都没跑过。

这一步只读产物、不碰图像，所以现在直接把上游证据摆成要测的样子
（`helpers.page_match` / `page_decision`）再跑真的 `run_page`：想验哪条通道，
就给哪条通道的证据。0.99 这个拐点改成**两侧都验**——刚过的进、差一点的不进，
单验一侧的话判据整个删掉测试也照样绿。
"""

from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_decision, page_match, write_product
from open_guji_cv.core.step import KINDS, STEPS

BOOK, PAGE, COL = "tbook", 1, 1


def _run(tmp_path, monkeypatch, *, match_recs, decision_recs=None):
    """摆好上游证据 → 跑 C1，返回 `seed_admit` 产物。"""
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE,
                  glyph_match=page_match(PAGE, BOOK, recs=match_recs, col=COL))
    if decision_recs is not None:
        write_product(ctx, "context_decide", PAGE,
                      context_decision=page_decision(PAGE, BOOK, recs=decision_recs,
                                                     col=COL))
    return STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"]


def _all(sa):
    return [r for cc in sa.columns for r in cc.chars]


def test_registered():
    assert "seed_admit" in STEPS and "seed_admit" in KINDS
    assert "db" in STEPS["seed_admit"].spec.needs


def test_auto_admissions_always_carry_a_channel_and_a_char(tmp_path, monkeypatch):
    """自动进库的必须说清走的哪条通道、进的哪个字——不许有匿名准入。"""
    sa = _run(tmp_path, monkeypatch, match_recs=[
        # 库 top1 高过拐点、无异语义竞争 → match_solo 自动进库
        dict(slot=1, verdict="unsure", cov=0.995, wmax=0.0, candidates=[("甲", 0.995)]),
        # 灰带，进不去，留给下面那条用例
        dict(slot=2, verdict="unsure", cov=0.96, wmax=0.0, candidates=[("乙", 0.96)]),
    ], decision_recs=[dict(slot=2, char="乙", margin=0.8, source="context")])

    auto = [r for r in _all(sa) if r.admit]
    assert auto, "没有一条自动进库，这条用例就测不到它要测的东西"
    for r in auto:
        assert r.channel, f"{r.id} 自动进库却没有通道名"
        assert r.char, f"{r.id} 自动进库却没有字"
        # human 是 2026-09-06 加的最高优先级通道：人裁过的位一票定案，
        # 任何自动通道都不许改写（seed_admit v1.4）
        assert r.provenance in ("match", "context", "align", "human"), \
            f"{r.id} provenance 不合法：{r.provenance}"


def test_match_solo_requires_the_cov_cutoff(tmp_path, monkeypatch):
    """match_solo 通道的 cov 必须够 0.99——那是实测拐点，不是拍的。

    库匹配按 cov 分档的准确率：same 100% / ≥0.99 100% / ≥0.98 95.2% /
    ≥0.95 68.5% / <0.95 10.2%（529 条人审回放）。

    **两侧都验**：0.995 该进、0.985 不该进。只验一侧的话，把判据整个删掉
    测试照样绿——原先那一版正是只验了「进来的 cov 都 ≥0.99」这一侧。
    """
    from open_guji_cv.clustering.seeding import admission_decision  # noqa: F401  存在性

    sa = _run(tmp_path, monkeypatch, match_recs=[
        dict(slot=1, verdict="unsure", cov=0.995, wmax=0.0, candidates=[("甲", 0.995)]),
        dict(slot=2, verdict="unsure", cov=0.985, wmax=0.0, candidates=[("乙", 0.985)]),
    ])
    by_slot = {r.slot: r for r in _all(sa)}

    assert by_slot[1].channel == "match_solo", (
        f"cov=0.995 过了拐点却没走 match_solo：{by_slot[1].channel} / {by_slot[1].doubts}")
    assert by_slot[2].channel != "match_solo", (
        f"cov=0.985 在拐点之下，不该走 match_solo：{by_slot[2].evidence}")
    assert not by_slot[2].admit, "0.985 不该自动进库"

    for r in _all(sa):
        if r.channel == "match_solo":
            assert r.evidence.get("cov", 0.0) >= 0.99, \
                f"{r.id} 走 match_solo 但 cov 只有 {r.evidence.get('cov')}"


def test_review_items_say_why(tmp_path, monkeypatch):
    """落回人审的要写明疑问——审查页靠它给人看「为什么拿不准」。"""
    sa = _run(tmp_path, monkeypatch, match_recs=[
        dict(slot=1, verdict="unsure", cov=0.96, wmax=0.0, candidates=[("乙", 0.96)]),
        dict(slot=2, verdict="diff", cov=0.40, wmax=0.0),
    ])
    review = [r for r in _all(sa) if not r.admit]
    assert review, "没有一条落回人审，这条用例就测不到它要测的东西"
    for r in review:
        assert r.doubts, f"{r.id} 落回人审却没说原因"


def test_counts_add_up(tmp_path, monkeypatch):
    """n_auto + n_review + n_excluded 必须等于这一页的全部字位。

    三者之和对不上就说明有字位既没进库也没落审、凭空消失了——排除名单里的格
    正是这么一类（seed_admit v1.3 加 n_excluded 之前它们不计入任何一边）。
    """
    sa = _run(tmp_path, monkeypatch, match_recs=[
        dict(slot=1, verdict="unsure", cov=0.995, wmax=0.0, candidates=[("甲", 0.995)]),
        dict(slot=2, verdict="unsure", cov=0.96, wmax=0.0, candidates=[("乙", 0.96)]),
        dict(slot=3, verdict="diff", cov=0.40, wmax=0.0),
    ])
    n = sum(len(cc.chars) for cc in sa.columns if cc.ok)
    assert n == 3
    assert sa.n_auto + sa.n_review + sa.n_excluded == n, \
        f"计数对不上：{sa.n_auto}+{sa.n_review}+{sa.n_excluded} != {n}"


def test_failed_column_is_passed_through_not_dropped(tmp_path, monkeypatch):
    """上游判 `ok=False` 的列原样带着错因出来——不能静默丢列，那会让逐列
    字数对账查不出问题。"""
    from open_guji_cv.products.kinds.recog import ColumnMatch, PageMatch

    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=PageMatch(
        page=PAGE, columns=[ColumnMatch(col=7, ok=False, error="弹性 DP 无解")]))
    sa = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"]
    assert [ (c.col, c.ok, c.error) for c in sa.columns ] == [(7, False, "弹性 DP 无解")]


def test_human_shapes_only_takes_v2_ids(tmp_path):
    """人裁表只认 `v2:` 前缀——v1 的 id 是另一个命名空间，混进来会整列错位。

    实测教训（2026-09-06）：库里 1,925 条人裁有 1,021 条是 v1 的
    `book:page:col:idx`，与 v2 的 `book:page:col:slot` 长得一样但不是同一格。
    第一版不加区分地收，vol01 判据 A 当场从 100% 掉到 94.70%
    （vol01:4:1:10 判「編」而金标「三」）。
    """
    import sqlite3

    from open_guji_cv.steps.seed_admit import _human_shapes

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
