# -*- coding: utf-8 -*-
"""hanzi 库：自造的小原始资料 → 构建 → 发布到假仓 → 按清单灌本机库 → 查询。

不联网：R2 用一个本地目录代替（`fetch` 换成按 sha 读这个目录），不读真表。"""
from __future__ import annotations

import hashlib
import json

import pytest

from open_guji_cv.hanzi import HanziDB
from open_guji_cv.hanzi import schema as S
from open_guji_cv.hanzi.build import build, publish
from open_guji_cv.hanzi.ids import leaves, split_alternatives


def _u(c: str) -> str:
    return f"U+{ord(c):04X}"


def _make_src(root):
    src = root / "src"
    src.mkdir()
    variants = "\n".join([
        "# Unihan_Variants.txt", "# Unicode Version 99.0.0", "",
        f"{_u('歷')}\tkSemanticVariant\t{_u('歴')}<kMatthews",
        f"{_u('歴')}\tkSemanticVariant\t{_u('歷')}",
        f"{_u('历')}\tkTraditionalVariant\t{_u('歷')} {_u('曆')}",   # 键简值繁 → 掉头
        f"{_u('后')}\tkSpoofingVariant\t{_u('后')}",                 # 自环，丢
        f"{_u('己')}\tkSpoofingVariant\t{_u('已')}",
        f"{_u('互')}\tkZVariant\t{_u('㸴')}",
    ]) + "\n"
    irg = "\n".join([f"{_u(c)}\tkRSUnicode\t77.12" for c in "歷歴历曆互㸴己已"]
                    + [f"{_u('歷')}\tkTotalStrokes\t16", f"{_u('歷')}\tkIRGKangXi\t0581.010"]) + "\n"
    (src / "unihan-Unihan_Variants.txt").write_text(variants, encoding="utf-8")
    (src / "unihan-Unihan_IRGSources.txt").write_text(irg, encoding="utf-8")
    (src / "unihan-Unihan_Readings.txt").write_text(f"{_u('歷')}\tkDefinition\tpass through\n",
                                                    encoding="utf-8")
    (src / "zi-families.jsonl").write_text(
        '{"q": "狼", "fam": ["郎"]}\n'                                         # 旧格式：只有一跳族
        '{"q": "互", "v": 2, "fam": ["牙"], "claims": [["GHZR", "GHZR-1497.10-12", "牙", "互"],'
        ' ["TVAR", "TVAR-A00053_002-0", "⿻𡕒一", "互"]], "links": [["A", "互", "D", "㸦"]]}\n',
        encoding="utf-8")
    (src / "cjkvi-twedu-variants.txt").write_text(
        "twedu/variant,<rev>,twedu/regular\n互,twedu/variant,㸴\n互,twedu/variant,⿱一彑\n", encoding="utf-8")
    (src / "cjkvi-hydzd-borrowed.txt").write_text("仍,hydcd/borrowed,乃,5287\n", encoding="utf-8")
    (src / "cjkvi-cjkvi-simplified.txt").write_text(
        "說,cjkvi/simplified,说\n说,cjkvi/traditional,說\n", encoding="utf-8")
    (src / "yitizi-index.js").write_text(
        'module.exports = {yitiziData: {"注":"註"\n}}', encoding="utf-8")
    (src / "charcomp-dt.jsonl").write_text('"歷@厤止"\n"註@言主"\n"\ue000@x"\n', encoding="utf-8")
    (src / "charcomp-rt.jsonl").write_text('"历~歴\ue001"\n"注"\n"~歷"\n', encoding="utf-8")
    (src / "charcomp-vt.json").write_text(json.dumps({"⻌": "辵"}, ensure_ascii=False), encoding="utf-8")
    (src / "yibai-ids_lv1.txt").write_text(
        "歷\t⿸厤止\n厤\t⿸厂秝\n秝\t⿰禾禾\n迴\t⿺⻌回\n"
        "一\t#(H)(.);{一}#(T)(t)\n說\t⿰言兌(G,T);⿰言兑(J)\n", encoding="utf-8")
    return src


