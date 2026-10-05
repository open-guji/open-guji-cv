# -*- coding: utf-8 -*-
"""四库总目第二册 (vol02) 标点、分段与实体链接抽取测试脚本。

职责：
1. 读取 002.lines.md，建立底本每个纯字到 3 段式拓扑坐标 <页>:<列>:<格>[子列] 的精确映射（含超框抬头负格位、夹注子列）；
2. 运行 reflow 分段与 Qwen-plus LLM 标点 + 实体识别（NER）；
3. 利用 SequenceMatcher 精密对齐，分别抽取独立的 punct.json 与 entity.json；
4. 与 book-index 知识库 (Work / Entity) 进行全库索引检索匹配；
5. 流式拉链合成 002.rich.md（带超链接 Level 3 Rich Markdown）与 002.md（标准阅读版）；
6. 严格不执行 git commit 或 git push。
"""
import difflib
import json
import os
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from open_guji_cv.render.punct_llm import PunctClient
from open_guji_cv.render.punct_extract import PunctAnnotation, PUNCT_CHARS, tokenize
from open_guji_cv.render.entity_extract import (
    EntityAnnotation,
    BookIndexMatcher,
    apply_entities_and_punctuations_to_markdown,
    build_entity_json,
)
from open_guji_cv.render.reflow_text import reflow, Line

_PREFIX = re.compile(r"^(\^*)(\.*)")
_PAGE = re.compile(r"^<!--\s*p(\d+)\s*-->$")
_UNIT = re.compile(
    r"<(?P<jz>[^<>]*)>"
    r"|:jz\[(?P<dj>[^\]]*)\](?:\{[^}]*\})?"
    r"|(?P<gap>\[\[[^\]]*\]\])"
    r"|(?P<box>□(?:\{[^}]*\})?)"
    r"|(?P<ch>.)", re.S)


def build_anchor_map(lines_md_text: str):
    """解析 002.lines.md，构建每个纯文本字符到拓扑坐标的映射。"""
    char_anchors: dict[int, str] = {}
    plain_chars: list[str] = []

    current_page = 0
    col_in_page = 0
    global_char_idx = 0

    for raw_line in lines_md_text.splitlines():
        line_str = raw_line.strip()
        if not line_str:
            continue
        pm = _PAGE.match(line_str)
        if pm:
            current_page = int(pm.group(1))
            col_in_page = 0
            continue

        col_in_page += 1
        m_pref = _PREFIX.match(line_str)
        raised = len(m_pref.group(1)) if m_pref else 0
        dots = len(m_pref.group(2)) if m_pref else 0
        body = line_str[m_pref.end():]

        # 初始格位：超框抬头为负，挪抬缩进顺延
        if raised > 0:
            current_grid = -raised
        elif dots > 0:
            current_grid = dots + 1
        else:
            current_grid = 1

        for u in _UNIT.finditer(body):
            if u.group("jz") is not None:
                parts = u.group("jz").split("|")
                left = parts[0] if len(parts) > 0 else ""
                right = parts[1] if len(parts) > 1 else ""
                grid_a = current_grid
                for c in left:
                    char_anchors[global_char_idx] = f"{current_page}:{col_in_page}:{grid_a}a"
                    plain_chars.append(c)
                    global_char_idx += 1
                    grid_a += 1
                grid_b = current_grid
                for c in right:
                    char_anchors[global_char_idx] = f"{current_page}:{col_in_page}:{grid_b}b"
                    plain_chars.append(c)
                    global_char_idx += 1
                    grid_b += 1
                current_grid += max(len(left), len(right))
            elif u.group("dj") is not None:
                for c in u.group("dj"):
                    char_anchors[global_char_idx] = f"{current_page}:{col_in_page}:{current_grid}"
                    plain_chars.append(c)
                    global_char_idx += 1
                    current_grid += 1
            elif u.group("gap") is not None or u.group("box") is not None:
                char_anchors[global_char_idx] = f"{current_page}:{col_in_page}:{current_grid}"
                plain_chars.append("□")
                global_char_idx += 1
                current_grid += 1
            else:
                ch = u.group("ch")
                if ch.isspace():
                    continue
                char_anchors[global_char_idx] = f"{current_page}:{col_in_page}:{current_grid}"
                plain_chars.append(ch)
                global_char_idx += 1
                current_grid += 1

    return plain_chars, char_anchors


