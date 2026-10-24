"""`guji close-check <册>`：一册书交付前的逐项体检（overview#413 C2；标准见 doc/runbook/整理一册书.md 第五节）。

只读：不改产物、不清缓存、不写事件。每项给出 pass / fail / manual / skip 与依据数字，
全部 pass（manual 由人另行确认）才算机器这一侧过关。

能机器判的项：
  1 产物新鲜（status；册配置登记了冻结基线 `freeze:` 时改比快照产物 sha，见 ops/freeze.py）＋ 缓存不错位（cache verify，只读）
  1c 模型在场：本机装了 torch、两份权重都在（不然 1a 的新鲜度是拿「没模型」比「没模型」，不可信），
     且 Step5-b 产物里有字的页都出过 embedding 候选（没 torch 跑出来的产物指纹照样新鲜，只能看产物）
  2 待审清零（待审卡片按类计数；`--tier rough` 粗校档只报数、不计，终校档 `final`（缺省）才计）
  2b 收尾闸 closure_gaps = 0（有定字裁决却没出字）
  2c □ 有去向：导出文本里每个阙文格在公众待审单或重切清单上（给了 --export-dir 才查）；待审单缺省读中心库
     `feedback/lists/proofing/<书>/<章>.pending.json`（数据目录里，`--pending` 可改，见 `release_gates.resolve_pending`）
  2d 整理本对不上的列（align_ref `coord_fallback`）逐列有交代（列交代单或重切清单）
     ——2c、2d 是用户 10-19 定的放行硬项（GUJI-624），粗校档、终校档都计，见 `ops/release_gates.py`
  8 字形库真源已提交（工作区 git 里 feedback/、output/glyph_store/ 没有未提交改动）
  10/11 lines.md 与 pages.json 自洽（给了 --export-dir 才查）
  12 Step9 产物在（reports/<册>/<册>.md 与对勘 html）
  7/13 避諱表、收尾记录在（给了 --notes 才查）
其余（3 4 5 6 9 14）只列为 manual，由人或会话按 runbook 逐项确认。
"""
from __future__ import annotations

import json
from pathlib import Path

PASS, FAIL, MANUAL, SKIP, ERROR = "pass", "fail", "manual", "skip", "error"


def _item(no: str, name: str, status: str, detail: str = "", data=None) -> dict:
    return {"no": no, "name": name, "status": status, "detail": detail, "data": data}


#: 参数里记「共享输入」内容指纹的字段：语料、证人／参照本、格位表、字组与异体表、借来的字形库、字体域等，
#: 由别的会话、别的册在中心库里更新，不是本册的代码、参数或人裁（A32 册 005 复盘 I，2026-10-24）。
SHARED_PARAMS = frozenset({
    "corpus_fingerprint", "witness_fingerprint", "lane_witness_fingerprint", "ai_evidence_fingerprint",
    "layout_fingerprint", "group_flow_fingerprint", "variants_fingerprint", "variant_graph_fingerprint",
    "iron_config_fingerprint", "note_fingerprint", "borrow_fingerprint", "db_font_fingerprint",
})
_SHARED_PREFIX = "参数变了："


def _shared_only(reason: str) -> list[str] | None:
    """过期原因是「参数变了：字段…」且字段全是共享输入 → 字段表；否则 None。"""
    if not reason.startswith(_SHARED_PREFIX):
        return None
    fields = reason[len(_SHARED_PREFIX):].split("、")
    return fields if fields and set(fields) <= SHARED_PARAMS else None