def _make_cfg(root):
    cfg = root / "repo" / "config"
    (cfg / "variants").mkdir(parents=True)
    (cfg / "ids").mkdir()
    (cfg / "variants" / "local_edges.json").write_text(json.dumps({"edges": [
        {"a": "㫖", "b": "旨", "tags": ["local:keben"],
         "directed": {"variant": "㫖", "regular": "旨"}, "why": "刻本实证"}]},
        ensure_ascii=False), encoding="utf-8")
    (cfg / "variants" / "never_group.json").write_text(json.dumps(
        {"pairs": [["注", "註"]], "_evidence": {"注/註": "注解 vs 註冊"}}, ensure_ascii=False),
        encoding="utf-8")
    (cfg / "ids" / "confusable_pairs_v1.tsv").write_text(
        "# 头\na\tb\tkind\tcos\tdetail\n己\t已\tslot\t0.947\tx\n己\t巳\tslot\t0.947\ty\n己\t乙\tvisual\t0.96\t\n",
        encoding="utf-8")
    return cfg


class FakeR2:
    """R2 的替身：一个按 sha 存文件的目录，`fetch(url)` 从 URL 末尾认出 sha。"""

    def __init__(self, root):
        self.root = root
        self.calls = 0
        self.tamper = False

    def __call__(self, url: str) -> bytes:
        self.calls += 1
        sha = url.rsplit("/", 1)[1].removesuffix(".txt")
        data = (self.root / sha[:2] / f"{sha}.txt").read_bytes()
        return data + b"x" if self.tamper else data


def _release(tmp_path):
    """构建 → 发布到假仓 `repo/`，部件包等文件进假 R2；返回 (清单, 假仓, 假 R2, 打开库的函数)。"""
    src, cfg = _make_src(tmp_path), _make_cfg(tmp_path)
    repo = cfg.parent
    m = build(src, cfg, tmp_path / "out")
    r2 = FakeR2(tmp_path / "r2")
    publish(tmp_path / "out", repo, blob_dir=r2.root)
    for f in m["files"].values():                       # 形近对表在仓里，也照样进 R2（旧版要用）
        if "path" in f:
            data = (repo / f["path"]).read_bytes()
            (r2.root / f["sha256"][:2]).mkdir(parents=True, exist_ok=True)
            (r2.root / f["sha256"][:2] / f"{f['sha256']}.txt").write_bytes(data)

    def opener(**kw):
        return HanziDB.open(repo=repo, root=tmp_path / "data", fetch=r2, **kw)
    return m, repo, r2, opener


@pytest.fixture()
def built(tmp_path):
    m, repo, r2, opener = _release(tmp_path)
    return m, opener(parts=True), (repo, r2, opener, tmp_path)


def test_ids_helpers():
    assert split_alternatives("⿰言兌(G,T);⿰言兑(J)") == [("⿰言兌", {"G", "T"}), ("⿰言兑", {"J"})]
    assert split_alternatives("#(H)(.)") == [("#(H)", {"."})]
    assert leaves("{一}#(T)(t)") == []
    assert leaves("⿺⻌回") == ["⻌", "回"]
    assert leaves("⿱艹\ue123") == ["艹"]            # 私用区不当部件


def test_build_is_reproducible_and_published(built):
    m, db, (repo, _, _, tmp) = built
    build(tmp / "src", repo / "config", tmp / "out2")
    assert (tmp / "out2" / "manifest.json").read_bytes() == (tmp / "out" / "manifest.json").read_bytes()
    assert m["unihan_version"] == "99.0.0"
    assert db.version == m["version"] == f"hanzi-{m['content_sha']}"
    hz = repo / "config" / "hanzi"
    assert json.loads((hz / "manifest.json").read_text(encoding="utf-8")) == m
    assert (hz / "versions" / f"{m['version']}.json").exists()
    assert sorted(p.name for p in (hz / "core").iterdir()) == ["edges.tsv", "forms.tsv", "sources.tsv"]
    assert not (hz / "parts").exists()                   # 部件包不进 git
    f = m["files"]["core/edges.tsv"]
    assert hashlib.sha256((hz / "core" / "edges.tsv").read_bytes()).hexdigest() == f["sha256"]


