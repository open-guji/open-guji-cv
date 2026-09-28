# -*- coding: utf-8 -*-
"""快照自动导入（`open_guji_cv/snap/`）：真 git、假 origin（本地 bare 仓），不 mock git。

一圈：云端 clone 上 `build_tree` + `commit_and_push` → 假 origin 上出现 `snap/…` 分支
→ 服务器 clone 上 `watch` → `import_pack` → 产物替换、备份、标记、导入记录。另走四种
情形（锁被占、sha 对不上、cv 不兼容、display-only）与 subset 合并、作废、分块附件、回滚。
新鲜度（`guji status`）用注入的假实现——真的要书 yaml + 管线，单测不该依赖。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from open_guji_cv.snap import gitio, importer as imp, manifest as mf, pack as sp, watch as sw

WS_DIR = "abcdefgh12-測試書"
BOOK = "b1"
STEPS = ["border_detect", "cell_shrink"]


def git(cwd: Path, *args: str) -> str:
    cp = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr
    return cp.stdout.strip()


def _init(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")


def write_products(products: Path, tag: str, pages=(1, 2, 3), steps=STEPS, rev="c0ffee1") -> None:
    for s in steps:
        d = products / BOOK / s
        d.mkdir(parents=True, exist_ok=True)
        lines = []
        for p in pages:
            key = f"p{p:04d}"
            (d / f"{key}.json").write_text(json.dumps({"v": tag, "page": p}), encoding="utf-8")
            lines.append(json.dumps({"key": key, "fingerprint": f"fp-{tag}-{p}", "params_hash": "ph1",
                                     "code_rev": rev, "status": "ok"}))
        (d / "_manifest.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (d / "_prev").mkdir(exist_ok=True)
        (d / "_prev" / "p0001.json").write_text("old", encoding="utf-8")


@pytest.fixture
def world(tmp_path):
    """假 origin（bare）+ 云端 clone + 服务器 clone + 服务器 cv 仓 + overview 仓。"""
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    _init(seed)
    (seed / WS_DIR / "books").mkdir(parents=True)
    (seed / WS_DIR / "books" / f"{BOOK}.yaml").write_text("id: b1\n", encoding="utf-8")
    (seed / WS_DIR / ".gitignore").write_text("products/\n", encoding="utf-8")
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "seed")
    git(tmp_path, "clone", "-q", "--bare", str(seed), str(origin))
    cloud = tmp_path / "cloud"
    server = tmp_path / "server"
    git(tmp_path, "clone", "-q", str(origin), str(cloud))
    git(tmp_path, "clone", "-q", str(origin), str(server))
    for r in (cloud, server):
        git(r, "config", "user.email", "t@t")
        git(r, "config", "user.name", "t")
    # 服务器 cv：A ← B（HEAD），另有一条分叉 X
    cv = tmp_path / "cv"
    _init(cv)
    (cv / "f").write_text("a")
    git(cv, "add", "-A"); git(cv, "commit", "-q", "-m", "A")
    a = git(cv, "rev-parse", "HEAD")
    git(cv, "checkout", "-q", "-b", "side")
    (cv / "f").write_text("x")
    git(cv, "commit", "-qam", "X")
    x = git(cv, "rev-parse", "HEAD")
    git(cv, "checkout", "-q", "main")
    (cv / "f").write_text("b")
    git(cv, "commit", "-qam", "B")
    b = git(cv, "rev-parse", "HEAD")
    overview = tmp_path / "overview"
    _init(overview)
    (overview / "README").write_text("x")
    git(overview, "add", "-A"); git(overview, "commit", "-q", "-m", "init")
    # 服务器上已有旧产物
    write_products(server / WS_DIR / "products", "old")
    return {"tmp": tmp_path, "origin": origin, "cloud": cloud, "server": server, "cv": cv,
            "A": a, "B": b, "X": x, "overview": overview, "state": tmp_path / "state" / "s.json"}


def fake_fresh(calls=None):
    def fn(ws_dir, book, pages):
        if calls is not None:
            calls.append((ws_dir, book, pages))
        n = len(list((Path(ws_dir) / "products" / book / "border_detect").glob("p*.json")))
        return {"border_detect": {"fresh": n, "stale": 0}, "cell_shrink": {"fresh": 0, "stale": n}}
    return fn


def make_pack(w, tag="new", *, stamp="20260927T2000", mode="replace-steps", cv=None, pages=None,
              supersedes=(), compatible_with=(), attachments=(), tamper=False, push=True) -> dict:
    prod = w["tmp"] / f"cloudprod-{stamp}"
    write_products(prod, tag)
    spec = sp.PackSpec(book=BOOK, products_root=prod, ws_dir=w["cloud"] / WS_DIR, pages=pages, mode=mode,
                       supersedes=list(supersedes), cv_commit=cv or w["A"],
                       compatible_with=list(compatible_with), attachments=list(attachments),
                       param_overrides={"cell_shrink": {"use_context": False}}, stamp=stamp,
                       glyph_fingerprint="fp-test", session="test-session")
    tree = w["tmp"] / f"tree-{stamp}"
    m = sp.build_tree(spec, tree)
    if tamper:
        (tree / "products" / BOOK / "border_detect" / "p0002.json").write_text("tampered", encoding="utf-8")
    sp.commit_and_push(w["cloud"], tree, m, push=push)
    return m


def run_watch(w, **kw):
    return sw.watch(ws_repo=w["server"], ws_roots=[w["server"]], cv_repo=w["cv"], state_path=w["state"],
                    overview=w["overview"], push=False, freshness_fn=kw.pop("freshness_fn", fake_fresh()), **kw)


def read_page(w, step="border_detect", page=1):
    return json.loads((w["server"] / WS_DIR / "products" / BOOK / step / f"p{page:04d}.json").read_text())


# ── 格式 ─────────────────────────────────────────────────────────────
def test_ws_key_and_branch_name():
    assert mf.ws_key("96mid1ogzk-欽定四庫全書總目武英殿刻本") == "96mid1ogzk"
    assert mf.ws_key("qtw-draft") == "qtw-draft"
    assert mf.branch_name("96mid1ogzk", "vol03", "20260927T2130") == "snap/96mid1ogzk/vol03/20260927T2130"
    with pytest.raises(mf.ManifestError):
        mf.branch_name("x", "../etc", "1")


def test_validate_rejects_path_escape_and_foreign_step(world):
    m = make_pack(world, push=False)
    bad = json.loads(json.dumps(m))
    bad["files"]["products/b1/border_detect/../../../x"] = {"sha256": "0" * 64}
    with pytest.raises(mf.ManifestError):
        mf.validate(bad)
    bad = json.loads(json.dumps(m))
    bad["files"]["products/b1/other_step/p0001.json"] = {"sha256": "0" * 64}
    with pytest.raises(mf.ManifestError):
        mf.validate(bad)


def test_pack_manifest_contents(world):
    m = make_pack(world, push=False)
    assert m["format"] == mf.FORMAT and m["branch"] == "snap/abcdefgh12/b1/20260927T2000"
    assert m["page_scope"] == "full" and m["pages"] == [1, 2, 3]
    assert m["params"]["cell_shrink"] == {"params_hash": ["ph1"], "overrides": {"use_context": False}}
    assert m["cv"]["code_revs"]["border_detect"] == ["c0ffee1"]
    assert m["glyph_db_fingerprint"] == "fp-test" and m["session"] == "test-session"
    assert not any("/_prev/" in k for k in m["files"])          # _prev 不进包
    assert "products/b1/border_detect/_manifest.jsonl" in m["files"]
    # 本地分支建好了，没推
    assert gitio.rev_parse(world["cloud"], "refs/heads/" + m["branch"]) is not None
    assert gitio.ls_remote_snaps(world["cloud"]) == {}


def test_pack_page_subset(world):
    m = make_pack(world, pages=[2], push=False)
    assert m["page_scope"] == "subset" and m["pages"] == [2]
    assert sorted(k.rsplit("/", 1)[1] for k in m["files"] if "/border_detect/" in k) == ["_manifest.jsonl", "p0002.json"]


# ── 一整圈 ───────────────────────────────────────────────────────────
def test_full_loop_pack_push_watch_import_record(world):
    m = make_pack(world)
    listing = gitio.ls_remote_snaps(world["server"])
    assert list(listing) == [m["branch"]] and len(listing[m["branch"]]) == 40
    calls = []
    out = run_watch(world, freshness_fn=fake_fresh(calls))
    assert out["imported"] == 1, out
    r = out["results"][0]
    assert r["status"] == imp.IMPORTED and r["backed_up_steps"] == STEPS
    assert read_page(world)["v"] == "new"
    book_dir = world["server"] / WS_DIR / "products" / BOOK
    backups = list((book_dir / mf.BACKUP_DIR).iterdir())
    assert len(backups) == 1 and json.loads((backups[0] / "border_detect" / "p0001.json").read_text())["v"] == "old"
    assert not list(book_dir.glob(mf.STAGING_PREFIX + "*"))    # 暂存区清掉了
    assert not (book_dir / "border_detect" / "_prev").exists()  # 整目录替换，云端 _prev 不带
    log = (book_dir / mf.IMPORTS_NAME).read_text().splitlines()
    assert json.loads(log[-1])["pack"] == m["id"]
    assert len(calls) == 2                                      # 导入前后各量一次
    rec = Path(out["record"])
    txt = rec.read_text(encoding="utf-8")
    assert rec.parent == world["overview"] / sw.RECORD_DIR
    assert m["branch"] in txt and "imported" in txt and "| border_detect | 新鲜3 | 新鲜3 |" in txt
    assert git(world["overview"], "log", "-1", "--format=%s").startswith("快照导入记录")
    # 下一轮：什么都不做、不写记录
    out2 = run_watch(world)
    assert out2["status"] == "idle"


def test_dry_run_changes_nothing(world):
    m = make_pack(world)
    r = imp.import_pack(m["branch"], ws_repo=world["server"],
                        ws_roots=[world["server"]], cv_repo=world["cv"], dry_run=True, freshness_fn=fake_fresh())
    assert r.status == imp.WOULD_IMPORT and r.detail["files"] > 0
    assert read_page(world)["v"] == "old"
    assert not (world["server"] / WS_DIR / "products" / BOOK / mf.BACKUP_DIR).exists()
    assert not list((world["server"] / WS_DIR / "products" / BOOK).glob(mf.STAGING_PREFIX + "*"))


# ── 四种情形 ─────────────────────────────────────────────────────────
def test_locked_skips_then_retries_without_duplicate_records(world):
    from open_guji_cv.core.runlock import book_run_lock
    make_pack(world)
    prod = world["server"] / WS_DIR / "products"
    with book_run_lock(BOOK, products=prod, note="别的跑批"):
        out = run_watch(world)
        assert out["results"][0]["status"] == imp.LOCKED
        assert out["results"][0]["holder"]["note"] == "别的跑批"
        assert read_page(world)["v"] == "old"
        out = run_watch(world)                  # 还占着：再试，但不再写记录
        assert out["results"][0]["status"] == imp.LOCKED and out["record"] is None
    out = run_watch(world)                      # 放了：导入
    assert out["results"][0]["status"] == imp.IMPORTED
    assert read_page(world)["v"] == "new"


def test_sha_mismatch_rejected_and_not_retried(world):
    make_pack(world, tamper=True)
    out = run_watch(world)
    r = out["results"][0]
    assert r["status"] == imp.SHA_MISMATCH
    assert any("p0002.json" in p for p in r["problems"])
    assert read_page(world)["v"] == "old"
    assert "sha256 对不上" in Path(out["record"]).read_text(encoding="utf-8")
    assert run_watch(world)["status"] == "idle"   # 终态：同一提交不再碰


def test_cv_incompatible_then_declared_compatible(world):
    make_pack(world, cv=world["X"], stamp="20260927T2001")
    out = run_watch(world)
    r = out["results"][0]
    assert r["status"] == imp.INCOMPATIBLE
    assert r["cv_check"]["checked"][world["X"]] == "不是 HEAD 的祖先"
    assert read_page(world)["v"] == "old"
    # 未知提交也按不兼容处理（找不到）
    make_pack(world, cv="f" * 40, stamp="20260927T2002", tag="unk")
    out = run_watch(world)
    unk = [x for x in out["results"] if x["branch"].endswith("T2002")][0]
    assert unk["status"] == imp.INCOMPATIBLE and "找不到" in unk["cv_check"]["checked"]["f" * 40]
    # 声明与 A 兼容 → 通过
    make_pack(world, cv=world["X"], compatible_with=[world["A"]], stamp="20260927T2003")
    out = run_watch(world)
    ok = [x for x in out["results"] if x["branch"].endswith("T2003")][0]
    assert ok["status"] == imp.IMPORTED and ok["cv_check"]["via"] == world["A"]


def test_display_only_marks_and_deploy_queue_skips(world, monkeypatch):
    m = make_pack(world, mode="display-only")
    out = run_watch(world)
    assert out["results"][0]["status"] == imp.IMPORTED
    prod = world["server"] / WS_DIR / "products"
    assert mf.display_only_steps(prod, BOOK) == set(STEPS)
    assert mf.read_marks(prod, BOOK)["display_only"]["cell_shrink"]["pack"] == m["id"]
    assert "只看不算" in Path(out["record"]).read_text(encoding="utf-8")

    # 部署器的过期步队列：display-only 的步不进
    from open_guji_cv.core import book as book_mod, engine as eng_mod, pipeline as pl_mod
    from open_guji_cv.ops import deploy_check as dc

    class FakeEngine:
        def __init__(self, *a, **k):
            pass

        def status(self, pages=None):
            return {"steps": {s: {"counts": {"stale": 3}} for s in [*STEPS, "glyph_match"]}}

    monkeypatch.setattr(book_mod, "list_books", lambda d: [BOOK])
    monkeypatch.setattr(book_mod, "load_book", lambda b, d: type("B", (), {"resolve_pages": lambda s, p: [1]})())
    monkeypatch.setattr(pl_mod, "default_pipeline_id", lambda b: "x")
    monkeypatch.setattr(pl_mod, "load_pipeline", lambda i: None)
    monkeypatch.setattr(eng_mod, "Engine", FakeEngine)
    monkeypatch.delenv("GUJI_PRODUCTS_DIR", raising=False)
    monkeypatch.setenv("GUJI_WORKSPACE", "placeholder")   # collect_stale_summary 会改它，测完还原
    assert dc.collect_stale_summary(world["server"] / WS_DIR) == {BOOK: ["glyph_match"]}

    # 之后一个 replace-steps 包导入同一步 → 标记清掉
    make_pack(world, stamp="20260927T2100", tag="real")
    run_watch(world)
    assert mf.display_only_steps(prod, BOOK) == set()


# ── 其余语义 ─────────────────────────────────────────────────────────
def test_subset_pack_merges_pages(world):
    make_pack(world, pages=[2], tag="p2only")
    out = run_watch(world)
    assert out["results"][0]["status"] == imp.IMPORTED
    assert read_page(world, page=1)["v"] == "old"
    assert read_page(world, page=2)["v"] == "p2only"
    assert read_page(world, page=3)["v"] == "old"
    lines = (world["server"] / WS_DIR / "products" / BOOK / "border_detect" / "_manifest.jsonl").read_text().splitlines()
    last = {}
    for ln in lines:
        d = json.loads(ln)
        last[d["key"]] = d["fingerprint"]
    assert last == {"p0001": "fp-old-1", "p0002": "fp-p2only-2", "p0003": "fp-old-3"}
    assert (world["server"] / WS_DIR / "products" / BOOK / "border_detect" / "_prev").is_dir()  # 服务器自己的 _prev 留着


def test_supersedes_imports_only_newest(world):
    old = make_pack(world, stamp="20260927T1000", tag="v1")
    make_pack(world, stamp="20260927T1100", tag="v2", supersedes=[old["branch"]])
    out = run_watch(world)
    st = {x["branch"]: x["status"] for x in out["results"]}
    assert st[old["branch"]] == imp.SUPERSEDED
    assert read_page(world)["v"] == "v2"


def test_backups_pruned_to_keep_two(world):
    for i in range(4):
        make_pack(world, stamp=f"20260927T0{i}00", tag=f"r{i}")
        run_watch(world)
    bdir = world["server"] / WS_DIR / "products" / BOOK / mf.BACKUP_DIR
    assert len(list(bdir.iterdir())) == mf.BACKUP_KEEP
    assert read_page(world)["v"] == "r3"


def test_chunked_attachment_reassembled_into_cv(world, monkeypatch):
    monkeypatch.setattr(sp, "CHUNK_BYTES", 1000)
    blob = world["tmp"] / "emb_abc.npz"
    blob.write_bytes(bytes(range(256)) * 10)          # 2560 字节 → 3 块
    m = make_pack(world, attachments=[sp.Attachment(root="cv", dest="models/r5/emb_abc.npz", src=blob)])
    assert len(m["attachments"][0]["parts"]) == 3
    out = run_watch(world)
    r = out["results"][0]
    assert r["status"] == imp.IMPORTED and r["attachments_placed"] == ["cv:models/r5/emb_abc.npz"]
    assert (world["cv"] / "models/r5/emb_abc.npz").read_bytes() == blob.read_bytes()


def test_url_attachment_verified(world):
    good = b"hello-index"
    import hashlib
    sha = hashlib.sha256(good).hexdigest()
    make_pack(world, attachments=[sp.Attachment(root="ws", dest="cache/x.npz", url="https://example/x", sha256=sha)])
    fetched = []

    def bad_fetch(url, dest):
        fetched.append(url)
        Path(dest).write_bytes(b"corrupt")

    out = run_watch(world, url_fetch=bad_fetch)
    assert out["results"][0]["status"] == imp.SHA_MISMATCH and fetched == ["https://example/x"]


def test_swap_rolls_back_on_failure(world, monkeypatch, tmp_path):
    book_dir = world["server"] / WS_DIR / "products" / BOOK
    staging = tmp_path / "stg"
    write_products(staging / "products", "new")
    real_replace = imp.os.replace
    n = {"i": 0}

    def flaky(a, b):
        n["i"] += 1
        if n["i"] == 4:                     # 第二步把新目录换上时失败
            raise OSError("boom")
        return real_replace(a, b)

    monkeypatch.setattr(imp.os, "replace", flaky)
    m = {"book": BOOK, "steps": STEPS, "page_scope": "full"}
    with pytest.raises(OSError):
        imp._swap_in(m, staging, book_dir, book_dir / mf.BACKUP_DIR / "t")
    monkeypatch.setattr(imp.os, "replace", real_replace)
    for s in STEPS:
        assert json.loads((book_dir / s / "p0001.json").read_text())["v"] == "old"


def test_no_workspace_is_retryable(world):
    make_pack(world)
    out = sw.watch(ws_repo=world["server"], ws_roots=[world["tmp"] / "nowhere"], cv_repo=world["cv"],
                   state_path=world["state"], overview=None, freshness_fn=fake_fresh())
    assert out["results"][0]["status"] == imp.NO_WORKSPACE
    assert imp.NO_WORKSPACE in imp.RETRYABLE
    out = run_watch(world)
    assert out["results"][0]["status"] == imp.IMPORTED


def test_create_workspace_only_when_declared(world, tmp_path):
    prod = tmp_path / "p"
    write_products(prod, "qtw")
    wsd = tmp_path / "src" / "qtw-draft"
    (wsd / "books").mkdir(parents=True)
    yml = wsd / "books" / "b1.yaml"
    yml.write_text("id: b1\n", encoding="utf-8")
    for create, stamp in ((False, "20260927T0001"), (True, "20260927T0002")):
        spec = sp.PackSpec(book=BOOK, products_root=prod, ws_dir=wsd, mode="display-only", cv_commit=world["A"],
                           stamp=stamp, create_workspace=create, glyph_fingerprint="x", session="s",
                           attachments=[sp.Attachment(root="ws", dest="books/b1.yaml", src=yml)])
        m = sp.build_tree(spec, tmp_path / f"t{stamp}")
        sp.commit_and_push(world["cloud"], tmp_path / f"t{stamp}", m)
    dry = run_watch(world, dry_run=True)
    st = {x["branch"].rsplit("/", 1)[1]: x for x in dry["results"]}
    assert st["20260927T0002"]["status"] == imp.WOULD_IMPORT and st["20260927T0002"]["workspace_would_create"]
    assert not (world["server"] / "qtw-draft").exists()          # 演练不建目录
    out = run_watch(world)
    st = {x["branch"].rsplit("/", 1)[1]: x for x in out["results"]}
    assert st["20260927T0001"]["status"] == imp.NO_WORKSPACE
    assert st["20260927T0002"]["status"] == imp.IMPORTED and st["20260927T0002"]["workspace_created"]
    assert (world["server"] / "qtw-draft" / "books" / "b1.yaml").read_text() == "id: b1\n"
    assert mf.display_only_steps(world["server"] / "qtw-draft" / "products", BOOK) == set(STEPS)


def _fresh_by_tag(fresh_tag):
    """新鲜度假实现：产物内容是 fresh_tag 的页算新鲜，其余算过期。"""
    def fn(ws_dir, book, pages):
        out = {}
        for s in STEPS:
            n_f = n_s = 0
            for f in (Path(ws_dir) / "products" / book / s).glob("p*.json"):
                if json.loads(f.read_text())["v"] == fresh_tag:
                    n_f += 1
                else:
                    n_s += 1
            out[s] = {"fresh": n_f, "stale": n_s}
        return out
    return fn


def test_downgrade_guard_rolls_back(world):
    # 服务器那份（old）新鲜、包里的（new）会判过期 → 整包换回，终态
    make_pack(world)
    out = run_watch(world, freshness_fn=_fresh_by_tag("old"))
    r = out["results"][0]
    assert r["status"] == imp.DOWNGRADE and r["downgraded"]["border_detect"] == "新鲜 3 → 0"
    assert read_page(world)["v"] == "old"
    book_dir = world["server"] / WS_DIR / "products" / BOOK
    assert (book_dir / "border_detect" / "_prev").is_dir()          # 服务器原目录原样回来
    assert not (book_dir / mf.BACKUP_DIR).exists() or not list((book_dir / mf.BACKUP_DIR).iterdir())
    assert not (book_dir / mf.IMPORTS_NAME).exists()
    assert "已整包换回" in Path(out["record"]).read_text(encoding="utf-8")
    assert run_watch(world, freshness_fn=_fresh_by_tag("old"))["status"] == "idle"
    # 手动 --force 照换
    r = imp.import_pack(out["results"][0]["branch"], ws_repo=world["server"], ws_roots=[world["server"]],
                        cv_repo=world["cv"], force=True, freshness_fn=_fresh_by_tag("old"))
    assert r.status == imp.IMPORTED and read_page(world)["v"] == "new"


def test_downgrade_guard_allows_improvement_and_display_only(world):
    make_pack(world, stamp="20260927T0100")
    out = run_watch(world, freshness_fn=_fresh_by_tag("new"))    # 变新 → 照导
    assert out["results"][0]["status"] == imp.IMPORTED
    make_pack(world, stamp="20260927T0200", tag="disp", mode="display-only")
    out = run_watch(world, freshness_fn=_fresh_by_tag("new"))    # display-only 不查
    assert out["results"][0]["status"] == imp.IMPORTED and read_page(world)["v"] == "disp"


def test_failure_after_swap_restores(world, monkeypatch):
    make_pack(world)

    def boom(*a, **k):
        raise RuntimeError("attach boom")

    monkeypatch.setattr(imp, "_place_attachments", boom)
    out = run_watch(world)
    assert out["results"][0]["status"] == imp.FAILED and "attach boom" in out["results"][0]["error"]
    assert read_page(world)["v"] == "old"
    assert (world["server"] / WS_DIR / "products" / BOOK / "border_detect" / "_prev").is_dir()


def test_fetch_keeps_full_clone_full(world):
    """服务器 guji-workspace 是完整 clone 时，拉包不许把它变成浅仓。"""
    make_pack(world)
    assert git(world["server"], "rev-parse", "--is-shallow-repository") == "false"
    run_watch(world)
    assert git(world["server"], "rev-parse", "--is-shallow-repository") == "false"
    assert not (world["server"] / ".git" / "shallow").exists()


def test_attachment_destinations_restricted(world, tmp_path):
    f = tmp_path / "evil.py"
    f.write_text("print('x')")
    for root, dest in (("cv", "open_guji_cv/core/engine.py"), ("ws", "scripts/ws.py"), ("cv", ".git/hooks/post-merge")):
        with pytest.raises(mf.ManifestError):
            make_pack(world, attachments=[sp.Attachment(root=root, dest=dest, src=f)], push=False,
                      stamp=f"20260927T1{len(dest):03d}")
    m = make_pack(world, attachments=[sp.Attachment(root="ws", dest=".gitignore", src=f)], push=False)
    assert m["attachments"][0]["dest"] == ".gitignore"


def test_manual_import_is_remembered_by_watch(world):
    """手动 import 之后定时器同一提交不再重导（09-27 服务器装机回执 #90）。"""
    m = make_pack(world)
    r = imp.import_pack(m["branch"], ws_repo=world["server"], ws_roots=[world["server"]], cv_repo=world["cv"],
                        freshness_fn=fake_fresh())
    assert r.status == imp.IMPORTED
    assert sw.remember(world["state"], r)
    assert json.loads(world["state"].read_text())[m["branch"]]["status"] == imp.IMPORTED
    out = run_watch(world)
    assert out["status"] == "idle"
    log = (world["server"] / WS_DIR / "products" / BOOK / mf.IMPORTS_NAME).read_text().splitlines()
    assert len(log) == 1                                # 只导了一次


