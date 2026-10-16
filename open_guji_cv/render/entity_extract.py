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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .punct_extract import PunctAnnotation


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
    note: str | None = None         # 例如「同名 3 条待消歧」
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
        if self.note:
            d["target"]["note"] = self.note
        if self.confidence < 1.0:
            d["confidence"] = round(self.confidence, 4)
        if self.source:
            d["source"] = self.source
        return d


#: 經傳篇名：《易》十翼等是經書的一部分，不是某人撰的書；book-index 里却有同名 Work
#: （如韓元吉《繫辭傳》），精确名匹配会误挂。一律不挂、不建档。
CLASSIC_SECTIONS = frozenset(
    "繫辭 繫辭傳 繫辭上傳 繫辭下傳 說卦 說卦傳 序卦 序卦傳 雜卦 雜卦傳 彖 彖傳 彖上傳 彖下傳 "
    "象 象傳 象上傳 象下傳 大象 小象 文言 文言傳 上經 下經 十翼".split())

_NAME_NORM = str.maketrans("吕郞", "呂郎")

#: 三字及以下的书名多是简称（「集解」「唐志」「本義」「考」），同名 Work 往往是别人的书：
#: vol02 实测 集解→淩唐佐、唐志→王沿、易本義→劉霖、五經→王弼 全是误挂。所以短书名只在
#: 「撰人在同段出现」或「前接人名核对为撰人」时才挂；下面这些经史名著例外，见名即挂。
WELL_KNOWN_SHORT = frozenset(
    "經義考 左傳 公羊傳 穀梁傳 孟子 論語 爾雅 史記 漢書 後漢書 三國志 晉書 宋書 南齊書 梁書 陳書 "
    "魏書 北齊書 周書 隋書 南史 北史 舊唐書 新唐書 宋史 遼史 金史 元史 明史 玉海 通典 通志 七略 七志 "
    "初學記 說文 文選 山海經 水經注 乾鑿度".split())
SHORT_TITLE_MAX = 3

#: 清代避諱改字：四庫提要里「鄭元」即鄭玄、「周宏正」即周弘正。book-index 里另有唐人鄭元，
#: 不还原就会误挂。还原后的名字在库里有才用它。
TABOO_RESTORE = str.maketrans("元宏", "玄弘")
#: 书名别称 → book-index 的条目名（库里「春秋左傳」是明包瑜的书，经本身题作「左傳」）
WORK_ALIAS = {"春秋左傳": "左傳", "春秋左氏傳": "左傳", "左氏傳": "左傳"}


