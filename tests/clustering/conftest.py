"""共享 fixture：合成 output/<book>/ 目录（phase4 图块 + phase5 簇，簇按真值字分组）；
外加直接往字形库塞合成字形的造数工具（v1 聚类链已删，不再靠它造库）。"""

import json
import random

import cv2
import numpy as np
import pytest

from open_guji_cv.clustering.extractor import CharExtractor, load_index
from open_guji_cv.clustering.synth import degrade, synthetic_glyph

TEXTS = ["甲", "乙", "丙", "丁", "戊", "己"]


def build_synth_book(root, book="tbook", n_pages=2, n_cols=3, n_chars=6,
                     wear=0.3, seed=0):
    """合成书：页面图 + phase3 网格 → 跑 M1，簇直接按真值字分组写 clusters.json。

    供 CandidateGenerator / vlm_assist 测试用（它们只读 phase4 + phase5 clusters.json）。
    真值：每格的字 = TEXTS[(seq + page) % 6]，也写进 phase3 的 text 字段。
    """
    book_dir = root / book
    (book_dir / "s6_binarize").mkdir(parents=True)
    (book_dir / "phase3_char_grid").mkdir(parents=True)

    rng = random.Random(seed)
    glyphs = [synthetic_glyph(random.Random(100 + i)) for i in range(len(TEXTS))]
    CELL, COLW = 70, 60
    for page in range(1, n_pages + 1):
        H = n_chars * CELL + 40
        W = n_cols * (COLW + 20) + 40
        img = np.full((H, W), 235, dtype=np.uint8)
        columns = []
        seq = 0
        for col_no in range(1, n_cols + 1):
            rx = W - 20 - (col_no - 1) * (COLW + 20)
            lx = rx - COLW
            cells = [{"type": "margin", "y_top": 0.0, "y_bottom": 20.0}]
            for idx in range(n_chars):
                gi = (seq + page) % len(glyphs)
                seq += 1
                y0, y1 = 20.0 + idx * CELL, 20.0 + (idx + 1) * CELL
                g = degrade(glyphs[gi], rng, wear=wear)
                g_img = cv2.resize(g * 255, (COLW - 12, CELL - 12),
                                   interpolation=cv2.INTER_NEAREST)
                region = img[int(y0) + 6:int(y1) - 6, lx + 6:rx - 6]
                region[g_img > 127] = 25
                cells.append({"type": "char", "index": idx,
                              "y_top": y0, "y_bottom": y1,
                              "text": TEXTS[gi], "confidence": 0.85})
            columns.append({"index": col_no, "left_x": float(lx),
                            "right_x": float(rx), "cells": cells})
        cv2.imwrite(str(book_dir / "s6_binarize" / f"{page}.png"), img)
        with open(book_dir / "phase3_char_grid" / f"{page}_char_grid.json",
                  "w", encoding="utf-8") as f:
            json.dump({"columns": columns}, f, ensure_ascii=False)

    CharExtractor().run_book(book_dir)
    by_char: dict[str, list[str]] = {}
    for inst in load_index(book_dir / "phase4_chars"):
        by_char.setdefault(inst.ocr_text, []).append(inst.id)
    clusters = [{"cluster_id": f"c{k:03d}", "size": len(ms), "members": ms,
                 "reps": ms[:3]}
                for k, (_, ms) in enumerate(sorted(by_char.items()))]
    (book_dir / "phase5_clusters").mkdir()
    with open(book_dir / "phase5_clusters" / "clusters.json", "w",
              encoding="utf-8") as f:
        json.dump({"clusters": clusters}, f, ensure_ascii=False)
    return book_dir


def seed_glyphs(db, chars=("甲", "乙"), n_each=5, edition="ed1", seed=0):
    """直接用 admit_instance 往库里塞合成字形：每字 n_each 个磨损变体。

    返回 {char: [本次新入库的 instance_id, ...]}（已在库的不算，admit 幂等）。字形来自 synth.synthetic_glyph（每字固定种子）。
    """
    import cv2
    rng = random.Random(seed)
    out: dict[str, list[str]] = {}
    for gi, ch in enumerate(chars):
        base = synthetic_glyph(random.Random(100 + gi))
        for k in range(n_each):
            g = degrade(base, rng, wear=0.3)
            ok, buf = cv2.imencode(".png", 255 - (g * 255).astype("uint8"))
            assert ok
            iid = f"tbook:{ch}:{k}"
            if db.admit_instance(iid, ch, buf.tobytes(), provenance="test",
                                 edition_tag=edition, page="1", col=gi, idx=k):
                out.setdefault(ch, []).append(iid)
    return out


@pytest.fixture(scope="module")
def synth_book(tmp_path_factory):
    return build_synth_book(tmp_path_factory.mktemp("out"))