def test_manual_import_cli_writes_state(world, monkeypatch, capsys):
    import sys
    from open_guji_cv import cli_v2
    m = make_pack(world)
    monkeypatch.setattr(imp, "default_freshness", fake_fresh())
    monkeypatch.setattr(sys, "argv", ["guji", "snap", "import", m["branch"], "--ws-repo", str(world["server"]),
                                      "--cv-repo", str(world["cv"]), "--state", str(world["state"])])
    with pytest.raises(SystemExit) as e:
        cli_v2.main()
    assert e.value.code == 0
    assert json.loads(world["state"].read_text())[m["branch"]]["status"] == imp.IMPORTED
    assert run_watch(world)["status"] == "idle"


def test_gitignore_attachment_merges_lines(world, tmp_path):
    """.gitignore 附件按行合并：只追加本地没有的行、不删本地的（服务器本地是 `*`）。"""
    local = world["server"] / WS_DIR / ".gitignore"
    local.write_text("*\nproducts/\n", encoding="utf-8")
    gi = tmp_path / "gi"
    gi.write_text("# 注释\nproducts/\nscans/\n", encoding="utf-8")
    make_pack(world, attachments=[sp.Attachment(root="ws", dest=".gitignore", src=gi)])
    out = run_watch(world)
    assert out["results"][0]["attachments_placed"] == ["ws:.gitignore"]
    assert local.read_text(encoding="utf-8").splitlines() == ["*", "products/", "# 注释", "scans/"]
    # 再来一包同样的 .gitignore：没有新行，不动
    make_pack(world, attachments=[sp.Attachment(root="ws", dest=".gitignore", src=gi)], stamp="20260927T2100")
    out = run_watch(world)
    assert out["results"][0]["status"] == imp.IMPORTED and out["results"][0]["attachments_placed"] == []
    assert local.read_text(encoding="utf-8").splitlines() == ["*", "products/", "# 注释", "scans/"]


