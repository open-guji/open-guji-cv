# -*- coding: utf-8 -*-
"""把 GlyphDB（output/glyph.db）里的实例真源统一成 canonical 格式。

    PYTHONPATH=. python scripts/canonicalize_glyph_db.py --db output/glyph.db

背景（2026-08-24 用户发现）：canonical 标准（256×256 灰度、只缩不放、
质心居中）此前只接在 import_book 批量路径上，逐页种子的 admit_instance
存的一直是原始裁切（尺寸各异、字忽上忽下，展示/比较不可比）。本脚本
一次性迁移存量：patch_png → to_canonical，derived（norm/skeleton/feat）
从 canonical 图重算，最后统一触碰 exemplars.added_at 让特征矩阵缓存
失效。幂等：已是 256×256 的行跳过。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from open_guji_cv.clustering.canonical import (CANON_SIZE,  # noqa: E402
                                               encode_png, to_canonical)
from open_guji_cv.clustering.glyph_db import GlyphDB, _now  # noqa: E402
from open_guji_cv.clustering.normalize import normalize_patch  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="output/glyph.db")
    args = ap.parse_args()
    db = GlyphDB(args.db)
    try:
        rows = db.conn.execute(
            "SELECT instance_id, patch_png FROM instances").fetchall()
        cur = db.conn.cursor()
        n = {"migrated": 0, "skipped": 0, "bad": 0}
        for iid, png in rows:
            gray = cv2.imdecode(np.frombuffer(png, np.uint8),
                                cv2.IMREAD_GRAYSCALE)
            if gray is None:
                n["bad"] += 1
                continue
            if gray.shape == (CANON_SIZE, CANON_SIZE):
                n["skipped"] += 1
                continue
            canon = to_canonical(gray)
            cur.execute(
                "UPDATE instances SET patch_png=?, updated_at=? "
                "WHERE instance_id=?", (encode_png(canon), _now(), iid))
            db._write_derived(cur, iid, normalize_patch(canon))
            n["migrated"] += 1
        cur.execute("UPDATE exemplars SET added_at=?", (_now(),))
        db.conn.commit()
        print(n)
    finally:
        db.close()


if __name__ == "__main__":
    main()
