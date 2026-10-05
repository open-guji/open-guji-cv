# -*- coding: utf-8 -*-
"""命名实体抽取、book-index 知识库匹配与富文本 Markdown 合成引擎。

核心能力：
1. 提取（Extract）：从大模型标注文本（含《书名号》与/专名号/）中抽取实体及其在底本中的起止格位；
2. 匹配（Match）：在 book-index 知识库（Work / Entity / Book）中检索对齐，补充 ID 与超链接；
3. 合成（Synthesize）：联合底本 lines.md、punct.json 与 entity.json，生成带超链接的 Level 3 Rich Markdown。
"""
from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .punct_extract import tokenize, PunctAnnotation


@dataclass
class EntityAnnotation:
    id: str
    type: str                       # "work" | "people" | "place" | "office" | "dynasty" | "other"
    text: str                       # 实体原文
    anchor_start: str               # 起始格位 <页>:<列>:<格>[子列]
    anchor_end: str                 # 结束格位
    start_offset: int = 0           # 纯文本字符偏移（可选缓存）
    end_offset: int = 0
    target_status: str = "new_candidate"  # "matched" | "new_candidate" | "external"
    target_id: str | None = None
    target_name: str | None = None
    target_href: str | None = None
    confidence: float = 1.0
    source: str = "auto"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "text": self.text,
            "anchor": {
                "start": self.anchor_start,
                "end": self.anchor_end
            },
            "span": {
                "start_offset": self.start_offset,
                "end_offset": self.end_offset
            },
            "target": {
                "status": self.target_status
            }
        }
        if self.target_id:
            d["target"]["entity_id"] = self.target_id
        if self.target_name:
            d["target"]["canonical_name"] = self.target_name
        if self.target_href:
            d["target"]["href"] = self.target_href
        if self.confidence < 1.0:
            d["confidence"] = round(self.confidence, 4)
        if self.source:
            d["source"] = self.source
        return d


class BookIndexMatcher:
    """轻量级 book-index 实体匹配器。"""

    def __init__(self, book_index_root: str | Path = "d:/workspace/book-index"):
        self.root = Path(book_index_root)
        self.works: dict[str, str] = {}    # title -> work_id
        self.people: dict[str, str] = {}   # name -> entity_id
        self._loaded = False

    def load_index(self, max_records: int = 2000) -> None:
        if self._loaded or not self.root.exists():
            return

        import os
        # 快速扫描 Work
        work_dir = self.root / "Work"
        if work_dir.exists():
            w_count = 0
            for r, _, files in os.walk(work_dir):
                for f in files:
                    if f.endswith(".json"):
                        try:
                            with open(os.path.join(r, f), "r", encoding="utf-8") as fp:
                                data = json.load(fp)
                            title = data.get("title")
                            wid = data.get("id")
                            if title and wid:
                                self.works[title] = wid
                                w_count += 1
                        except Exception:
                            pass
                    if w_count >= max_records:
                        break
                if w_count >= max_records:
                    break

        # 快速扫描 Entity (people)
        entity_dir = self.root / "Entity"
        if entity_dir.exists():
            p_count = 0
            for r, _, files in os.walk(entity_dir):
                for f in files:
                    if f.endswith(".json"):
                        try:
                            with open(os.path.join(r, f), "r", encoding="utf-8") as fp:
                                data = json.load(fp)
                            name = data.get("primary_name")
                            eid = data.get("id")
                            if name and eid:
                                self.people[name] = eid
                                p_count += 1
                        except Exception:
                            pass
                    if p_count >= max_records:
                        break
                if p_count >= max_records:
                    break

        self._loaded = True

    def match(self, ent_type: str, text: str) -> dict[str, Any]:
        """根据实体类型与文本匹配知识库。"""
        if not self._loaded:
            self.load_index()

        if ent_type == "work":
            # 优先精确匹配书名
            if text in self.works:
                wid = self.works[text]
                return {
                    "status": "matched",
                    "entity_type": "work",
                    "entity_id": wid,
                    "canonical_name": text,
                    "href": f"book-index://Work/{wid}"
                }
        elif ent_type == "people":
            # 优先精确匹配人名
            if text in self.people:
                eid = self.people[text]
                return {
                    "status": "matched",
                    "entity_type": "people",
                    "entity_id": eid,
                    "canonical_name": text,
                    "href": f"book-index://Entity/{eid}"
                }

        # 默认待新建候选实体
        return {
            "status": "new_candidate",
            "canonical_name": text
        }


