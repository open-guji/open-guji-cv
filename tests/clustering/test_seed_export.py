"""种子审查页面侧测试：批次装配 / HTML 渲染 / 事件解析往返。

全部用合成 SeedItem + 小合成图块，不依赖真实大数据。
"""

import base64
import json

import cv2
import numpy as np
import pytest

from open_guji_cv.clustering.seed_queue import (
    DOUBT_DEGRADED_CROP, DOUBT_LABELS, DOUBT_NEAR_FORM, DOUBT_REPLACE_ALIGN,
    DOUBT_SIGNAL_CONFLICT, SEED_EVENT_PREFIX, STATUS_CONFIRMED,
    STATUS_SKIPPED, SeedItem)
from open_guji_cv.clustering.review.seed_export import (
    build_seed_batch, export_seed_batch, ingest_seed_events, render_seed_html)


# ── fixture：合成书目录 + 队列 ───────────────────────────────────────

def _make_patch(path, seed=0):
    """小合成灰度图块：白底 + 几笔深色横竖（足够让 normalize 有墨迹）。"""
    rng = np.random.default_rng(seed)
    img = np.full((48, 44), 230, dtype=np.uint8)
    img[10:14, 8:36] = 30                       # 横
    img[10:40, 20:24] = 30                      # 竖
    img += rng.integers(0, 8, img.shape, dtype=np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img)


def _item(book, page, col, idx, **kw):
    iid = f"{book}:{page}:{col}:{idx}"
    d = dict(instance_id=iid, book=book, page=str(page), col=col, idx=idx,
             patch_path=f"patches/{page}/{col}_{idx}.png", tier="clean")
    d.update(kw)
    return SeedItem(**d)


@pytest.fixture()
def seed_book(tmp_path):
    """合成 output/<book>/：phase4_chars 图块 + phase9_seed/queue.jsonl。

    第 4 页 3 条待审（含 1 条 skipped）+ 1 条已裁决；第 5 页 2 条待审；
    另有 2 条 auto_admitted 撑全书进度。
    """
    book_dir = tmp_path / "tbook"
    items = [
        _item("tbook", 4, 1, 0,
              ocr={"char": "諭", "prob": 0.62,
                   "topk": [["諭", 0.62], ["論", 0.31], ["喻", 0.04]]},
              align={"char": "論", "op": "replace"},
              doubts=[DOUBT_SIGNAL_CONFLICT, DOUBT_NEAR_FORM,
                      DOUBT_REPLACE_ALIGN],
              match={"verdict": "unsure", "char": None, "matched_id": None,
                     "cov": 0.973, "wmax": 0.1,
                     "candidates": [["論", 0.981], ["諭", 0.973]],
                     "guard": "never_match", "n_verified": 6}),
        _item("tbook", 4, 2, 3,
              ocr={"char": "彖", "prob": 0.18},
              align=None, tier="degraded",
              doubts=[DOUBT_DEGRADED_CROP],
              status=STATUS_SKIPPED),
        _item("tbook", 4, 2, 5,
              ocr={"char": "欽", "prob": 0.97},
              align={"char": "欽", "op": "equal"},
              proposed="欽",
              doubts=[DOUBT_REPLACE_ALIGN]),
        _item("tbook", 4, 3, 1, status=STATUS_CONFIRMED, decided_char="天",
              provenance="human"),
        _item("tbook", 5, 1, 0,
              ocr={"char": "大", "prob": 0.88},
              align={"char": "太", "op": "replace"},
              doubts=[DOUBT_SIGNAL_CONFLICT, DOUBT_NEAR_FORM]),
        _item("tbook", 5, 1, 1,
              ocr={"char": "問", "prob": 0.91},
              align={"char": "間", "op": "replace"},
              doubts=[DOUBT_SIGNAL_CONFLICT]),
        _item("tbook", 3, 1, 0, status="auto_admitted", proposed="王",
              provenance="align"),
        _item("tbook", 3, 1, 1, status="auto_admitted", proposed="臣",
              provenance="align"),
    ]
    for i, it in enumerate(items):
        _make_patch(book_dir / "phase4_chars" / it.patch_path, seed=i)
    qdir = book_dir / "phase9_seed"
    qdir.mkdir(parents=True)
    (qdir / "queue.jsonl").write_text(
        "\n".join(it.to_json() for it in items) + "\n", encoding="utf-8")
    return book_dir