def _split_shared(steps: dict) -> tuple[dict, dict[str, int]]:
    """把只因共享输入变了（及其沿 DAG 传下来的「上游过期」）而过期的页从坏账里剔出来。

    一步里过期原因全是共享字段或「上游过期」、且没有缺失／失败／阻塞，才整步剔掉；
    「上游产物变了」（上游已重跑出不同产物）、册配置、本册参数、显式失效、旧条目分不出的「参数变了」都算本册的。
    返回（剔完的坏账，{共享字段: 页数}）；有一步不全是共享的，就不剔（字段计数照报）。"""
    bad: dict = {}
    fields: dict[str, int] = {}
    own = False
    for sid, d in steps.items():
        c = {k: d["counts"][k] for k in ("stale", "missing", "failed", "blocked") if d["counts"][k]}
        if not c:
            continue
        bad[sid] = c
        reasons = d.get("stale_reasons") or {}
        for r, n in reasons.items():
            f = _shared_only(r)
            if f is not None:
                for x in f:
                    fields[x] = fields.get(x, 0) + n
            elif r != "上游过期":
                own = True
        if set(c) != {"stale"}:
            own = True
    if own or not fields:
        return bad, fields
    return {}, fields


def _fresh(eng, pages, strict_cv: bool = False) -> dict:
    """第 1a 项。缺省（用户 10-19 定「在跑它的那个版本下新鲜就行」）：只因代码／版本变了过期、
    产物记着正式版 cv_version 的页算新鲜，只计数并列出本册用到的 cv 版本；`strict_cv` 回到旧口径。

    只因共享输入被别处更新而过期（`SHARED_PARAMS`，见 `_split_shared`）也不算失败，另起一句点名字段，
    冻结时记一笔（1.0 发布标准 I）；本册自己的变动照旧判失败，原因里两类都列。"""
    st = eng.status(pages=pages, code_ok=not strict_cv)
    bad, shared = _split_shared(st["steps"])
    n_code = sum(d.get("code_only", 0) for d in st["steps"].values())
    vers: dict[str, int] = {}
    for d in st["steps"].values():
        for v, n in (d.get("cv_versions") or {}).items():
            vers[v] = vers.get(v, 0) + n
    note = (f"（另有 {n_code} 页只是代码／版本变了，不计；产物用到的 cv 版本："
            + "、".join(f"{v}×{n}" for v, n in sorted(vers.items())) + "）") if n_code else ""
    if shared:
        what = "、".join(f"{k}×{n}" for k, n in sorted(shared.items()))
        note += (f"（共享输入被别处更新：{what}；冻结时记一笔，不算失败）" if not bad
                 else f"（其中共享输入变了的：{what}；另有本册自己的变动，见各步原因）")
    data = bad or None
    if bad:
        data = {sid: {**c, "reasons": st["steps"][sid].get("stale_reasons") or {}} for sid, c in bad.items()}
    elif shared:
        data = {"shared_inputs": shared}
    return _item("1a", "产物新鲜", PASS if not bad else FAIL,
                 ("全部新鲜" if not bad else f"{len(bad)} 步有过期/缺失/失败") + note, data)


def _fresh_or_frozen(eng, pages, ws: Path, strict_cv: bool = False) -> dict:
    """册配置登记了冻结基线（`freeze:`）就比快照，否则照旧比现行指纹（GUJI-601）。"""
    from .freeze import fresh_frozen, is_frozen
    if not is_frozen(eng.book):
        return _fresh(eng, pages, strict_cv)
    from ..core.workspace import feedback_root
    return fresh_frozen(eng, pages, ws, feedback_root=feedback_root())


def _models(eng, pages) -> dict:
    """第 1c 项：裁判与识别模型真的在场。

    Step3 的切点裁判（U-Net）和 Step5-b 的 CNN 都是「没 torch／没权重就悄悄退回旧办法」：
    产物照出，只打一条警告。Step3 的指纹把「裁判不可用」记成空串，可本机也没 torch 时
    期望值同样是空串，1a 照报新鲜；Step5-b 的指纹只看权重文件、不看 torch。
    所以这里先查本机，再查 Step5-b 产物里 embedding 有没有出过候选（D 10-19 报）。"""
    import importlib.util
    from ..clustering import cnn_candidates as CNN
    from ..core.spec import page_key
    from ..utils.cut_select import DEFAULT_CKPT as JUDGE_CKPT
    env = []
    if importlib.util.find_spec("torch") is None:
        env.append("没装 torch")
    if not Path(JUDGE_CKPT).is_file():
        env.append(f"缺切点裁判权重 {JUDGE_CKPT}")
    if not Path(CNN.DEFAULT_CKPT).is_file():
        env.append(f"缺识别权重 {CNN.DEFAULT_CKPT}")
    no_emb = []
    for pg in pages:
        rare = eng.store.read(eng.book.id, "rare_candidates", page_key(pg), "rare_candidates")
        if rare is None:
            continue
        n = sum(len(c.chars) for c in rare.columns)
        if n and not rare.sources.get("emb"):
            no_emb.append(pg)
    bad = env or no_emb
    parts = []
    if env:
        parts.append("本机" + "、".join(env) + "：1a 的新鲜度不可信，装齐后重跑 status")
    if no_emb:
        parts.append(f"Step5-b 有 {len(no_emb)} 页没出 embedding 候选（多半是没 torch 时跑的），"
                     f"`guji step rare_candidates <册> --pages … --force` 重跑这几页")
    return _item("1c", "模型在场", FAIL if bad else PASS, "；".join(parts) or "torch 与两份权重都在，Step5-b 各页都有 embedding 候选",
                 {"env": env, "rare_no_emb": no_emb} if bad else None)


