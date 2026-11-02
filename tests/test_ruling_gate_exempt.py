"""大模型裁定（ctx_ruling）按窗口内容键，不随换图源失效：换图源的册也要能写入（2026-10-31，vol31 第34页因此整页失败）。"""


def test_ctx_ruling_passes_rev_gate_even_with_stale_cell_key():
    from open_guji_cv.core.event_files import RevGate
    g = RevGate(books_dir=None)
    g.rev = lambda book: 5                       # 册 yaml 钉 source_rev=5
    target = {"step": "seed_admit", "unit": "cell", "key": "vol31:34:3:17", "book": "vol31", "anchor": None}
    assert g.admits("ctx_ruling", target)
    assert not g.admits("human_verdict", target)   # 人裁等按格的事件仍照旧拦
