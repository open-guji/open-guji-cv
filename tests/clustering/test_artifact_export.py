"""无命令行审查：批次导出 + 事件回收 测试。"""

import base64
import json

from open_guji_cv.clustering.feedback import load_events
from open_guji_cv.clustering.review.artifact_export import (
    build_batch, export_batch, extract_events, ingest_events, render_html)
from open_guji_cv.clustering.review.state import ReviewSession


def test_build_batch(synth_book):
    batch = build_batch(synth_book, limit=5)
    assert batch["entries"], "合成书应有可疑簇"
    assert len(batch["entries"]) <= 5
    assert batch["batch_id"].startswith(batch["book"])
    e = batch["entries"][0]
    # 图块是合法 PNG
    raw = base64.b64decode(e["patches"][0]["b64"])
    assert raw[:4] == b"\x89PNG"
    # 上下文两种模式齐备
    assert e["ctx_compact"]["mode"] == "compact"
    assert e["ctx_full"]["mode"] == "full"


def test_render_html_self_contained(synth_book):
    batch = build_batch(synth_book, limit=5)
    page = render_html(batch)
    assert "guji-log" in page
    assert batch["batch_id"] in page
    for e in batch["entries"]:
        assert e["cluster_id"] in page
    assert "data:image/png;base64," in page
    # 主题令牌三态齐备（防"只在暗色块定义颜色"经典 bug）
    assert "prefers-color-scheme: dark" in page
    assert ':root[data-theme="dark"]' in page
    # 非 Artifact 托管（GitHub Pages）时不报错的能力探测
    assert "window.claude && window.claude.use" in page


def test_export_batch_writes_file(synth_book):
    out = export_batch(synth_book, limit=3)
    assert out.exists() and out.suffix == ".html"
    assert "guji-log" in out.read_text(encoding="utf-8")


def test_extract_events_tolerant():
    text = """随便的前缀 markdown 转写
GUJI-EVENT {"op":"confirm","cluster":"c1","char":"甲","batch":"b","seq":1}
中间噪声 GUJI-EVENT 不是json的行
GUJI-EVENT {"op":"mark","instance":"x:1:0:0","note":"存疑","batch":"b","seq":2}
"""
    evs = extract_events(text)
    assert [e["op"] for e in evs] == ["confirm", "mark"]


def test_ingest_roundtrip_and_dedupe(synth_book):
    s = ReviewSession(synth_book)
    cid = max(s.clusters.values(), key=lambda c: c["size"])["cluster_id"]
    iid = next(iter(s.instances))
    text = (
        f'GUJI-EVENT {json.dumps({"op": "confirm", "cluster": cid, "char": "戊", "batch": "t1", "seq": 1})}\n'
        f'GUJI-EVENT {json.dumps({"op": "mark", "instance": iid, "flag": "uncertain", "batch": "t1", "seq": 2})}\n'
        f'GUJI-EVENT {json.dumps({"op": "confirm", "cluster": "c99999", "char": "错", "batch": "t1", "seq": 3})}\n'
    )
    r1 = ingest_events(synth_book, text)
    assert r1["parsed"] == 3 and r1["new"] == 2
    assert len(r1["errors"]) == 1        # 未知簇不中断，记入 errors

    # 状态生效
    s2 = ReviewSession(synth_book)
    assert s2.cluster_detail(cid)["label"] == "戊"
    assert s2.state.marks.get(iid) == "uncertain"

    # 重复回收 → 全部去重
    r2 = ingest_events(synth_book, text)
    assert r2["new"] == 0 and r2["duplicate"] == 2

    # labels.jsonl 事件保留 batch/seq 供追溯
    evs = load_events(s2.labels_path)
    assert any(e.get("batch") == "t1" and e.get("seq") == 1 for e in evs)


def test_flag_buttons_and_ingest(synth_book):
    """问题按钮渲染 + flag 事件回收。"""
    batch = build_batch(synth_book, limit=5)
    page = render_html(batch)
    for flag in ("truncated", "contaminated", "not_text"):
        assert f'data-flag="{flag}"' in page
    # impure 仅多成员簇显示
    multi = [e for e in batch["entries"] if e["size"] >= 2]
    if not multi:
        assert 'data-flag="impure"' not in page

    s = ReviewSession(synth_book)
    cid = batch["entries"][0]["cluster_id"]
    text = ('GUJI-EVENT '
            + json.dumps({"op": "flag", "cluster": cid,
                          "flag": "contaminated", "batch": "tf", "seq": 1}))
    r = ingest_events(synth_book, text)
    assert r["new"] == 1 and not r["errors"]
    assert ReviewSession(synth_book).cluster_detail(cid)["flag"] == "contaminated"


def test_extract_events_bare_jsonl():
    """下載按钮导出的裸 JSONL（无 GUJI-EVENT 前缀）也能解析。"""
    text = ('{"op":"confirm","cluster":"c1","char":"甲","batch":"b","seq":1}\n'
            '不是json的行\n'
            '{"op":"flag","cluster":"c2","flag":"not_text","batch":"b","seq":2}\n'
            '{"note":"没有op字段"}\n')
    evs = extract_events(text)
    assert [e["op"] for e in evs] == ["confirm", "flag"]


def test_render_html_autosave_wiring(synth_book):
    """自动保存链路：publish 调用 + labels.jsonl 恢复 + localStorage 备份。"""
    page = render_html(build_batch(synth_book, limit=3))
    assert "publish({'labels.jsonl'" in page
    assert "fetch('labels.jsonl')" in page
    assert "localStorage" in page
    assert "save-status" in page
