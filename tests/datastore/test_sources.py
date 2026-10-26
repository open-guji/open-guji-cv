"""原图页图（datastore/sources.py）：生成、发布、换页、取回，全部用假 Worker 与本地缓存，不上网。"""
import io
import json
import zipfile

import pytest
from PIL import Image

from open_guji_cv.datastore import sources as S
from open_guji_cv.datastore.client import BlobCache, CentralError


class FakeSrc:
    """只认 /v1/packs（正式桶），按名字只增不改，同名再存回 409。"""
    branch = "main"

    def __init__(self):
        self.objs = {}

    def _call(self, method, path, query=None, data=None, raw=False, **kw):
        import urllib.parse
        assert query["bucket"] == "main"
        if path == "/v1/packs":
            pre = query["prefix"]
            return {"packs": [{"key": k, "bytes": len(v)} for k, v in sorted(self.objs.items()) if k.startswith(pre)]}
        key = urllib.parse.unquote(path[len("/v1/packs/"):])
        if method == "PUT":
            if key in self.objs:
                raise CentralError(409, "exists", key)
            self.objs[key] = data
            return {"key": key}
        if key not in self.objs:
            raise CentralError(404, "not_found", key)
        return self.objs[key]


def _tif(w, h, mode="1", ink=(5, 5)):
    im = Image.new(mode, (w, h), 1 if mode == "1" else 255)
    im.putpixel(ink, 0)
    b = io.BytesIO()
    im.save(b, "TIFF")
    return b.getvalue()


def _zip(tmp_path, leaves):
    p = tmp_path / "x_tif.zip"
    with zipfile.ZipFile(p, "w") as z:
        for i, data in enumerate(leaves, 1):
            z.writestr(f"x_tif/x_{i:04d}.tif", data)
    return p


def test_encode_matches_rgb_png_rule():
    im = Image.open(io.BytesIO(_tif(40, 60)))
    b = io.BytesIO()
    im.convert("RGB").save(b, "PNG")
    assert S.encode_page(im) == b.getvalue()          # 殿本线上原图就是这么转的（模块头）


def test_build_splits_and_numbering(tmp_path):
    z = _zip(tmp_path, [_tif(30, 40), _tif(80, 40), _tif(30, 40)])
    pages, blobs = S.build_from_zip(z, splits={2: [{"part": "a", "crop": [40, 0, 40, 40]},
                                                   {"part": "b", "crop": [0, 0, 40, 40]}]})
    assert [p["seq"] for p in pages] == ["0001", "0002a", "0002b", "0003"]
    assert [p["page"] for p in pages] == [1, 2, 3, 4]
    assert pages[1]["ops"] == [{"crop": [40, 0, 40, 40]}] and (pages[1]["w"], pages[1]["h"]) == (40, 40)
    assert all(S.sha256(blobs[p["sha256"]]) == p["sha256"] for p in pages)
    sus = S.check_pages([{**p, "seq": "0009"} if p["seq"] == "0001" else p for p in pages]
                        + [{"seq": "0010", "page": 5, "w": 80, "h": 40, "sha256": "0" * 64}])
    assert [p["seq"] for p in sus] == ["0010"]        # 宽的那页报疑似合扫；已拆的 a/b 不报


def test_rotate_clockwise():
    im = Image.new("L", (20, 10), 255)
    out = S.apply_ops(im, [{"rotate": 90}])
    assert out.size == (10, 20)
    with pytest.raises(ValueError):
        S.apply_ops(im, [{"rotate": 45}])


def _publish(src, pages, blobs, uploaded, **kw):
    t = S.new_table("96mid1ogzk", "11", ws="ws-x", book="vol11", sources=[], pages=pages, **kw)
    return S.publish(src, t, blobs, by="test", why="t", upload=lambda b: uploaded.update(b))


