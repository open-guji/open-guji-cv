"""第三步看图 `glyph_vis` 的离线 ask：导出给对话看图判，答案写回 `vis_glyph` 缓存（CV3 2026-11-28）。

`glyph_vis` 缺省离线（`model` 空或不在线）：只读缓存，没命中的格在产物里记 `status=pending`＋`ask`
（`{img_sha, prompt, prompt_sha, cands, model}`）。本模块照第四步文意 ask 的 `feedback/llm_queue` 的形状做这一路，
入口挂在同一个命令组下（`llm_queue vis-export／vis-import`），与第四步 `evidence.group.solvers[*].ask` 那条互不相干：

1. `vis-export`：扫一册或多册的 `glyph_vis` 产物（可点名页），把 pending 的 ask 按 `(img_sha, prompt_sha, 候选集合)`
   去重（跨册也去重），**跳过缓存里已有答案的**（按本书当前 `model`＋`accept_models` 口径，开了 `accept_legacy` 的也认
   legacy，同 `glyph_vis.run_page`）。输出目录：
   - `img/<题号>.png`：就是送模型的那张图（`groups/vis_img.render_png`，与在线同一个函数、同口径）；
   - `manifest.jsonl`：每题一行 `{id, key, img, png_sha, img_sha, img_shape, patch, prompt, prompt_sha, cands, options,
     models, cells}`（`options` 就是在线时用户消息里那一行候选）；
   - `prompt.md`：系统提示原文、用户消息模板，加答题格式。
   字块按本书当前参数（`patch`）重读后重算 `img_sha`，与 ask 里的不同（字块变了、产物旧了）不出题、报 `img_changed`；
   ask 的提示词与本书当前提示词／代码对不上的报 `stale_prompt`（重跑 `glyph_vis` 后再导）。
2. 对话看图判：逐题看 PNG，按 `prompt.md` 只按刻形选，在 manifest 行上补 `char`（候选之一或「其他」）、`conf`
   （high／mid／low）、`why`（≤40 字），存成答案 jsonl。
3. `vis-import`：答案按 `key`（没有就按 `id`）对回 manifest，核 `img_sha`、`prompt_sha`、候选集合一致、提示词仍是现行
   代码的，再用 `VisGlyphStore.put` 写进 `<feedback>/vis_glyph/`，`model="session:<名>"`。答案不在候选里又不是「其他」、
   conf 不认、与 manifest 不符的**拒收并报告**；同一答案重复导入不再写（幂等），答案改了就追加一条（后到覆盖）。
   **只写本机，不推中心库，不调任何模型服务。**
4. 导入后从 `glyph_vis` 起 `--force` 重跑（缓存内容不进指纹）；书配置 `glyph_vis.accept_models` 要列上 `session:<名>`
   才会命中（导入时 manifest 的 `models` 里没有它会提示）。

    python -m open_guji_cv.feedback.llm_queue vis-export vol20 vol21 -w <工作区> --out 看图待判/ [--pages 1-30]
    python -m open_guji_cv.feedback.llm_queue vis-import 看图待判/answers.jsonl --name A24 [--manifest 看图待判/manifest.jsonl]
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

MANIFEST = "manifest.jsonl"
PROMPT_FILE = "prompt.md"
IMG_DIR = "img"
STEP = "glyph_vis"
SESSION_PREFIX = "session:"


def qkey(img_sha: str, prompt_sha: str, cands) -> str:
    """一题的稳定键（去重键的哈希）：同图、同提示词、同候选集合＝同一题，跨册、跨次导出不变。"""
    from ..groups.vis_img import cands_key
    return hashlib.sha256(f"{img_sha}|{prompt_sha}|{cands_key(cands)}".encode()).hexdigest()[:16]


def session_model(name: str) -> str:
    """对话判写进缓存的 `model` 值：`session:<名>`（已带前缀的原样用）。"""
    name = (name or "").strip()
    if not name:
        raise ValueError("vis-import 要给判题人的名字（--name），写成 model=session:<名>")
    return name if name.startswith(SESSION_PREFIX) else SESSION_PREFIX + name


def book_pages(ctx) -> list[int]:
    """本册已有 `glyph_vis` 产物的页号。"""
    d = ctx.store.step_dir(ctx.book.id, STEP)
    out = []
    for f in d.glob("p[0-9]*.json"):
        try:
            out.append(int(f.stem[1:]))
        except ValueError:
            continue
    return sorted(out)


def pending_of_page(doc) -> list[tuple[int, object]]:
    """一页 `PageVis` → [(列号, VisRec)]：`status=pending` 且带 ask 的格。"""
    return [(c.col, v) for c in doc.columns for v in c.chars if v.status == "pending" and v.ask]


def _answered(store, ask: dict, models: list[str], accept_legacy: bool) -> bool:
    """缓存里已有答案（同 `glyph_vis.run_page` 的读法：常规键按 models 依次试；开了 accept_legacy 再认 legacy）。"""
    cands = ask.get("cands") or []
    if store.lookup(ask["img_sha"], ask["prompt_sha"], cands, models) is not None:
        return True
    if accept_legacy:
        lg = store.lookup_legacy(ask["img_sha"])
        return lg is not None and bool(lg.get("other") or lg.get("char") in cands)
    return False


def collect(ctx_pages: Iterable[tuple[object, Iterable[int] | None]], store=None) -> tuple[list[dict], dict[str, bytes], dict]:
    """[(RunContext, 页号｜None＝全册)] → (题目行, {题号: PNG 字节}, 报告)。题号按首格排序后 q0001 起编。"""
    from .. import steps as _steps  # noqa: F401  注册各步
    from ..core.step import STEPS, page_key
    from ..groups import vis_img as V
    from ..steps.glyph_vis import GlyphVisStep
    from .vis_glyph import default_root, open_store

    st = store if store is not None else open_store(default_root())
    rep = {"pages": 0, "pending_cells": 0, "answered_cells": 0, "stale_prompt": 0, "patch_missing": 0,
           "img_changed": 0, "questions": 0, "cells": 0}
    rows: dict[str, dict] = {}
    pngs: dict[str, bytes] = {}
    bad: set[str] = set()                     # 读不到图／图变了的题键：同键别的格也不再试
    for ctx, pages in ctx_pages:
        p = ctx.params_for(STEPS[STEP])
        psha = V.prompt_sha(p.prompt)
        models = [m for m in [p.model, *p.accept_models] if m]
        for page in (sorted(pages) if pages is not None else book_pages(ctx)):
            doc = ctx.store.read(ctx.book.id, STEP, page_key(page), STEP)
            if doc is None:
                continue
            rep["pages"] += 1
            pend = pending_of_page(doc)
            if not pend:
                continue
            crec = raw = None
            for col, v in pend:
                rep["pending_cells"] += 1
                ask = v.ask
                if ask.get("prompt") != p.prompt or ask.get("prompt_sha") != psha:
                    rep["stale_prompt"] += 1
                    continue
                if _answered(st, ask, models, p.accept_legacy):
                    rep["answered_cells"] += 1
                    continue
                k = qkey(ask["img_sha"], psha, ask["cands"])
                if k in rows:
                    rows[k]["cells"].append(v.id)
                    continue
                if k in bad:
                    continue
                if crec is None:
                    chars = ctx.product("char_index", page)
                    crec = {r.id: r for cc in chars.columns for r in cc.chars}
                    raw = ctx.raw_page(page) if p.patch == "raw" else None
                c = crec.get(v.id)
                patch = GlyphVisStep._patch(ctx, page, col, v, c, p.patch, raw)[0] if c is not None else None
                if patch is None:
                    rep["patch_missing"] += 1
                    continue
                if V.img_sha(patch) != ask["img_sha"]:
                    rep["img_changed"] += 1
                    bad.add(k)
                    continue
                cands = V.sort_cands(ask["cands"])
                png = V.render_png(patch)
                pngs[k] = png
                rows[k] = {"key": k, "png_sha": hashlib.sha256(png).hexdigest()[:16], "img_sha": ask["img_sha"],
                           "img_shape": [int(x) for x in V.gray(patch).shape[:2]], "patch": p.patch,
                           "prompt": p.prompt, "prompt_sha": psha, "cands": cands,
                           "options": V.PROMPTS[p.prompt][1].format(cands="、".join(cands)),
                           "models": models, "cells": [v.id]}
    out, named = [], {}
    for i, r in enumerate(sorted(rows.values(), key=lambda r: (r["cells"][0], r["key"])), 1):
        qid = f"q{i:04d}"
        named[qid] = pngs[r["key"]]
        out.append({"id": qid, **r, "img": f"{IMG_DIR}/{qid}.png"})
    rep["questions"] = len(out)
    rep["cells"] = sum(len(r["cells"]) for r in out)
    return out, named, rep


def prompt_md(prompts: Iterable[str]) -> str:
    """`prompt.md`：系统提示与用户模板原文（与在线一字不差），加答题格式。"""
    from ..groups import vis_img as V
    parts = ["# 看图判字（glyph_vis 离线 ask）\n",
             ("每题看 `img` 那张 PNG（就是在线送模型的那张），**只按图上刻形**在该行 `options` 的候选里选一个；"
              "不看格号、不猜文意、不按常见字选。\n"),
             "答案：在 manifest 每行上补三列存成 jsonl（其余列原样保留，`key` 不能改）：\n",
             ('`"char"`：候选之一或「其他」；`"conf"`：high／mid／low；`"why"`：≤40 字，只写刻形部件依据。'
              "拿不准的题可以不答（不写 char），不会写进缓存。\n")]
    for pid in sorted(set(prompts)):
        sys_, tmpl = V.PROMPTS[pid]
        parts.append(f"\n## 提示词 `{pid}`（prompt_sha {V.prompt_sha(pid)}）\n\n### 系统提示\n\n```\n{sys_}\n```\n\n"
                     f"### 用户消息\n\n图，再加一行（即 `options`）：\n\n```\n{tmpl}\n```\n")
    return "".join(parts)


def write_export(out_dir: Path, rows: list[dict], pngs: dict[str, bytes]) -> None:
    """落盘：`img/<题号>.png`、`manifest.jsonl`、`prompt.md`。目录里上次导出的旧图先清掉，免得题号错配。"""
    out_dir = Path(out_dir)
    img = out_dir / IMG_DIR
    img.mkdir(parents=True, exist_ok=True)
    for old in img.glob("q*.png"):
        old.unlink()
    for qid, png in pngs.items():
        (img / f"{qid}.png").write_bytes(png)
    (out_dir / MANIFEST).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    (out_dir / PROMPT_FILE).write_text(prompt_md(r["prompt"] for r in rows), encoding="utf-8")


def import_answers(answers: Iterable[dict], manifest: Iterable[dict], *, name: str, store=None,
                   batch: str | None = None) -> dict:
    """答案行（manifest 行＋char/conf/why）→ 写进 `vis_glyph` 缓存。→ 报告
    `{model, written, updated, unchanged, unanswered, rejected: [{id, key, why}], not_accepted}`。"""
    import time

    from ..groups import vis_img as V
    from .vis_glyph import VisGlyphStore, answer_of, default_root
    model = session_model(name)
    batch = batch or f"glyph-vis-session-{time.strftime('%Y%m%d', time.gmtime())}"
    st = store if store is not None else VisGlyphStore(default_root())
    man = list(manifest)
    by_key = {m["key"]: m for m in man if m.get("key")}
    by_id = {m["id"]: m for m in man if m.get("id")}
    rep: dict = {"model": model, "written": 0, "updated": 0, "unchanged": 0, "unanswered": 0, "rejected": [],
                 "not_accepted": False}
    used = []

    def reject(a, why):
        rep["rejected"].append({"id": a.get("id"), "key": a.get("key"), "why": why})

    for a in answers:
        m = by_key.get(a.get("key")) if a.get("key") else by_id.get(a.get("id"))
        if m is None:
            reject(a, "manifest 里没有这题")
            continue
        if a.get("id") and m.get("id") and a["id"] != m["id"]:
            reject(a, f"题号与 manifest 不符（{a['id']}≠{m['id']}）")
            continue
        cs = V.sort_cands(m.get("cands") or [])
        if (a.get("img_sha", m["img_sha"]) != m["img_sha"] or a.get("prompt_sha", m["prompt_sha"]) != m["prompt_sha"]
                or V.sort_cands(a.get("cands", cs)) != cs or not cs):
            reject(a, "img_sha／prompt_sha／候选集合与 manifest 不符")
            continue
        if m.get("prompt") not in V.PROMPTS or V.prompt_sha(m["prompt"]) != m["prompt_sha"]:
            reject(a, "提示词或渲染口径已改，答案不会被命中（重跑 glyph_vis 后重新导出）")
            continue
        ch = (a.get("char") or "").strip() if isinstance(a.get("char"), str) else a.get("char")
        if not ch:
            rep["unanswered"] += 1
            continue
        if ch not in cs and ch != V.OTHER:
            reject(a, f"答案「{ch}」不在候选里，也不是「{V.OTHER}」")
            continue
        conf = a.get("conf")
        if conf not in V.CONFS:
            reject(a, f"conf 只认 {'／'.join(V.CONFS)}，拿到 {conf!r}")
            continue
        why = str(a.get("why") or "")[:60]
        old = st.lookup(m["img_sha"], m["prompt_sha"], cs, [model])
        if old is not None and answer_of(old) == ch and old.get("conf") == conf and (old.get("why") or "") == why:
            rep["unchanged"] += 1
            continue
        st.put(img_sha=m["img_sha"], img_shape=m.get("img_shape") or [0, 0], patch=m.get("patch") or "char_patch",
               prompt=m["prompt"], prompt_sha=m["prompt_sha"], cands=cs, char=ch, conf=conf, why=why, model=model,
               cell=(m.get("cells") or [None])[0], batch=batch)
        rep["updated" if old is not None else "written"] += 1
        used.append(m)
    rep["not_accepted"] = any(model not in (m.get("models") or []) for m in used)
    return rep


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def parse_pages(spec: str | None) -> list[int] | None:
    """`1-30,45` → 页号；空＝全册。"""
    if not spec or spec == "all":
        return None
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return sorted(out)


def book_ctx(book: str, products: str | None = None):
    """命令行用：按册号建只读的 RunContext（同 `pending_cells.patch_reader`：本机产物根、图像缓存、本册缺省管线）。"""
    from .. import steps as _steps  # noqa: F401
    from ..core.book import load_book
    from ..core.pipeline import default_pipeline_id, load_pipeline
    from ..core.step import RunContext
    from ..products.cache import ImageCache
    from ..products.store import ProductStore
    b = load_book(book)
    return RunContext(b, ProductStore(Path(products)) if products else ProductStore(), ImageCache(),
                      log=lambda _: None, pipeline=load_pipeline(default_pipeline_id(b)))