def _cache(eng, pages) -> dict:
    from .cache_verify import verify_book
    res = verify_book(eng, pages, fix=False, log=lambda *_: None)
    n = res.get("bad_columns", 0)
    tr = res.get("pages_trusted_by_stamp") or {}
    note = f"；戳对得上免查：字块 {tr.get('char_patch', 0)} 页、列图 {tr.get('column_image', 0)} 页" if tr else ""
    return _item("1b", "缓存不错位", PASS if not n else FAIL,
                 f"错位 {n} 列" + ("（`guji cache verify --fix`）" if n else "") + note, res.get("bad_pages") or None)


def _glyph_store_missing(ws: Path) -> str | None:
    """工作区没有字形库（glyph_store 目录与 glyph.db 都没有）→ 返回缺什么；齐了返回 None。"""
    from ..core.workspace import data_root
    out = Path(ws) / "output"
    gs = (data_root(Path(ws)) or Path(ws)) / "output" / "glyph_store"
    if (out / "glyph.db").is_file():
        return None
    # 空目录不算有库：要有字形账本或人裁事件文件才算
    if gs.is_dir() and ((gs / "glyphs.jsonl").is_file() or (gs / "feedback" / "events").is_dir()
                        or (gs / "events").is_dir()):
        return None
    return f"{out} 下没有 glyph.db，glyph_store 也缺或是空目录"


def _queue(book: str, store, ws: Path | None = None, tier: str = "final") -> dict:
    from ..review.cards import cards, doubt_codes
    # 没有字形库的工作区上，待审卡片出不来，会报「待审 0 ✓」——假绿（GUJI-364 评论 12573，vol01 实有 290 格待审）。
    # 缺库就当体检出错，不当通过。
    miss = _glyph_store_missing(ws) if ws is not None else None
    if miss:
        raise RuntimeError(f"工作区缺字形库，待审数不可信：{miss}（须在带 store 的 H 道工作区跑）")
    res = cards(book, "all", limit=1, only="review", store=store, gate_cut=False,
                skip_decided=True, cls="*", doubt="*")
    cc = res.get("class_counts") or {}
    n = sum(cc.values())
    # 看图判错送回人审的格（overview#428）也在待审里，单列出来：清它要人在控制台裁，不是重跑
    nv = (res.get("doubt_counts") or {}).get("vision_flag", 0)
    # 重切清单上的格不算待审（D 10-19）：那些列 cv 切不对、文本在 book-text 里手拼，格的 id 与 cv 切分
    # 对不上，落不了格事件；它们的去向已经在 2c／2d 把关（要有交代），这里再算一遍就永远清不掉。
    skipped = 0
    if n:
        from .release_gates import RecutList
        rl = RecutList.load(book)
        if rl.pages or rl.cols or rl.cells:
            full = cards(book, "all", limit=1_000_000, only="review", store=store, gate_cut=False,
                         skip_decided=True, cls="*", doubt="*")
            lst = full.get("cards")
            if lst is not None and not full.get("truncated"):
                kept: dict[str, int] = {}
                nv = 0
                for c in lst:
                    if rl.covers_cell(f"{c['page']}:{c['col']}:{c['slot']}{c.get('sub') or ''}"):
                        skipped += 1
                        continue
                    kept[c.get("cls") or "_none"] = kept.get(c.get("cls") or "_none", 0) + 1
                    if "vision_flag" in doubt_codes(c.get("doubts")):
                        nv += 1
                if skipped:
                    cc, n = kept, sum(kept.values())
    detail = (f"待审 {n} 格" + (f"（其中看图判错 {nv} 格，doubt=vision_flag）" if nv else "")
              + (f"；另有 {skipped} 格在重切清单上，不计（见 2c／2d）" if skipped else ""))
    if tier == "rough":     # 粗校档（整理设计 R5，Maren 10-17 定）：待审留给精校，只报数不计
        return _item("2", "待审清零", PASS, detail + "（粗校档不计，终校档才计）", cc or None)
    return _item("2", "待审清零", PASS if not n else FAIL, detail, cc or None)


