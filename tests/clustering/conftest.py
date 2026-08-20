"""共享 fixture：合成一个完整的 output/<book>/ 目录（phase4~6 齐全）。"""

import json
import random

import cv2
import numpy as np
import pytest

from open_guji_cv.clustering.clusterer import ClusterParams, ConservativeClusterer
from open_guji_cv.clustering.extractor import CharExtractor
from open_guji_cv.clustering.labeling import rank_book
from open_guji_cv.clustering.candidates import CandidateGenerator, PriorSource
from open_guji_cv.clustering.lm import UniformLM
from open_guji_cv.clustering.synth import degrade, synthetic_glyph
from open_guji_cv.clustering.variants import VariantMap

TEXTS = ["甲", "乙", "丙", "丁", "戊", "己"]


def build_synth_book(root, book="tbook", n_pages=2, n_cols=3, n_chars=6,
                     wear=0.3, seed=0):
    """合成书：页面图 + phase3 网格 → 依次跑 M1/M3/M4/M5，返回书目录。

    与 CLI 冒烟测试相同的数据形状，供 review/update 测试复用。
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
    ConservativeClusterer(ClusterParams(feature="raw")).run_book(
        book_dir, montage=True)
    vm = VariantMap({})
    CandidateGenerator([PriorSource()], vm).run_book(book_dir)
    rank_book(book_dir, UniformLM(), vm)
    return book_dir


@pytest.fixture(scope="module")
def synth_book(tmp_path_factory):
    return build_synth_book(tmp_path_factory.mktemp("out"))