def _queue(book_dir):
    return book_dir / "phase9_seed" / "queue.jsonl"


# ── 批次装配 ─────────────────────────────────────────────────────────

def test_build_batch_filters_page_and_status(seed_book):
    batch = build_seed_batch(seed_book, _queue(seed_book), page=4)
    ids = [e["instance_id"] for e in batch["entries"]]
    # 第 4 页的 pending + skipped 都出，已裁决的不出
    assert ids == ["tbook:4:1:0", "tbook:4:2:3", "tbook:4:2:5"]
    assert batch["page"] == "4"
    assert batch["batch_id"].startswith("tbook-seed-4-")
    # 进度口径：页含已裁决底数；全书含 auto_admitted
    assert batch["page_total"] == 4 and batch["page_done"] == 1
    assert batch["book_total"] == 8 and batch["book_done"] == 3


def test_build_batch_default_page_is_first_pending(seed_book):
    # 无 progress.json → 页号最小的待审页（第 3 页全 auto_admitted，跳过）
    batch = build_seed_batch(seed_book, _queue(seed_book))
    assert batch["page"] == "4"


def test_build_batch_follows_progress_pointer(seed_book):
    (_queue(seed_book).parent / "progress.json").write_text(
        json.dumps({"current_page": 5}), encoding="utf-8")
    batch = build_seed_batch(seed_book, _queue(seed_book))
    assert batch["page"] == "5"
    assert len(batch["entries"]) == 2


def test_build_batch_images_decode(seed_book):
    batch = build_seed_batch(seed_book, _queue(seed_book), page=4)
    e = batch["entries"][0]
    raw = base64.b64decode(e["patch_b64"])
    assert raw[:4] == b"\x89PNG", "patch_b64 不是合法 PNG"
    # 三轮起不再放归一图（实审反馈：对人眼定字没有用）
    assert "norm_b64" not in e


def test_build_batch_doubt_labels_complete(seed_book):
    batch = build_seed_batch(seed_book, _queue(seed_book), page=4)
    e = batch["entries"][0]
    codes = {d["code"] for d in e["doubts"]}
    assert codes == {DOUBT_SIGNAL_CONFLICT, DOUBT_NEAR_FORM,
                     DOUBT_REPLACE_ALIGN}
    for d in e["doubts"]:
        assert d["label"] == DOUBT_LABELS[d["code"]]   # 说明齐全且来自契约
        assert 1 <= d["no"] <= 6                       # 设计文档表格编号


def test_build_batch_choices_order_and_merge(seed_book):
    batch = build_seed_batch(seed_book, _queue(seed_book), page=4)
    e0 = batch["entries"][0]           # 諭/論 冲突条
    chars = [c["char"] for c in e0["choices"]]
    assert chars[0] == "諭"            # OCR top1 先（无 proposed）
    assert set(chars) == {"諭", "論", "喻"}
    lun = next(c for c in e0["choices"] if c["char"] == "論")
    # 同字合并保留各源数值：OCR prob + 对齐 op + 库内 cov
    assert lun["ocr_prob"] == 0.31
    assert lun["align_op"] == "replace"
    assert lun["db_cov"] == 0.981
    e2 = next(e for e in batch["entries"]
              if e["instance_id"] == "tbook:4:2:5")
    assert e2["choices"][0]["char"] == "欽" and e2["choices"][0]["proposed"]


def test_build_batch_errors_are_clear(seed_book, tmp_path):
    with pytest.raises(FileNotFoundError, match="种子队列不存在"):
        build_seed_batch(seed_book, tmp_path / "nope" / "queue.jsonl")
    empty = tmp_path / "queue.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="空"):
        build_seed_batch(seed_book, empty)
    with pytest.raises(ValueError, match="没有第 99 页"):
        build_seed_batch(seed_book, _queue(seed_book), page=99)


# ── HTML 渲染 ────────────────────────────────────────────────────────

