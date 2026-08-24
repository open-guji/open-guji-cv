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
    """自动保存链路：publish 调用 + 恢复 fetch + localStorage 备份。"""
    page = render_html(build_batch(synth_book, limit=3))
    assert "ns.publish({'labels.txt'" in page
    assert "fetch('labels.txt')" in page
    assert "localStorage" in page
    assert "save-status" in page


def test_export_button_always_visible_with_fallback(synth_book):
    """导出按钮始终可见；能力不可用时退回「全选日志供复制」。"""
    page = render_html(build_batch(synth_book, limit=3))
    assert 'id="dl"' in page and 'id="dl" hidden' not in page
    assert "selectLog" in page          # 兜底路径存在
    assert "Ctrl/Cmd+C" in page


def test_events_carry_members_for_remap(synth_book):
    """簇级事件带成员实例 id，重跑聚类后可重绑。"""
    batch = build_batch(synth_book, limit=3)
    assert all(e["members"] for e in batch["entries"])
    page = render_html(batch)
    assert "data-members=" in page


def test_publish_uses_inferable_extension_and_type(synth_book):
    """保存文件名必须用平台能推断类型的副檔名并显式给 contentType。

    回归：用过 labels.jsonl —— 平台推断不出类型，publish 被判
    invalid_content 直接拒绝，整批审查静默丢失。
    """
    page = render_html(build_batch(synth_book, limit=3))
    assert "'labels.txt'" in page
    assert "contentType: 'text/plain'" in page
    assert "publish({'labels.jsonl'" not in page
    assert "fetch('labels.txt')" in page


def test_save_failure_is_loud(synth_book):
    """保存失效必须显眼并带错误码（上一轮灰色小字导致用户没察觉）。"""
    page = render_html(build_batch(synth_book, limit=3))
    assert "自動儲存失效（" in page      # 错误码进入提示
    assert 'data-bad' in page            # 触发红底样式
    assert '#save-status[data-bad="1"]' in page


def test_no_unsettled_promise_can_hang_status(synth_book):
    """平台 promise 永不落地时必须超时报错，不能停在中间态。

    回归：用户看到「未儲存」卡死——publish 的 promise 悬着，
    状态机没有任何出口。
    """
    page = render_html(build_batch(synth_book, limit=3))
    assert "withTimeout" in page
    assert "publish_timeout" not in page      # 由 tag 参数拼出，不硬编码
    assert "'publish')" in page and "'use')" in page


def test_copy_is_primary_path(synth_book):
    """复制不依赖任何平台能力，且未导出记录要醒目。"""
    page = render_html(build_batch(synth_book, limit=3))
    assert 'id="copybar"' in page
    assert "navigator.clipboard" in page
    assert "條未匯出" in page
    assert '#copybar[data-pending="1"]' in page


def test_js_has_no_unterminated_string(synth_book):
    """JS 字面量不得含真换行（Python 三引号里 \n 未转义会写坏脚本）。"""
    from open_guji_cv.clustering.review.artifact_export import _JS
    bad = [i for i, line in enumerate(_JS.split("\n"), 1)
           if (line.count("'") - line.count("\\'")) % 2]
    assert not bad, f"第 {bad} 行单引号未闭合"


def test_multi_book_batch_keys_and_dispatch(synth_book, tmp_path):
    """多册批次：DOM 键含册前缀防重号；事件按 book 分派回收。"""
    batch = build_batch([synth_book, synth_book], limit=6)
    assert batch["books"] == [synth_book.name]      # 同一册两次 → 去重后一册
    page = render_html(batch)
    assert f'data-book="{synth_book.name}"' in page
    assert f'data-cid="{synth_book.name}|' in page
    assert "ev.book = parts[0]" in page             # JS 拆册

    # 外册事件不应被本册收下
    s = ReviewSession(synth_book)
    cid = next(iter(s.clusters))
    text = "\n".join([
        "GUJI-EVENT " + json.dumps({"op": "confirm", "cluster": cid,
                                    "char": "甲", "book": synth_book.name,
                                    "batch": "mb", "seq": 1}),
        "GUJI-EVENT " + json.dumps({"op": "confirm", "cluster": "cXXX",
                                    "char": "乙", "book": "other_book",
                                    "batch": "mb", "seq": 2}),
    ])
    r = ingest_events(synth_book, text)
    assert r["new"] == 1 and r["other_books"] == 1 and not r["errors"]


def test_candidates_carry_gloss_annotations():
    """候选注记：释义/拼音随 gloss 表出现，候选间异体/通假关系要标出来。"""
    from open_guji_cv.clustering.review.artifact_export import _with_gloss

    cands = [{"char": "仍", "p": 0.6}, {"char": "乃", "p": 0.3},
             {"char": "為", "p": 0.1}]
    out = _with_gloss(cands)
    assert [c["char"] for c in out] == ["仍", "乃", "為"]   # 顺序与内容不变
    rel_of = {c["char"]: c.get("rel", []) for c in out}
    assert any(r["char"] == "乃" and r["kind"] == "通假"
               for r in rel_of["仍"])                        # 仍↔乃 通假
    assert all(r["char"] != "為" for r in rel_of["仍"])      # 无关字不标
    # gloss 表在（本仓库随带 unihan 层）→ 拼音应就位；表缺失时允许降级
    from open_guji_cv.gloss import gloss_of
    if gloss_of("仍"):
        assert out[0]["py"]


def test_render_candidates_includes_rel_and_gloss():
    from open_guji_cv.clustering.review.artifact_export import (
        _render_candidates, _with_gloss)
    html = _render_candidates({"candidates": _with_gloss(
        [{"char": "仍", "p": 0.6}, {"char": "乃", "p": 0.4}])})
    assert "通假" in html and 'class="cand"' in html