def extract_entities_from_annotated(plain_chars: str,
                                    annotated_text: str,
                                    char_to_anchor: dict[int, str] | None = None,
                                    matcher: BookIndexMatcher | None = None,
                                    source: str = "llm:qwen-plus") -> list[EntityAnnotation]:
    """从大模型生成的标记文本中提取书名号《…》与专名号/…/，并匹配实体库。"""
    # 匹配 《书名》 以及 /专名/
    ent_regex = re.compile(r"《(?P<work>[^》]+)》|/(?P<zm>[^/]+)/")

    # 1. 记录 annotated_text 中每个字符对应的纯字下标
    # 先剥离非实体标记，构建字符映射
    clean_annotated = []
    char_map: list[int] = []  # annotated_text 字符下标 -> clean_annotated 纯字下标
    i = 0
    while i < len(annotated_text):
        c = annotated_text[i]
        if c in "《》/":
            char_map.append(len(clean_annotated))
        elif c in "\r\n\t " or c in "，。、；：？！「」『』（）…—·":
            char_map.append(len(clean_annotated))
        elif c in "<>":
            char_map.append(len(clean_annotated))
        else:
            char_map.append(len(clean_annotated))
            clean_annotated.append(c)
        i += 1

    extracted_clean = "".join(clean_annotated)

    # 2. 与底本纯汉字 SequenceMatcher 对齐
    sm = difflib.SequenceMatcher(None, plain_chars, extracted_clean, autojunk=False)
    qmap: dict[int, int] = {}
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                qmap[j1 + k] = i1 + k

    # 3. 抽取实体区间
    entities: list[EntityAnnotation] = []
    ent_count = 0

    for m in ent_regex.finditer(annotated_text):
        ent_count += 1
        is_work = m.group("work") is not None
        ent_type = "work" if is_work else "people"  # 专名默认先设为 people，后续由规则或 LLM 细分
        raw_text = m.group("work") if is_work else m.group("zm")

        # 计算实体内容在 clean_annotated 中的起止纯字下标
        content_start_char_idx = m.start(1 if is_work else 2)
        content_end_char_idx = m.end(1 if is_work else 2) - 1

        clean_start = char_map[content_start_char_idx]
        clean_end = char_map[content_end_char_idx]

        # 映射回底本 plain_chars 的 offset
        p_start = qmap.get(clean_start, 0)
        p_end = qmap.get(clean_end, p_start + len(raw_text) - 1)

        # 获取起止物理格位
        start_anc = char_to_anchor.get(p_start, f"1:1:{p_start + 1}") if char_to_anchor else f"1:1:{p_start + 1}"
        end_anc = char_to_anchor.get(p_end, f"1:1:{p_end + 1}") if char_to_anchor else f"1:1:{p_end + 1}"

        # 匹配知识图谱
        tgt = matcher.match(ent_type, raw_text) if matcher else {"status": "new_candidate", "canonical_name": raw_text}

        entities.append(EntityAnnotation(
            id=f"e{ent_count:04d}",
            type=ent_type,
            text=raw_text,
            anchor_start=start_anc,
            anchor_end=end_anc,
            start_offset=p_start,
            end_offset=p_end + 1,
            target_status=tgt.get("status", "new_candidate"),
            target_id=tgt.get("entity_id"),
            target_name=tgt.get("canonical_name", raw_text),
            target_href=tgt.get("href"),
            source=source
        ))

    return entities


def apply_entities_and_punctuations_to_markdown(
        plain_tokens: list[tuple[str, str]],
        punctuations: list[PunctAnnotation],
        entities: list[EntityAnnotation],
        include_breaks: bool = True) -> str:
    """三合一流式注入渲染：同时注入标点、分段与实体超链接，输出 Level 3 富文本 Markdown。"""
    # 建立 offset 索引
    punct_map: dict[int, list[PunctAnnotation]] = {}
    for p in punctuations:
        if p.kind == "break" and not include_breaks:
            continue
        punct_map.setdefault(p.char_offset, []).append(p)

    ent_starts: dict[int, EntityAnnotation] = {}
    ent_ends: dict[int, EntityAnnotation] = {}
    for e in entities:
        ent_starts[e.start_offset] = e
        ent_ends[e.end_offset - 1] = e

    out: list[str] = []
    pi = 0
    pending_marks: list[str] = []

    for orig, ch in plain_tokens:
        if ch == "":
            if orig.isspace() and include_breaks:
                continue
            pending_marks.append(orig)
            continue

        # 1. 字符前点号
        if pi in punct_map:
            for p in punct_map[pi]:
                if p.pos == "before":
                    out.append(p.mark)

        # 2. 实体前包装（如开书名号、链接前缀）
        if pi in ent_starts:
            ent = ent_starts[pi]
            if ent.type == "work":
                out.append("《")
                if ent.target_status == "matched" and ent.target_href:
                    out.append("[")
            else:
                if ent.target_status == "matched" and ent.target_href:
                    out.append("[/")
                else:
                    out.append("/")

        out.extend(pending_marks)
        pending_marks.clear()
        out.append(orig)

        # 3. 实体后闭合
        if pi in ent_ends:
            ent = ent_ends[pi]
            if ent.type == "work":
                if ent.target_status == "matched" and ent.target_href:
                    out.append(f"]({ent.target_href})")
                out.append("》")
            else:
                if ent.target_status == "matched" and ent.target_href:
                    out.append(f"/]({ent.target_href})")
                else:
                    out.append("/")

        # 4. 字符后标点与分段符
        if pi in punct_map:
            for p in punct_map[pi]:
                if p.pos == "after":
                    out.append(p.mark)

        pi += 1

    out.extend(pending_marks)
    return "".join(out)


def build_entity_json(book_id: str, title: str, volume: int,
                      entities: list[EntityAnnotation],
                      creator: str = "qwen-plus:ner_v1") -> dict[str, Any]:
    """生成符合 guji-entity v0.1 规范的完整 JSON 对象。"""
    matched = sum(1 for e in entities if e.target_status == "matched")
    new_cand = sum(1 for e in entities if e.target_status == "new_candidate")
    works = sum(1 for e in entities if e.type == "work")
    people = sum(1 for e in entities if e.type == "people")
    places = sum(1 for e in entities if e.type == "place")
    offices = sum(1 for e in entities if e.type == "office")

    return {
        "$schema": "https://open-guji.org/schema/entity/v0.1.json",
        "version": "0.1.0",
        "book_id": book_id,
        "volume": volume,
        "metadata": {
            "title": title,
            "creator": creator,
            "base_edition": "original"
        },
        "stats": {
            "total_entities": len(entities),
            "matched": matched,
            "new_candidates": new_cand,
            "works": works,
            "people": people,
            "places": places,
            "offices": offices
        },
        "entities": [e.to_dict() for e in entities]
    }