def test_render_html_core_elements(seed_book):
    batch = build_seed_batch(seed_book, _queue(seed_book), page=4)
    page = render_seed_html(batch)
    assert SEED_EVENT_PREFIX in page                  # 事件前缀进了 JS
    for e in batch["entries"]:
        assert e["instance_id"] in page               # 全部 instance_id
    assert batch["batch_id"] in page
    assert "data:image/png;base64," in page
    # 页头进度（本页 + 全书）
    assert 'id="prog"' in page and 'id="bookprog"' in page
    # 疑问码中文说明上了页面
    assert DOUBT_LABELS[DOUBT_SIGNAL_CONFLICT] in page
    # 对齐 op 徽标与库内 cov
    assert "replace" in page and "cov" in page


def test_render_html_theme_tokens_three_states(seed_book):
    page = render_seed_html(build_seed_batch(seed_book, _queue(seed_book),
                                             page=4))
    assert "prefers-color-scheme: dark" in page
    assert ':root:not([data-theme="light"])' in page
    assert ':root[data-theme="dark"]' in page


def test_render_html_persistence_wiring(seed_book):
    """三层持久化（二轮：整页 publish(html)）：日志内嵌 + localStorage + 兜底。

    一轮的 files 形式（publish({'seed_events.txt':…})）对单文件 artifact
    拒 capability_disabled（vol01 第 4 页实测）——改整页快照发布，
    日志内嵌页面自身，恢复不再走 fetch。
    """
    page = render_seed_html(build_seed_batch(seed_book, _queue(seed_book),
                                             page=4))
    assert "snapshotHtml" in page                     # 整页快照发布
    assert "ns.publish(snapshotHtml())" in page
    assert "seed_events.txt'" not in page.replace(    # files 形式已废
        ".seed_events.txt", "")                       # （下载文件名除外）
    assert "fetch(" not in page                       # 恢复不走网络
    assert "sessionStorage" in page                   # 重载前后视图接续
    assert "localStorage" in page                     # 崩溃备份
    assert "navigator.clipboard" in page              # 复制主路径
    assert 'id="dl"' in page and "selectLog" in page  # 下载/全选兜底
    assert "withTimeout" in page                      # promise 悬空防卡死
    assert '#save-status[data-bad="1"]' in page       # 保存失效红底显眼


def test_render_html_single_key_ops(seed_book):
    page = render_seed_html(build_seed_batch(seed_book, _queue(seed_book),
                                             page=4))
    for frag in ("'not_a_char'", "'skip'", "'confirm'", "undoStack",
                 "e.key >= '1' && e.key <= '9'"):
        assert frag in page
    assert 'class="reopen"' in page                   # 已裁决可展开复查


def test_render_js_strings_terminated(seed_book):
    """JS 单引号字面量必须闭合（三引号里真换行写坏脚本的回归）。"""
    from open_guji_cv.clustering.review.seed_export import _JS
    bad = [i for i, line in enumerate(_JS.split("\n"), 1)
           if (line.count("'") - line.count("\\'")) % 2]
    assert not bad, f"第 {bad} 行单引号未闭合"


def test_export_writes_file(seed_book, tmp_path):
    out = export_seed_batch(seed_book, _queue(seed_book), page=4,
                            out_path=tmp_path / "r.html")
    assert out.exists()
    assert "guji-log" in out.read_text(encoding="utf-8")


# ── 事件解析往返 ─────────────────────────────────────────────────────

def test_ingest_roundtrip(seed_book):
    """页面发出的事件行 → ingest 解析后与原始决策一致（含去重）。"""
    evs_out = [
        {"op": "confirm", "instance_id": "tbook:4:1:0", "char": "諭",
         "batch": "tbook-seed-4-x", "seq": 1, "ts": "2026-08-23T00:00:00+00:00"},
        {"op": "skip", "instance_id": "tbook:4:2:3",
         "batch": "tbook-seed-4-x", "seq": 2, "ts": "2026-08-23T00:00:01+00:00"},
        {"op": "not_a_char", "instance_id": "tbook:4:2:5",
         "batch": "tbook-seed-4-x", "seq": 3, "ts": "2026-08-23T00:00:02+00:00"},
    ]
    text = ("页面日志前缀噪声\n"
            + "\n".join(f"{SEED_EVENT_PREFIX} {json.dumps(e, ensure_ascii=False)}"
                        for e in evs_out)
            + f"\n{SEED_EVENT_PREFIX} 不是json\n"
            # 重复 (batch,seq)：后到覆盖
            + f'{SEED_EVENT_PREFIX} {json.dumps(dict(evs_out[0], char="論"), ensure_ascii=False)}\n')
    got = ingest_seed_events(text)
    assert len(got) == 3
    by_iid = {e["instance_id"]: e for e in got}
    assert by_iid["tbook:4:1:0"]["op"] == "confirm"
    assert by_iid["tbook:4:1:0"]["char"] == "論"     # (batch,seq) 去重后到覆盖
    assert by_iid["tbook:4:2:3"]["op"] == "skip"
    assert by_iid["tbook:4:2:5"]["op"] == "not_a_char"
    assert ingest_seed_events("") == []
    assert ingest_seed_events("没有事件的文本") == []


