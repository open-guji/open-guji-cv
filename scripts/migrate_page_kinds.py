"""把册 yaml 里老的页型参数（border_detect_gate.body_pages／table_pages、row_segment.roster_pages）改写成 page_kinds。

用法：python scripts/migrate_page_kinds.py <工作区>/books [--apply] [--only vol01,vol02] [--diff]

缺省干跑：只列哪些册用了老写法、改后每步 params_hash 是否逐一不变。--apply 才写 books/ 下的文件；
**不推中心库**（推库要用户点头）。逻辑见 open_guji_cv/ops/page_kinds_migrate.py。
"""
import argparse
import sys
from pathlib import Path

from open_guji_cv.ops.page_kinds_migrate import run


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("books_dir")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", default=None, help="册号清单，逗号分隔")
    ap.add_argument("--diff", action="store_true", help="每册打印改动 diff")
    a = ap.parse_args()
    res = run(Path(a.books_dir), apply=a.apply, only=a.only.split(",") if a.only else None)
    if not res:
        print("没有册用老写法。")
        return 0
    bad = 0
    for r in res:
        mv = "；".join(f"{k} {v}" for k, v in (r.get("moved") or {}).items())
        tag = {"dry": "可改", "migrated": "已改", "conflict": "✗ 冲突", "unchanged_fp_mismatch": "✗ 指纹有变", "error": "✗ 出错"}[r["status"]]
        print(f"{r['book']:12s} {tag}  {mv}" + (f"  {r['detail']}" if r.get("detail") else "")
              + (f"  （空值去掉 {r['dropped']}）" if r.get("dropped") else ""))
        if a.diff and r.get("diff"):
            print(r["diff"])
        bad += r["status"] in ("conflict", "unchanged_fp_mismatch", "error")
    print(f"共 {len(res)} 册用老写法，{bad} 册没法自动改。" + ("" if a.apply else "（干跑，没写文件；加 --apply 才写）"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
