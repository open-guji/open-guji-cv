# -*- coding: utf-8 -*-
"""跑 pipeline 前后的 manager 行为：备输入（钉版字形库、Step5-b 模板索引）、整册跑完自动存包。

2026-10-27 拆分 M2：原先夹在 `cli_v2.cmd_pipeline` 里，现在单独成模块，`guji pipeline` 缺省仍调用（行为不变），
加 `--no-prep` / `--no-pack` 可以关掉，由 manager 显式 prep → 跑 → pack。设计见 doc/design/拆分-pipeline与manager.md。
本模块不在任何 Step 的 `code_deps` 里。"""

from __future__ import annotations


def rare_index_missing(book: str):
    """→ `(inst, [(名, 字表, key, 路径)…])`：Step5-b 两档 embedding 模板表里盘上缺的；算不出来 → `(None, [])`。"""
    try:
        from ..clustering import cnn_candidates as cc
        from ..clustering.rare_panel import book_charsets
        from ..steps.align_ref import book_corpus
        inst = cc.CnnCandidates(ckpt=cc.DEFAULT_CKPT)
        if not inst.available:
            return None, []
        cs_base, cs_esc, _ = book_charsets(book, book_corpus(book))
        miss = [(n, cs, k, f) for n, cs in (("base", cs_base), ("escalate", cs_esc)) if cs
                for k, f, _x in [inst.emb_index_key(cs)] if not f.exists()]
        return inst, miss
    except Exception:  # noqa: BLE001 —— 只是预备，算不出来就交给跑批照旧处理
        return None, []


def ensure_rare_index(book: str, jobs: int = 1, log=print) -> None:
    """跑批前把 Step5-b 的 embedding 模板表备好（A30 10-24 实测，overview#429 续）。

    缺表时管线在 `rare_candidates.parallel_warm` 里**单核**现建：殿本一册两档约 7.2 万字，
    云端 4 核会话 37–60 分钟，其余核闲着；同机两册还各建一遍同一张表。现在开跑前：

    1. 有与本机同规格的全字表向量包 → 按 **fp32** 落成（几秒）。fp32 与 `build_emb_matrix`
       现建逐位相同（v0.5.12 实测 300 字 `np.array_equal`，最大差 0.0）；**不用** int8——
       `pull-rare-index` 的缺省精度 int8 最大差约 0.004，会改候选，跑批不能悄悄换精度。
       落盘的 key、路径与现建同一个函数算，产物指纹不变。
    2. 没有同规格的包、`jobs > 1` → `ops.rare_index_build.build_parallel` 分片多进程现建
       （逐位相同，4 核约快 4 倍）。
    3. 其余情况只提示，跑批照旧现建。

    不改任何 Step、不进任何指纹；出错一律退回原行为（只提示）。`GUJI_NO_RARE_INDEX_PREP=1` 关掉 1、2。"""
    import os
    import time
    inst, miss = rare_index_missing(book)
    if not miss:
        return
    from ..clustering import cnn_candidates as cc
    n = sum(len(m[1]) for m in miss)
    desc = ", ".join(f"{a} {len(b)} 字（{f.name}）" for a, b, _k, f in miss)
    if os.environ.get("GUJI_NO_RARE_INDEX_PREP") != "1":
        t0 = time.time()
        try:
            from ..clustering import emb_pack
            m = emb_pack.find(emb_pack.current_spec())
            pk = emb_pack.EmbPack.load(m, precision="fp32") if m else None
        except Exception as e:  # noqa: BLE001
            log(f"Step5-b 模板索引：读向量包失败（{type(e).__name__}: {e}），改走现建", flush=True)
            pk = None
        if pk is not None:
            try:
                import json

                def compute(chars):
                    if not inst._ensure():
                        raise RuntimeError("本机没有 torch/checkpoint，包外的字算不了")
                    from ..clustering.synth import render_char
                    return cc.build_emb_matrix(inst._net, inst._dev, tuple(chars), {}, render_char)

                for name, cs, key, f in miss:
                    mat, names = pk.materialize(cs, compute)
                    if mat.shape[0] == 0:
                        raise RuntimeError(f"{name} 落成 0 行")
                    cc._save_emb_index(f, mat, names)
                    f.with_name(f.name + ".source.json").write_text(
                        json.dumps({"emb": pk.version, "precision": "fp32"}, ensure_ascii=False) + "\n",
                        encoding="utf-8")
                    log(f"Step5-b 模板索引：{name} {len(names)}/{len(cs)} 字从向量包 {pk.version}（fp32）落成"
                        f" → {f.name}", flush=True)
                log(f"Step5-b 模板索引备好（向量包，{time.time() - t0:.1f}s）", flush=True)
                return
            except Exception as e:  # noqa: BLE001
                log(f"Step5-b 模板索引：从向量包落成失败（{type(e).__name__}: {e}），改走现建", flush=True)
        if jobs > 1 and inst._ensure():
            try:
                from ..ops.rare_index_build import build_parallel
                for name, cs, key, f in miss:
                    if f.exists():
                        continue
                    log(f"Step5-b 模板索引：没有同规格向量包，{name} {len(cs)} 字 {jobs} 进程现建", flush=True)
                    mat, names = build_parallel(inst, cs, jobs)
                    if mat.shape[0] == 0:
                        raise RuntimeError(f"{name} 建成 0 行")
                    cc._save_emb_index(f, mat, names)
                log(f"Step5-b 模板索引备好（{jobs} 进程现建，{time.time() - t0:.0f}s）", flush=True)
                return
            except Exception as e:  # noqa: BLE001
                log(f"Step5-b 模板索引：多进程现建失败（{type(e).__name__}: {e}），交给跑批单核现建", flush=True)
    log(f"⚠️ Step5-b 模板索引未预建：{desc}。若有页要算，第一页会单核现建 {n} 字（约 {n // 25 // 60} 分钟）。"
        f"建议先 `guji cache pull-rare-index --book {book} -w <工作区> --precision fp32`（从向量包落成，几秒；"
        f"别用缺省 int8，会改候选），没有同规格的向量包时再 `guji cache build-rare-index --book {book} --jobs 4`",
        flush=True)


