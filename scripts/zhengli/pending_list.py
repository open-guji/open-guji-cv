#!/usr/bin/env python3
"""NNN.pending.json 最简版（GUJI-550，设计 GUJI-543 §6.2）。

来源：ai-team `team/整理/GUJI-543/pending_list.py`，2026-10-20 迁入 cv `scripts/zhengli/`（GUJI-652）。
迁入适配：`--cv-root` 改为可选，缺省用本仓根（本文件上两级）；仍可显式给别的 cv 仓（兼容旧用法）；main() 加可选 argv 参数（便于测试）。
用途：从 products 快照的 seed_admit 列出待审格，写成 book-text 要的 `<章>.pending.json`（可并入 guji-proof 0.2 字段）。

只读 products 快照里的 seed_admit 产物，列出待审格；不改 cv 导出器，不写 products。
待审格 = seed_admit 里 admit=false 且 doubts 不含 'excluded' 的格
（与产物页头 n_review 一致；排除名单命中的格不出审查卡）。

审卡队列口径（Eliot，GUJI-364 13220）：close-check 的审卡队列（cards(only=review, skip_decided)）
比产物未放行格多出「排除名单里带无锚老人裁字、放回待审」的格；0.1.0 的 pending 须按审卡队列列。
给 --review-queue <文件，一行一个格号，可带 <册>: 前缀> 即按该队列出，并校验产物 60 格都在其中。

用法：
    python3 scripts/zhengli/pending_list.py --products <products 根> --book vol01 --chapter 001 \
        --rev vol01-r0 --cv-commit 9587e67c [--cv-version v0.x.y] \
        [--review-queue <审卡队列格号文件>] [--cards <卡片JSON> [--cv-root <open-guji-cv 根，缺省本仓>]] --out <目录>
    写进中心库（待审单与公众意见走中心库，块 B）：把 --out 换成 --ws <中心库工作区 id> --text-id <book-text 条目 id>，
    写到 $GUJI_DATA_HOME/main/<ws>/feedback/lists/proofing/<text-id>/<章>.pending.json，再 `guji db sync -w <工作区>`。

GUJI-557：给了 --cards（cards(book, pages="all", only="all", skip_decided=False, gate_cut=False, cls="*")
的 cards 列表存成 JSON），每格并入 guji-proof 0.2 字段（cv `review/proof_fields.pending_fields`，
只加字段，不动 cell／review）；待审格在卡片里找不到就退出。不给就和 0.1 逐字节一样。
相似字 `alt`（10-19）：卡片 JSON 用 cv `guji audit alt <册> -w <工作区> [--fetch-zi]` 出（它自己现算全册卡、
挂好 alt，写 reports/<册>/<册>.cards.alt.json），把这个文件当 --cards 给本脚本即可；字形图再跑同目录 alt_build.py。

字段名集中在下面常量。cv_version 为字符串（cv-vX.Y.Z）或 null；rev 须形如 <册>-r<n>。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# 字段名以 book-text#148（fca7df10）F-OV-07 为准
KEY_REV, KEY_CV_VERSION, KEY_CV_COMMIT, KEY_CELLS = "rev", "cv_version", "cv_commit", "cells"
KEY_CELL, KEY_STATUS = "cell", "review"  # book-text F-OV-07（#148）
STATUS_PENDING = "pending"

#: 本仓根（scripts/zhengli/ 上两级）：--cv-root 的缺省值（GUJI-652 迁入后）。
CV_ROOT = Path(__file__).resolve().parents[2]


def pending_cells(seed_dir: Path, book: str) -> tuple[list[dict], int]:
    """返回 (待审格列表, 产物页头 n_review 之和)。格号 a = 页:列:格序[sub]。"""
    cells: list[dict] = []
    n_review = 0
    for f in sorted(seed_dir.glob("p*.json")):
        s = json.loads(f.read_text(encoding="utf-8"))["seed_admit"]
        n_review += s.get("n_review", 0)
        for col in s["columns"]:
            for ch in col["chars"]:
                if ch["admit"] or "excluded" in ch.get("doubts", []):
                    continue
                prefix = f"{book}:"
                cid = ch["id"]
                if not cid.startswith(prefix):
                    sys.exit(f"格号 {cid} 不以 {prefix} 开头")
                cells.append({KEY_CELL: cid[len(prefix):], KEY_STATUS: STATUS_PENDING})
    return cells, n_review


def read_queue(path: Path, book: str) -> list[str]:
    """读审卡队列格号（去 <册>: 前缀、空行与 # 注释，去重保序）。"""
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith(f"{book}:"):
            line = line[len(book) + 1:]
        if line not in out:
            out.append(line)
    return out