def test_render_html_label_only_toggle(seed_book):
    """「字形不入库」拨钮：按钮 + 热键 B + confirm 事件带 admit:false 的接线。"""
    page = render_seed_html(build_seed_batch(seed_book, _queue(seed_book),
                                             page=4))
    assert 'class="noadm"' in page and "字形不入库" in page
    assert "toggleNoAdmit" in page
    assert "ev.admit = false" in page
    assert "'b' || e.key === 'B'" in page
    assert "data-noadmit" in page


def test_context_strip_crosses_columns():
    """列首字：上下文条用上一列末尾补足窗口，邻列字带 adj 样式与界标。"""
    from open_guji_cv.clustering.review.seed_export import _render_context
    e = {"context": {
        "col_ocr": "甲乙丙丁戊己庚辛壬癸子丑", "col_ref": "甲乙丙丁戊己庚辛壬癸子丑",
        "pos": 0, "ref_char": "甲", "ref_op": "equal",
        "prev_ocr": "金木水火土", "prev_ref": "金木水火土",
        "next_ocr": "春夏秋冬", "next_ref": "春夏秋冬"}}
    html_out = _render_context(e)
    assert 'class="adj"' in html_out and 'class="colbrk"' in html_out
    assert "土" in html_out                      # 上一列末字接上了
    assert "春" not in html_out                  # 列首不需要下一列
    # 列尾字：反向
    e["context"]["pos"] = 11
    html_out = _render_context(e)
    assert "春" in html_out and "土" not in html_out


def test_confusable_candidates_get_hints(seed_book):
    """同卡出现同形字组两员（日/曰）→ 按钮加读音/用例提示。"""
    from open_guji_cv.clustering.review.seed_export import (
        _confusable_hints_for, _render_seed_card)
    hints = _confusable_hints_for(["日", "曰", "修"])
    assert hints["日"].startswith("rì") and hints["曰"].startswith("yuē")
    assert "修" not in hints                      # 组外不加注
    assert _confusable_hints_for(["日", "修"]) == {}   # 单独出现不加注
    e = {"instance_id": "t:1:1:1", "col": 1, "idx": 1, "tier": "clean",
         "status": "pending_review", "patch_b64": None,
         "choices": [
             {"char": "日", "ocr_prob": 0.18, "align_op": None,
              "ref_op": None, "db_cov": 0.96, "proposed": True},
             {"char": "曰", "ocr_prob": None, "align_op": None,
              "ref_op": "replace", "db_cov": None, "proposed": False}],
         "ocr": None, "align": None, "doubts": [], "db": None,
         "context": None, "note": None}
    card = _render_seed_card(e)
    assert "rì 日月" in card and "yuē 子曰" in card


def test_recrop_event_is_parsed_and_validated():
    """recrop 事件：bbox 必须是四个数且右下大于左上，坏框宁可丢掉。"""
    from open_guji_cv.clustering.seed_queue import parse_seed_events
    good = ('GUJI-SEED-EVENT {"op":"recrop","instance_id":"b:5:2:15",'
            '"char":"言","bbox":[1304,1753,1473,1913],"batch":"x","seq":1}')
    assert len(parse_seed_events(good)) == 1
    for bad in ('"bbox":[1,2,3]', '"bbox":[9,9,1,1]', '"bbox":"nope"'):
        line = ('GUJI-SEED-EVENT {"op":"recrop","instance_id":"b:5:2:15",'
                f'"char":"言",{bad},"batch":"x","seq":2}}')
        assert parse_seed_events(line) == []


