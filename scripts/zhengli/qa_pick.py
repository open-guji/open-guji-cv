#!/usr/bin/env python3
"""机器放行格质检：按通道挑低置信格、出拼图，判完出汇总（GUJI-693，GUJI-730 P2-1）。

不随机抽（用户定）：在 seed_admit 里 admit=True、非人裁（channel≠human）、非排除的格中，
每条放行通道按置信从低到高取若干，总数 < 200。同一份产物、同一组配额，挑出的样本逐格一样（可复跑）。
置信：context 通道看 `evidence.ctx_margin`（上下文余量），其余看 `evidence.cov`；没有数的排最前（最没底）。

  pick   只读 products 快照（seed_admit）＋出单版 cord（格框）＋原图 → --out 下：
           样本.json      样本集（id、配额、文本 sha、每格 n/格号/通道/字/置信/框）
           清单.md        逐格一行，带「判」空栏，照抄成判.tsv 填
           sheetNN.png    拼图，每张 20 格，红框是格框，左上角是序号 n
  tally  读样本.json＋判.tsv（列：n、判〔对/错/看不出〕、类型〔判错时必填〕、扩查〔是/否，可空〕、备注）
           → 汇总.md（按通道、按错误类型）＋ qa.jsonl（每格一条，留给 book-qa 分片／audit 事件）

不写中心库、不改产物。判错的格要改字，照常走人裁事件。

用法：
  python3 scripts/zhengli/qa_pick.py pick --book vol05 --products <products 根> \
      --cord <出单版 005.cord.json> --raw-dir <原图目录> --out <目录> [--text-sha <book-text sha>] \
      [--quota rare_ref=20 --quota context=12 …] [--max 199]
  python3 scripts/zhengli/qa_pick.py tally --sample <目录>/样本.json --verdicts <判.tsv> --judge <裁定人>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

#: 默认配额：照册 005 质检（2026-10-22）的挑法；没列的通道不挑。总数封顶 --max。
DEFAULT_QUOTA = {
    "rare_ref": 20, "context": 12, "witness3": 10, "match_replace": 10, "coord_fallback": 8,
    "group_flow": 6, "iron": 4, "split_ref": 4, "seal": 4, "note_lexicon": 4, "match_ref": 8,
}
MAX_CELLS = 199                      # 用户定：样本少于 200
VERDICTS = ("对", "错", "看不出")
#: 1.0 发布标准 §G6 的错误类型
ERROR_TYPES = ("形近替换", "异体码位", "切分错位", "漏切", "阙文↔字", "标记", "非字入文", "其他")
PER_SHEET, SHEET_COLS, TILE = 20, 5, 160
LA = ZoneInfo("America/Los_Angeles")


def conf(rec: dict) -> float | None:
    """这一格的置信数：context 用 ctx_margin，其余用 cov；lane 通道的数可能在 evidence.lane 里。"""
    ev = rec.get("evidence") or {}
    key = "ctx_margin" if rec.get("channel") == "context" else "cov"
    v = ev.get(key)
    if v is None:
        v = (ev.get("lane") or {}).get(key)
    return float(v) if isinstance(v, (int, float)) else None


def admitted(seed_dir: Path, book: str, pages: set[int] | None = None) -> list[dict]:
    """seed_admit 里机器放行的格：admit=True、channel 不是 human、不带 excluded。"""
    out = []
    for f in sorted(seed_dir.glob("p*.json")):
        s = json.loads(f.read_text(encoding="utf-8"))["seed_admit"]
        if pages and s.get("page") not in pages:
            continue
        for col in s["columns"]:
            if not col.get("ok", True):
                continue
            for r in col["chars"]:
                if not r.get("admit") or r.get("channel") in (None, "human") or "excluded" in (r.get("doubts") or []):
                    continue
                cid = r["id"]
                out.append({"id": cid, "a": cid[len(book) + 1:] if cid.startswith(book + ":") else cid,
                            "page": s.get("page"), "channel": r["channel"], "char": r.get("char"),
                            "conf": conf(r)})
    return out


def pick(cells: list[dict], quota: dict[str, int], cap: int = MAX_CELLS) -> list[dict]:
    """每个通道按置信从低到高取配额个（没数的最前，同分按格号），按配额表顺序拼起来，封顶 cap。"""
    by: dict[str, list[dict]] = {}
    for c in cells:
        by.setdefault(c["channel"], []).append(c)
    out: list[dict] = []
    for ch, n in quota.items():
        pool = sorted(by.get(ch, []), key=lambda c: (c["conf"] is not None, c["conf"] or 0.0, c["id"]))
        out += pool[:n]
    return out[:cap]


def sample_id(book: str, ids: list[str], quota: dict[str, int], text_sha: str | None) -> str:
    raw = json.dumps([book, sorted(ids), quota, text_sha], ensure_ascii=False, sort_keys=True)
    return f"qa-{book}-{hashlib.sha256(raw.encode()).hexdigest()[:10]}"


def cord_boxes(cord: dict, book: str) -> dict[str, tuple[int, list[int]]]:
    """cv 格号（book:页:列:格）→ (页, 框)。cord 格有 id 用 id，没有用 a 补 book 前缀。"""
    out = {}
    for pg in cord["pages"]:
        for c in pg.get("cells", []):
            if c.get("box"):
                out[c.get("id") or f"{book}:{c['a']}"] = (pg["page"], c["box"])
    return out


def _font(size: int):
    from PIL import ImageFont
    for p in (os.environ.get("QA_FONT"), "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if p and Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                pass
    return ImageFont.load_default()


def tile(im, box: list[int], n: int, font):
    """格框外扩一半裁出，缩进 TILE×TILE，画红框和序号。"""
    from PIL import Image, ImageDraw
    x, y, w, h = box
    px, py = w // 2, h // 2
    x0, y0 = max(0, x - px), max(0, y - py)
    crop = im.crop((x0, y0, min(im.width, x + w + px), min(im.height, y + h + py))).convert("RGB")
    s = min((TILE - 20) / crop.width, (TILE - 20) / crop.height)
    crop = crop.resize((max(1, round(crop.width * s)), max(1, round(crop.height * s))))
    t = Image.new("RGB", (TILE, TILE), "white")
    ox, oy = (TILE - crop.width) // 2, 18 + (TILE - 18 - crop.height) // 2
    t.paste(crop, (ox, oy))
    d = ImageDraw.Draw(t)
    d.rectangle([ox + (x - x0) * s, oy + (y - y0) * s, ox + (x - x0 + w) * s, oy + (y - y0 + h) * s], outline="red", width=2)
    d.text((3, 1), f"#{n}", fill="black", font=font)
    return t


def sheets(rows: list[dict], raw_dir: Path, out: Path) -> list[str]:
    from PIL import Image
    font, cache, names = _font(14), {}, []
    for k in range(0, len(rows), PER_SHEET):
        part = [r for r in rows[k:k + PER_SHEET] if r.get("box")]
        if not part:
            continue
        nrow = -(-len(part) // SHEET_COLS)
        sheet = Image.new("RGB", (SHEET_COLS * TILE, nrow * TILE), "white")
        for i, r in enumerate(part):
            if r["page"] not in cache:
                cache.clear()
                cache[r["page"]] = Image.open(raw_dir / f"{r['page']}.png")
            sheet.paste(tile(cache[r["page"]], r["box"], r["n"], font), ((i % SHEET_COLS) * TILE, (i // SHEET_COLS) * TILE))
        name = f"sheet{k // PER_SHEET + 1:02d}.png"
        sheet.save(out / name)
        names.append(name)
    return names


def cmd_pick(a) -> int:
    quota = dict(DEFAULT_QUOTA)
    if a.quota:
        quota = {}
        for q in a.quota:
            ch, _, n = q.partition("=")
            quota[ch] = int(n)
    pages = {int(p) for p in a.pages.split(",")} if a.pages else None
    seed_dir = Path(a.products) / a.book / "seed_admit"
    if not seed_dir.is_dir():
        sys.exit(f"✗ 没有 {seed_dir}")
    pool = admitted(seed_dir, a.book, pages)
    rows = pick(pool, quota, a.max)
    boxes = cord_boxes(json.loads(Path(a.cord).read_text(encoding="utf-8")), a.book) if a.cord else {}
    for i, r in enumerate(rows, 1):
        r["n"] = i
        if r["id"] in boxes:
            r["page"], r["box"] = boxes[r["id"]][0], boxes[r["id"]][1]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    have = Counter(c["channel"] for c in pool)
    got = Counter(r["channel"] for r in rows)
    sid = sample_id(a.book, [r["id"] for r in rows], quota, a.text_sha)
    doc = {"schema": "guji-qa-sample/0.1", "id": sid, "book": a.book, "text_sha": a.text_sha,
           "picked_at": datetime.now(LA).isoformat(timespec="seconds"), "rule": "每通道置信最低若干，不随机",
           "quota": quota, "max": a.max, "pool": dict(have), "cells": rows}
    (out / "样本.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    names = sheets(rows, Path(a.raw_dir), out) if a.raw_dir else []
    no_box = [r["n"] for r in rows if not r.get("box")]
    md = [f"# {a.book} 机器放行格质检样本 {sid}", "",
          f"规则：每通道置信最低若干，不随机；共 {len(rows)} 格（上限 {a.max}）。文本 sha：{a.text_sha or '（未给）'}。", "",
          "| 通道 | 放行格 | 配额 | 取 |", "|---|---|---|---|"]
    md += [f"| {ch} | {have.get(ch, 0)} | {n} | {got.get(ch, 0)} |" for ch, n in quota.items()]
    other = sorted(set(have) - set(quota))
    if other:
        md += ["", "没配额（不挑）的通道：" + "、".join(f"{ch} {have[ch]}" for ch in other)]
    md += ["", f"拼图：{'、'.join(names) or '（没给 --raw-dir，未出）'}" + (f"；缺框没进拼图：{no_box}" if no_box else ""), "",
           "判完照下表抄成判.tsv（制表符分隔，表头 n 判 类型 扩查 备注；判＝对/错/看不出，判错时类型必填："
           + "／".join(ERROR_TYPES) + "）。", "",
           "| n | 格 | 通道 | 机器字 | 置信 | 判 | 类型 |", "|---|---|---|---|---|---|---|"]
    md += [f"| {r['n']} | {r['a']} | {r['channel']} | {r['char'] or '（非字）'} | "
           f"{'—' if r['conf'] is None else round(r['conf'], 4)} |  |  |" for r in rows]
    (out / "清单.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"✓ {sid}：{len(rows)} 格，拼图 {len(names)} 张 → {out}")
    return 0


def read_verdicts(path: Path) -> dict[int, dict]:
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    head = lines[0].split("\t")
    if head[:2] != ["n", "判"]:
        sys.exit("✗ 判.tsv 表头要以「n<TAB>判」开头")
    out, bad = {}, []
    for ln in lines[1:]:
        row = dict(zip(head, (x.strip() for x in ln.split("\t"))))
        n, v, t = int(row["n"]), row.get("判", ""), row.get("类型", "")
        if v not in VERDICTS or (v == "错" and t not in ERROR_TYPES) or (t and t not in ERROR_TYPES):
            bad.append(n)
        out[n] = row
    if bad:
        sys.exit(f"✗ 这些 n 的判／类型不对（判：{'/'.join(VERDICTS)}；类型：{'/'.join(ERROR_TYPES)}）：{bad}")
    return out


def tally(sample: dict, verdicts: dict[int, dict], judge: str) -> tuple[list[dict], str]:
    rows, ts = [], datetime.now(LA).isoformat(timespec="seconds")
    for c in sample["cells"]:
        v = verdicts.get(c["n"])
        rows.append({"sample": sample["id"], "cell": c["id"], "channel": c["channel"], "char": c["char"],
                     "conf": c["conf"], "text_sha": sample.get("text_sha"),
                     "verdict": v["判"] if v else None, "type": (v or {}).get("类型") or None,
                     "expanded": {"是": True, "否": False}.get((v or {}).get("扩查", "")),
                     "note": (v or {}).get("备注") or None, "judge": judge if v else None, "ts": ts if v else None})
    by_ch: dict[str, Counter] = {}
    for r in rows:
        by_ch.setdefault(r["channel"], Counter())[r["verdict"] or "未判"] += 1
    types = Counter(r["type"] for r in rows if r["verdict"] == "错")
    n_done = sum(1 for r in rows if r["verdict"])
    n_err = sum(1 for r in rows if r["verdict"] == "错")
    n_unk = sum(1 for r in rows if r["verdict"] == "看不出")
    md = [f"# 质检汇总 {sample['id']}（{sample['book']}）", "",
          f"挑格：每通道置信最低若干，不随机，共 {len(rows)} 格；已判 {n_done}，错 {n_err}，看不出 {n_unk}。",
          f"裁定：{judge}（一人裁定即算定）。文本 sha：{sample.get('text_sha') or '（未给）'}。", "",
          "错误率只报数、不设门槛；样本是挑出来的低置信格，**不是全册错误率的估计**。", "",
          "| 通道 | 格 | 对 | 错 | 看不出 | 未判 |", "|---|---|---|---|---|---|"]
    for ch, c in by_ch.items():
        md.append(f"| {ch} | {sum(c.values())} | {c['对']} | {c['错']} | {c['看不出']} | {c['未判']} |")
    md += ["", "| 错误类型 | 格 |", "|---|---|"] + [f"| {t} | {n} |" for t, n in types.most_common()]
    errs = [r for r in rows if r["verdict"] in ("错", "看不出")]
    if errs:
        md += ["", "| 格 | 通道 | 机器字 | 判 | 类型 | 扩查 | 备注 |", "|---|---|---|---|---|---|---|"]
        md += [f"| {r['cell']} | {r['channel']} | {r['char'] or '（非字）'} | {r['verdict']} | {r['type'] or ''} | "
               f"{'' if r['expanded'] is None else ('是' if r['expanded'] else '否')} | {r['note'] or ''} |" for r in errs]
    return rows, "\n".join(md) + "\n"


def cmd_tally(a) -> int:
    sp = Path(a.sample)
    sample = json.loads(sp.read_text(encoding="utf-8"))
    rows, md = tally(sample, read_verdicts(Path(a.verdicts)), a.judge)
    out = Path(a.out) if a.out else sp.parent
    (out / "qa.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    (out / "汇总.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pick")
    p.add_argument("--book", required=True)
    p.add_argument("--products", default=os.environ.get("GUJI_PRODUCTS_DIR"), required=not os.environ.get("GUJI_PRODUCTS_DIR"))
    p.add_argument("--cord", help="出单版 <章>.cord.json（格框）；不给就不出拼图框")
    p.add_argument("--raw-dir", help="原图目录（<页>.png）；不给就不出拼图")
    p.add_argument("--out", required=True)
    p.add_argument("--pages", help="只看这些页，逗号分隔")
    p.add_argument("--text-sha", help="被检 book-text 文本 sha（记进样本，供追查）")
    p.add_argument("--quota", action="append", help="通道=格数，可多次；给了就整张替换默认配额")
    p.add_argument("--max", type=int, default=MAX_CELLS)
    p.set_defaults(fn=cmd_pick)
    t = sub.add_parser("tally")
    t.add_argument("--sample", required=True)
    t.add_argument("--verdicts", required=True)
    t.add_argument("--judge", required=True)
    t.add_argument("--out")
    t.set_defaults(fn=cmd_tally)
    a = ap.parse_args(argv)
    if getattr(a, "max", 0) and a.max >= 200:
        sys.exit("✗ 样本要少于 200（用户定）")
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