def test_publish_replace_pull_roundtrip(tmp_path):
    src = FakeSrc()
    z = _zip(tmp_path, [_tif(30, 40), _tif(30, 40, ink=(7, 7))])
    pages, blobs = S.build_from_zip(z)
    up = {}
    r1 = _publish(src, pages, blobs, up)
    assert r1["rev"] == 1 and r1["prev"] is None and r1["changed"] == ["0001", "0002"]
    assert set(up) == {p["sha256"] for p in pages}
    S.write_pointer(src, "ws-x", "vol11", "96mid1ogzk", "vol11")
    S.write_pointer(src, "ws-x", "vol11", "96mid1ogzk", "11")           # 同值再写：跳过
    with pytest.raises(ValueError):
        S.write_pointer(src, "ws-x", "vol11", "96mid1ogzk", "12")
    assert S.resolve(src, "ws-x", "vol11") == ("96mid1ogzk", "11")

    # 换第 2 页（人工处理），页表出 r2，只传新图，旧图不删
    fixed = io.BytesIO()
    Image.new("RGB", (30, 40), (255, 255, 255)).save(fixed, "PNG")
    t2, b2 = S.with_page(S.read_table(src, "96mid1ogzk", "11"), "0002", fixed.getvalue(), "去污", "test")
    for k in ("rev", "prev", "prev_sha256", "created", "by", "why", "changed", "n_pages"):
        t2.pop(k)
    up2 = {}
    r2 = S.publish(src, t2, b2, by="test", why="去污", upload=lambda b: up2.update(b))
    assert r2["rev"] == 2 and r2["changed"] == ["0002"] and set(up2) == set(b2)
    assert r2["pages"][1]["ops"][-1]["manual"] == "去污"
    assert S.revisions(src, "96mid1ogzk", "11") == [1, 2]

    # 取回：缓存 → 目标目录；已有且 sha 对的不动；指定旧版能取回旧字节
    store = {**up, **up2}
    cache = BlobCache(tmp_path / "cache")
    dest = tmp_path / "raw" / "vol11"
    res = S.pull(src, S.read_table(src, "96mid1ogzk", "11"), lambda p: dest / f"{p}.png", cache=cache,
                 fetch=lambda shas: {s: store[s] for s in shas})
    assert res == {"written": 2, "kept": 0, "pages": 2, "rev": 2}
    assert (dest / "2.png").read_bytes() == fixed.getvalue()
    mark = json.loads((dest / S.PULL_MARK).read_text(encoding="utf-8"))
    assert mark["rev"] == 2 and mark["pages"]["2"]["seq"] == "0002"
    res = S.pull(src, S.read_table(src, "96mid1ogzk", "11"), lambda p: dest / f"{p}.png", cache=cache,
                 fetch=lambda shas: pytest.fail("缓存已有，不该再取"))
    assert res["kept"] == 2 and res["written"] == 0
    S.pull(src, S.read_table(src, "96mid1ogzk", "11", rev=1), lambda p: dest / f"{p}.png", cache=cache,
           fetch=lambda shas: {s: store[s] for s in shas})
    assert (dest / "2.png").read_bytes() == blobs[pages[1]["sha256"]]


def test_publish_guards(tmp_path):
    src = FakeSrc()
    pages, blobs = S.build_from_zip(_zip(tmp_path, [_tif(30, 40)]))
    with pytest.raises(ValueError, match="不在手边"):
        _publish(src, pages, {}, {})
    bad = [{**pages[0], "seq": "12"}]
    with pytest.raises(ValueError, match="页序不合法"):
        _publish(src, bad, blobs, {})
    gap = [{**pages[0], "page": 3}]
    with pytest.raises(ValueError, match="连续"):
        _publish(src, gap, blobs, {})
    _publish(src, gap, blobs, {}, page_numbering="keep")        # 老册保留原编号
    # 两人同时发布同一版：后到的 409
    src.objs[S.table_key("96mid1ogzk", "11", 2)] = b"{}"
    orig = S.revisions
    try:
        S.revisions = lambda *a: [1]
        with pytest.raises(S.TableConflict):
            _publish(src, pages, blobs, {})
    finally:
        S.revisions = orig