def test_multi_page_batch(tmp_path):
    """--page 14,15 连审两页：卡片按页→列→字位排序，页号写成 14+15。"""
    from open_guji_cv.clustering.review.seed_export import build_seed_batch
    from open_guji_cv.clustering.seed_queue import STATUS_PENDING, SeedItem
    d = tmp_path / "tb" / "phase9_seed"
    d.mkdir(parents=True)
    rows = [SeedItem(instance_id=f"tb:{pg}:1:{i}", book="tb", page=pg, col=1,
                     idx=i, patch_path="p.png", tier="clean",
                     status=STATUS_PENDING)
            for pg in ("15", "14") for i in (1, 0)]
    (d / "queue.jsonl").write_text(
        "".join(r.to_json() + "\n" for r in rows), encoding="utf-8")
    b = build_seed_batch(tmp_path / "tb", d / "queue.jsonl", page="14,15")
    assert b["page"] == "14+15"
    assert [e["instance_id"] for e in b["entries"]] == [
        "tb:14:1:0", "tb:14:1:1", "tb:15:1:0", "tb:15:1:1"]


def test_card_shows_column_sequence_not_raw_idx(tmp_path):
    """卡头的「第几字」= 该列 char 的实际位次（1 起），不是格号 idx。

    idx 是格号：空格位也占号、从 0 起。拿它当序号，用户对着原图数会
    错位（2026-08-25 实锤）。context.pos 也不行——那按 OCR 载体算，
    载体缺格时同样对不上。
    """
    from open_guji_cv.clustering.review.seed_export import render_seed_html
    e = {"instance_id": "b:1:2:5", "col": 2, "idx": 5, "seq": 3,
         "tier": "clean", "intrusion": [], "status": "pending_review",
         "patch_b64": None, "region": None, "choices": [], "ocr": None,
         "align": None, "doubts": [], "context": None, "match": None,
         "proposed": None}
    html = render_seed_html({"book": "b", "page": "1", "batch_id": "t",
                             "entries": [e], "n_done": 0, "n_total": 1,
                             "page_total": 1, "page_done": 0,
                             "book_total": 1, "book_done": 0,
                             "pages_pending": []})
    assert "第2列第3字" in html          # seq，不是 idx+1=6，也不是 5


def test_stale_context_is_dropped_not_rendered():
    """队列行的 context 与 index 口径对不上（旧切分算的）→ 整块摘掉。

    实锤 vol01:4:2:20：卡片图块是「第」，context 却是旧切分的，pos 指到
    下一格的「一」。宁可少显示一条辅助信息，也不能给一条错位的高亮。
    """
    from open_guji_cv.clustering.review.seed_export import _checked_context

    class _It:
        context = {"col_ocr": "甲乙丙丁", "col_ref": "甲乙丙丁", "pos": 3}

    it = _It()
    assert _checked_context(it, 4) == it.context      # pos == seq-1 → 留
    assert _checked_context(it, 3) is None            # 错一位 → 摘
    assert _checked_context(it, None) == it.context   # 没有 index 就别管


def test_mobile_shrink_and_scroll_hide_top_bar():
    """手机端：字号缩一档 + 顶栏滚动收起。

    用户 2026-08-26 手机实拍反馈：标题「vol01 种子审查 · 第41+…+50页」
    在窄屏折成三行，加上两条进度与两个按钮，顶栏吃掉小半屏——而审字时
    这些一个都用不上。
    """
    from open_guji_cv.clustering.review.seed_export import render_seed_html
    e = {"instance_id": "b:1:2:5", "col": 2, "idx": 5, "seq": 3,
         "tier": "clean", "intrusion": [], "status": "pending_review",
         "patch_b64": None, "region": None, "choices": [], "ocr": None,
         "align": None, "doubts": [], "context": None, "match": None,
         "proposed": None}
    html = render_seed_html({"book": "b", "page": "1", "batch_id": "t",
                             "entries": [e], "n_done": 0, "n_total": 1,
                             "page_total": 1, "page_done": 0,
                             "book_total": 1, "book_done": 0,
                             "pages_pending": []})
    # 手机断点存在，且标题单行截断（不折成三行）
    assert "@media (max-width: 640px)" in html
    assert "text-overflow:ellipsis" in html
    # 顶栏可收起：样式 + 驱动它的滚动逻辑，缺一不可
    assert '.top[data-hide="1"]{transform:translateY(-100%)}' in html
    assert "bar.setAttribute('data-hide'" in html
    # 往上滚要能回来；往下滚没越过阈值时**什么都不做**（不能强制显示，
    # 否则会跟 setActive 的显式收起打架，顶栏又压住卡头）
    assert "if(dy < 0){ bar.setAttribute('data-hide', '0'); return; }" in html
    assert "if(y > bar.offsetHeight * 2) bar.setAttribute('data-hide', '1')" in html


