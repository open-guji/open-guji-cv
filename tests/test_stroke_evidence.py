"""5b 笔画证据（`clustering.stroke_evidence`，`font.stroke_evidence` 开关）：归一、打分、重排、缺省关、缺资源。
骨架和检测输出都自己造，不读模型文件。"""
import numpy as np
import pytest

from open_guji_cv.clustering import stroke_evidence as SE


def _stroke(cls, x0, y0, x1, y1):
    """一条直笔段 → (类, 中xy, 起xy, 终xy)，0–1 坐标。"""
    return [cls, (x0 + x1) / 2, (y0 + y1) / 2, x0, y0, x1, y1]


def _form(strokes):
    a = np.array(strokes, np.float32)
    pts = a[:, 1:].reshape(-1, 2)
    lo, hi = pts.min(0), pts.max(0)
    a[:, 1:] = ((pts - lo) / np.maximum(hi - lo, 1e-6)).reshape(-1, 6)
    return a[:, 0].astype(np.int64), a[:, 1:]


# 「王」三横一竖，「土」两横一竖，「川」三竖
WANG = [_stroke(0, 0, 0, 1, 0), _stroke(0, .1, .5, .9, .5), _stroke(0, 0, 1, 1, 1), _stroke(1, .5, 0, .5, 1)]
TU = [_stroke(0, .1, .4, .9, .4), _stroke(0, 0, 1, 1, 1), _stroke(1, .5, 0, .5, 1)]
CHUAN = [_stroke(1, 0, 0, 0, 1), _stroke(1, .5, 0, .5, 1), _stroke(1, 1, 0, 1, 1)]
FORMS = {"王": [_form(WANG)], "土": [_form(TU)], "川": [_form(CHUAN)]}


def _det(strokes, score=0.9, scale=100.0, off=14.0, jitter=0.0, seed=0):
    """把 0–1 的笔段摆进 128 图，造成检测输出 [n, 8]：分数, 类, 三点。"""
    r = np.random.default_rng(seed)
    a = np.array(strokes, np.float32)
    out = np.zeros((len(a), 8), np.float32)
    out[:, 0] = score
    out[:, 1] = a[:, 0]
    out[:, 2:] = a[:, 1:] * scale + off + r.normal(0, jitter, (len(a), 6))
    return out


def _se(det):
    return SE.StrokeEvidence(forms=FORMS, detect=lambda imgs: [det for _ in imgs])


def test_book_switch_defaults_off():
    assert SE.book_stroke_evidence(None) == (False, SE.RRF_WEIGHT, "rrf")
    assert SE.book_stroke_evidence({}) == (False, SE.RRF_WEIGHT, "rrf")
    assert SE.book_stroke_evidence({"stroke_evidence": {"enabled": True, "weight": 2}}) == (True, 2.0, "rrf")
    assert SE.book_stroke_evidence({"stroke_evidence": {"enabled": True, "mode": "emb"}}) == (True, SE.DEFAULT_WEIGHT, "emb")
    with pytest.raises(ValueError):
        SE.book_stroke_evidence({"stroke_evidence": {"mode": "x"}})


def test_normalize_drops_duplicates_and_low_scores():
    det = _det(WANG)
    dup = det[:1].copy()
    dup[0, 0] = 0.5
    dup[0, 2:] += 1.0                                   # 同类、三点只差 1 像素：重复检出
    low = det[1:2].copy()
    low[0, 0] = 0.1
    low[0, 2:] += 30
    qc, qp = SE.normalize_strokes(np.vstack([det, dup, low]))
    assert len(qc) == 4 and qp.min() >= 0 and qp.max() <= 1
    assert SE.normalize_strokes(_det(WANG[:2])) is None  # 不足 MIN_STROKES 段


def test_score_prefers_matching_skeleton_and_survives_stretch():
    se = _se(None)
    for scale, jit in ((100.0, 0.0), (70.0, 1.5)):
        det = _det(WANG, scale=scale, jitter=jit)
        det[:, 3::2] *= 1.15                             # 竖向拉长：逐候选对齐要能吃掉
        sc = se.scores(det, ["王", "土", "川", "㐀"])
        assert "㐀" not in sc                             # 索引里没有的字不出分
        assert sc["王"] > sc["土"] > sc["川"]
        assert sc["王"] > 0.8


def test_duplicate_detections_do_not_score_twice():
    qc, qp = SE.normalize_strokes(_det(TU))
    cc, cp = FORMS["王"][0]
    one = SE.match_score(qc, qp, cc, cp)
    extra = np.vstack([qp, qp[:1] + 0.03])               # 多检一条几乎重合的横
    two = SE.match_score(np.append(qc, qc[0]), extra.astype(np.float32), cc, cp)
    assert two <= one + 0.05                             # 一对一匹配：多出来的那条拿不到分


