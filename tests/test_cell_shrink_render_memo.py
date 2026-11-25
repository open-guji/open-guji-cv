"""cell_shrink 再生字块的按页记忆（2026-11-03 整列抽字、2026-11-05 cells 产物与列图）：
缓存清空后逐格再生的字块，记忆开（戳取得到）与关（戳取不到）都与 Step4 当初写进缓存的逐像素相同。"""
import numpy as np


def test_regenerated_patches_match_with_and_without_memo(tmp_path, monkeypatch, ws, fixture_page):
    from helpers import run_keben_from_raw

    from open_guji_cv.core.book import load_book
    from open_guji_cv.steps import cell_shrink
    from open_guji_cv.utils.image_io import imread

    ctx, _ = run_keben_from_raw(tmp_path, monkeypatch, book=load_book("keben"), gray=fixture_page)
    chars = ctx.product("char_index", 1)
    keys = [r.patch_key for c in chars.columns if c.ok for r in c.chars if r.patch_key]
    assert len(keys) > 50
    d = ctx.cache.root / ctx.book.id / "char_patch"
    orig = {k: imread(str(d / f"{k}.png"), 0, strict=True) for k in keys}

    def regen():
        for f in d.glob("*.png"):
            f.unlink()
        cell_shrink._RENDER_MEMO.clear()
        return {k: ctx.image("char_patch", k) for k in keys}

    off = regen()                                    # 测试产物没有 manifest：戳取不到、不记忆
    assert not cell_shrink._RENDER_MEMO

    class _E:
        status, sha256 = "ok", "cells-sha"

    class _M:
        def get(self, _k):
            return _E()

    real_manifest = ctx.store.manifest
    monkeypatch.setattr(ctx, "cache_stamp", lambda kind, key: f"stamp-{kind}")
    monkeypatch.setattr(ctx.store, "manifest",
                        lambda b, s: _M() if s == ctx.producer("cells").spec.id else real_manifest(b, s))
    on = regen()
    memo = next(iter(cell_shrink._RENDER_MEMO.values()))
    assert "cells" in memo and memo["imgs"]          # 记忆真的用上了
    for k in keys:
        assert np.array_equal(off[k], orig[k]), k
        assert np.array_equal(on[k], orig[k]), k


def test_inner_memo_key_follows_product_stamps(tmp_path, monkeypatch):
    """`_INNER_MEMO` 的键带 cells／column_windows 产物 sha：产物换了（重跑、换配置）键就变，旧页内框线不串；没戳不记。"""
    from helpers import make_book, make_ctx

    import open_guji_cv.steps  # noqa: F401
    from open_guji_cv.core.step import STEPS

    ctx = make_ctx(tmp_path, make_book(expected_cols=9), raw={})
    step = STEPS["cell_shrink"]
    assert step._inner_memo_key(ctx, 1) is None            # 没有产物 manifest

    sha = {"v": "a"}

    class _E:
        status = "ok"

        @property
        def sha256(self):
            return sha["v"]

    class _M:
        def get(self, _k):
            return _E()

    monkeypatch.setattr(ctx.store, "manifest", lambda b, s: _M())
    k1 = step._inner_memo_key(ctx, 1)
    sha["v"] = "b"
    k2 = step._inner_memo_key(ctx, 1)
    assert k1 is not None and k1 != k2
