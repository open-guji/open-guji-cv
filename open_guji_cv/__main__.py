"""`python -m open_guji_cv <command>` 与 `guji-cv <command>`：与 `guji` 是同一套命令（cli_v2）。

2026-10-06 cv 大清理（overview#413）：v1 的旧命令（cut / preprocess / extract / run / chars / cluster /
label / seed / review / update / bench …）连同 v1 管线一起退役删除；还在用的 `glyph-db` 搬到
`cli_glyph_db.py`，两个入口都能用。旧实现见分支 `archive/pre-cleanup-2026-10-06`。
"""
import io
import sys

if hasattr(sys.stdout, "buffer") and not isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
elif hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from .cli_v2 import main  # noqa: E402

if __name__ == "__main__":
    main()