def test_register_local_keeps_bytes(tmp_path):
    d = tmp_path / "vol03"
    d.mkdir()
    for p in (1, 2, 3):
        Image.new("L", (10 + p, 20), 255).save(d / f"{p}.png")
    pages, blobs = S.register_local(d, {1: "0001", 2: "0105a", 3: "0106"}, ops_of_page={2: [{"crop": [0, 0, 1, 1]}]})
    assert [(p["page"], p["seq"]) for p in pages] == [(1, "0001"), (2, "0105a"), (3, "0106")]
    assert all(blobs[p["sha256"]] == (d / f"{p['page']}.png").read_bytes() for p in pages)
    assert pages[1]["ops"] == [{"crop": [0, 0, 1, 1]}]


def test_keys_and_ids():
    assert S.norm_vol("vol3") == "03" and S.norm_vol(11) == "11"
    assert S.table_key("96mid1ogzk", "11", 7) == "source/pages/96mid1ogzk/11/r007.json"
    assert S.orig_key("96mid1ogzk", "11", "a_tif.zip") == "source/orig/96mid1ogzk/11/a_tif.zip"
    with pytest.raises(ValueError):
        S.table_key("../x", "11", 1)


def test_local_source_ascii_key(tmp_path):
    p = tmp_path / "NLC403-312001066864-15647_北行日錄_卷一.pdf"
    p.write_bytes(b"%PDF-1.4")
    rec = S.local_source(p, "https://example.org/x")
    assert rec["file"] == "NLC403-312001066864-15647.pdf" and rec["name"] == p.name
    assert rec["sha256"] == S.sha256(b"%PDF-1.4") and rec["kind"] == "file"
    q = tmp_path / "全唐文.PDF"
    q.write_bytes(b"x")
    assert S.local_source(q)["file"] == S.sha256(b"x")[:16] + ".pdf"     # 名字里没有 ASCII 就用 sha 头


@pytest.mark.skipif(not __import__("shutil").which("ddjvu") or not __import__("shutil").which("cjb2"),
                    reason="没装 djvulibre")
def test_djvu_to_zip_lossless(tmp_path):
    import subprocess
    im = Image.new("1", (64, 48), 1)
    for x in range(10, 30):
        im.putpixel((x, 20), 0)
    im.save(tmp_path / "a.pbm")
    subprocess.run(["cjb2", "-lossless", str(tmp_path / "a.pbm"), str(tmp_path / "a.djvu")], check=True)
    z = tmp_path / "leaves.zip"
    assert S.djvu_to_zip(tmp_path / "a.djvu", z) == 1
    pages, blobs = S.build_from_zip(z)
    assert [p["seq"] for p in pages] == ["0001"]
    out = Image.open(io.BytesIO(blobs[pages[0]["sha256"]]))
    assert out.convert("L").tobytes() == im.convert("L").tobytes()     # JB2 无损页逐像素不变
    assert blobs[pages[0]["sha256"]] == S.encode_page(im)               # 与 IA tif 走同一条编码，sha 相同


def test_commons_source_checks_sha1(tmp_path):
    p = tmp_path / "vol11.djvu"                                    # 本地叫什么都行，R2 里按 Commons 名存
    p.write_bytes(b"AT&TFORM")
    import hashlib
    info = {"title": "File:CADAL06061310 欽定四庫全書總目·卷二十一~卷二十二.djvu", "sha1": hashlib.sha1(b"AT&TFORM").hexdigest(), "timestamp": "2019-12-28T22:55:27Z",
            "url": "https://upload.wikimedia.org/x.djvu"}
    rec = S.commons_source(p, info)
    assert rec["kind"] == "commons" and rec["file"] == "CADAL06061310.djvu" and rec["commons_timestamp"] == info["timestamp"]
    with pytest.raises(ValueError, match="sha1"):
        S.commons_source(p, {**info, "sha1": "0" * 40})