def cell_key(cid: str) -> list:
    return [(0, int(x), "") if x.isdigit() else (1, 0, x) for x in re.split(r"[:]", cid)]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--products", required=True, type=Path)
    ap.add_argument("--book", required=True)
    ap.add_argument("--chapter", required=True)
    ap.add_argument("--rev", required=True, help="<册>-r<n>，如 vol01-r0")
    ap.add_argument("--cv-commit", required=True)
    ap.add_argument("--cv-version", default=None, help="首个正式 tag 前可不填（null）")
    ap.add_argument("--review-queue", type=Path, default=None,
                    help="close-check 审卡队列格号文件（一行一个）；给了就按它出")
    ap.add_argument("--cards", type=Path, default=None, help="cards(cls='*') 的卡片列表 JSON；给了就并入 0.2 字段")
    ap.add_argument("--cv-root", type=Path, default=None, help="open-guji-cv 根目录（--cards 时用来 import proof_fields；缺省本仓根）")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--ws", default=None, help="中心库工作区 id（如 siku-zongmu）；与 --text-id 一起代替 --out")
    ap.add_argument("--text-id", default=None, help="book-text 条目 id（如 96mid1ogzk）")
    ap.add_argument("--branch", default="main", help="数据目录分支（默认 main）")
    a = ap.parse_args(argv)
    if bool(a.ws) != bool(a.text_id):
        sys.exit("--ws 与 --text-id 要一起给")
    if bool(a.out) == bool(a.ws):
        sys.exit("--out 与 --ws/--text-id 二选一")
    if a.ws:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", a.ws) or not re.fullmatch(r"[0-9a-z]{4,24}", a.text_id):
            sys.exit("--ws 或 --text-id 格式不对")
        home = Path(os.environ.get("GUJI_DATA_HOME") or Path.home() / ".guji-data")
        a.out = home / a.branch / a.ws / "feedback" / "lists" / "proofing" / a.text_id
    if a.cv_root and not a.cards:
        sys.exit("--cv-root 只在给了 --cards 时有用")
    if a.cards and not a.cv_root:
        a.cv_root = CV_ROOT

    seed_dir = a.products / a.book / "seed_admit"
    if not seed_dir.is_dir():
        sys.exit(f"没有 {seed_dir}")
    # book-text 的 F-OV-07 要求 rev 形如 <章号NNN>-r<n>（如 001-r1）；cv 侧快照分支叫 <册>-r<n>（如 vol01-r1），两种都收
    if not re.fullmatch(r"(?:" + re.escape(a.book) + r"|" + re.escape(a.chapter) + r")-r\d+", a.rev):
        sys.exit(f"rev={a.rev!r} 应形如 {a.chapter}-r<n>（book-text F-OV-07）或 {a.book}-r<n>")
    cells, n_review = pending_cells(seed_dir, a.book)
    if len(cells) != n_review:
        sys.exit(f"格数不符：脚本 {len(cells)}，seed_admit 页头 n_review 合计 {n_review}")
    note = "= seed_admit n_review"
    if a.review_queue:
        queue = read_queue(a.review_queue, a.book)
        have = {c[KEY_CELL] for c in cells}
        missing = sorted(have - set(queue), key=cell_key)
        if missing:
            sys.exit(f"产物未放行格不在审卡队列里（{len(missing)} 格，如 {missing[:5]}）：队列文件口径不对？")
        extra = sorted(set(queue) - have, key=cell_key)
        cells += [{KEY_CELL: c, KEY_STATUS: STATUS_PENDING} for c in extra]
        note = f"= 产物未放行 {len(have)} ＋ 审卡队列多出 {len(extra)}（排除名单放回待审）"
    if a.cards:
        sys.path.insert(0, str(a.cv_root))
        from open_guji_cv.review.proof_fields import pending_fields
        by_id = {c["id"]: c for c in json.loads(a.cards.read_text(encoding="utf-8"))}
        lost = [c[KEY_CELL] for c in cells if f"{a.book}:{c[KEY_CELL]}" not in by_id]
        if lost:
            sys.exit(f"{len(lost)} 个待审格在卡片文件里找不到（如 {lost[:5]}）：卡片口径不对？")
        for c in cells:
            c.update(pending_fields(by_id[f"{a.book}:{c[KEY_CELL]}"]))
    doc = {
        KEY_REV: a.rev,
        KEY_CV_VERSION: a.cv_version,
        KEY_CV_COMMIT: a.cv_commit,
        KEY_CELLS: cells,
    }
    a.out.mkdir(parents=True, exist_ok=True)
    path = a.out / f"{a.chapter}.pending.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{path}: {len(cells)} 格（{note}）")


if __name__ == "__main__":
    main()