def test_gitignore_merge_undone_on_downgrade(world, tmp_path):
    local = world["server"] / WS_DIR / ".gitignore"
    local.write_text("*\n", encoding="utf-8")
    gi = tmp_path / "gi"
    gi.write_text("scans/\n", encoding="utf-8")
    make_pack(world, attachments=[sp.Attachment(root="ws", dest=".gitignore", src=gi)])
    out = run_watch(world, freshness_fn=_fresh_by_tag("old"))
    assert out["results"][0]["status"] == imp.DOWNGRADE
    assert local.read_text(encoding="utf-8") == "*\n"


# ── 09-27 服务器 vol03/vol04 T2132 事后补的三处 ──────────────────────
def _add_raw_upstream(prod: Path, sha_of) -> None:
    for s in STEPS:
        mfp = prod / BOOK / s / "_manifest.jsonl"
        rows = [json.loads(l) for l in mfp.read_text().splitlines() if l.strip()]
        for r in rows:
            r["upstream"] = {"raw_page": sha_of(int(r["key"][1:]))}
        mfp.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_raw_mismatch_waits_then_imports(world, tmp_path):
    prod = tmp_path / "rawprod"
    write_products(prod, "new")
    _add_raw_upstream(prod, lambda p: f"{p:064d}")
    spec = sp.PackSpec(book=BOOK, products_root=prod, ws_dir=world["cloud"] / WS_DIR, cv_commit=world["A"],
                       stamp="20260927T2132", glyph_fingerprint="x", session="s")
    m = sp.build_tree(spec, tmp_path / "t")
    sp.commit_and_push(world["cloud"], tmp_path / "t", m)
    server_raw = {"state": "old"}

    def raw_check(ws_dir, book, want):
        assert want == {p: f"{p:064d}" for p in (1, 2, 3)}
        return {} if server_raw["state"] == "new" else {1: "服务器原图与包算的时候不是同一张"}

    out = run_watch(world, raw_check=raw_check)
    r = out["results"][0]
    assert r["status"] == imp.RAW_MISMATCH and r["raw_pages"] == {"1": "服务器原图与包算的时候不是同一张"}
    assert read_page(world)["v"] == "old"
    assert "等 guji-workspace pull" in Path(out["record"]).read_text(encoding="utf-8")
    out = run_watch(world, raw_check=raw_check)          # 还没 pull：再试、不重复写记录
    assert out["results"][0]["status"] == imp.RAW_MISMATCH and out["record"] is None
    server_raw["state"] = "new"                          # 服务器 pull 了
    out = run_watch(world, raw_check=raw_check)
    assert out["results"][0]["status"] == imp.IMPORTED and read_page(world)["v"] == "new"