NER_PROMPT = """你是古籍整理专家。请给下面这段《四庫全書總目提要》加现代标点，并标注书名号与专名号。

要求：
1. 标点符号：使用逗号、句号、顿号、分号、冒号、引号等（，。、；：？！「」『』）；
2. 书名与篇名：使用《书名号》，如《易傳》、《漢書》、《七略》；
3. 专有名词（人名、地名、官职、朝代）：使用斜杠包裹 /专名/，如 /卜子夏/、/漢京/、/太常博士/、/唐/；
4. 双行夹注记号 < 和 > 必须原样保留在原位，注内文字也要加标点和专名/书名；
5. 严禁改动任何原文字符（不增字、不删字、不换字、不转简体、□ 保留）；
6. 只输出标注后的文本，不要任何解释。

原文：
{text}"""


def process_paragraph_ner(plain_para: str, client: PunctClient, cache_dir: Path) -> str:
    """调用 LLM 进行标点 + NER 标注，带本地缓存。"""
    import hashlib
    ck = hashlib.sha256(plain_para.encode("utf-8")).hexdigest()[:24]
    cf = cache_dir / f"ner_{ck}.json"
    if cf.exists():
        try:
            return json.loads(cf.read_text(encoding="utf-8"))["out"]
        except Exception:
            pass

    prompt = NER_PROMPT.format(text=plain_para)
    out = client.ask(prompt)
    cf.write_text(json.dumps({"para": plain_para, "out": out}, ensure_ascii=False), encoding="utf-8")
    return out


