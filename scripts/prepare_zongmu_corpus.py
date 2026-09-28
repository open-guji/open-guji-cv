# -*- coding: utf-8 -*-
"""四庫光盘版整理本语料 —— 剔除现代影印前言，出一份「正文起点」干净版。

背景（overview#123）：`corpus/zongmu_wenyuange_wikisource.txt`（书级配置里标
`quality: best`、`label: 四库光盘版`）开头混着一篇臺灣商務印書館 1983 年
（民國七十二年）写的《影印文淵閣四庫全書緣起》等影印说明，不属于武英殿刻本
正文，却参与了卷首几页的 `align_ref` 锚定与字频统计（`歷` 24 处里 22 处出在
这里，见 overview#27 的 `scripts/experiments/ji_li_codepoint_audit/`）。

**不改原始语料文件**：本脚本只读 `zongmu_wenyuange_wikisource.txt`，另写一份
`zongmu_wenyuange_wikisource.body.txt`（同目录）。书级配置（`books/volNN.yaml`
的 `references[0].file`）改指到这份新文件，`align_ref`/`context_decide`/
`rare_candidates`/`font_candidates.book_charset`/`report.witness` 等**所有**
消费者都通过 `book_corpus()` 这一个进口读语料（见 `steps/align_ref.py`
`book_corpus()` 模块头），换文件名即可让它们全部生效，不用逐个改代码——
这是选「出干净版本」而不是「yaml 加排除区间字段」的理由：后者要在至少六个
读语料的模块里分别接一道过滤，前言这类整段裁切用「另存一份」代价更小、
覆盖面更确定。

**正文起点判据**：与 #27 审计脚本同一条精确标题行正则——`^卷[首N]` 这种粗糙
判据会把前言/目录里逐卷罗列的引用行也误判成本书标题；`^欽定四庫全書總目卷
[首一二三四五六七八九十百]+$`（整行匹配）才是真正的卷端题。取全文第一处
命中之前的所有行为前言，命中行本身与之后一律原样保留（**含空白行、含每一
个字节**——不重新分段、不去标点、不改任何标记）。

用法：
    PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/bin/python scripts/prepare_zongmu_corpus.py

不传参数：默认处理 `corpus_path()` 解析出的 `zongmu_wenyuange_wikisource.txt`
（走 `GUJI_WORKSPACE`，与其余管线同一套路径解析，不会读错文件）。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from open_guji_cv.core.workspace import corpus_path  # noqa: E402

RAW_NAME = "zongmu_wenyuange_wikisource.txt"
BODY_NAME = "zongmu_wenyuange_wikisource.body.txt"

#: 与 overview#27 审计脚本 `classify_positions.py` 同一条正则：真正的卷端题
#: 整行匹配「欽定四庫全書總目卷N」，不匹配前言/目录里散落的「卷一」「卷二」引用。
HEAD_RE = re.compile(r"^欽定四庫全書總目(卷[首一二三四五六七八九十百]+)$")


def find_body_start(lines: list[str]) -> int:
    """返回正文第一行在 `lines`（0-indexed）里的下标；找不到就报错，不要悄悄退化。"""
    for i, ln in enumerate(lines):
        if HEAD_RE.match(ln.rstrip("\n")):
            return i
    raise SystemExit("没找到任何 `欽定四庫全書總目卷…` 整行标题，语料格式可能变了，不敢裁")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", default=None, help="覆盖默认输入路径（调试用）")
    ap.add_argument("--out", default=None, help="覆盖默认输出路径（调试用）")
    args = ap.parse_args()

    raw_path = Path(args.raw) if args.raw else corpus_path(RAW_NAME)
    out_path = Path(args.out) if args.out else raw_path.with_name(BODY_NAME)

    text = raw_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    start = find_body_start(lines)

    preface = lines[:start]
    body = lines[start:]

    preface_chars = sum(len(l) for l in preface)
    body_chars = sum(len(l) for l in body)

    out_path.write_text("".join(body), encoding="utf-8")

    print(f"输入：{raw_path}（{len(lines)} 行 / {len(text)} 字符）")
    print(f"前言（丢弃）：第 1–{start} 行 / {preface_chars} 字符")
    print(f"  首行：{preface[0].rstrip()!r}" if preface else "  （无前言）")
    print(f"  末行：{preface[-1].rstrip()!r}" if preface else "")
    print(f"正文（保留）：第 {start + 1}–{len(lines)} 行 / {body_chars} 字符")
    print(f"  首行：{body[0].rstrip()!r}")
    print(f"输出：{out_path}")

    # 自证：正文部分必须与原文件逐字节相同（只是掐头，不是重新生成）。
    assert text.encode("utf-8")[len("".join(preface).encode("utf-8")):] == "".join(body).encode("utf-8")


if __name__ == "__main__":
    main()