class BookIndexMatcher:
    """轻量级 book-index 实体匹配器。"""

    def __init__(self, book_index_root: str | Path = "d:/workspace/book-index"):
        self.root = Path(book_index_root)
        self.works: dict[str, str] = {}    # title -> work_id
        self.people: dict[str, str] = {}   # name -> entity_id
        self.entities_by_type: dict[str, dict[str, str]] = {} # type -> (name -> entity_id)
        # 同名全收（上面三张 dict 后写覆盖前写，同名只剩一条）：判"同名多条不挂"用
        self.ids_by_name: dict[tuple[str, str], list[str]] = {}  # (work|people|…, 名) -> [id]
        self.meta: dict[str, dict[str, Any]] = {}                 # id -> 分片索引原条
        self._loaded = False

    def _add(self, kind: str, name: str, oid: str, item: dict[str, Any]) -> None:
        ids = self.ids_by_name.setdefault((kind, name), [])
        if oid not in ids:
            ids.append(oid)
        self.meta[oid] = item

    def work_authors(self, wid: str) -> list[tuple[str, str | None]]:
        """Work 的撰人 [(名, entity_id)]，按需读条目 JSON（分片索引里没有撰人）。"""
        m = self.meta.get(wid) or {}
        path = self.root / m.get("path", "") if m.get("path") else None
        if path is None or not path.is_file():
            return []
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        out = []
        for a in d.get("authors") or []:
            for n in (a.get("name"), a.get("original_name")):
                if n:
                    out.append((n, a.get("entity_id")))
        return out

    def _author_ok(self, wid: str, name: str, eid: str | None) -> bool:
        key = name.translate(_NAME_NORM)
        return any((eid and aid == eid) or n.translate(_NAME_NORM) == key
                   for n, aid in self.work_authors(wid))

    def describe(self, oid: str) -> str:
        """条目一行摘要（抽检表里给人判误挂用）：朝代、生卒、路径。"""
        m = self.meta.get(oid)
        if not m:
            return ""
        bits = [m.get("dynasty") or ""]
        if m.get("birth_year") or m.get("death_year"):
            bits.append(f"{m.get('birth_year') or '?'}–{m.get('death_year') or '?'}")
        bits.append(m.get("path", ""))
        return " ".join(b for b in bits if b)

    def load_index(self, max_records: int = 100000) -> None:
        if self._loaded or not self.root.exists():
            return

        import os
        # 1. 优先从预构建的快速分片索引加载 (book-index/index/works 与 book-index/index/entities)
        idx_works_dir = self.root / "index" / "works"
        if idx_works_dir.exists():
            for f in os.listdir(idx_works_dir):
                if f.endswith(".json"):
                    try:
                        with open(idx_works_dir / f, "r", encoding="utf-8") as fp:
                            data = json.load(fp)
                        for item in data.values():
                            title = item.get("title")
                            wid = item.get("id")
                            if title and wid:
                                self.works[title] = wid
                                self._add("work", title, wid, item)
                    except Exception:
                        pass

        idx_entities_dir = self.root / "index" / "entities"
        if idx_entities_dir.exists():
            for f in os.listdir(idx_entities_dir):
                if f.endswith(".json"):
                    try:
                        with open(idx_entities_dir / f, "r", encoding="utf-8") as fp:
                            data = json.load(fp)
                        for item in data.values():
                            name = item.get("primary_name")
                            eid = item.get("id")
                            st = item.get("subtype", "people")
                            if name and eid:
                                self._add(st, name, eid, item)
                                if st not in self.entities_by_type:
                                    self.entities_by_type[st] = {}
                                self.entities_by_type[st][name] = eid
                                if st == "people":
                                    self.people[name] = eid
                    except Exception:
                        pass

        # 2. 回退到直接目录扫描（若未加载到预构建索引）
        if not self.works:
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

        if not self.people:
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

    def match(self, ent_type: str, text: str, dynasty_hint: str | None = None,
              author_hint: tuple[str, str | None] | None = None,
              context: str | None = None) -> dict[str, Any]:
        """根据实体类型与文本匹配知识库。

        `dynasty_hint`：紧挨在名字前的朝代（四庫提要「漢鄭玄注」「魏王弼撰」的写法）。
        同名多条时用它筛：条目朝代含该字样的恰好一条才挂，否则不挂。
        `author_hint`：紧挨在书名前的人名 (名, entity_id)（「焦竑經籍志」「陸游老學庵筆記」）。
        书名只有一条时撰人对不上就不挂（vol02 抽检 5 例误挂有 2 例是这种），同名多条时用它消歧。
        `context`：书名附近的原文（前几个字＋提要书名行的下一段开头）。给了它，短书名
        （见 `WELL_KNOWN_SHORT`）要撰人在其中出现才挂。整段太宽：一条提要提到的人很多，
        vol02 抽检里「易傳」挂到同段提过的丁易東、「易解」挂到胡瑗，都是这么错的。
        """
        if not self._loaded:
            self.load_index()

        if ent_type == "work" and text in WORK_ALIAS:
            r = self.match(ent_type, WORK_ALIAS[text], dynasty_hint, author_hint, context)
            if r.get("status") == "matched":
                r["note"] = f"别称，按「{WORK_ALIAS[text]}」挂"
            return r
        if ent_type == "people":
            restored = text.translate(TABOO_RESTORE)
            if restored != text and self.ids_by_name.get(("people", restored)):
                r = self.match(ent_type, restored, dynasty_hint, author_hint, context)
                r["note"] = f"避諱字還原「{text}」→「{restored}」" + (f"；{r['note']}" if r.get("note") else "")
                return r

        same = self.ids_by_name.get((ent_type, text), [])
        n_same = len(same)
        if ent_type == "work" and text in CLASSIC_SECTIONS:
            return {"status": "new_candidate", "canonical_name": text, "note": "經傳篇名，不挂、不建档"}
        if ent_type == "work" and author_hint and same:
            hit = [w for w in same if self._author_ok(w, *author_hint)]
            if len(hit) == 1:
                return {
                    "status": "matched",
                    "entity_type": "work",
                    "entity_id": hit[0],
                    "canonical_name": text,
                    "href": f"book-index://Work/{hit[0]}",
                    "note": f"按撰人「{author_hint[0]}」核对" + (f"（同名 {n_same} 条）" if n_same > 1 else ""),
                }
            if not hit and any(self.work_authors(w) for w in same):
                return {
                    "status": "new_candidate",
                    "canonical_name": text,
                    "note": f"前接人名「{author_hint[0]}」与同名 {n_same} 条撰人皆不合",
                }
        if (ent_type == "work" and context is not None and same and len(text) <= SHORT_TITLE_MAX
                and text not in WELL_KNOWN_SHORT):
            ctx = context.translate(_NAME_NORM)
            hit = [w for w in same
                   if any(len(n) >= 2 and n.translate(_NAME_NORM) in ctx for n, _ in self.work_authors(w))]
            if len(hit) == 1:
                return {
                    "status": "matched",
                    "entity_type": "work",
                    "entity_id": hit[0],
                    "canonical_name": text,
                    "href": f"book-index://Work/{hit[0]}",
                    "note": "短书名，撰人见于书名近旁",
                }
            return {
                "status": "new_candidate",
                "canonical_name": text,
                "note": "短书名（多为简称），近旁不见 book-index 同名条目的撰人，不挂",
            }
        if n_same > 1 and dynasty_hint:
            hit = [i for i in same if dynasty_hint in (self.meta.get(i, {}).get("dynasty") or "")]
            if len(hit) == 1:
                kind = "Work" if ent_type == "work" else "Entity"
                return {
                    "status": "matched",
                    "entity_type": ent_type,
                    "entity_id": hit[0],
                    "canonical_name": text,
                    "href": f"book-index://{kind}/{hit[0]}",
                    "note": f"同名 {n_same} 条，按朝代「{dynasty_hint}」消歧",
                }
        if n_same > 1:
            # 同名多条：精确名匹配分不出是哪一条，挂上去就是误挂，留给建档消歧
            return {
                "status": "new_candidate",
                "canonical_name": text,
                "note": f"同名 {n_same} 条待消歧: " + " ".join(self.ids_by_name[(ent_type, text)][:5]),
            }

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
        elif ent_type in ("people", "place", "office", "dynasty"):
            # 优先从具体类型的实体库匹配
            if ent_type in self.entities_by_type and text in self.entities_by_type[ent_type]:
                eid = self.entities_by_type[ent_type][text]
                return {
                    "status": "matched",
                    "entity_type": ent_type,
                    "entity_id": eid,
                    "canonical_name": text,
                    "href": f"book-index://Entity/{eid}"
                }
            # 其次匹配通用 people 库
            if ent_type == "people" and text in self.people:
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
    # 书名两层都记（guji-format#3）：标点层里与 work 实体同位的《》由实体包装出，这里跳过免得重出
    work_open = {e.start_offset for e in entities if e.type == "work"}
    work_close = {e.end_offset - 1 for e in entities if e.type == "work"}
    for k, ps in list(punct_map.items()):
        punct_map[k] = [p for p in ps
                        if not (p.mark == "《" and p.pos == "before" and k in work_open)
                        and not (p.mark == "》" and p.pos == "after" and k in work_close)]

    out: list[str] = []
    pi = 0
    pending_marks: list[str] = []
    pending_breaks: list[str] = []

    def flush_marks() -> None:
        # 版面记号的次序：先收小注（`>`、`]{…}`），再分段，再页码标记/开小注。
        # 否则段末字在注内时分段符会落进注里（`藏本\n\n>`），开书名号会跑到
        # 页码标记前面（`《<!-- p4 -->周易`）。
        k = 0
        while k < len(pending_marks) and pending_marks[k][:1] in (">", "]"):
            k += 1
        out.extend(pending_marks[:k])
        out.extend(pending_breaks)
        out.extend(pending_marks[k:])
        pending_marks.clear()
        pending_breaks.clear()

    for orig, ch in plain_tokens:
        if ch == "":
            if orig.isspace() and include_breaks:
                continue
            pending_marks.append(orig)
            continue

        flush_marks()

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

        # 4. 字符后标点；分段符等后面的版面记号收完再出
        if pi in punct_map:
            for p in punct_map[pi]:
                if p.pos == "after":
                    (pending_breaks if p.kind == "break" else out).append(p.mark)

        pi += 1

    flush_marks()
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