def test_default_raw_check_real_book(tmp_path):
    ws = tmp_path / "ws"
    (ws / "books").mkdir(parents=True)
    (ws / "raw").mkdir()
    (ws / "books" / "b1.yaml").write_text('id: b1\ntitle: t\nraw_dir: raw\nraw_pattern: "{page}.png"\n',
                                          encoding="utf-8")
    (ws / "raw" / "1.png").write_bytes(b"page-one")
    (ws / "raw" / "2.png").write_bytes(b"page-two-server")
    import hashlib
    h = lambda b: hashlib.sha256(b).hexdigest()   # noqa: E731
    bad = imp.default_raw_check(ws, "b1", {1: h(b"page-one"), 2: h(b"page-two-cloud"), 3: h(b"x")})
    assert bad == {2: "服务器原图与包算的时候不是同一张", 3: "服务器没有这页原图"}
    assert imp.default_raw_check(ws, "b1", {1: h(b"page-one")}) == {}
    assert "skipped" in imp.default_raw_check(ws, "nobook", {1: "0" * 64})


def test_downgrade_record_has_three_columns_and_rollback_ok(world):
    make_pack(world)
    out = run_watch(world, freshness_fn=_fresh_by_tag("old"))
    r = out["results"][0]
    assert r["status"] == imp.DOWNGRADE and r["rollback_ok"] is True
    assert r["freshness_after_rollback"] == r["freshness_before"]
    txt = Path(out["record"]).read_text(encoding="utf-8")
    assert "| 步 | 导入前 | 换上后 | 换回后 |" in txt and "换回后与导入前一致：是" in txt
    assert "| border_detect | 新鲜3 | 过期3 | 新鲜3 |" in txt


