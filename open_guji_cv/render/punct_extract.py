# -*- coding: utf-8 -*-
"""古籍标点与分段独立外挂抽取及合成工具。

核心职责：
1. 提取（Extract）：对齐底本纯文字流与大模型带标点/分段的输出，剥离出独立的 `*.punct.json`；
2. 合成（Apply / Synthesize）：将 `*.punct.json` 注入底本字流，无损还原出带标点、分段的 Level 3 Markdown。
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Any

# 常用句读点号（不含实体书名号《》，书名号由 entity 模块作为实体边界独立处理）
PUNCT_CHARS = set("，。、；：？！「」『』（）…—·,.;:?!\"'“”‘’")
OPENER_MARKS = set("「『（“‘")
CLOSER_MARKS = set("」』）”’，。、；：？！…—·,.;:?!")

_TOK = re.compile(
    r"(?P<mark><!--\s*p\d+\s*-->|\x00p\d+\x00)"
    r"|<(?P<jz>[^<>]*)>"
    r"|:jz\[(?P<dj>[^\]]*)\](?P<djattr>\{[^}]*\})?"
    r"|(?P<gap>\[\[[^\]]*\]\])"
    r"|(?P<box>□(?:\{[^}]*\})?)"
    r"|(?P<ch>.)", re.S)


def tokenize(text: str, _inner: bool = False) -> list[tuple[str, str]]:
    """将文本切分为 [(原文片段, 实体文字/空串)]。
    页码标记 <!-- pN --> 的实体文字为空串，不计入字符偏移。
    """
    out: list[tuple[str, str]] = []
    for m in _TOK.finditer(text):
        if m.group("mark") is not None:
            out.append((m.group(0), ""))
        elif m.group("jz") is not None and not _inner:
            out.append(("<", ""))
            out += tokenize(m.group("jz"), True)
            out.append((">", ""))
        elif m.group("dj") is not None and not _inner:
            out.append((":jz[", ""))
            out += tokenize(m.group("dj"), True)
            out.append(("]" + (m.group("djattr") or ""), ""))
        elif m.group("gap") is not None or m.group("box") is not None:
            out.append((m.group(0), "□"))
        else:
            ch = m.group(0)
            # 换行与空白在底本字符流中不计入实体字偏移
            if ch.isspace():
                out.append((ch, ""))
            else:
                out.append((ch, ch))
    return out


@dataclass
class PunctAnnotation:
    mark: str
    kind: str = "point"             # "point" (句逗) | "break" (分段 \n\n) | "range" (书名号/引号)
    pos: str = "after"              # "after" | "before"
    char_offset: int = 0            # 纯文本字流中的绝对偏移下标
    pre_char: str = ""              # 锚点前一个字（防漂移校验）
    anchor: str | None = None       # 拓扑键，例如 "3:3:1:10" 或 "1:5:2:8"
    confidence: float = 1.0
    source: str = "auto"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "mark": self.mark,
            "kind": self.kind,
            "pos": self.pos,
            "char_offset": self.char_offset,
            "pre_char": self.pre_char,
        }
        if self.anchor:
            d["anchor"] = self.anchor
        if self.confidence < 1.0:
            d["confidence"] = round(self.confidence, 4)
        if self.source:
            d["source"] = self.source
        return d


def extract_punctuations(plain_text: str, annotated_text: str,
                         source: str = "llm",
                         max_bad_ratio: float = 0.05) -> tuple[list[PunctAnnotation], int]:
    """比对底本纯文本与带标点/换行的模型输出，抽取出 PunctAnnotation 列表与不匹配字数。

    `plain_text`：不含标点和换行的纯文字序列。
    `annotated_text`：LLM 生成的带标点及换行符（如 \\n 或 \\n\\n）的文本。
    """
    # 1. 规范化换行：将连续一个或多个换行符规范化为双换行 '\n\n'
    norm_annotated = re.sub(r"\r\n|\r|\n+", "\n\n", annotated_text.strip())

    stripped_chars: list[str] = []
    # 记录在 stripped_chars 下标之前插入的符号列表：idx -> [(mark, kind)]
    inserted_before: dict[int, list[tuple[str, str]]] = {}

    idx = 0
    while idx < len(norm_annotated):
        if norm_annotated[idx:idx + 2] == "\n\n":
            pos = len(stripped_chars)
            inserted_before.setdefault(pos, []).append(("\n\n", "break"))
            idx += 2
        elif norm_annotated[idx] in PUNCT_CHARS:
            pos = len(stripped_chars)
            inserted_before.setdefault(pos, []).append((norm_annotated[idx], "point"))
            idx += 1
        elif norm_annotated[idx] in "<>":
            # 夹注起止符，属于排版记号，不作为汉字比对
            idx += 1
        elif norm_annotated[idx].isspace():
            # 普通空格忽略
            idx += 1
        else:
            stripped_chars.append(norm_annotated[idx])
            idx += 1

    extracted_plain = "".join(stripped_chars)

    # 2. SequenceMatcher 对齐
    sm = difflib.SequenceMatcher(None, plain_text, extracted_plain, autojunk=False)
    qmap: dict[int, int] = {}
    bad = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                qmap[j1 + k] = i1 + k
        else:
            bad += max(i2 - i1, j2 - j1)

    # 3. 映射标点到 plain_text 字符下标
    annotations: list[PunctAnnotation] = []
    keys = sorted(qmap)

    for q, marks in sorted(inserted_before.items()):
        # 确定在 plain_text 中的锚点字下标
        if q == 0:
            # 文本开头的起首标点（如开引号）
            target_idx = 0
            pos = "before"
            pre_ch = plain_text[0] if plain_text else ""
        else:
            prev_q = q - 1
            if prev_q in qmap:
                target_idx = qmap[prev_q]
            else:
                # 寻找最近已匹配的锚点
                prev_matched = [k for k in keys if k <= prev_q]
                target_idx = qmap[prev_matched[-1]] if prev_matched else 0
            pos = "after"
            pre_ch = plain_text[target_idx] if target_idx < len(plain_text) else ""

        for mark, kind in marks:
            annotations.append(PunctAnnotation(
                mark=mark,
                kind=kind,
                pos=pos,
                char_offset=target_idx,
                pre_char=pre_ch,
                source=source
            ))

    return annotations, bad


def apply_punctuations(plain_tokens: list[tuple[str, str]],
                       annotations: list[PunctAnnotation],
                       include_breaks: bool = True) -> str:
    """将独立标点/分段注释注入底本 token 序列，复原富文本。

    `plain_tokens`：[(原始片段, 实体文字/空串)]，由 tokenize() 得到。
    `include_breaks`：True 时应用自然段分段符（输出自然段）；False 时忽略分段符（保持原刻分行或连续行）。
    """
    # 按照 char_offset 组织标点
    offset_map: dict[int, list[PunctAnnotation]] = {}
    for ann in annotations:
        if ann.kind == "break" and not include_breaks:
            continue
        offset_map.setdefault(ann.char_offset, []).append(ann)

    out: list[str] = []
    pi = 0
    pending_marks: list[str] = []

    for orig, ch in plain_tokens:
        if ch == "":
            # 空白符或页码标记
            if orig.isspace() and include_breaks:
                # 如果要应用分段符，底本中的换行空白不重复输出
                continue
            pending_marks.append(orig)
            continue

        # 处理在此字之前的起首标点 (pos == "before")
        if pi in offset_map:
            for ann in offset_map[pi]:
                if ann.pos == "before":
                    out.append(ann.mark)

        out.extend(pending_marks)
        pending_marks.clear()
        out.append(orig)

        # 处理在此字之后的标点/分段符 (pos == "after")
        if pi in offset_map:
            for ann in offset_map[pi]:
                if ann.pos == "after":
                    out.append(ann.mark)
        pi += 1

    out.extend(pending_marks)
    return "".join(out)


def build_punct_json(book_id: str, title: str,
                     annotations: list[PunctAnnotation],
                     creator: str = "qwen-plus") -> dict[str, Any]:
    """生成符合 guji-punct v0.1 规范的完整 JSON 对象。"""
    points = sum(1 for a in annotations if a.kind == "point")
    breaks = sum(1 for a in annotations if a.kind == "break")
    periods = sum(1 for a in annotations if a.mark == "。")
    commas = sum(1 for a in annotations if a.mark == "，")

    return {
        "$schema": "https://open-guji.org/schema/punct/v0.1.json",
        "version": "0.1.0",
        "book_id": book_id,
        "metadata": {
            "title": title,
            "creator": creator,
            "base_edition": "original",
            "description": "基于 original 底本自动生成独立外挂标点与分段，正文字符保持严格解耦。"
        },
        "stats": {
            "total_annotations": len(annotations),
            "points": points,
            "paragraph_breaks": breaks,
            "periods": periods,
            "commas": commas
        },
        "punctuations": [a.to_dict() for a in annotations]
    }