def test_core_needs_no_download_parts_fetched_once(tmp_path):
    m, _, r2, opener = _release(tmp_path)
    db = opener()
    assert set(db.family("歷", srcs=["unihan"])) == {"歴"}
    assert r2.calls == 0                                  # 核心包与形近表都在仓里
    assert db.components("歷") == ["厤", "止"]          # 第一次部件查询才拉
    n_parts = sum(1 for f in m["files"].values() if f["pack"] == "parts")
    assert r2.calls == n_parts
    opener().components("歷")                            # 本机已灌好，不再拉
    assert r2.calls == n_parts
    with pytest.raises(RuntimeError):
        opener(parts=False).ids("歷")


def test_crlf_checkout_still_counts_as_local(tmp_path):
    """Windows 的 git 把 tsv 检出成 CRLF：仍认仓里那份，不去 R2 下载。"""
    _, repo, r2, opener = _release(tmp_path)
    for p in [*(repo / "config" / "hanzi" / "core").iterdir(), *(repo / "config" / "ids").iterdir()]:
        p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
    db = opener(parts=False)
    assert r2.calls == 0
    assert db.near("己", 1)[0][0] == "乙" and db.edges("㫖", "旨")


def test_download_checks_sha(tmp_path):
    _, _, r2, opener = _release(tmp_path)
    r2.tamper = True
    with pytest.raises(ValueError, match="sha256"):
        opener(parts=True)


def test_old_version_still_opens(tmp_path):
    m, repo, r2, opener = _release(tmp_path)
    v1 = m["version"]
    edges = repo / "config" / "variants" / "local_edges.json"
    edges.write_text(json.dumps({"edges": []}), encoding="utf-8")          # 出新版：手工边删掉
    m2 = build(tmp_path / "src", repo / "config", tmp_path / "out")
    publish(tmp_path / "out", repo, blob_dir=r2.root)
    assert m2["version"] != v1
    assert not opener().edges("㫖", "旨")
    old = opener(version=v1)                              # 仓里的核心包已是新版，旧版的从 R2 按 sha 取
    assert old.version == v1 and old.edges("㫖", "旨")



def test_edges_keep_source_rel_direction(built):
    _, db, _ = built
    e = [x for x in db.edges("歷", "歴") if x.src.startswith("unihan")]
    assert [(x.rel, x.directed, x.src) for x in e] == [("variant", 0, "unihan:kSemanticVariant")]
    assert e[0].ref == "kMatthews"                       # 两个方向合成一行，出处留着
    # kTraditionalVariant 键简值繁：存成 (繁, 简) 有向
    assert [(x.a, x.b, x.rel, x.directed) for x in db.edges("历", "曆")] == [("曆", "历", "simp", 1)]
    # cjkvi/traditional 掉头后与 cjkvi/simplified 是同一条
    assert [(x.a, x.b) for x in db.edges("說", "说")] == [("說", "说")]
    assert db.edges("仍", "乃")[0].rel == "borrow"
    assert db.edges("己", "已")[0].rel == "spoof"
    assert not db.edges("后", "后")


def test_family_excludes_never_rels_and_distinct(built):
    _, db, _ = built
    assert set(db.family("歷", srcs=["unihan"])) == {"歴"}          # 简繁不进族
    assert set(db.family("歷", rels=S.FAMILY_RELS | {"simp"}, srcs=["unihan"])) == {"歴", "历"}
    assert set(db.family("歷")) == {"歴", "历"}                     # 历 由部件檢索 related 进来
    assert {e.src for e in db.family("歷")["歴"]} == {"unihan:kSemanticVariant", "charcomp:rt"}
    assert "註" not in db.family("注")                    # 人审定 distinct 剔掉
    assert "註" in db.family("注", drop_distinct=False)
    assert set(db.family("己")) == set()                  # 钓鱼形近不是异体
    assert set(db.family("互", srcs=["twedu"])) == {"㸴"}
    # 两跳只是一跳成员再走一跳
    assert set(db.family("历", rels={"simp", "variant"}, depth=2)) == {"歷", "曆", "歴"}