def test_pack_brings_gates_along(world, tmp_path):
    prod = tmp_path / "gp"
    write_products(prod, "new", steps=["border_detect", "border_detect_gate", "column_warp", "column_gate"])
    spec = sp.PackSpec(book=BOOK, products_root=prod, ws_dir=world["cloud"] / WS_DIR, cv_commit=world["A"],
                       steps=["border_detect", "column_warp"], stamp="20260927T0003",
                       glyph_fingerprint="x", session="s")
    m = sp.build_tree(spec, tmp_path / "gt")
    assert m["steps"] == ["border_detect", "border_detect_gate", "column_warp", "column_gate"]
    assert m["gates_added"] == ["border_detect_gate", "column_gate"]


def test_glyph_fingerprint_follows_borrowed_db(world, tmp_path, monkeypatch):
    import sqlite3
    db = tmp_path / "borrowed.db"
    sqlite3.connect(db).close()
    monkeypatch.setenv("GUJI_GLYPH_DB", str(db))
    monkeypatch.setattr("open_guji_cv.steps.glyph_match.db_fingerprint", lambda p: f"fp:{Path(p).name}")
    assert sp._glyph_fp(world["cloud"] / WS_DIR) == "fp:borrowed.db"


def test_pack_cli_reads_products_of_given_workspace(world, tmp_path, monkeypatch, capsys):
    """`guji snap pack <book> -w <ws>` 读的是 <ws>/products（没设 GUJI_WORKSPACE 时也是）。"""
    import sys
    from open_guji_cv import cli_v2
    ws = world["cloud"] / WS_DIR
    write_products(ws / "products", "fromws")
    monkeypatch.delenv("GUJI_WORKSPACE", raising=False)
    monkeypatch.delenv("GUJI_PRODUCTS_DIR", raising=False)
    monkeypatch.setattr(sys, "argv", ["guji", "snap", "pack", BOOK, "-w", str(ws), "--cv-commit", world["A"],
                                      "--no-push", "--stamp", "20260927T0444"])
    cli_v2.main()
    out = json.loads(capsys.readouterr().out)
    assert out["files"] == 8 and out["branch"].endswith("T0444")


