# -*- coding: utf-8 -*-
"""`recognize-profile` 版式识别的快照回归。

2026-09-20 重建。原先这份东西在 `tests/recognize-profile/test_recognize_profile.py`：
一个带 `argparse` / `main()` / `if __name__ == "__main__"` 的**脚本**，用 `python
tests/recognize-profile/test_recognize_profile.py` 跑，对 `data/` 下九本书各跑一遍
再比 `snapshot/*.json`。两个毛病：

1. **它叫 `test_*.py` 却一条 pytest 用例都没有**——跑全仓时 pytest 报
   「0 tests collected」，看着像有这么个测试在守着，实际什么都没跑；
2. 输入是 `data/`（293 MB 生产样本数据，会换批），快照一变就要重落。

拆成两半（脚本那半已迁去 `scripts/snapshot_recognize_profile.py`，连同它的
九份快照）：

- **自动化的这半**在这里：只对 `tests/fixtures/` 里那三张冻结真页跑，
  期望值冻结在 `tests/fixtures/recognize_profile_keben.json`。输入和期望都在
  测试目录下、都不会变，所以这条**每次都真的执行**，跑红就只可能是识别代码变了。
- **全量九本书**那半仍按需手跑：`python scripts/snapshot_recognize_profile.py`
  （`--update` 重落快照，`--books` 只跑某几本）。那是对生产样本的巡检，不是
  自动化测试。

比对**排除 `detection_confidence`**：那是逐字段的置信度浮点，像素级的微小
变化就会动最后几位，钉它等于钉住浮点数。识别结论本身（版面/行数/边框/颜色…）
才是该稳的东西。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PAGES = FIXTURES / "workspace" / "raw" / "keben"
EXPECTED = FIXTURES / "recognize_profile_keben.json"

#: 比对时忽略的字段：逐字段置信度是浮点，钉它等于钉浮点数。
IGNORE_FIELDS = {"detection_confidence"}


@pytest.fixture
def pages(tmp_path) -> Path:
    """把冻结样页复制一份到 tmp 再跑。

    `GujiPipeline.analyze()` 会往**输入目录**里写一份 `profile.json`（副产物），
    直接指向 `tests/fixtures/` 的话会污染冻结数据——这一点是这轮踩出来的。
    """
    dst = tmp_path / "book"
    shutil.copytree(PAGES, dst)
    return dst


def _profile(pages: Path, out_dir: Path) -> dict:
    from open_guji_cv.pipeline import GujiPipeline

    d = GujiPipeline(output_dir=str(out_dir)).analyze(str(pages)).to_dict()
    return {k: v for k, v in d.items() if k not in IGNORE_FIELDS}


def test_profile_matches_the_frozen_snapshot(pages, tmp_path):
    got = _profile(pages, tmp_path / "out")
    want = json.loads(EXPECTED.read_text(encoding="utf-8"))
    assert got == want, (
        "版式识别结论与冻结快照不符。确认是有意的改动之后，用\n"
        f"    python scripts/snapshot_recognize_profile.py --refresh-fixture\n"
        "重落这份快照，**并在提交信息里说清哪个字段为什么变**——\n"
        f"差异：{ {k: (want.get(k), got.get(k)) for k in set(want) | set(got) if want.get(k) != got.get(k)} }")


def test_profile_is_deterministic(pages, tmp_path):
    """同一批图跑两遍结论必须一样——识别里不许掺随机性。"""
    a = _profile(pages, tmp_path / "a")
    b = _profile(pages, tmp_path / "b")
    assert a == b


def test_confidence_fields_are_present_and_in_range(pages, tmp_path):
    """置信度不比值，但**必须都在、且落在 [0,1]**——越界说明归一化坏了。"""
    from open_guji_cv.pipeline import GujiPipeline

    d = GujiPipeline(output_dir=str(tmp_path / "out")).analyze(str(pages)).to_dict()
    conf = d.get("detection_confidence") or {}
    assert conf, "一个置信度字段都没有"
    bad = {k: v for k, v in conf.items() if not (0.0 <= float(v) <= 1.0)}
    assert not bad, f"置信度越界：{bad}"