def test_forms_and_charcomp(built):
    _, db, _ = built
    info = db.info("互")
    assert [f["key"] for f in info["forms"]] == ["⿱一彑", "⿻𡕒一"]      # cjkvi 的、字统网的
    rt = sorted((e.a, e.b, e.rel) for e in db.edges_of("歷") if e.src == "charcomp:rt")
    assert rt == [("历", "歷", "related"), ("歴", "歷", "variant")]   # 私用区那个丢掉
    assert [(e.rel) for e in db.edges("注", "註") if e.src == "charcomp:rt"] == ["related"]


def test_pool_matches_family_pool_shape(built):
    _, db, _ = built
    pool = db.pool(["己", "注"], near_k=2)
    assert pool["己"] == {"p": "己", "src": "piv"}
    assert pool["乙"]["src"] == "near"                    # 分数最高
    assert pool["已"]["src"] == "near"                    # 同分按原表行序
    assert "巳" not in pool
    assert pool["註"] == {"p": "注", "src": "v,rt"}        # 池子不剔 distinct（只是候选）
    assert db.pool(["注"], srcs=["rt"]).keys() == {"注", "註"}
    assert db.pool(["狼"])["郎"] == {"p": "狼", "src": "zi"}   # 字统网派生族（原始资料 zi-families.jsonl）
    claim = [e for e in db.edges("互", "牙") if e.src.startswith("zi")]
    assert [(e.a, e.b, e.directed, e.src, e.sense) for e in claim] == [("互", "牙", 1, "zi:GHZR", "GHZR-1497.10-12")]
    assert db.edges("互", "㸦")[0].src == "zi:link" and db.pool(["互"])["㸦"]["src"] == "zi"
    assert {"key": "⿻𡕒一", "regular": "互", "src": "zi:TVAR", "ref": "TVAR-A00053_002-0"} in db.info("互")["forms"]


def test_components(built):
    _, db, _ = built
    assert db.components("歷") == ["厤", "止"]
    assert db.components("歷", max_depth=3) == ["厤", "止", "厂", "秝", "禾"]
    assert db.by_components(["禾", "止"]) == ["歷"]
    assert db.by_components(["辵"]) == ["迴"]              # 部件变体折叠
    assert db.by_components(["禾"], max_depth=2) == ["秝", "厤"]
    assert db.by_components(["禾", "厂"]) == ["厤", "歷"]
    assert db.by_ids("⿸厤止") == ["歷"]
    assert {s for s, *_ in db.ids("歷")} == {"yibai:lv1"}
    assert db.info("歷")["strokes"] == 16


def test_export_variants_json(built):
    _, db, _ = built
    doc = db.export_variants_json()
    assert doc["pairs"]["歴"]["歷"] == ["unihan:kSemanticVariant"]
    assert doc["pairs"]["㫖"]["旨"] == ["local:keben"]
    assert doc["directed"]["㫖"] == {"旨": ["local:keben"]}
    assert doc["directed"]["历"] == {"曆": ["unihan:kTraditionalVariant"],
                                     "歷": ["unihan:kTraditionalVariant"]}
    assert "註" not in doc["pairs"].get("注", {}) or doc["pairs"]["注"]["註"] == ["yitizi"]
    assert all("charcomp" not in t for bs in doc["pairs"].values() for ts in bs.values() for t in ts)


def test_missing_sources_are_skipped(tmp_path):
    cfg = _make_cfg(tmp_path)
    (tmp_path / "src").mkdir()
    m = build(tmp_path / "src", cfg, tmp_path / "out")
    assert "unihan-Unihan_Variants.txt" in m["stats"]["missing"]
    publish(tmp_path / "out", cfg.parent, blob_dir=tmp_path / "r2")
    db = HanziDB.open(repo=cfg.parent, root=tmp_path / "data", fetch=FakeR2(tmp_path / "r2"))
    assert db.distinct("注", "註")
    assert db.near("己", 1)[0][0] == "乙"