def _closure(book: str, pages, store, ws: Path | None = None) -> dict:
    from ..review.verdict_view import closure_gaps, closure_mismatches
    miss = _glyph_store_missing(ws) if ws is not None else None
    if miss:
        raise RuntimeError(f"工作区缺字形库，收尾闸不可信：{miss}（须在带 store 的 H 道工作区跑）")
    gaps = closure_gaps(book, pages, store)
    mism = closure_mismatches(book, pages, store)
    return _item("2b", "收尾闸", PASS if not gaps else FAIL,
                 f"已定字却没出字 {len(gaps)} 格；人裁字≠放行字 {len(mism)} 格（报告项，需人扫一眼）",
                 {"gaps": [g["id"] for g in gaps], "mismatches": [m["id"] for m in mism]})


def _export_chapter(export_dir: Path) -> str | None:
    """导出目录里只有一章时取它的章号（`NNN.lines.md`）。"""
    ld = sorted(Path(export_dir).glob("*.lines.md"))
    stem = ld[0].name.split(".")[0] if len(ld) == 1 else ""
    return stem if len(stem) == 3 and stem.isdigit() else None


def _lacuna(book: str, export_dir: Path, chapter: str | None, pending: Path | str | None) -> dict:
    """`pending`：`--pending` 的原值（不给是 None）。缺省读中心库待审单（GUJI-711，`resolve_pending`）。"""
    from .release_gates import check_lacuna, resolve_pending
    path, note = resolve_pending(pending, book, chapter or _export_chapter(export_dir))
    r = check_lacuna(book, export_dir, chapter, path)
    bad = r["loose"] or r["recut_bad"]
    detail = (f"□ {r['lacuna']} 个：上人审页 {len(r['pending'])}，在重切清单 {len(r['recut'])}，"
              f"没去向 {len(r['loose'])}" + (f"（{note}）" if note else "")
              + (f"；重切清单有 {len(r['recut_bad'])} 行位置写坏" if r["recut_bad"] else ""))
    return _item("2c", "□ 有去向", FAIL if bad else PASS, detail,
                 {"loose": r["loose"][:200], "recut_bad": r["recut_bad"][:50]} if bad else None)


def _fallback(book: str, pages, store) -> dict:
    from .release_gates import HOT_PAGE_COLS as RG_HOT
    from .release_gates import check_fallback
    r = check_fallback(book, pages, store)
    bad = r["loose"] or r["ledger_bad"] or r["recut_bad"]
    acts = "，".join(f"{k} {v}" for k, v in sorted(r["by_action"].items()))
    detail = (f"整理本对不上的列 {r['columns']} 列：已交代 {r['columns'] - len(r['loose'])}"
              + (f"（{acts}）" if acts else "") + f"，没交代 {len(r['loose'])}"
              + (f"；列交代单有 {len(r['ledger_bad'])} 行写坏" if r["ledger_bad"] else "")
              + (f"；其中 {len(r['hot_pages'])} 页各 ≥{RG_HOT} 列没交代，宜整页进重切清单（"
                 + "、".join(f"p{h['page']}" for h in r["hot_pages"][:10])
                 + ("…" if len(r["hot_pages"]) > 10 else "") + "）" if r["hot_pages"] else ""))
    return _item("2d", "整理本对不上的列有交代", FAIL if bad else PASS, detail,
                 {"loose": r["loose"][:500], "ledger_bad": r["ledger_bad"][:50],
                  "recut_bad": r["recut_bad"][:50], "hot_pages": r["hot_pages"][:200]} if bad else None)