def test_rerank_reorders_without_changing_candidates():
    se = _se(_det(WANG, jitter=1.0))
    row = [("土", 0.80), ("王", 0.795), ("川", 0.77), ("○", 0.76)]
    img = np.full((64, 64), 255, np.uint8)
    out = se.rerank_rows([img], [row], weight=0.1)[0]
    assert out[0] == ("王", 0.795)                        # 余弦差 0.005，被笔画分翻过来
    assert sorted(out) == sorted(row)                    # 候选和各自的余弦都不动
    assert se.rerank_rows([img], [row], weight=0.0)[0] is row
    far = [("土", 0.95), ("王", 0.60)]
    assert se.rerank_rows([img], [far], weight=0.1)[0] == far   # 余弦差得多，轻的一票翻不动


def test_too_few_strokes_or_single_candidate_left_alone():
    img = np.full((64, 64), 255, np.uint8)
    row = [("土", 0.80), ("王", 0.78)]
    assert _se(_det(WANG[:2])).rerank_rows([img], [row], 0.1)[0] == row
    called = []
    se = SE.StrokeEvidence(forms=FORMS, detect=lambda imgs: called.append(len(imgs)) or [])
    assert se.rerank_rows([img], [[("王", 0.9)]], 0.1) == [[("王", 0.9)]]
    assert called == []                                  # 只有一个候选的格不跑检测


def test_missing_resources_warn_once_and_passthrough(tmp_path, capsys):
    se = SE.StrokeEvidence(model_dir=tmp_path)
    assert not se.available
    row = [("土", 0.80), ("王", 0.78)]
    img = np.full((64, 64), 255, np.uint8)
    assert se.rerank_rows([img], [row], 0.1) == [row]
    assert se.rerank_rows([img], [row], 0.1) == [row]
    assert capsys.readouterr().err.count("笔画证据") == 1


def test_rare_for_batch_signature_default_off():
    """`rare_for_batch` 的 `stroke` 缺省 None：不传就不进笔画证据那一支。"""
    import inspect

    from open_guji_cv.clustering.rare_panel import rare_for_batch
    assert inspect.signature(rare_for_batch).parameters["stroke"].default is None


def test_step_declares_code_dep():
    from open_guji_cv.steps.rare_candidates import RareCandidatesStep
    assert "open_guji_cv.clustering.stroke_evidence" in RareCandidatesStep.spec.code_deps


def test_orders_rank_union_and_fuse_as_extra_route():
    """`mode: rrf`：笔画分只给已有候选排名次；进 `_fuse` 当多出来的一路，不带新候选。"""
    from open_guji_cv.clustering.rare_panel import _fuse
    img = np.full((64, 64), 255, np.uint8)
    se = _se(_det(WANG, jitter=1.0))
    order = se.orders([img], [["土", "川", "王", "○"]])[0]
    assert order == ["王", "土", "川"]                     # 没骨架的 ○ 不投票
    assert se.orders([img], [["王"]]) == [[]]
    cls = [("川", 0.9)]
    emb = [("土", 0.80), ("王", 0.79), ("川", 0.70)]
    off = [h["char"] for h in _fuse([], [], cls, emb, 10)]
    assert [h["char"] for h in _fuse([], [], cls, emb, 10, stroke_order=None, stroke_w=0.0)] == off
    assert [h["char"] for h in _fuse([], [], cls, emb, 10, stroke_order=order, stroke_w=0.0)] == off      # 权重 0 = 没这一路
    on = [h["char"] for h in _fuse([], [], cls, emb, 10, stroke_order=order, stroke_w=40.0)]
    assert sorted(on) == sorted(off) and on[0] == "王"


def test_canonical_input_squares_pipeline_patches_and_keeps_library_ones():
    """管线 `char_patch` 是贴格裁的长方块，检测前要转成入库那种 256 方画布；已经是的原样用。"""
    tight = np.full((170, 220), 255, np.uint8)
    tight[10:160, 100:120] = 0                            # 一竖，贴着上下边
    tight[80:95, 5:215] = 0                               # 一横，贴着左右边
    out = SE.canonical_input(tight)
    assert out.shape == (256, 256) and out.dtype == np.uint8
    ys, xs = np.nonzero(out < 128)
    assert xs.min() > 10 and xs.max() < 245 and ys.min() > 10 and ys.max() < 245   # 留出了白边
    w, h = xs.max() - xs.min(), ys.max() - ys.min()
    assert abs(w / h - 210 / 150) < 0.1                    # 等比，没被压成方的
    assert SE.canonical_input(out) is out
    assert SE.canonical_input(np.dstack([tight] * 3)).shape == (256, 256)
