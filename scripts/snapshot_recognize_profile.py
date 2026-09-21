"""recognize-profile 全量样本巡检（**脚本，不是 pytest 测试**）。

对 `data/` 下每本书执行 recognize-profile，与 `snapshot/` 里保存的 JSON 快照
比对，确认版式识别在九种版式上都没退化。

2026-09-20 从 `tests/recognize-profile/test_recognize_profile.py` 迁到这里。
它本来就是个带 argparse 的脚本，一条 pytest 用例都没有——放在 `tests/` 下
跑全仓时只会报「0 tests collected」，看着像有测试守着，其实什么都没跑。
而且它吃的是 `data/`（293 MB 生产样本，会换批），不满足「测试只依赖
`tests/` 下冻结数据」那条口径。

**自动化的那份回归在 `tests/test_recognize_profile.py`**：只跑
`tests/fixtures/` 里那三张冻结真页，期望值也冻结在测试目录下，每次都真的执行。
这个脚本管的是「九种版式的巡检」，按需手跑。

用法:
    python scripts/snapshot_recognize_profile.py                 # 比对快照
    python scripts/snapshot_recognize_profile.py --update        # 重落快照
    python scripts/snapshot_recognize_profile.py --books book1,book3
    python scripts/snapshot_recognize_profile.py --refresh-fixture
        # 重落 tests/fixtures/recognize_profile_keben.json（那条自动化回归的期望值）

快照目录结构:
    scripts/recognize_profile_snapshot/
    └── snapshot/
        ├── book1.json         # 快照 JSON（纳入版本控制）
        ├── ...
        └── _output/           # 调试用 annotated 图片（gitignore）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 迁到 scripts/ 之后仓根少一层（原先在 tests/recognize-profile/ 下）。
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from open_guji_cv.pipeline import GujiPipeline
from open_guji_cv.profile import BookProfile

SNAPSHOT_DIR = Path(__file__).parent / "recognize_profile_snapshot" / "snapshot"
OUTPUT_DIR = SNAPSHOT_DIR / "_output"
DATA_DIR = _project_root / "data"

# 比对时忽略的字段（浮点数精度敏感或不影响功能的字段）
IGNORE_FIELDS = {"detection_confidence"}


def _normalize_for_compare(d: dict) -> dict:
    """移除比对时应忽略的字段，返回新字典。"""
    return {k: v for k, v in d.items() if k not in IGNORE_FIELDS}


def recognize_one(book_name: str) -> dict:
    """对一本书执行 recognize-profile，返回结果字典。"""
    book_dir = DATA_DIR / book_name
    if not book_dir.is_dir():
        raise FileNotFoundError(f"数据目录不存在: {book_dir}")

    # 输出到临时目录，不污染主 output/
    out_dir = OUTPUT_DIR / book_name
    out_dir.mkdir(parents=True, exist_ok=True)

    pipeline = GujiPipeline(output_dir=str(out_dir))
    profile = pipeline.analyze(str(book_dir))
    return profile.to_dict()


FIXTURE_PAGES = _project_root / "tests" / "fixtures" / "workspace" / "raw" / "keben"
FIXTURE_EXPECTED = (_project_root / "tests" / "fixtures"
                    / "recognize_profile_keben.json")


def refresh_fixture() -> None:
    """重落 `tests/test_recognize_profile.py` 那条自动化回归的期望值。

    在 tmp 里跑——`GujiPipeline.analyze()` 会往输入目录写一份 `profile.json`
    副产物，直接指向 `tests/fixtures/` 会污染冻结数据。
    """
    import shutil
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    pages = tmp / "book"
    shutil.copytree(FIXTURE_PAGES, pages)
    d = GujiPipeline(output_dir=str(tmp / "out")).analyze(str(pages)).to_dict()
    d = {k: v for k, v in d.items() if k not in IGNORE_FIELDS}
    FIXTURE_EXPECTED.write_text(
        json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  已重落 fixture 期望值: {FIXTURE_EXPECTED}")


def update_snapshots(books: list[str]) -> None:
    """运行识别并保存快照。"""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    for book in books:
        print(f"\n{'=' * 50}")
        print(f"更新快照: {book}")
        print(f"{'=' * 50}")
        try:
            result = recognize_one(book)
            snap_path = SNAPSHOT_DIR / f"{book}.json"
            with open(snap_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"  已保存: {snap_path}")
        except Exception as e:
            print(f"  失败: {e}")


def check_snapshots(books: list[str]) -> bool:
    """比对识别结果与快照，返回是否全部通过。

    **别叫 `test_snapshots`**：本文件是个独立命令行脚本（见模块头「用法」），
    不是 pytest 用例——它带位置参数 `books`，pytest 收集到 `test_` 开头的函数
    会把 `books` 当 fixture 找，找不到就报 `fixture 'books' not found`，整个
    测试套件多一条 collection ERROR。2026-09-15 改名消掉。
    """
    all_pass = True
    results = []

    for book in books:
        snap_path = SNAPSHOT_DIR / f"{book}.json"
        if not snap_path.exists():
            print(f"  {book}: 快照不存在，跳过（先运行 --update）")
            results.append((book, "SKIP"))
            continue

        print(f"\n测试: {book}")
        try:
            actual = recognize_one(book)
        except Exception as e:
            print(f"  识别失败: {e}")
            results.append((book, "ERROR"))
            all_pass = False
            continue

        with open(snap_path, "r", encoding="utf-8") as f:
            expected = json.load(f)

        actual_cmp = _normalize_for_compare(actual)
        expected_cmp = _normalize_for_compare(expected)

        if actual_cmp == expected_cmp:
            print(f"  PASS")
            results.append((book, "PASS"))
        else:
            print(f"  FAIL — 结果与快照不一致:")
            all_pass = False
            results.append((book, "FAIL"))
            # 打印差异
            for key in sorted(set(list(actual_cmp.keys()) + list(expected_cmp.keys()))):
                a = actual_cmp.get(key)
                e = expected_cmp.get(key)
                if a != e:
                    print(f"    {key}: 期望={e!r}  实际={a!r}")

    # 汇总
    print(f"\n{'=' * 50}")
    print("汇总:")
    for book, status in results:
        marker = {"PASS": "+", "FAIL": "X", "SKIP": "-", "ERROR": "!"}[status]
        print(f"  [{marker}] {book}: {status}")

    passed = sum(1 for _, s in results if s == "PASS")
    total = sum(1 for _, s in results if s != "SKIP")
    print(f"\n  {passed}/{total} 通过")
    return all_pass


def find_books() -> list[str]:
    """找到 data/ 下所有有 profile.json 或图片的书。"""
    books = []
    for d in sorted(DATA_DIR.iterdir()):
        if d.is_dir() and d.name.startswith("book"):
            books.append(d.name)
    return books


def main():
    parser = argparse.ArgumentParser(description="recognize-profile 全量样本巡检")
    parser.add_argument("--update", action="store_true",
                        help="更新快照（首次运行或算法改进后）")
    parser.add_argument("--refresh-fixture", action="store_true",
                        help="重落 tests/fixtures/recognize_profile_keben.json"
                             "（tests/test_recognize_profile.py 的期望值）")
    parser.add_argument("--books", default=None,
                        help="只测某些书（逗号分隔，如 book1,book3）")
    args = parser.parse_args()

    if args.books:
        books = [b.strip() for b in args.books.split(",")]
    else:
        books = find_books()

    if not books:
        print("未找到测试数据")
        return 1

    print(f"测试书目: {', '.join(books)}")

    if args.refresh_fixture:
        refresh_fixture()
        return 0
    if args.update:
        update_snapshots(books)
        return 0
    else:
        ok = check_snapshots(books)
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
