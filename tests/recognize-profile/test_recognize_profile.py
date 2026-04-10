"""recognize-profile 快照测试。

对 data/ 下每本书执行 recognize-profile，将结果与 snapshot/ 中保存的
JSON 快照比对，确保版式识别结果稳定不退化。

用法:
    # 正常测试（比对快照）
    cd d:/workspace/open-guji-cv
    python tests/recognize-profile/test_recognize_profile.py

    # 更新快照（首次运行或算法改进后）
    python tests/recognize-profile/test_recognize_profile.py --update

    # 只测某本书
    python tests/recognize-profile/test_recognize_profile.py --books book1,book3

快照目录结构:
    tests/recognize-profile/
    ├── snapshot/
    │   ├── book1.json         # 快照 JSON（纳入版本控制）
    │   ├── book2.json
    │   ├── ...
    │   └── _output/           # 调试用 annotated 图片（gitignore）
    │       ├── book1/
    │       └── ...
    └── test_recognize_profile.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root))

from open_guji_cv.pipeline import GujiPipeline
from open_guji_cv.profile import BookProfile

SNAPSHOT_DIR = Path(__file__).parent / "snapshot"
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


def test_snapshots(books: list[str]) -> bool:
    """比对识别结果与快照，返回是否全部通过。"""
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
    parser = argparse.ArgumentParser(description="recognize-profile 快照测试")
    parser.add_argument("--update", action="store_true",
                        help="更新快照（首次运行或算法改进后）")
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

    if args.update:
        update_snapshots(books)
        return 0
    else:
        ok = test_snapshots(books)
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