def test_attach_only_pack_and_import(world, tmp_path):
    """纯附件包（Z17 回馈）：本地没有 products 也能打；导入只落位附件、不碰 products。"""
    idx = tmp_path / "emb_k.npz"
    idx.write_bytes(b"index-bytes" * 100)
    spec = sp.PackSpec(book="rare-index", products_root=tmp_path / "nothing-here", ws_dir=world["cloud"] / WS_DIR,
                       mode="attach-only", cv_commit=world["A"], stamp="20260927T2330",
                       attachments=[sp.Attachment(root="cv", dest="models/glyph_cnn_r5/emb_k.npz", src=idx)],
                       glyph_fingerprint="x", session="s")
    m = sp.build_tree(spec, tmp_path / "t")
    assert m["steps"] == [] and m["files"] == {} and m["page_scope"] == "none"
    assert m["branch"] == "snap/abcdefgh12/rare-index/20260927T2330"
    sp.commit_and_push(world["cloud"], tmp_path / "t", m)
    before = read_page(world)
    out = run_watch(world)
    r = out["results"][0]
    assert r["status"] == imp.IMPORTED and r["attachments_placed"] == ["cv:models/glyph_cnn_r5/emb_k.npz"]
    assert (world["cv"] / "models/glyph_cnn_r5/emb_k.npz").read_bytes() == idx.read_bytes()
    assert read_page(world) == before
    assert not (world["server"] / WS_DIR / "products" / "rare-index").exists()
    assert run_watch(world)["status"] == "idle"
    with pytest.raises(mf.ManifestError):
        sp.build_tree(sp.PackSpec(book="x", products_root=tmp_path, ws_dir=world["cloud"] / WS_DIR,
                                  mode="attach-only", cv_commit=world["A"]), tmp_path / "t2")


