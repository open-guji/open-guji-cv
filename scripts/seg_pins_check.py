#!/usr/bin/env python3
"""推格级钉子（manual-cells）前的预检（A22 F3，2026-11-10）。逻辑在 `open_guji_cv/feedback/pins_check.py`。

查四件事，只读、不改本机产物、缓存和中心库：
  1. 钉子列 vs cell_shrink：钉子每一格都要出同号字格（防史記 r16 那种静默丢字）；
  2. 照执行机条件（空字块缓存、不现切）重算涉及页的人裁绑定，标出会让 seed_admit 报 no_patch 的事件
     （史記 04 #1746、06 #1747）和不再采信（review／void）的事件；
  3. 给失锚的老事件出补锚草稿（墨框取**旧切分**那一格的页面框，预演落到新切分哪一格），人看图核过才推；
  4. 本册人裁事件 id 有没有重复。

用法一（缺省，沙箱）：本机数据目录是推之前的样子（刚 db pull），新钉子写在一个单独文件里：

    export GUJI_WORKSPACE=<工作区>
    python scripts/seg_pins_check.py --book 04 --items <新 manual-cells items.jsonl> --out <报告目录>

  工具把涉及页的产物、列图拷进临时目录，用新钉子从 row_segment 跑到 cell_shrink（要装 torch），
  旧切分就是本机现有产物。本机产物、缓存一概不动。

用法二（--no-run）：已经把新钉子写进本机分片、本机重跑过，只做检查：

    python scripts/seg_pins_check.py --book 04 --no-run --base-items <改之前的分片> --old-products <旧产物根>

  --pages 可直接点名页。退出码：0 = 可以推；3 = 有问题（看报告）；2 = 用法错或本机条件不够（缺切点裁判权重、
  字形库没拉：结论不可信，拒跑）。沙箱里任何一步失败（如缺原图）一律判不通过。
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", required=True, help="册号（book id）")
    ap.add_argument("--items", help="新 manual-cells items.jsonl（沙箱模式：要推的那份）")
    ap.add_argument("--no-run", action="store_true", help="不沙箱重跑：新钉子已在本机分片、本机已重跑")
    ap.add_argument("--base-items", help="改钉子之前的分片：--no-run 时与本机现行分片比；沙箱模式下替代本机分片当基线")
    ap.add_argument("--old-products", help="--no-run 时：旧切分的产物根（出补锚草稿用）")
    ap.add_argument("--pages", help="直接点名页（逗号分隔），盖过按改动算出的页")
    ap.add_argument("--out", default="seg_pins_check_out", help="报告目录")
    a = ap.parse_args(argv)
    if not a.no_run and not a.items:
        ap.error("沙箱模式要 --items（或加 --no-run）")

    from open_guji_cv.core.spec import page_key
    from open_guji_cv.feedback import pins_check as pc
    from open_guji_cv.feedback.lookup import MANUAL_CELLS_SHARD, check_manual_cells
    from open_guji_cv.gold.store import verdict_store
    from open_guji_cv.products.store import ProductStore
    from open_guji_cv.report.slots import CELLS_KIND, cells_step

    book = a.book
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="pins_check_"))
    shard = verdict_store().items_path(MANUAL_CELLS_SHARD)
    if a.no_run:
        new_file = shard
        old = pc.pins_of(pc.read_items(Path(a.base_items)), book) if a.base_items else None
    else:
        new_file = Path(a.items)
        # 基线：给了 --base-items 就用它（本机分片已经推过新钉子时，拿推之前那份比），否则本机分片
        old = pc.pins_of(pc.read_items(Path(a.base_items) if a.base_items else shard), book)
    fmt = check_manual_cells(new_file) if new_file.exists() else [f"{new_file} 不存在"]
    new = pc.pins_of(pc.read_items(new_file), book)
    changed = pc.diff_pins(old, new) if old is not None else {k: "pinned" for k in new}
    if a.pages:
        pages = sorted({int(x) for x in a.pages.split(",") if x.strip()})
    else:
        pages = sorted({pg for pg, _c in changed})
    cols = {k for k, v in changed.items() if v != "removed" and k[0] in pages}

    lines = [f"# 推钉子预检 {book}", "",
             f"- 新钉子：`{new_file}`（格式问题 {len(fmt)} 条）",
             f"- 改动列 {len(changed)}：" + "、".join(f"{p}:{c}({v})" for (p, c), v in changed.items()),
             f"- 涉及页：{','.join(map(str, pages)) or '无'}",
             (f"- 推库后交单从 row_segment 重跑这些页：`guji_jobs submit --book {book} --from row_segment "
              f"--pages {','.join(map(str, pages))} …`"), ""]
    bad = bool(fmt)
    lines += [f"- 格式：{p}" for p in fmt]

    if pages:
        why = pc.glyph_db_missing()
        if why:
            print(f"❌ {why}：人裁绑定要读它。先 `guji db sync -w <工作区>`（或 db pull）拉字形库再跑。", file=sys.stderr)
            return 2

    if a.no_run:
        store = ProductStore()
        old_store = ProductStore(Path(a.old_products)) if a.old_products else None
    else:
        lines.append(f"- 沙箱：`{tmp}`（从 row_segment 跑到 cell_shrink）")
        try:
            store, _cache, rep = pc.sandbox_rerun(book, pages, tmp / "sandbox", new) if pages else (ProductStore(), None, None)
        except pc.SandboxNotReady as e:
            print(f"❌ {e}", file=sys.stderr)
            return 2
        old_store = ProductStore()
        errs = pc.run_failures(rep) if rep is not None else []
        lines += [f"- 沙箱重跑失败：{e}" for e in errs]
        bad |= bool(errs)
    lines.append("")

    # 1. 钉子 vs cell_shrink
    lines += ["## 一、钉子列 vs cell_shrink", ""]
    n1 = 0
    for pg, col in sorted(cols):
        chars = store.read(book, "cell_shrink", page_key(pg), "char_index")
        cc = None if chars is None else next((c for c in chars.columns if c.col == col), None)
        if chars is None:
            lines.append(f"- {book}:{pg}:{col} cell_shrink 没出产物（重跑失败或上游缺失）")
            n1 += 1
            continue
        for p in pc.check_pin_vs_chars(new[(pg, col)], cc):
            lines.append(f"- {book}:{pg}:{col} {p}")
            n1 += 1
    lines += [f"- 共 {n1} 处问题" if n1 else "- 全部一致", ""]
    bad |= n1 > 0

    # 2. 模拟执行机绑定
    rows = pc.simulate_bindings(book, pages, tmp / "exec", store=store) if pages else {}
    verdict = {eid: pc.classify_row(r) for eid, r in rows.items()}
    in_cols = {eid for eid, r in rows.items()
               if tuple(map(int, r["key"].split(":")[1:3])) in {(p, c) for p, c in changed}}
    with open(out / "bindings.tsv", "w", encoding="utf-8") as f:
        f.write("event\tkey\tshape\tstatus\tbound\twhy\tverdict\tin_changed_col\n")
        f.writelines("\t".join(str(x if x is not None else "") for x in (
                eid, r["key"], r.get("shape"), r["status"], r.get("bound"), r.get("why"),
                verdict[eid], int(eid in in_cols))) + "\n" for eid, r in sorted(rows.items(), key=lambda kv: kv[1]["key"]))
    probs = [eid for eid, v in verdict.items() if v != "ok"]
    # 旧切分上照执行机条件再算一遍绑定：补锚草稿要（人裁当时落在哪一格），也用来认「老失锚」——
    # 不在改动列、旧切分下也没绑上的，推不推这次钉子都一样，单列出来、不计入结论（SJ 11-10）
    old_rows = (pc.simulate_bindings(book, pages, tmp / "exec_old", store=old_store)
                if old_store is not None and probs else {})
    probs, preexist = pc.split_preexisting(probs, in_cols, old_rows)
    lines += ["## 二、照执行机条件重算人裁绑定", "",
              f"- 涉及页人裁 {len(rows)} 条，其中改动列里 {len(in_cols)} 条",
              f"- 失锚（执行机 seed_admit 报 no_patch 或悄悄丢人裁）{sum(verdict[e] == 'unbound' for e in probs)} 条；"
              f"对不上（review／void，回待审）{sum(verdict[e] == 'lost' for e in probs)} 条"
              + (f"；另老失锚 {len(preexist)} 条（见下，不计）" if preexist else ""),
              "- 明细 `bindings.tsv`", ""]
    for eid in sorted(probs, key=lambda e: rows[e]["key"]):
        r = rows[eid]
        lines.append(f"- {r['key']} {r.get('shape') or ''} {r['status']}{('/' + r['why']) if r.get('why') else ''}"
                     f"{'' if eid in in_cols else '（不在改动列）'}")
    bad |= any(verdict[e] == "unbound" for e in probs) or any(e in in_cols for e in probs)
    if preexist:
        lines += ["", f"### 老失锚 {len(preexist)} 条（不在改动列、旧切分下也没绑上，不计入结论）", ""]
        for eid in sorted(preexist, key=lambda e: rows[e]["key"]):
            r, o = rows[eid], old_rows[eid]
            lines.append(f"- {r['key']} {r.get('shape') or ''} {r['status']}{('/' + r['why']) if r.get('why') else ''}"
                         f"（旧切分：{o.get('status')}{('/' + o['why']) if o.get('why') else ''}）")

    # 3. 补锚草稿
    lines += ["", "## 三、补锚草稿", ""]
    if old_store is not None and probs:
        step = cells_step(book)
        # old_rows（上面算好）：人裁当时落在哪一格，按那一格的位置出墨框（不按事件格号）
        drafts, skipped = [], []
        from open_guji_cv.feedback.events import EventLog, iter_events_readonly
        has_anchor = {e.id for e in iter_events_readonly(EventLog())
                      if e.id in probs and e.target.anchor and e.target.anchor.get("bbox")}
        for eid in sorted(probs, key=lambda e: rows[e]["key"]):
            r = rows[eid]
            if eid in has_anchor:
                skipped.append(f"{r['key']}：事件自带锚，补锚档不起作用，要人重审")
                continue
            pg = int(r["key"].split(":")[1])
            orow = old_rows.get(eid) or {}
            ob = orow.get("bound") if orow.get("status") in pc.USE or orow.get("bound") else None
            if not ob:
                skipped.append(f"{r['key']}：旧切分下这条人裁也没绑上（{orow.get('status') or '无绑定'}），不出草稿，要人重审")
                continue
            oc = old_store.read(book, step, page_key(pg), CELLS_KIND)
            nc = store.read(book, step, page_key(pg), CELLS_KIND)
            d = (pc.propose_anchor(r["key"], eid, pc.cell_boxes(oc), nc, old_bound=ob)
                 if oc is not None and nc is not None else None)
            if d is None:
                skipped.append(f"{r['key']}：旧切分里没有 {ob} 这一格")
                continue
            d["evidence"]["shape"] = r.get("shape")
            seen = pc.old_char(old_store.read(book, "seed_admit", page_key(pg), "seed_admit"), ob)
            d["evidence"]["old_char"] = seen
            if seen and r.get("shape") and seen != r.get("shape"):
                d["evidence"]["warn"] = f"旧格 {ob} 定的是「{seen}」，人裁是「{r.get('shape')}」"
            drafts.append(d)
        with open(out / "anchors_draft.jsonl", "w", encoding="utf-8") as f:
            for d in drafts:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        for d in drafts:
            ev = d["evidence"]
            lines.append(f"- {d['key']} {ev.get('shape') or ''}（旧格 {ev['old_cell']}）→ {ev['pred']}"
                         f"{(' ' + ev['to']) if ev['to'] and ev['to'] != d['key'] else ''}（墨框落入 {ev['inside']:.0%}）"
                         + (f" ⚠️ {ev['warn']}" if ev.get("warn") else ""))
        lines += [f"- {s}" for s in skipped]
        lines += ["", f"草稿 {len(drafts)} 行在 `anchors_draft.jsonl`。逐条看图核人裁原意后，"
                  f"追加到 `feedback/anchors/{book}.jsonl`（evidence 里写原因），再重跑本预检到 0。"]
    elif probs:
        lines.append("- 没有旧切分（--no-run 时要给 --old-products），不出草稿")
    else:
        lines.append("- 不需要")

    # 4. 重复事件 id
    from open_guji_cv.feedback.events import EventLog, iter_events_readonly
    dup = pc.duplicate_event_ids(e for e in iter_events_readonly(EventLog())
                                 if e.target.key.startswith(f"{book}:"))
    lines += ["", "## 四、人裁事件 id 重复", "",
              ("- 无" if not dup else "\n".join(f"- {k} ×{n}" for k, n in sorted(dup.items())))]
    bad |= bool(dup)

    lines += ["", f"结论：{'有问题，先处理再推' if bad else '可以推'}"]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 3 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
