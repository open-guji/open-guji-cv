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

复审格（M10 复盘，10-23）：`--recheck <文件>` 把指定格放回单上（不论产物放没放行、人裁过没有），每行
`格号<TAB>说明<TAB>旧人裁事件 id<TAB>旧人裁的字`（后三列可省；`#` 起注释；可带「册:」前缀）。这些格带
`recheck: true`、`note`（网站卡片头上常显）、`prior`（{c, id, ts}，网站提示「这次提交的选择会替代它」）；
pending_route 不扣它们。格号在现行产物里没有的（多半重切过）不硬放，记进 `<out>/recheck_missing.tsv`。
复审格可能已放行、卡片里不一定有字段，找不到卡片就只带格号和说明，不退出。

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
#: 产物所依页表的 rev（产物目录 `_source.json`，`products.store.ProductStore.source_rev` 同口径）；产物没带来历就不写。
KEY_SOURCE_REV = "source_rev"

#: 本仓根（scripts/zhengli/ 上两级）：--cv-root 的缺省值（GUJI-652 迁入后）。
CV_ROOT = Path(__file__).resolve().parents[2]


def products_source_rev(products: Path, book: str) -> int | None:
    """本册产物出自哪一版页表（`<产物根>/<册>/_source.json` 的 rev）；没有、读不了 → None。"""
    try:
        rev = json.loads((Path(products) / book / "_source.json").read_text(encoding="utf-8")).get("rev")
        return None if rev is None else int(rev)
    except (OSError, ValueError, TypeError, AttributeError):
        return None


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


def all_cells(seed_dir: Path, book: str) -> set[str]:
    """现行产物里的全部格号（放行、待审、排除名单都算）。"""
    out: set[str] = set()
    for f in sorted(seed_dir.glob("p*.json")):
        for col in json.loads(f.read_text(encoding="utf-8"))["seed_admit"]["columns"]:
            for ch in col["chars"]:
                out.add(ch["id"].split(":", 1)[1] if ch["id"].startswith(f"{book}:") else ch["id"])
    return out


def read_recheck(path: Path, book: str) -> dict[str, dict]:
    """复审清单：`格号[\t说明[\t旧人裁 id[\t旧人裁的字[\t旧人裁时间]]]]`，一行一格；表头行（格位／cell 开头）、空行、# 注释跳过。"""
    out: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = [x.strip() for x in line.split("\t")]
        cell = parts[0].removeprefix(f"{book}:")
        if cell in ("格位", "格号", "cell"):
            continue
        note, pid, pc, pts = (parts[1:] + ["", "", "", ""])[:4]
        info: dict = {}
        if note:
            info["note"] = note
        if pc:
            info["prior"] = {"c": pc, **({"id": pid} if pid else {}), **({"ts": pts} if pts else {})}
        out.setdefault(cell, {}).update(info)
    return out


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
    ap.add_argument("--recheck", type=Path, default=None,
                    help="复审清单（格号<TAB>说明<TAB>旧人裁 id<TAB>旧人裁的字）：这些格不论放没放行都放回单上")
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
    recheck: dict[str, dict] = {}
    rc_missing: list[str] = []
    if a.recheck:
        recheck = read_recheck(a.recheck, a.book)
        have_all = all_cells(seed_dir, a.book)
        by_cell = {c[KEY_CELL]: c for c in cells}
        for cell in sorted(recheck, key=cell_key):
            if cell not in have_all:
                rc_missing.append(cell)
                continue
            if cell not in by_cell:
                by_cell[cell] = {KEY_CELL: cell, KEY_STATUS: STATUS_PENDING}
                cells.append(by_cell[cell])
        cells.sort(key=lambda c: cell_key(c[KEY_CELL]))
        note += f"；复审 {len(recheck) - len(rc_missing)} 格（现行切分里没有的 {len(rc_missing)} 格不放）"
    if a.cards:
        sys.path.insert(0, str(a.cv_root))
        from open_guji_cv.review.proof_fields import pending_fields
        by_id = {c["id"]: c for c in json.loads(a.cards.read_text(encoding="utf-8"))}
        lost = [c[KEY_CELL] for c in cells if f"{a.book}:{c[KEY_CELL]}" not in by_id and c[KEY_CELL] not in recheck]
        if lost:
            sys.exit(f"{len(lost)} 个待审格在卡片文件里找不到（如 {lost[:5]}）：卡片口径不对？")
        for c in cells:
            if f"{a.book}:{c[KEY_CELL]}" in by_id:
                c.update(pending_fields(by_id[f"{a.book}:{c[KEY_CELL]}"]))
    for c in cells:                      # 复审字段最后写：卡片里的同名字段不能盖掉它
        if c[KEY_CELL] in recheck:
            c.update({"recheck": True, **recheck[c[KEY_CELL]]})
    src_rev = products_source_rev(a.products, a.book)
    doc = {
        KEY_REV: a.rev,
        KEY_CV_VERSION: a.cv_version,
        KEY_CV_COMMIT: a.cv_commit,
        # 换图源（GUJI-748）：单子记下格号是哪一版页表上的，换单门据此认出换源前的旧单；产物没带来历就不写
        **({KEY_SOURCE_REV: src_rev} if src_rev is not None else {}),
        KEY_CELLS: cells,
    }
    a.out.mkdir(parents=True, exist_ok=True)
    path = a.out / f"{a.chapter}.pending.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if a.recheck:
        (a.out / "recheck_missing.tsv").write_text(
            "格位\t说明\n" + "".join(f"{c}\t{recheck[c].get('note', '')}\n" for c in rc_missing), encoding="utf-8")
    print(f"{path}: {len(cells)} 格（{note}）")


if __name__ == "__main__":
    main()
