# -*- coding: utf-8 -*-
"""按形区分四对（强/強、却/卻、回/囘、并/幷，字形库 11 §〇）的逐例复核——**选样**这一半。

出审查卡是 `review-artifact` skill 的活（BODY/card()/自存那套壳），本脚本只管
「选哪些刻例、按什么口径抽样」——这一半跟真图无关，能在没有真库的地方测。

    GUJI_WORKSPACE=<书目录> PYTHONPATH=. python scripts/glyph_codepoint_review_select.py \
        --book <id> [--cap 40] --out cards.json

`cards.json` 是给下一步（真图 + review-artifact skill 拼页）的输入：每条
`{instance_id, pair, char, patch_png_b64}`。**云端只出这个 json，不发布页面**
——发布页面要真图，见任务书 §用户裁定「服务器执行步骤」。
"""

from __future__ import annotations

import argparse
import base64
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from glyph_codepoint_unify import _belongs_to_book  # noqa: E402

#: 按形区分四对（字形库 11 §〇 用户裁定，2026-09-27）。**不是**书级指定类
#: （别/內、内/內进 `BookSpec.codepoints`，不进这里）。
SHAPE_SPLIT_PAIRS: list[tuple[str, str]] = [("强", "強"), ("却", "卻"), ("回", "囘"), ("并", "幷")]


def collect_instances(conn: sqlite3.Connection, book: str,
                      pairs: list[tuple[str, str]] = SHAPE_SPLIT_PAIRS
                      ) -> dict[str, list[str]]:
    """本书库里这四对（两个码位都算）的全部刻例，按**字头**分组
    （分组单位是「字」，不是「对」——分层抽样要按字头分层，一对里两个字头
    数量往往悬殊，混在一起抽会把少数字头抽没）。"""
    chars = {c for p in pairs for c in p}
    out: dict[str, list[str]] = {c: [] for c in chars}
    rows = conn.execute(
        "SELECT instance_id, label FROM instances WHERE label IN ({})".format(
            ",".join("?" * len(chars))), tuple(chars)).fetchall()
    for iid, label in rows:
        if _belongs_to_book(iid, book):
            out[label].append(iid)
    return {c: sorted(ids) for c, ids in out.items()}


def stratified_sample(groups: dict[str, list], cap: int = 40) -> tuple[dict[str, list], dict[str, int]]:
    """按字头分层抽到总数 ≤ `cap`。组内**等距**取（跟 `glyph_codepoint_census.py::_sheets`
    同一口径：`step = len//quota`，覆盖面比随机取或掐头更均匀）。

    配额分配：总数不超 cap 时全收（不抽样）；超了按各组大小比例分配名额，
    四舍五入之后余量给最大的组吃掉——保证配额之和正好是 `cap`，每个非空组
    至少分到 1 个名额（`cap` 够分的前提下）。返回 `(抽到的, 每组剩下没抽的数)`。
    """
    total = sum(len(v) for v in groups.values())
    if total <= cap:
        return {c: list(v) for c, v in groups.items()}, {c: 0 for c in groups}
    nonempty = [c for c, v in groups.items() if v]
    quota = {c: max(1, round(len(groups[c]) / total * cap)) for c in nonempty}
    # 四舍五入可能让总数偏离 cap 一两个，用最大的组吃掉差额（不会把哪个组吃成负数：
    # cap 至少等于非空组数时，每组保底 1 的余量足够吸收 ±(组数) 的偏差）。
    diff = cap - sum(quota.values())
    if diff and nonempty:
        biggest = max(nonempty, key=lambda c: len(groups[c]))
        quota[biggest] = max(1, quota[biggest] + diff)
    sample: dict[str, list] = {}
    leftover: dict[str, int] = {}
    for c, ids in groups.items():
        q = min(quota.get(c, 0), len(ids))
        step = max(1, len(ids) // q) if q else 1
        picked = ids[::step][:q] if q else []
        sample[c] = picked
        leftover[c] = len(ids) - len(picked)
    return sample, leftover


def to_card(instance_id: str, char: str, patch_png: bytes,
           pairs: list[tuple[str, str]] = SHAPE_SPLIT_PAIRS) -> dict:
    pair = next((f"{a}{b}" for a, b in pairs if char in (a, b)), char)
    return {"instance_id": instance_id, "pair": pair, "char": char,
           "patch_png_b64": base64.b64encode(patch_png).decode("ascii")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--book", required=True)
    ap.add_argument("--cap", type=int, default=40)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    from open_guji_cv.core.workspace import glyph_db_path

    conn = sqlite3.connect(f"file:{glyph_db_path()}?mode=ro", uri=True)
    try:
        groups = collect_instances(conn, a.book)
        sample, leftover = stratified_sample(groups, a.cap)
        cards = []
        for char, ids in sample.items():
            for iid in ids:
                png = conn.execute("SELECT patch_png FROM instances WHERE instance_id=?",
                                   (iid,)).fetchone()[0]
                cards.append(to_card(iid, char, bytes(png)))
    finally:
        conn.close()

    total_have = sum(len(v) for v in groups.values())
    print(f"{a.book}: 库里共 {total_have} 例，抽 {len(cards)} 张（cap={a.cap}）")
    for char, n in leftover.items():
        if n:
            print(f"  {char}: 剩 {n} 例未抽（共 {len(groups[char])}）")
    a.out.write_text(json.dumps({"book": a.book, "cards": cards, "leftover": leftover,
                                 "n_total": total_have}, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