def main():
    book_text_dir = Path("d:/workspace/book-text/Book/k/z/g/96mid1ogzk/original")
    lines_md_file = book_text_dir / "002.lines.md"
    cache_dir = book_text_dir / ".punct_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    print(f"1. 加载 002.lines.md: {lines_md_file}")
    lines_md_text = lines_md_file.read_text(encoding="utf-8")
    plain_chars, char_anchors = build_anchor_map(lines_md_text)
    print(f"   底本全册字符数: {len(plain_chars)}")

    # 2. 初始化知识库匹配器
    print("2. 加载 book-index 知识库索引...")
    matcher = BookIndexMatcher("d:/workspace/book-index")
    matcher.load_index()
    print(f"   已加载书名: {len(matcher.works)} 部, 人物/专名: {len(matcher.people)} 条")

    # 3. reflow 分段测试（选取卷首二前 15 页代表段落做深度测试）
    print("3. 进行段落切分与抽取测试（选取前 15 页核心提要）...")
    lines = lines_md_text.splitlines()
    sub_lines = []
    cur_p = 0
    for ln in lines:
        pm = _PAGE.match(ln.strip())
        if pm:
            cur_p = int(pm.group(1))
        if 3 <= cur_p <= 15:
            sub_lines.append(ln)
    test_sub_text = "\n".join(sub_lines)

    test_reflow_in = re.sub(r"^<!--\s*p(\d+)\s*-->", r"#第\1页", test_sub_text, flags=re.M)
    paras, stats = reflow(test_reflow_in, "default")
    print(f"   切分出自然段: {len(paras)} 段")

    client = PunctClient("qwen", "qwen-plus", cache_dir=cache_dir)

    all_puncts: list[PunctAnnotation] = []
    all_entities: list[EntityAnnotation] = []
    all_tokens_for_synthesis: list[tuple[str, str]] = []

    global_char_cursor = 0
    ent_counter = 0

    for pi, para in enumerate(paras):
        para_raw = para.text
        # 移除页码标记用于纯段落处理
        para_for_llm = re.sub(r"\x00p\d+\x00", "", para_raw)
        para_tokens = tokenize(para_raw)
        para_base_chars = [c for orig, c in para_tokens if c != ""]

        # 收集供合成使用的 tokens
        all_tokens_for_synthesis.extend(para_tokens)
        if pi < len(paras) - 1:
            all_tokens_for_synthesis.append(("\n\n", ""))

        if not para_base_chars:
            continue

        print(f"   处理段落 {pi+1}/{len(paras)} ({len(para_base_chars)} 纯字)...")
        annotated = process_paragraph_ner(para_for_llm, client, cache_dir)

        # 解析 annotated 文本
        # 1. 扫描实体
        m_ents = []
        for m in re.finditer(r"《(?P<work>[^》]+)》|/(?P<zm>[^/]+)/", annotated):
            is_w = m.group("work") is not None
            raw_val = m.group("work") if is_w else m.group("zm")
            content_span = (m.start(1 if is_w else 2), m.end(1 if is_w else 2))
            m_ents.append(("work" if is_w else "zm", raw_val, content_span))

        # 2. 提取 annotated 的纯字与标点
        clean_annot_chars = []
        puncts_in_annot = []

        i = 0
        while i < len(annotated):
            c = annotated[i]
            if c in "《》/":
                i += 1
                continue
            if c in PUNCT_CHARS:
                prev_clean = len(clean_annot_chars) - 1
                if prev_clean >= 0:
                    puncts_in_annot.append((c, "after", prev_clean))
                i += 1
                continue
            if c.isspace() or c in "<>:jz[]{}=单行":
                i += 1
                continue
            clean_annot_chars.append(c)
            i += 1

        # 3. 对齐底本与 LLM 输出
        sm = difflib.SequenceMatcher(None, para_base_chars, clean_annot_chars, autojunk=False)
        annot_to_base = {}
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    annot_to_base[j1 + k] = i1 + k

        # 4. 映射标点到底本绝对格位
        for mark, pos, c_idx in puncts_in_annot:
            if c_idx in annot_to_base:
                b_idx_in_para = annot_to_base[c_idx]
                abs_pos = global_char_cursor + b_idx_in_para
                pre_ch = plain_chars[abs_pos] if abs_pos < len(plain_chars) else ""
                anc = char_anchors.get(abs_pos, f"3:1:{abs_pos+1}")

                all_puncts.append(PunctAnnotation(
                    mark=mark,
                    kind="point",
                    pos=pos,
                    char_offset=abs_pos,
                    pre_char=pre_ch,
                    anchor=anc,
                    confidence=1.0,
                    source="qwen-plus"
                ))

        # 5. 映射实体到底本绝对格位
        for etype_tag, raw_text, (cs, ce) in m_ents:
            pure_t = re.sub(r"[\s，。、；：？！「」『』《》/<>]", "", raw_text)
            if not pure_t:
                continue

            prefix = annotated[:cs]
            clean_prefix = re.sub(r"[\s《》/，。、；：？！「」『』（）…—·<>:jz\[\]{}=单行]", "", prefix)
            s_clean = len(clean_prefix)
            e_clean = s_clean + len(pure_t) - 1

            if s_clean in annot_to_base and e_clean in annot_to_base:
                b_s = annot_to_base[s_clean]
                b_e = annot_to_base[e_clean]

                abs_s = global_char_cursor + b_s
                abs_e = global_char_cursor + b_e

                anc_s = char_anchors.get(abs_s, f"3:1:{abs_s+1}")
                anc_e = char_anchors.get(abs_e, f"3:1:{abs_e+1}")

                # 细分类型
                if etype_tag == "work":
                    ent_type = "work"
                elif any(d in pure_t for d in ["唐", "宋", "元", "明", "清", "漢", "梁", "晉", "周", "齊", "開元", "咸淳"]):
                    ent_type = "dynasty"
                elif any(o in pure_t for o in ["學士", "祭酒", "博士", "進士", "官", "總管", "教授"]):
                    ent_type = "office"
                elif any(p in pure_t for p in ["人", "州", "陽", "都", "川", "京"]):
                    ent_type = "place"
                else:
                    ent_type = "people"

                tgt = matcher.match(ent_type, pure_t)
                ent_counter += 1

                all_entities.append(EntityAnnotation(
                    id=f"e{ent_counter:04d}",
                    type=ent_type,
                    text=pure_t,
                    anchor_start=anc_s,
                    anchor_end=anc_e,
                    start_offset=abs_s,
                    end_offset=abs_e + 1,
                    target_status=tgt.get("status", "new_candidate"),
                    target_id=tgt.get("entity_id"),
                    target_name=tgt.get("canonical_name", pure_t),
                    target_href=tgt.get("href"),
                    source="qwen-plus"
                ))

        # 段末自然段分段符
        last_b_idx = global_char_cursor + len(para_base_chars) - 1
        pre_ch = plain_chars[last_b_idx] if last_b_idx < len(plain_chars) else ""
        anc_break = char_anchors.get(last_b_idx, f"3:1:{last_b_idx+1}")
        all_puncts.append(PunctAnnotation(
            mark="\n\n",
            kind="break",
            pos="after",
            char_offset=last_b_idx,
            pre_char=pre_ch,
            anchor=anc_break,
            confidence=1.0,
            source="rule:reflow"
        ))

        global_char_cursor += len(para_base_chars)

    print(f"\n4. 抽取完成: 标点 {len(all_puncts)} 个, 实体 {len(all_entities)} 个")

    # 5. 写入 002.punct.json
    punct_json_data = {
        "$schema": "https://open-guji.org/schema/punct/v0.1.json",
        "version": "0.1.0",
        "book_id": "96mid1ogzk",
        "volume": 2,
        "metadata": {
            "title": "欽定四庫全書總目·卷首二（vol02）",
            "creator": "qwen-plus",
            "base_edition": "original",
            "description": "基于 original 底本自动生成独立外挂标点与分段，采用 3 段式拓扑坐标 <页>:<列>:<格>[子列] 锚定，正文字符保持严格解耦。"
        },
        "stats": {
            "total_annotations": len(all_puncts),
            "points": sum(1 for p in all_puncts if p.kind == "point"),
            "paragraph_breaks": sum(1 for p in all_puncts if p.kind == "break"),
        },
        "punctuations": [p.to_dict() for p in all_puncts]
    }
    punct_file = book_text_dir / "002.punct.json"
    punct_file.write_text(json.dumps(punct_json_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"   已写入独立标点: {punct_file}")

    # 6. 写入 002.entity.json
    entity_json_data = build_entity_json(
        book_id="96mid1ogzk",
        title="欽定四庫全書總目·卷首二（vol02）",
        volume=2,
        entities=all_entities,
        creator="qwen-plus:ner_v1"
    )
    entity_file = book_text_dir / "002.entity.json"
    entity_file.write_text(json.dumps(entity_json_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"   已写入独立实体: {entity_file}")

    # 7. 合成 002.rich.md (Level 3 Rich Markdown)
    print("5. 正在合成 Level 3 Rich Markdown...")
    rich_md = apply_entities_and_punctuations_to_markdown(
        all_tokens_for_synthesis, all_puncts, all_entities, include_breaks=True
    )
    rich_file = book_text_dir / "002.rich.md"
    rich_file.write_text(rich_md + "\n", encoding="utf-8")
    print(f"   已写入富文本: {rich_file}")

    # 合成 002.md (标准版)
    std_md = apply_entities_and_punctuations_to_markdown(
        all_tokens_for_synthesis, all_puncts, [], include_breaks=True
    )
    std_file = book_text_dir / "002.md"
    std_file.write_text(std_md + "\n", encoding="utf-8")
    print(f"   已写入标准版: {std_file}")

    # 8. 打印统计与样例
    matched_works = [e for e in all_entities if e.type == "work" and e.target_status == "matched"]
    matched_peoples = [e for e in all_entities if e.type != "work" and e.target_status == "matched"]
    print("\n" + "="*60)
    print("【测试统计报告】")
    print(f"总实体数: {len(all_entities)}")
    print(f"命中知识库 Work: {len(matched_works)} 个 (示例: {[w.text for w in matched_works[:5]]})")
    print(f"命中知识库 Entity: {len(matched_peoples)} 个 (示例: {[p.text for p in matched_peoples[:5]]})")
    print("="*60)
    print("【002.rich.md 效果预览 (前 1000 字符)】")
    print("="*60)
    print(rich_md[:1000])
    print("="*60)


if __name__ == "__main__":
    main()
