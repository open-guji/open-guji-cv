"""老写法 → `page_kinds` 迁移（页型表第 3 步，2026-11-04）。

册 yaml 里的

    params:
      border_detect_gate: {body_pages: [88], table_pages: ["8-163"]}
      row_segment: {roster_pages: ["89-132"]}

改写成顶层

    page_kinds: {body: [88], table: ["8-163"], roster: ["89-132"]}

用 ruamel 往返读写，注释和排版尽量保留（搬走的行上的行内注释会跟着丢，干跑时看 diff）。
**每册都核**：改写前后各用缺省管线算一遍每步的 `params_hash`，一步不同就不改写那册（报「指纹有变」）。
缺省只干跑；`apply=True` 才写文件。写的是 `books_dir` 下的册 yaml（`guji db sync` 拉下来的那份），
**不推中心库**——推库要用户点头（`guji db push`）。

本模块在 ops，不进任何 Step 的 `code_deps`。
"""
from __future__ import annotations

import difflib
import io
import shutil
import tempfile
from pathlib import Path

from ..core.page_kinds import KIND_PARAM, load_page_kinds


def _rt():
    from ruamel.yaml import YAML
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.allow_unicode = True
    y.indent(mapping=2, sequence=4, offset=2)      # 册 yaml 的写法：`  - file:`（序列缩进 2、短横后 2）
    return y


def migrate_text(text: str) -> tuple[str | None, dict]:
    """一份册 yaml 文本 → (新文本 | None, 信息)。

    信息：`moved` {页型: 页号}，`dropped` [老字段路径]（空值去掉），`conflict`（已有 page_kinds 且值不同）。
    没有老写法 → (None, 信息里 moved 为空)。"""
    y = _rt()
    data = y.load(text)
    info: dict = {"moved": {}, "dropped": [], "conflict": None}
    if not hasattr(data, "get"):
        return None, info
    params = data.get("params")
    if not params:
        return None, info
    found: dict[str, object] = {}
    for kind, (sid, field) in KIND_PARAM.items():
        sub = params.get(sid)
        if sub is not None and field in sub:
            found[kind] = sub[field]
    if not found:
        return None, info
    moved: dict[str, object] = {}
    for kind, v in found.items():
        if not v:
            info["dropped"].append(".".join(KIND_PARAM[kind]))
        else:
            moved[kind] = v
    existing = data.get("page_kinds")
    if existing:
        old = load_page_kinds(dict(existing))
        for k, v in moved.items():
            if k in old and old[k] != list(v):
                info["conflict"] = f"page_kinds.{k} 已有且与老写法不同（{old[k]} / {list(v)}）"
                return None, info
    for kind, (sid, field) in KIND_PARAM.items():
        sub = params.get(sid)
        if sub is not None and field in sub:
            del sub[field]
            if not sub:
                del params[sid]
    if not params:
        del data["params"]
    if moved:
        from ruamel.yaml.comments import CommentedMap
        pk = data.get("page_kinds")
        if pk is None:
            pk = CommentedMap()
            keys = list(data.keys())
            pos = keys.index("params") if "params" in keys else len(keys)
            data.insert(pos, "page_kinds", pk)
        for kind in KIND_PARAM:               # 固定顺序 body／table／roster
            if kind in moved:
                pk[kind] = moved[kind]
    info["moved"] = {k: [p for p in v] for k, v in moved.items()}
    buf = io.StringIO()
    y.dump(data, buf)
    return buf.getvalue(), info


def step_fingerprints(book_id: str, books_dir: Path) -> dict[str, str]:
    """缺省管线逐步的 `params_hash`（册配置里新老写法的唯一差别只能在这里体现）。"""
    import warnings
    from ..core.book import load_book
    from ..core.engine import Engine, params_hash
    from ..core.pipeline import default_pipeline_id, load_pipeline
    from ..core.step import STEPS
    from ..products.cache import ImageCache
    from ..products.store import ProductStore
    with warnings.catch_warnings():                 # 迁移前的册本来就带老写法，别刷屏
        warnings.simplefilter("ignore", FutureWarning)
        book = load_book(book_id, books_dir)
    pl = load_pipeline(default_pipeline_id(book))
    with tempfile.TemporaryDirectory() as t:
        eng = Engine(book, pl, store=ProductStore(Path(t) / "p"), cache=ImageCache(Path(t) / "c"), log=lambda s: None)
        out = {}
        for sid in pl.steps:
            st = STEPS[sid]
            out[sid] = params_hash(eng.ctx.params_for(st), st.spec.soft_params, st.spec.path_params)
        return out


def run(books_dir: Path, *, apply: bool = False, only: list[str] | None = None) -> list[dict]:
    """扫 `books_dir` 下每份册 yaml。返回每份有老写法的册的结果：
    `{book, status: migrated|dry|unchanged_fp_mismatch|conflict|error, moved, dropped, diff, detail}`。"""
    books_dir = Path(books_dir)
    results: list[dict] = []
    for f in sorted(books_dir.glob("*.yaml")):
        if only and f.stem not in only:
            continue
        text = f.read_text(encoding="utf-8")
        try:
            new, info = migrate_text(text)
        except Exception as e:  # noqa: BLE001
            results.append({"book": f.stem, "status": "error", "detail": f"{type(e).__name__}: {e}"})
            continue
        if info["conflict"]:
            results.append({"book": f.stem, "status": "conflict", "detail": info["conflict"], **info})
            continue
        if new is None:
            continue
        diff = "".join(difflib.unified_diff(text.splitlines(True), new.splitlines(True), f"{f.name}", f"{f.name}（改后）", n=1))
        # 指纹核：把改后的文本放进一份临时拷贝（带上同级 config/），改前改后各算一遍
        with tempfile.TemporaryDirectory() as t:
            tb = Path(t) / "books"
            shutil.copytree(books_dir, tb)
            cfg = books_dir.parent / "config"
            if cfg.is_dir():                    # 只拷顶层 yaml（基础配置在这）；语料包、字形包动辄上百 MB，指纹用不着
                (Path(t) / "config").mkdir()
                for y in cfg.glob("*.yaml"):
                    shutil.copy2(y, Path(t) / "config" / y.name)
            try:
                before = step_fingerprints(f.stem, tb)
                (tb / f.name).write_text(new, encoding="utf-8")
                after = step_fingerprints(f.stem, tb)
            except Exception as e:  # noqa: BLE001
                results.append({"book": f.stem, "status": "error", "detail": f"算指纹出错 {type(e).__name__}: {e}", **info})
                continue
        if before != after:
            bad = sorted(s for s in before if before[s] != after.get(s))
            results.append({"book": f.stem, "status": "unchanged_fp_mismatch", "detail": f"这些步的参数指纹会变：{bad}", **info})
            continue
        if apply:
            f.write_text(new, encoding="utf-8")
        results.append({"book": f.stem, "status": "migrated" if apply else "dry", "diff": diff, **info})
    return results
