# -*- coding: utf-8 -*-
"""`render/siku_extract.py`：整册标点＋实体流水线。数据全部自造，LLM 用假的。

覆盖 #397 点名的四种版面：夹注 `<a|b>`（含注内阙文）、阙文 `[[]]`、超框抬头
（负格位、无第 0 格）、页码标记（跨页段落、rich.md 里原样透出）。
"""
from __future__ import annotations

import json
import re

from open_guji_cv.render import siku_extract as sx
from open_guji_cv.render.entity_extract import BookIndexMatcher

LINES = """<!-- p3 -->
^經部總敘
子夏易傳十一卷<內府|藏本>舊本題卜子夏撰
<!-- p4 -->
漢鄭玄注<周[[]]|易>魏王弼撰[[]]其說
"""


class FakeLLM:
    """按「送来的原文 → 回答」查表；没登记的原样返回（= 不加标点）。"""

    def __init__(self, table: dict[str, str]):
        self.table = table
        self.asked: list[str] = []

    def ask(self, user: str) -> str:
        plain = user.split("原文：\n", 1)[1].split("\n", 1)[0]
        self.asked.append(plain)
        return self.table.get(plain, plain)


def _matcher(tmp_path) -> BookIndexMatcher:
    (tmp_path / "index" / "works").mkdir(parents=True, exist_ok=True)
    (tmp_path / "index" / "entities").mkdir(parents=True, exist_ok=True)
    works = {"w1": {"id": "w1", "title": "子夏易傳", "dynasty": "周"}}
    ents = {
        "p1": {"id": "p1", "primary_name": "鄭玄", "subtype": "people", "dynasty": "東漢"},
        "p2": {"id": "p2", "primary_name": "鄭玄", "subtype": "people", "dynasty": "晉"},
        "p3": {"id": "p3", "primary_name": "王弼", "subtype": "people", "dynasty": "三國魏"},
        "p4": {"id": "p4", "primary_name": "王弼", "subtype": "people", "dynasty": "明"},
        "p5": {"id": "p5", "primary_name": "卜子夏", "subtype": "people"},
        "p6": {"id": "p6", "primary_name": "卜子夏", "subtype": "people"},
    }
    (tmp_path / "index" / "works" / "0.json").write_text(json.dumps(works, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "index" / "entities" / "0.json").write_text(json.dumps(ents, ensure_ascii=False), encoding="utf-8")
    m = BookIndexMatcher(tmp_path)
    m.load_index()
    return m


def _by_char(slots):
    return [(s.ch, s.anchor) for s in slots]


def test_anchor_raised_has_no_zero_cell():
    slots = sx.parse_lines_md(LINES)
    assert _by_char(slots)[:4] == [("經", "3:1:-1"), ("部", "3:1:1"), ("總", "3:1:2"), ("敘", "3:1:3")]


def test_anchor_jiazhu_subcolumns_share_start_cell():
    col2 = [(s.ch, s.anchor) for s in sx.parse_lines_md(LINES) if (s.page, s.col) == (3, 2)]
    assert col2[7:12] == [("內", "3:2:8a"), ("府", "3:2:9a"), ("藏", "3:2:8b"), ("本", "3:2:9b"),
                          ("舊", "3:2:10")]               # 夹注占 max(2,2)=2 格


def test_gap_inside_jiazhu_is_one_cell_and_page_resets_columns():
    slots = sx.parse_lines_md(LINES)
    p4 = [(s.ch, s.anchor) for s in slots if s.page == 4]
    assert p4[:7] == [("漢", "4:1:1"), ("鄭", "4:1:2"), ("玄", "4:1:3"), ("注", "4:1:4"),
                      ("周", "4:1:5a"), ("□", "4:1:6a"), ("易", "4:1:5b")]
    assert ("魏", "4:1:7") in p4                       # 夹注 max(2,1)=2 格
    assert p4[-3] == ("□", "4:1:11")


def test_count_blank_columns_switch():
    text = "<!-- p1 -->\n甲\n\n乙\n"
    assert [s.anchor for s in sx.parse_lines_md(text)] == ["1:1:1", "1:2:1"]
    assert [s.anchor for s in sx.parse_lines_md(text, count_blank_columns=True)] == ["1:1:1", "1:3:1"]


def test_parse_annotated_tags_and_punct():
    p = sx.parse_annotated("《子夏易傳》十一卷，{人:卜子夏}撰。「云」")
    assert p.stripped == "子夏易傳十一卷卜子夏撰云"
    assert p.spans == [("work", 0, 4), ("people", 7, 10)]
    assert p.punct_before == {7: "，", 11: "。「", 12: "」"}


def _run(tmp_path, table, **kw):
    llm = FakeLLM(table)
    res = sx.run_volume(LINES, llm, _matcher(tmp_path), workers=1, **kw)
    return llm, res


A1 = "《子夏易傳》十一卷<內府藏本>，舊本題{人:卜子夏}撰。"
A2 = "{朝:漢}{人:鄭玄}注<{书:周□易}>，{朝:魏}{人:王弼}撰，□其說。"


def _answers(llm_plain: list[str]) -> dict[str, str]:
    """跨页的一段会作一块送来；按块里有哪几半拼回答。"""
    out = {}
    for p in llm_plain:
        ans = (A1 if p.startswith("子夏") else "") + (A2 if "漢鄭玄" in p else "")
        if ans:
            out[p] = ans
    return out


def test_volume_punct_entities_and_rich_md(tmp_path):
    probe, _ = _run(tmp_path, {})
    _, res = _run(tmp_path, _answers(probe.asked))
    r = res.report
    assert r["unmatched_chars"] == 0 and r["chunks_failed"] == 0
    by = {(p.mark, p.anchor) for p in res.puncts if p.kind == "point"}
    assert ("，", "3:2:9b") in by                      # 夹注后的逗号挂在注内末字（右行）之后
    assert ("。", "3:2:16") in by
    assert ("，", "4:1:5b") in by and ("，", "4:1:10") in by
    ents = {e.text: e for e in res.entities}
    assert ents["子夏易傳"].target_status == "matched" and ents["子夏易傳"].anchor_start == "3:2:1"
    assert ents["卜子夏"].target_status == "new_candidate" and "同名 2 条" in ents["卜子夏"].note
    # 朝代紧挨在前 → 同名消歧
    assert ents["鄭玄"].target_id == "p1" and ents["王弼"].target_id == "p3"
    assert ents["周□易"].anchor_start == "4:1:5a" and ents["周□易"].anchor_end == "4:1:5b"
    assert "\x00" not in res.rich_md and "<!-- p4 -->" in res.rich_md
    assert "[[]]" in res.rich_md                          # 阙文原样透出
    assert "《[子夏易傳](book-index://Work/w1)》" in res.rich_md


def test_rich_md_keeps_every_base_char(tmp_path):
    probe, _ = _run(tmp_path, {})
    _, res = _run(tmp_path, _answers(probe.asked))
    rich = re.sub(r"\]\([^)]*\)|<!--[^>]*-->", "", res.rich_md).replace("[[]]", "□")
    rich = re.sub(r"[《》\[\]/，。、；：？！「」『』<>\s]", "", rich)
    assert rich == "".join(s.ch for s in sx.parse_lines_md(LINES))


def test_changed_chars_chunk_is_dropped_and_reported(tmp_path):
    probe, _ = _run(tmp_path, {})
    table = {p: o.replace("鄭玄", "郑玄").replace("王弼", "王粥").replace("<", "").replace(">", "")
             for p, o in _answers(probe.asked).items()}
    llm, res = _run(tmp_path, table, max_bad_ratio=0.02)
    assert res.report["chunks_failed"] == 1
    assert res.report["failed"][0]["anchor"] == "3:2:1"
    assert not any(p.kind == "point" for p in res.puncts)
    assert not res.entities
    assert sum(1 for a in llm.asked if a.startswith("子夏")) == 2      # 作废重问一次


def test_outputs_and_candidates_tsv(tmp_path):
    probe, _ = _run(tmp_path, {})
    _, res = _run(tmp_path, _answers(probe.asked))
    paths = sx.write_outputs(res, tmp_path / "out", 2, book_id="b", title="t", creator="fake")
    pj = json.loads(paths["punct"].read_text(encoding="utf-8"))
    assert pj["volume"] == 2 and all("anchor" in p for p in pj["punctuations"])
    ej = json.loads(paths["entity"].read_text(encoding="utf-8"))
    assert ej["stats"]["matched"] == 3
    rows = paths["candidates"].read_text(encoding="utf-8").splitlines()
    assert rows[0].split("\t")[:5] == ["类型", "名称", "出处坐标", "上下文", "建议"]
    cand = {r.split("\t")[1]: r.split("\t") for r in rows[1:]}
    assert cand["周□易"][0] == "work" and cand["周□易"][2] == "4:1:5a"
    assert "同名 2 条" in cand["卜子夏"][4]
    assert "【卜子夏】" in cand["卜子夏"][3]


def test_sample_and_score(tmp_path):
    probe, _ = _run(tmp_path, {})
    _, res = _run(tmp_path, _answers(probe.asked))
    paths = sx.write_outputs(res, tmp_path, 2, book_id="b", title="t", creator="fake")
    chars, anchors = sx.load_render_chars(LINES)
    assert chars == res.render_chars and anchors == res.anchors
    pj = json.loads(paths["punct"].read_text(encoding="utf-8"))
    rows = sx.sample_punct(pj, chars, n=3, seed=1)
    assert len(rows) == 3 and all("【" in r["上下文"] and r["坐标"] for r in rows)
    ej = json.loads(paths["entity"].read_text(encoding="utf-8"))
    m = _matcher(tmp_path / "bi")
    erows = sx.sample_entities(ej, chars, m, n=50)
    assert {r["原文"] for r in erows} == {"子夏易傳", "鄭玄", "王弼"}
    assert any(r["条目信息"].startswith("東漢") for r in erows)
    for r, v in zip(erows, ["对", "误挂", "对"]):
        r["判定(对/误挂/非专名/类型错)"] = v
    sx.write_tsv(erows, tmp_path / "e.tsv")
    sc = sx.score_tsv(tmp_path / "e.tsv")
    assert sc["judged"] == 3 and sc["ok_rate"] == 0.6667 and sc["mislink_rate"] == 0.3333


def test_render_break_goes_after_note_close_and_opener_after_page_mark():
    from open_guji_cv.render.entity_extract import EntityAnnotation, apply_entities_and_punctuations_to_markdown
    from open_guji_cv.render.punct_extract import PunctAnnotation, tokenize
    toks = tokenize("甲<乙丙><!-- p4 -->丁戊")
    puncts = [PunctAnnotation("\n\n", "break", "after", 2)]
    ents = [EntityAnnotation("e1", "work", "丁戊", "", "", 3, 5)]
    md = apply_entities_and_punctuations_to_markdown(toks, puncts, ents)
    assert md == "甲<乙丙>\n\n<!-- p4 -->《丁戊》"


def test_mid_paragraph_chunk_tail_punct_is_dropped():
    ch = sx.Chunk(0, "甲乙丙", [0, 1, 2], para_end=False)
    cr = sx.ChunkResult(True, 0, 3, {1: "，", 3: "。"}, [])
    pts, _ = sx._chunk_to_render(ch, cr)
    assert pts == [("，", 0, "after")]
    ch.para_end = True
    pts, _ = sx._chunk_to_render(ch, cr)
    assert pts == [("，", 0, "after"), ("。", 2, "after")]


def test_dynasty_hint_from_untagged_prefix():
    chars = list("漢鄭玄注後魏王弼")
    assert sx.dynasty_before(chars, 1, None) == "漢"
    assert sx.dynasty_before(chars, 6, None) == "魏"
    assert sx.dynasty_before(chars, 4, None) is None
