"""四把尺子的回归。

这个模块的 bug **不会报错，只会给出好看的错数**——开发时 R4 先后虚高成
20.74% 和 13.42%（真值 0.51%），两次都跑得好好的。所以这里把踩过的坑
钉成用例：窗口越界的症状是「被切」厚度接近一个整字（~110px），而真被切
的笔画只有几十像素。
"""

from __future__ import annotations

import numpy as np
import pytest

from open_guji_cv.eval.rulers import CLIP_MIN_PX, _clipped_ink, _runs_over


class _Cell:
    def __init__(self, y0: float, y1: float) -> None:
        self.y0, self.y1 = y0, y1


def _prof(h: int, inks: list[tuple[int, int]]) -> np.ndarray:
    p = np.zeros(h)
    for a, b in inks:
        p[a:b] = 0.5
    return p


def test_runs_over_edges():
    m = np.array([1, 1, 0, 0, 1, 0, 1, 1], dtype=bool)
    assert _runs_over(m) == [(0, 2), (4, 5), (6, 8)]
    assert _runs_over(np.zeros(5, dtype=bool)) == []
    assert _runs_over(np.ones(3, dtype=bool)) == [(0, 3)]


def test_no_clip_when_box_fills_cell():
    """紧框贴着格线：框外无空间，必然 0。"""
    prof = _prof(300, [(100, 200)])
    assert _clipped_ink(prof, (0, 100, 0, 200), _Cell(100, 200), 300) == 0


def test_detects_stroke_clipped_above():
    """紧框上方紧贴着一段笔画墨 → 算被切。"""
    prof = _prof(300, [(75, 100), (100, 200)])   # 上方 25px 笔画
    n = _clipped_ink(prof, (0, 100, 0, 200), _Cell(70, 210), 300)
    assert n >= CLIP_MIN_PX and n < 40


def test_ignores_ink_not_touching_box():
    """墨在格内但离紧框有距离 → 是框线残渣/噪声，不算被切。"""
    prof = _prof(300, [(72, 92), (100, 200)])    # 与紧框间隔 8px
    assert _clipped_ink(prof, (0, 100, 0, 200), _Cell(70, 210), 300) == 0


def test_window_never_reaches_neighbour_char():
    """窗口只到本格格线——这是 R4 两次虚高的根因。

    构造：本格 [100,200]，紧框 [105,195]，**格外**（邻字）有 110px 的整字墨。
    窗口若开到版框就会把那 110px 当成「被切」。
    """
    prof = _prof(400, [(105, 195), (210, 320)])  # 后者是邻字
    n = _clipped_ink(prof, (0, 105, 0, 195), _Cell(100, 200), 400)
    assert n < 30, f"窗口越界扫到邻字了：{n}px（整字高度量级）"


@pytest.mark.parametrize("goal_key", ["R1", "R2", "R3", "R4"])
def test_measure_shape_on_a_frozen_real_page(goal_key, tmp_path, monkeypatch, ws,
                                             fixture_page):
    """真页上跑通，且分母非空、比值合理。

    2026-09-20 改：原先读 `load_book("vol01").dev_set` 的工作区产物，工作区
    不在就 skip——于是**这个模块最要紧的那条护栏**（R4 窗口越界会飙到十几个
    百分点）在云端从来没执行过，而它守的正是这个模块唯一的历史故障。

    现在拿 `tests/fixtures/` 里那张冻结真页从 Step1 跑到 Step4 再量。样本固定，
    所以「分母非空」这类形状断言每次都真的执行；具体数值仍然不写死——那是
    算法的输出，钉住它就变成了「算法不许改进」。
    """
    from open_guji_cv.core.book import load_book
    from open_guji_cv.eval.rulers import measure

    import open_guji_cv.steps  # noqa: F401  —— 注册产物种类与步骤
    from helpers import run_keben_from_raw

    run_keben_from_raw(tmp_path, monkeypatch, book=load_book("keben"), gray=fixture_page)
    rs = {r["key"]: r for r in measure("keben", [1])["rulers"]}
    r = rs[goal_key]
    assert r["den"] > 0, f"{goal_key} 分母为 0，说明产物没读到"
    assert 0 <= r["num"] <= r["den"]
    # R4 若窗口越界会飙到十几个百分点；正常应远低于此
    if goal_key == "R4":
        assert r["value"] < 5.0, f"R4={r['value']}% 太高，多半是窗口又越界了"