def test_is_fix_only_reader_facing():
    assert S.is_fix({"seq": "0105a", "ops": [{"crop": [0, 0, 1, 1]}]})
    assert S.is_fix({"seq": "0007", "ops": [{"rotate": 90}]})
    assert S.is_fix({"seq": "0007", "ops": [{"manual": "去污", "by": "A30"}]})          # guji source replace 换的图
    assert not S.is_fix({"seq": "0001", "ops": [{"manual": "书脊签，存档时缩小"}]})      # 登记时的存档说明
    assert not S.is_fix({"seq": "0002", "ops": []})


def test_fix_groups_checks_leaves():
    pages = [{"seq": s, "ops": []} for s in ("0001", "0002a", "0002b", "0003")]
    pages[1]["ops"] = pages[2]["ops"] = [{"crop": [0, 0, 1, 1]}]
    groups = S.fix_groups({"pages": pages}, 3)
    assert [(leaf, [p["seq"] for p in ps]) for leaf, ps in groups] == [(2, ["0002a", "0002b"])]
    with pytest.raises(ValueError, match="对不上"):
        S.fix_groups({"pages": pages}, 4)
    with pytest.raises(ValueError, match="对不上"):
        S.fix_groups({"pages": [pages[0], pages[3]]}, 3)


def test_reroot_keeps_old_bytes():
    prev = {"pages": [{"seq": "0001", "page": 1, "sha256": "a", "src": "s1:x", "ops": [{"manual": "书脊"}]},
                      {"seq": "0002a", "page": 2, "sha256": "b", "src": "s1:y", "ops": [{"crop": [0, 0, 1, 1]}]}]}
    new = [{"seq": "0001", "page": 1, "sha256": "A", "src": "s3:n_0001.tif", "ops": []},
           {"seq": "0002", "page": 2, "sha256": "B", "src": "s3:n_0002.tif", "ops": []}]
    pages, kept = S.reroot_pages(prev, new, lambda o, n: o["seq"] != "0001")
    assert kept == ["0001"] and pages[0] == prev["pages"][0]
    assert pages[1] == {"seq": "0002a", "page": 2, "sha256": "b", "src": "s3:n_0002.tif", "ops": []}
    with pytest.raises(ValueError, match="页"):
        S.reroot_pages(prev, new[:1], lambda o, n: True)


@pytest.mark.skipif(not all(__import__("shutil").which(t) for t in ("ddjvu", "cjb2", "djvm", "djvused")),
                    reason="没装 djvulibre")
def test_pack_for_commons_splits_one_leaf(tmp_path):
    import subprocess

    def leaf(w, h, marks):
        im = Image.new("1", (w, h), 1)
        for x, y in marks:
            for d in range(6):
                im.putpixel((x + d, y), 0)
        return im
    leaves = [leaf(40, 60, [(5, 5)]), leaf(80, 120, [(5, 5), (50, 5), (5, 70), (50, 70)]), leaf(40, 60, [(20, 30)])]
    parts = []
    for i, im in enumerate(leaves, 1):
        im.save(tmp_path / f"l{i}.pbm")
        subprocess.run(["cjb2", "-dpi", "300", str(tmp_path / f"l{i}.pbm"), str(tmp_path / f"l{i}.djvu")], check=True)
        parts.append(str(tmp_path / f"l{i}.djvu"))
    root = tmp_path / "root.djvu"
    subprocess.run(["djvm", "-c", str(root), *parts], check=True)
    crops = {"a": [40, 0, 40, 60], "b": [0, 0, 40, 60], "c": [40, 60, 40, 60], "d": [0, 60, 40, 60]}
    blobs, pages = {}, []
    for seq, im, ops in [("0001", leaves[0], [])] + [(f"0002{k}", leaves[1].crop((c[0], c[1], c[0] + c[2], c[1] + c[3])),
                                                       [{"crop": c}]) for k, c in crops.items()] + [("0003", leaves[2], [])]:
        data = S.encode_page(im)
        blobs[S.sha256(data)] = data
        pages.append({"seq": seq, "page": len(pages) + 1, "sha256": S.sha256(data), "ops": ops})
    table = {"book_id": "96mid1ogzk", "vol": "03", "rev": 2, "pages": pages}
    out = tmp_path / "new.djvu"
    res = S.pack_for_commons(table, root, blobs.__getitem__, out)
    assert (res["pages_before"], res["pages_after"]) == (3, 6) and S.djvu_count(out) == 6
    assert res["changes"] == [{"leaf": 2, "seqs": ["0002a", "0002b", "0002c", "0002d"], "pages": [2, 3, 4, 5],
                               "ops": [[{"crop": c}] for c in crops.values()]}]
    msg = S.commons_comment(table, res)
    assert "原第2页" in msg and "3→6" in msg and "96mid1ogzk/03 r002" in msg
    with pytest.raises(ValueError, match="对不上"):                     # 页表缺叶就不出文件
        S.pack_for_commons({**table, "pages": pages[:5]}, root, blobs.__getitem__, tmp_path / "bad.djvu")