def _store_committed(ws: Path) -> dict:
    from ..core.workspace import central_marker
    if central_marker(Path(ws)):
        # 迁到中心库后（GUJI-608）：看数据目录有没有没推的改动（不连网，对上次拉／推的基准）
        try:
            from .central_glyph import glyph_hooks
            from ..datastore.workcopy import local_changes
            dirty = local_changes(Path(ws), glyph_hooks(Path(ws)))
        except BaseException as e:  # noqa: BLE001  （含 SystemExit：还没拉过）
            return _item("8", "字形库与人裁已推进中心库", ERROR, f"{type(e).__name__}: {e}")
        return _item("8", "字形库与人裁已推进中心库", PASS if not dirty else FAIL,
                     "数据目录与中心库一致" if not dirty else f"{len(dirty)} 个文件没推（`guji db push -w <工作区>`）",
                     dirty[:50] or None)
    return _item("8", "字形库与人裁已推进中心库", FAIL,
                 f"工作区还没迁进中心库（`guji db migrate -w {ws}`）；字形库与人裁不再提交进工作区 git")


def _export(export_dir: Path, chapter: str | None) -> list[dict]:
    from ..formats.guji_format import _plain_chars
    ld = sorted(export_dir.glob("*.lines.md"))
    if chapter:
        ld = [p for p in ld if p.name.startswith(chapter + ".")]
    if len(ld) != 1:
        return [_item("10", "lines.md", FAIL, f"{export_dir} 下找到 {len(ld)} 个 lines.md，应为 1 个")]
    lines = ld[0]
    stem = lines.name[: -len(".lines.md")]
    pj = export_dir / f"{stem}.pages.json"
    chars = _plain_chars(lines.read_text(encoding="utf-8"))
    items = [_item("10", "lines.md", PASS, f"{lines.name}：{len(chars)} 字元（导出器口径，含阙文占位）",
                   {"chars": len(chars), "lacuna": sum(1 for c in chars if c in ("〓", "□"))})]
    if not pj.exists():
        items.append(_item("11", "pages.json", FAIL, f"缺 {pj.name}"))
        return items
    pages = json.loads(pj.read_text(encoding="utf-8"))
    offs = {c["o"] for p in pages["pages"] for c in p["cells"] if isinstance(c.get("o"), int)}
    missing = [i for i in range(len(chars)) if i not in offs]
    extra = sorted(o for o in offs if o >= len(chars))
    ok = not missing and not extra
    items.append(_item("11", "pages.json 与 lines.md 逐字对上", PASS if ok else FAIL,
                       f"{len(pages['pages'])} 页；无框的字 {len(missing)}，多出的框 {len(extra)}"
                       "；抽检框位要另外目测（check_pages_json_boxes.py）",
                       {"missing": missing[:50], "extra": extra[:50]} if not ok else None))
    return items


def _step9(reports: Path, book: str) -> dict:
    rep = reports / book
    md = rep / f"{book}.md"
    html = sorted(rep.glob("collation_*.html"))
    ok = md.exists() and bool(html)
    return _item("12", "Step9 产物", PASS if ok else FAIL,
                 f"{'有' if md.exists() else '缺'} {md.name}；对勘 html {len(html)} 份")


def _notes(notes: Path) -> list[dict]:
    out = []
    av = sorted(notes.glob("避諱改字表*.md"))
    out.append(_item("7", "避諱改字表", PASS if av else FAIL, av[-1].name if av else f"{notes} 下没有"))
    rec = notes / "收尾记录.md"
    out.append(_item("13", "收尾记录", PASS if rec.exists() else FAIL, rec.name if rec.exists() else "缺"))
    return out


