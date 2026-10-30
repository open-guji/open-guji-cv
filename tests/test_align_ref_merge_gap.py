"""align_ref 近簇合并锚定（anchor_merge_gap）与 replace 段长上限（replace_max_len），2026-10-30 北行 bxgb。"""
from open_guji_cv.clustering.align_eval import anchor_page, build_ngram_index
from open_guji_cv.clustering.align_label import label_page
from open_guji_cv.steps.align_ref import AlignRefParams, merged_anchor

FILL = "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥"


def _corpus():
    head = "".join(FILL[(i * 7) % len(FILL)] + FILL[(i * 3) % len(FILL)] for i in range(200))
    a = "天地玄黃宇宙洪荒日月盈昃辰宿列張寒來暑往秋收冬藏閏餘成歲律呂調陽雲騰致雨露結爲霜金生麗水玉出崑岡"
    extra = "劍號巨闕珠稱夜光果珍李柰菜重芥薑"   # 整理本多出、刻本删掉的一句（17 字）
    b = "海鹹河淡鱗潛羽翔龍師火帝鳥官人皇始制文字乃服衣裳推位讓國有虞陶唐弔民伐罪周發殷湯坐朝問道垂拱平章"
    return head + a + extra + b + head[::-1], a + b


def _slots(text):
    return [(1 + i // 21, 1 + i % 21, ch) for i, ch in enumerate(text)]


def test_split_clusters_merge():
    corpus, page = _corpus()
    idx = build_ngram_index(corpus)
    # 刻本侧每 10 字毁 1 字，票变稀，前后两半的簇（偏移差 17）互相压制
    noisy = "".join("〇" if i % 10 == 0 else ch for i, ch in enumerate(page))
    assert anchor_page(noisy, idx) is None
    off = merged_anchor(_slots(noisy), idx, 40)
    assert off is not None and corpus[off:off + 4] == page[:4]
    labs, ok = label_page("1", _slots(noisy), "t", corpus, idx, offset=off)
    assert ok and sum(lab.op == "equal" for lab in labs) > len(page) // 2


def test_merge_gap_off_by_default(tmp_path):
    f = tmp_path / "c.txt"
    f.write_text("天地玄黃", encoding="utf-8")
    d = AlignRefParams(corpus=str(f)).model_dump()
    assert "anchor_merge_gap" not in d and "replace_max_len" not in d
    d2 = AlignRefParams(corpus=str(f), anchor_merge_gap=40, replace_max_len=12).model_dump()
    assert d2["anchor_merge_gap"] == 40 and d2["replace_max_len"] == 12


def test_replace_max_len():
    corpus, page = _corpus()
    idx = build_ngram_index(corpus)
    hyp = page[:20] + "〇〇〇〇〇" + page[25:]          # 5 字长段认错，两头 equal 夹住
    ids = lambda labs: {lab.instance_id for lab in labs}
    got3, ok = label_page("1", _slots(hyp), "t", corpus, idx)
    got12, _ = label_page("1", _slots(hyp), "t", corpus, idx, max_replace_len=12)
    assert ok
    new = ids(got12) - ids(got3)
    assert len(new) == 5
    assert {lab.char for lab in got12 if lab.instance_id in new} == set(page[20:25])