def test_product_pack_without_products_dir_hints_attach_only(world, tmp_path):
    with pytest.raises(FileNotFoundError, match="attach-only"):
        sp.build_tree(sp.PackSpec(book="nobook", products_root=tmp_path, ws_dir=world["cloud"] / WS_DIR,
                                  cv_commit=world["A"]), tmp_path / "t3")


def test_pack_cli_dry_run_never_pushes(world, monkeypatch, capsys):
    """`guji snap pack --dry-run` 只打印计划：不调 commit/push、假 origin 上不出分支、本地也不建分支（#174）。"""
    import sys
    from open_guji_cv import cli_v2
    prod = world["tmp"] / "cloudprod-dry"
    write_products(prod, "dry")
    called = []
    monkeypatch.setattr(sp, "commit_and_push", lambda *a, **k: called.append("commit_and_push"))
    monkeypatch.setattr(gitio, "push_commit", lambda *a, **k: called.append("push_commit"))
    monkeypatch.delenv("GUJI_PRODUCTS_DIR", raising=False)
    monkeypatch.setattr(sys, "argv", ["guji", "snap", "pack", BOOK, "-w", str(world["cloud"] / WS_DIR),
                                      "--from-products", str(prod), "--cv-commit", world["A"],
                                      "--stamp", "20260928T0300", "--dry-run"])
    cli_v2.main()
    out = json.loads(capsys.readouterr().out)
    assert called == []
    assert out["dry_run"] is True and out["pushed"] is False and out["commit"] is None
    assert out["branch"].startswith("snap/") and out["pages"] == 3 and out["files"] > 0
    assert git(world["origin"], "branch", "--list", "snap/*") == ""
    assert git(world["cloud"], "branch", "--list", "snap/*") == ""