# ── 任务卡 #54 第4条：快照只带 products/、没带 cache/ 时要报错，不许悄悄给 0/None ──
def test_measure_errors_when_column_image_cache_entirely_missing(tmp_path, monkeypatch,
                                                                  fixture_page, ws):
    """拿快照复算：`products/` 有、`cache/` 没有——R2 系尺子以前会因为
    `_col_profile()` 全部返回 None 而悄悄把分母算成 0（下游看板常把
    `value=None` 显示成 0），且不报错。这种"过闸有解的列一张列图缓存都
    读不到"的结构性缺失现在要报错，不许假装量出来了。"""
    from open_guji_cv.core.book import load_book
    from open_guji_cv.eval.rulers import measure

    import open_guji_cv.steps  # noqa: F401
    from helpers import run_keben_from_raw

    run_keben_from_raw(tmp_path, monkeypatch, book=load_book("keben"), gray=fixture_page)
    import shutil
    shutil.rmtree(tmp_path / "cache" / "keben" / "column_image")   # 模拟"只有快照的 products/"

    with pytest.raises(RuntimeError, match="cache"):
        measure("keben", [1])


def test_measure_tolerates_sporadic_single_column_cache_miss(tmp_path, monkeypatch,
                                                              fixture_page, ws):
    """个别列的缓存被 LRU 淘汰是正常运行中会发生的事——不该被 K4 那道闸误伤。
    只删一列的缓存（不是全删），应当正常出结果，不报错。"""
    from open_guji_cv.core.book import load_book
    from open_guji_cv.eval.rulers import measure

    import open_guji_cv.steps  # noqa: F401
    from helpers import run_keben_from_raw

    run_keben_from_raw(tmp_path, monkeypatch, book=load_book("keben"), gray=fixture_page)
    img_dir = tmp_path / "cache" / "keben" / "column_image"
    files = sorted(img_dir.iterdir())
    assert len(files) > 1, "这张 fixture 页只有一列，测不出「个别列缺失」——挑张多列的页"
    files[0].unlink()   # 只删一列

    out = measure("keben", [1])   # 不该抛
    assert out["rulers"]


# ── #174：R2c 等要给页／列明细，不只总数 ──────────────────────────────
def test_by_page_aggregates_full_detail_even_when_truncated():
    from open_guji_cv.eval.rulers import Ruler
    r = Ruler("R2c", "t", num=25, den=30,
              detail=[{"page": 149, "col": c % 3, "y": c} for c in range(22)]
              + [{"page": 7, "col": 1, "y": 0}] * 3)
    d = r.to_dict(full=False)
    assert len(d["detail"]) == 20                              # detail 仍截断
    assert d["by_page"] == {"7": {"n": 3, "cols": [1]},        # by_page 按全量汇总、页号排序
                            "149": {"n": 22, "cols": [0, 1, 2]}}


def test_r2c_detail_covers_every_counted_line(tmp_path, monkeypatch, ws, fixture_page):
    """R2c 以前只给「无缝」那一种记明细，「缝上有墨」只进总数——明细条数 ≠ num。"""
    from open_guji_cv.core.book import load_book
    from open_guji_cv.eval.rulers import measure

    import open_guji_cv.steps  # noqa: F401
    from helpers import run_keben_from_raw

    run_keben_from_raw(tmp_path, monkeypatch, book=load_book("keben"), gray=fixture_page)
    r = {x["key"]: x for x in measure("keben", [1], full=True)["rulers"]}["R2c"]
    assert len(r["detail"]) == r["num"]
    assert sum(e["n"] for e in r["by_page"].values()) == r["num"]
    assert all(d["why"] in ("无缝", "缝上有墨") for d in r["detail"])


def test_check_rulers_detail_flag_prints_rows(monkeypatch, capsys):
    from open_guji_cv import cli_v2
    from open_guji_cv.eval import rulers
    fake = {"book": "b", "n_pages": 1, "rulers": [
        {"key": "R2c", "title": "缝后仍穿墨", "num": 2, "den": 9, "value": 22.2, "unit": "%",
         "detail": [{"page": 149, "col": 3, "y": 400, "why": "无缝"},
                    {"page": 149, "col": 7, "y": 88, "why": "缝上有墨", "px": 4}],
         "by_page": {"149": {"n": 2, "cols": [3, 7]}}}]}
    seen = {}

    def fake_measure(book, pages, st, full=False):
        seen["full"] = full
        return fake
    monkeypatch.setattr(rulers, "measure", fake_measure)
    monkeypatch.setattr("open_guji_cv.core.book.load_book",
                        lambda b: type("B", (), {"resolve_pages": lambda self, s: [149]})())
    args = type("A", (), {"action": "rulers", "book": "b", "pages": None, "full": False, "detail": "r2c"})()
    cli_v2.cmd_check(args)
    out = capsys.readouterr().out
    assert seen["full"] is True
    assert "p149    2 条  列 3,7" in out
    assert "p149\tc7\ty=88  why=缝上有墨  px=4" in out