def ensure_glyph_pin(book) -> None:
    """册钉了有快照的字形库版本：本机没建那一版的库（或库过时）就先建（`ops/glyph_snapshot.py`，GUJI-727）。"""
    if not getattr(book, "glyph_pin", None):
        return
    from ..core.glyph_pin import load_manifest
    from ..core.workspace import workspace_root
    ws = workspace_root()
    if ws is None or load_manifest(ws, book.glyph_pin) is None:
        return
    from ..ops.glyph_snapshot import ensure_pins
    ensure_pins(ws, [book.glyph_pin])


def auto_pack(args, eng, steps: list[str], full_steps, book_versions) -> None:
    """整册从头跑到尾、没有失败页 → 顺手把产物打包存进 R2（sheldon 10-21：免得忘）。

    只在「--pages all 且跑的是整条 pipeline（没给 --from/--to 或给的就是首尾两步）」时存；
    `--no-pack` 或 `GUJI_AUTO_PACK=0` 关。没有令牌、存失败只提醒，不改跑批的返回码。
    标签按版本三段拼，后缀 `full`；不标 main（要标用 `guji products pack promote`）。"""
    import os
    if getattr(args, "no_pack", False) or os.environ.get("GUJI_AUTO_PACK", "1") == "0":
        return
    if str(getattr(args, "pages", "")) != "all" or steps != full_steps(eng):
        return
    book = eng.book.id
    if not os.environ.get("GUJI_DATA_TOKEN"):
        print(f"  ⓘ 整册跑完，没设 GUJI_DATA_TOKEN，没自动存包：guji products pack push {book} --change full")
        return
    try:
        from ..datastore import packs as PK
        root = eng.store.root
        info = PK.push_products(book, root, change="full", vers=book_versions(book, root),
                                note="guji pipeline 整册跑完自动存")
        print(f"  ✓ 整册跑完，产物已自动存包：{info['name']}（{info['bytes'] / 1e6:.1f} MB）")
    except Exception as e:     # noqa: BLE001 —— 存包失败不算跑批失败
        print(f"  ⚠ 整册跑完，自动存包失败（{e}）：手动 guji products pack push {book} --change full")


def print_unpacked(book: str, store) -> None:
    """本机这册产物有没存包的新结果就提醒一句（`datastore.packs.unpacked_note`；不挡什么）。"""
    try:
        from ..datastore.packs import unpacked_note
        msg = unpacked_note(store.root, book)
    except Exception:          # noqa: BLE001 —— 提醒算不出来不碍事
        msg = None
    if msg:
        print(f"  ⓘ {msg}")




def install_derived_fetcher() -> None:
    """过渡期：`guji` 入口把"去 R2 取派生缓存"注册给 pipeline（`core.derived.FETCHER`）。
    pipeline 自己不 import datastore；M4 后改由 manager 在跑之前把文件取到 `GUJI_DERIVED_DIR`。"""
    from ..core import derived
    from ..datastore.packs import fetch_derived
    derived.FETCHER = fetch_derived
