# -*- coding: utf-8 -*-
"""训好的语言模型跨机分发（2026-10-20）：本机没命中先去 R2 取，取不到才现训；取回的与现训逐项相同。
不连网：`fetch_derived` 换成从另一个目录拷文件的替身。"""
from __future__ import annotations

import shutil

from open_guji_cv.clustering import seeding
from open_guji_cv.datastore import packs


def test_cached_lm_uses_fetched_copy_before_training(tmp_path, monkeypatch):
    book = "欽定四庫全書總目提要" * 20
    # 机器 A：现训并落缓存
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "a"))
    a = seeding.build_seed_lm(book, None)
    (src,) = list((tmp_path / "a" / "general_lm").glob("book-*.json"))
    # 机器 B：本机没有，R2 有（替身从 A 拷）；训练函数一被调就失败
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "b"))
    got = []

    def fake_fetch(kind_dir, name, dest):
        got.append((kind_dir, name))
        if name != src.name:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        return True
    from open_guji_cv.core import derived
    monkeypatch.setattr(derived, "FETCHER", fake_fetch)
    monkeypatch.setattr(seeding, "train_ngram", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该现训")))
    b = seeding.build_seed_lm(book, None)
    assert got == [("lm", src.name)]
    assert b.counts == a.counts and b.vocab == a.vocab


def test_fetch_derived_without_token_is_a_noop(tmp_path, monkeypatch):
    monkeypatch.delenv("GUJI_DATA_TOKEN", raising=False)
    assert packs.fetch_derived("lm", "x.json", tmp_path / "x.json") is False
    monkeypatch.setenv("GUJI_DATA_TOKEN", "t")
    monkeypatch.setenv("GUJI_DERIVED_FETCH", "0")
    assert packs.fetch_derived("lm", "x.json", tmp_path / "x.json") is False


class _MemR2:
    """`packs._call` 的替身：对象存在字典里。"""
    def __init__(self):
        self.objs: dict[str, bytes] = {}

    def __call__(self, src, method, key, data=None, raw=False, **kw):
        if method == "PUT":
            self.objs[key] = bytes(data)
            return {}
        return self.objs[key]


def test_push_and_fetch_file_stream_in_parts_plain_and_gzip(tmp_path, monkeypatch):
    import os
    r2 = _MemR2()
    monkeypatch.setattr(packs, "_call", r2)
    monkeypatch.setattr(packs, "PART_BYTES", 1000)                 # 逼出多段
    f = tmp_path / "big.bin"
    f.write_bytes(os.urandom(2500) + b"\0" * 5000)                 # 后半段可压；压完仍超一段

    for level in (None, 1):
        r2.objs.clear()
        man = packs.push_file("k", f, src=object(), gzip_level=level)
        assert man["bytes"] == 7500 and len(man["parts"]) >= 2
        assert all(p["bytes"] <= 1000 for p in man["parts"])
        assert (man.get("encoding") == "gzip") == (level is not None)
        out = tmp_path / f"out-{level}.bin"
        assert packs.fetch_file("k", out, src=object()) == 7500
        assert out.read_bytes() == f.read_bytes()
    # 某段坏了：不落盘、不留半截
    r2.objs["k/part-000"] = b"x" + r2.objs["k/part-000"][1:]
    bad = tmp_path / "bad.bin"
    import pytest
    with pytest.raises(ValueError):
        packs.fetch_file("k", bad, src=object())
    assert not bad.exists() and not bad.with_suffix(".bin.part").exists()
