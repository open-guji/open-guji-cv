# -*- coding: utf-8 -*-
"""自造的小 book-text 条目（char／cord／punct／entity／index／CHANGES），给 A3、C1、D1a 的测试用。不读任何真仓。

第 3 页两列：
- 第 1 列「欽定卷」占 1–3 格，第 3 格之下是一方印章（cord marks 里 ``excluded``，像真书 002 ``3:1:9`` 之下那格），再下是留白；
- 第 2 列抬头一格（``-1``）、正文、一段双行夹注（``2a 3a``／``2b``）、阙文 □、正文。
"""
from __future__ import annotations

import json
from pathlib import Path

BOOK = "bkxyz"
ENTRY = f"Book/x/y/z/{BOOK}"

CHANGES = """# original 版本日志

| 日期 | 册 | 线 | 旧→新 | 说明 | PR |
|---|---|---|---|---|---|
| 2026-10-07 | bkxyz/002 | 文本＋标点＋实体 | →1.0.0 | 首次并 main：cv 0.2.0（commit 4a9388ac），快照 snap/bkxyz/vol02/20261007T0100，cv 侧本册 002-r1 | #22 |
| 2026-10-08 | bkxyz/002 | 实体 | 1.0.0→1.1.0 | 专名补 | #23 |
| 2026-10-19 | bkxyz/002 | 文本 | 1.0.0→1.0.1 | 逐处改正 3 格\\|含列末 □ | #184 |
| 2026-10-19 | bkxyz/002 | 文本 | 1.0.1（不变） | pending 改字段 | #185 |
| 2026-10-20 | bkxyz/003 | 文本 | →0.1.0 | 粗校完（cv rc/v0.4.6） | #190 |
| 2026-10-21 | bkxyz/002 | 文本 | 1.0.1→1.0.2 | 改 1 格；意见 op_span_0123456789 | #300 |
| 2026-10-21 | other/002 | 文本 | 1.0.0→1.0.1 | 别的书 | #1 |
"""

#: 截到 1.0.1 为止的 CHANGES（D1a 的 bump 从 1.0.1 起）
CHANGES_101 = "\n".join(ln for ln in CHANGES.splitlines() if "#300" not in ln) + "\n"


def page3_char() -> dict:
    return {"page": 3, "columns": [
        {"col": 1, "cells": [{"a": "3:1:1", "c": "欽"}, {"a": "3:1:2", "c": "定"}, {"a": "3:1:3", "c": "卷"}]},
        {"col": 2, "raised": 1, "cells": [
            {"a": "3:2:-1", "c": "御"}, {"a": "3:2:1", "c": "製"},
            {"a": "3:2:2a", "c": "甲"}, {"a": "3:2:3a", "c": "乙"},
            {"a": "3:2:2b", "c": "丙"},
            {"a": "3:2:4", "c": "□", "lacuna": True}, {"a": "3:2:5", "c": "文"}]},
    ]}


def char(version: str = "1.0.1") -> dict:
    return {"$schema": "https://open-guji.org/schema/char/v0.1.json", "version": version, "book_id": BOOK, "volume": 2,
            "pages": [{"page": 1, "columns": []}, {"page": 2, "columns": []}, page3_char()]}


CANVAS_W, CANVAS_H = 400, 600
SEAL_BOX = [298, 200, 64, 70]


def cord() -> dict:
    """框：第 1 列 x=300..360，第 n 格 y=50n；第 2 列 x=200..260（夹注 a 在右半、b 在左半）。"""
    def cb(slot, x=300, w=60):
        return [x, 50 * slot, w, 48]
    cells = [{"a": "3:1:1", "box": cb(1), "id": "g1"}, {"a": "3:1:2", "box": cb(2), "id": "g2"},
             {"a": "3:1:3", "box": cb(3), "id": "g3"},
             {"a": "3:2:-1", "box": [200, 0, 60, 48], "id": "g4"}, {"a": "3:2:1", "box": [200, 50, 60, 48], "id": "g5"},
             {"a": "3:2:2a", "box": [230, 100, 30, 48], "id": "g6"}, {"a": "3:2:3a", "box": [230, 150, 30, 48], "id": "g7"},
             {"a": "3:2:2b", "box": [200, 100, 30, 48], "id": "g8"},
             {"a": "3:2:4", "box": [200, 200, 60, 48], "id": "g9"}, {"a": "3:2:5", "box": [200, 250, 60, 48], "id": "g10"}]
    marks = [{"kind": "excluded", "id": "mseal1", "slot": 3, "col": 1, "box": SEAL_BOX, "note": "排除名单·非字（墨污/切坏）"},
             {"kind": "blank", "id": "mblank1", "slot": 6, "col": 1, "box": [300, 300, 60, 48]},
             {"kind": "excluded", "id": "mjz1", "slot": 3, "col": 2, "box": [200, 150, 30, 48],
              "note": "排除名单·非字（墨污/切坏）"}]

    def canvas(n):
        return {"id": f"https://iiif.test/iiif/{BOOK}/canvas/02/{n:04d}", "seq": f"{n:04d}", "width": CANVAS_W, "height": CANVAS_H}
    return {"$schema": "https://open-guji.org/schema/cord/v0.1.json", "book_id": BOOK, "volume": 2, "pages": [
        {"page": 1, "canvas": canvas(1), "cells": []},
        {"page": 2, "canvas": canvas(2), "cells": []},
        {"page": 3, "image": {"width": CANVAS_W, "height": CANVAS_H, "sha256": "0" * 64}, "canvas": canvas(3),
         "producers": {"cv": {"tool": "open-guji-cv", "rev": "abc1234", "pipeline": "keben_body_v2",
                              "snapshot": "guji-workspace snap/bkxyz/vol02"}},
         "columns": [{"col": 1, "kind": "body", "box": [295, 0, 70, 600]}, {"col": 2, "kind": "body", "box": [195, 0, 70, 600]}],
         "cells": cells, "marks": marks}]}