@pytest.mark.skipif(not __import__("shutil").which("pdfimages"), reason="没有 pdfimages（poppler-utils）")
def test_pdf_to_zip_keeps_embedded_bytes(tmp_path):
    """PDF 源件（哈佛 DRS 等）：每页一张嵌入图原样抽出（JPEG 字节不变，不重压），按页号排。"""
    ims = [Image.new("RGB", (60 + 10 * i, 40), (200, 180 - 40 * i, 150)) for i in range(3)]
    pdf = tmp_path / "s.pdf"
    ims[0].save(pdf, save_all=True, append_images=ims[1:])
    z = tmp_path / "leaves.zip"
    n, dec = S.source_to_zip(pdf, z)
    assert (n, dec) == (3, "pdfimages")
    names = S.zip_leaves(z)
    assert len(names) == 3 and [S._leaf_no(x, i) for i, x in enumerate(names, 1)] == [1, 2, 3]
    with zipfile.ZipFile(z) as zz:
        assert [Image.open(io.BytesIO(zz.read(x))).size for x in names] == [(60, 40), (70, 40), (80, 40)]


def test_spreads_finds_fold_in_margins(tmp_path):
    """对开图：书脊折痕在天头地脚里是唯一的暗线；版框里另画一条更黑的竖线，不能被它带偏。"""
    from PIL import ImageDraw

    from open_guji_cv.datastore import spreads as SP
    W, H, fold = 1000, 700, 520
    im = Image.new("L", (W, H), 225)
    d = ImageDraw.Draw(im)
    d.rectangle([60, 100, fold - 8, 620], outline=20, width=6)           # 右半叶版框
    d.rectangle([fold + 8, 100, W - 60, 620], outline=20, width=6)       # 左半叶版框
    d.line([(fold - 30, 100), (fold - 30, 620)], fill=0, width=8)        # 版框里的栏线（更黑）
    d.line([(fold, 0), (fold, H)], fill=150, width=3)                    # 折痕（浅）
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "PNG")
    cover = io.BytesIO()
    Image.new("RGB", (400, 700), "white").save(cover, "PNG")
    z = tmp_path / "leaves.zip"
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("s_0001.png", cover.getvalue())                     # 书衣单页：不拆
        zz.writestr("s_0002.png", buf.getvalue())
    rows, diag = SP.detect(z, "01")
    assert [r["canvas_seq"] for r in rows] == ["0002a", "0002b"]
    x = rows[1]["xywh"][2]
    assert abs(x - fold) <= 4 and rows[0]["xywh"] == [x, 0, W - x, H]
    assert not diag[0]["weak"]
    SP.sheet(z, diag, tmp_path / "sheet.png")
    assert (tmp_path / "sheet.png").exists()