MANUAL_ITEMS = [
    ("3", "队列外改判清零：最新放行错穷举里每格都有人裁或写明原因"),
    ("4", "切分问题有着落：修好的已重算复审，没修好的标存疑并列出"),
    ("5", "己/已/巳 全族按文意定，不拿证人当真值"),
    ("6", "对勘存疑逐条有人裁或说明"),
    ("9", "人裁入测试集，dry-run updated = 0"),
    ("14", "改过页面的册已记进 Commons 修图记录"),
]


def run(eng, ws: Path, pages, export_dir: Path | None = None, chapter: str | None = None,
        notes: Path | None = None, reports: Path | None = None, tier: str = "final",
        pending: Path | str | None = None, strict_cv: bool = False) -> dict:
    book = eng.book.id
    items: list[dict] = []
    checks = [
        ("1a", "产物新鲜", lambda: [_fresh_or_frozen(eng, pages, ws, strict_cv)]),
        ("1b", "缓存不错位", lambda: [_cache(eng, pages)]),
        ("1c", "模型在场", lambda: [_models(eng, pages)]),
        ("2", "待审清零", lambda: [_queue(book, eng.store, ws, tier)]),
        ("2b", "收尾闸", lambda: [_closure(book, pages, eng.store, ws)]),
        ("2c", "□ 有去向", lambda: [_lacuna(book, export_dir, chapter, pending)] if export_dir else
         [_item("2c", "□ 有去向", SKIP, "没给 --export-dir")]),
        ("2d", "整理本对不上的列有交代", lambda: [_fallback(book, pages, eng.store)]),
        ("8", "字形库与人裁已推进中心库", lambda: [_store_committed(ws)]),
        ("10", "lines.md／pages.json", lambda: _export(export_dir, chapter) if export_dir else
         [_item("10", "lines.md", SKIP, "没给 --export-dir"), _item("11", "pages.json", SKIP, "没给 --export-dir")]),
        ("12", "Step9 产物", lambda: [_step9(reports or ws / "reports", book)]),
        ("7", "避諱表／收尾记录", lambda: _notes(notes) if notes else
         [_item("7", "避諱改字表", SKIP, "没给 --notes"), _item("13", "收尾记录", SKIP, "没给 --notes")]),
    ]
    for no, name, fn in checks:
        try:
            items.extend(fn())
        except Exception as e:  # noqa: BLE001 —— 一项算不出来不拖垮整张体检表
            items.append(_item(no, name, ERROR, f"{type(e).__name__}: {e}"))
    items.extend(_item(no, txt, MANUAL) for no, txt in MANUAL_ITEMS)
    order = {s: i for i, s in enumerate(["1a", "1b", "1c", "2", "2b", "2c", "2d", "3", "4", "5", "6", "7", "8", "9",
                                         "10", "11", "12", "13", "14"])}
    items.sort(key=lambda it: order.get(it["no"], 99))
    machine = [it for it in items if it["status"] not in (MANUAL, SKIP)]
    return {"book": book, "workspace": str(ws), "pages": len(pages), "tier": tier,
            "machine_ok": all(it["status"] == PASS for it in machine),
            "counts": {s: sum(1 for it in items if it["status"] == s) for s in (PASS, FAIL, ERROR, MANUAL, SKIP)},
            "items": items}


ICON = {PASS: "✓", FAIL: "✗", ERROR: "!", MANUAL: "·", SKIP: "-"}


def print_report(res: dict) -> None:
    print(f"{res['book']} 交付体检（{'粗校档' if res.get('tier') == 'rough' else '终校档'}）· {res['pages']} 页 · {res['workspace']}")
    for it in res["items"]:
        print(f"  {ICON[it['status']]} {it['no']:>3} {it['name']}" + (f"：{it['detail']}" if it["detail"] else ""))
    c = res["counts"]
    verdict = "机器项全部通过" if res["machine_ok"] else "机器项未通过"
    print(f"  —— {verdict}（通过 {c['pass']}，未过 {c['fail']}，出错 {c['error']}；"
          f"待人确认 {c['manual']}，未查 {c['skip']}）")