def test_auto_advance_hides_top_bar_and_aligns_tall_cards():
    """裁决完自动前进时：收起顶栏 + 过高的卡片对齐到顶。

    用户 2026-08-26 手机实拍：裁决完自动滚到下一张，sticky 顶栏正压在
    卡片头上，要审的字被挡住。两处一起治——顶栏收起（这一滚是程序发起
    的，用户没在读它），卡片比视口高时用 block:'start' 而不是 'center'
    （否则卡头被顶出屏幕），外加 scroll-margin-top 兜底。
    """
    from open_guji_cv.clustering.review.seed_export import render_seed_html
    e = {"instance_id": "b:1:2:5", "col": 2, "idx": 5, "seq": 3,
         "tier": "clean", "intrusion": [], "status": "pending_review",
         "patch_b64": None, "region": None, "choices": [], "ocr": None,
         "align": None, "doubts": [], "context": None, "match": None,
         "proposed": None}
    html = render_seed_html({"book": "b", "page": "1", "batch_id": "t",
                             "entries": [e], "n_done": 0, "n_total": 1,
                             "page_total": 1, "page_done": 0,
                             "book_total": 1, "book_done": 0,
                             "pages_pending": []})
    assert "if(bar) bar.setAttribute('data-hide', '1');" in html
    assert "tall ? 'start' : 'center'" in html
    assert "scroll-margin-top:3.2rem" in html


def test_mobile_row_stacks_and_recrop_leaves_a_visible_badge():
    """手机窄屏两件事（用户 2026-08-26 实拍两条抱怨）：

    一、「圖片佔了一半的豎排的位置」——原图 + 上下文竖排条 + 主区三者
    横排，412px 宽下 `.cand` 撑到 380px，整页横向溢出到 574px。手机块把
    `.row` 改成竖排堆叠，主区独占整行。

    二、「確認之後它總是彈開，讓我再次重新切分，無限循環」——重切是**几何
    通道**，不定字、不推进，面板一关卡片看着毫无变化，用户以为没生效就
    再切一遍。卡头挂一枚常驻徽章，定字之前一直亮着；重放也要跟着日志
    回来（发布重载之后痕迹不能丢），定案/非字之后自动隐去。
    """
    from open_guji_cv.clustering.review.seed_export import render_seed_html
    e = {"instance_id": "b:1:2:5", "col": 2, "idx": 5, "seq": 3,
         "tier": "clean", "intrusion": [], "status": "pending_review",
         "patch_b64": None, "region": None, "choices": [], "ocr": None,
         "align": None, "doubts": [], "context": None, "match": None,
         "proposed": None}
    html = render_seed_html({"book": "b", "page": "1", "batch_id": "t",
                             "entries": [e], "n_done": 0, "n_total": 1,
                             "page_total": 1, "page_done": 0,
                             "book_total": 1, "book_done": 0,
                             "pages_pending": []})
    # 一：窄屏堆叠，主区不再跟图片抢宽
    assert "@media (max-width: 640px)" in html
    assert "flex-direction:column" in html
    assert ".main{min-width:0;width:100%}" in html
    assert "overflow-x:hidden}   /* 兜底" in html

    # 二：徽章存在、默认收着、只有 data-recropped 才亮、定案后隐去
    assert '<span class="rcbadge">' in html
    assert ".rcbadge{display:none" in html
    assert '.card[data-recropped="1"] .rcbadge{display:inline-block}' in html
    assert ('.card[data-state="done"] .rcbadge,'
            '.card[data-state="nac"] .rcbadge{display:none}') in html
    # 确认重切时挂上；日志重放时挂回来；归零时摘掉（日志是唯一真源）
    assert html.count("card.setAttribute('data-recropped', '1')") >= 2
    assert "else if(ev.op === 'recrop')" in html
    assert "cs[i].removeAttribute('data-recropped');" in html