def punct(text_version: str = "1.0.1") -> dict:
    return {"$schema": "https://open-guji.org/schema/punct/v0.2.json", "version": "1.1.0", "text_version": text_version,
            "book_id": BOOK, "punctuations": [
                {"mark": "#", "kind": "heading", "pos": "before", "char_offset": 0, "anchor": "3:1:1"},
                {"mark": "\n\n", "kind": "break", "pos": "after", "char_offset": 2, "pre_char": "卷", "anchor": "3:1:3"},
                {"mark": "。", "pos": "after", "char_offset": 4, "pre_char": "製", "anchor": "3:2:1"},
                {"mark": "，", "pos": "after", "char_offset": 6, "pre_char": "乙", "anchor": "3:2:3a"},
                {"mark": "。", "pos": "after", "char_offset": 9, "pre_char": "文", "anchor": "3:2:5"}]}


def entity(text_version: str = "1.0.1") -> dict:
    return {"$schema": "https://open-guji.org/schema/entity/v0.2.json", "version": "1.1.0", "text_version": text_version,
            "book_id": BOOK, "volume": 2, "entities": [
                {"id": "e1", "type": "people", "text": "甲乙", "anchor": {"start": "3:2:2a", "end": "3:2:3a"},
                 "span": {"start_offset": 5, "end_offset": 7}},
                {"id": "e2", "type": "work", "text": "文", "anchor": {"start": "3:2:5", "end": "3:2:5"},
                 "span": {"start_offset": 9, "end_offset": 10}}]}


def index(text_version: str = "1.0.1") -> dict:
    return {"book_id": BOOK, "chapters": [{"n": 2, "file": "002", "char_file": "002.char.json", "cord_file": "002.cord.json",
                                           "text_version": text_version, "punct_file": "002.punct.json",
                                           "entity_file": "002.entity.json", "punct_version": "1.1.0",
                                           "entity_version": "1.1.0"}]}


def compact(obj, indent=0):
    """与 book-text ``original_version.dumps_compact`` 同口径（一格一行）。"""
    def flat(v):
        if isinstance(v, dict):
            return all(not isinstance(x, dict) and flat(x) for x in v.values())
        if isinstance(v, list):
            return all(not isinstance(x, dict) and flat(x) for x in v)
        return True
    pad, pad1 = "  " * indent, "  " * (indent + 1)
    if flat(obj) or not isinstance(obj, (dict, list)):
        return json.dumps(obj, ensure_ascii=False, separators=(", ", ": "))
    if isinstance(obj, dict):
        items = [f"{pad1}{json.dumps(k, ensure_ascii=False)}: {compact(v, indent + 1)}" for k, v in obj.items()]
        return "{\n" + ",\n".join(items) + "\n" + pad + "}" if items else "{}"
    items = [pad1 + compact(v, indent + 1) for v in obj]
    return "[\n" + ",\n".join(items) + "\n" + pad + "]" if items else "[]"


def make(root: Path, *, changes: str = CHANGES) -> Path:
    """在 root 下造一个 book-text 检出，返回版本目录。"""
    vd = root / ENTRY / "default"
    vd.mkdir(parents=True)
    (root / ENTRY / "manifest.json").write_text(json.dumps({"versions": [{"key": "default", "is_original": True}]}),
                                                encoding="utf-8")
    (vd / "002.char.json").write_text(compact(char()) + "\n", encoding="utf-8")
    (vd / "002.cord.json").write_text(compact(cord()) + "\n", encoding="utf-8")
    (vd / "002.punct.json").write_text(json.dumps(punct(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (vd / "002.entity.json").write_text(json.dumps(entity(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (vd / "index.json").write_text(json.dumps(index(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (vd / "CHANGES.md").write_text(changes, encoding="utf-8")
    return vd
