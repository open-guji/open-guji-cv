# -*- coding: utf-8 -*-
"""eval_seg_health.level1：一级四个指标（列网劈列、对表错列、对文字错位、挤格列）在自造产物上各命中一次。"""
import importlib.util
import json
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "eval_seg_health", Path(__file__).resolve().parent.parent / "scripts" / "eval_seg_health.py")
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules["eval_seg_health"] = _MOD
_SPEC.loader.exec_module(_MOD)

TEXT = "天地玄黃宇宙洪荒日月盈昃辰宿列張寒來"     # 18 字，第 1 列格 1–18


def _write(path: Path, kind: str, body: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({kind: body}, ensure_ascii=False), encoding="utf-8")


def _jsonl(path: Path, rows):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")


def _chars(page, col, slots, text, tall=()):
    out = []
    for i, s in enumerate(slots):
        h = 200 if s in tall else 100
        out.append(dict(id=f"vol01:{page}:{col}:{s}", slot=s, cell_type="char", char=text[i], admit=True,
                        bbox_page=[0, s * 100, 80, s * 100 + h]))
    return out


def _book(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    s18 = list(range(1, 19))
    _jsonl(corpus / "layout_slots.jsonl", [dict(vol="vol01", page=1, col=c, slots=s18) for c in (1, 2, 3)])
    _jsonl(corpus / "page_map.jsonl", [dict(vol="vol01", page=1, dzg_id="d1", side=0)])
    _jsonl(corpus / "0001.jsonl", [dict(id="d1", cols=[
        dict(no=c - 1, runs=[dict(t="text", start=0, s=TEXT)]) for c in (1, 2, 3)])])
    root = tmp_path / "products"
    _write(root / "vol01/column_gate/p0001.json", "gate", dict(column_widths=[100, 100, 40]))
    cols = [
        dict(col=1, chars=_chars(1, 1, s18, TEXT)),                       # 好列
        dict(col=2, chars=_chars(1, 2, s18[:-1], TEXT[:-1], tall={5})),  # 少一格、第 5 格挤两字
        dict(col=3, chars=_chars(1, 3, s18, TEXT[2:] + "XX")),           # 字整体错两格
    ]
    _write(root / "vol01/cell_shrink/p0001.json", "char_index", dict(columns=cols))
    _write(root / "vol01/seed_admit/p0001.json", "seed_admit", dict(columns=cols))
    return root, corpus


def test_level1_flags_each_kind_once(tmp_path):
    root, corpus = _book(tmp_path)
    r = _MOD.level1(root, "vol01", _MOD.Ref(corpus))
    assert r["cols"] == 3
    assert r["colnet_pages"] == [1]
    assert r["layout_miss"] == [(1, 2)]
    assert r["merged_cols"] == [(1, 2)]
    assert r["text_shift"] == [(1, 3)]
