# -*- coding: utf-8 -*-
"""候选表 → 码位审核页（guji-manager review-pages char_card，--no-rest-ok 一格一卡）的 items。

每个码取至多 N 个样例格：本书切图（从 siku-qiefen-v2 页图按文本层字框裁）＋维基 Commons 标准字形图（SKQS_<n>.svg，并排显示）。
候选字（来源）带在格上，点即选。用法：
  python3 make_review_items.py --cand pua_table_candidates.jsonl --v2zip q.zip --out DIR [--only open|all] [--n 2] [--no-wiki]
再：guji-manager review-pages build char_card --items DIR/items.jsonl --book 96mid1ogzk --out DIR/page.html --no-rest-ok
"""
from __future__ import annotations
import argparse, gzip, hashlib, io, json, time, urllib.parse, subprocess, zipfile
from pathlib import Path


def wiki_thumbs(names: list[str], out: Path, width: int = 250) -> dict[str, Path]:
    """Commons API 一批至多 50 个题名取缩图地址，再逐个下载；限流时退避。已有的跳过。"""
    got = {}
    todo = [n for n in names if not (out / f"{n}.png").exists()]
    for n in names:
        if (out / f"{n}.png").exists():
            got[n] = out / f"{n}.png"
    for i in range(0, len(todo), 40):
        batch = todo[i:i + 40]
        q = "https://commons.wikimedia.org/w/api.php?action=query&prop=imageinfo&iiprop=url&format=json&iiurlwidth=%d&titles=%s" % (
            width, urllib.parse.quote("|".join("File:" + n for n in batch)))
        for attempt in range(6):
            r = subprocess.run(["curl", "-sS", "-m", "60", q], capture_output=True, text=True)
            try:
                d = json.loads(r.stdout); break
            except Exception:
                time.sleep(10 * (attempt + 1))
        else:
            continue
        for pg in d.get("query", {}).get("pages", {}).values():
            ii = (pg.get("imageinfo") or [{}])[0]
            url, name = ii.get("thumburl"), pg.get("title", "")[5:].replace(" ", "_")
            if not url:
                continue
            for attempt in range(6):
                p = out / f"{name}.png"
                r = subprocess.run(["curl", "-sS", "-m", "60", "-o", str(p), "-w", "%{http_code}", url], capture_output=True, text=True)
                if r.stdout.strip() == "200":
                    got[name] = p; break
                p.unlink(missing_ok=True); time.sleep(8 * (attempt + 1))
            time.sleep(1.0)
        time.sleep(2)
    return got


# 候选表窗口对位没对上、但按松散上下文（忽略标点、PUA 当通配）在 v2 页文字里找到的位置：(章, 页, 下标)。
# 2026-11-06 补：EB36/EBDA/EC2F/EADF/EA79；EA84 的两处出自 v2 没收的篇目，找不到，保留无切图。
EXTRA_LOCS = {
    "daizhige:U+EB36": [("24", 48, 39), ("24", 48, 40)],
    "daizhige:U+EBDA": [("1", 54, 167)],
    "daizhige:U+EC2F": [("16", 79, 55)],
    "daizhige:U+EADF": [("16", 79, 57)],
    "daizhige:U+EA79": [("7", 66, 2)],
}


def main():
    from PIL import Image
    ap = argparse.ArgumentParser()
    ap.add_argument("--cand", required=True); ap.add_argument("--v2zip", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="open", choices=["open", "all", "plan"]); ap.add_argument("--n", type=int, default=2)
    ap.add_argument("--no-wiki", action="store_true")
    a = ap.parse_args()
    out = Path(a.out); (out / "crops").mkdir(parents=True, exist_ok=True); (out / "wiki").mkdir(exist_ok=True)
    rows = [json.loads(l) for l in open(a.cand, encoding="utf-8")]
    if a.only == "open":
        rows = [r for r in rows if r["verdict"] == "open"]
    elif a.only == "plan":
        # 11-06 审核顺序：未定（候选不一致/无候选在前，其余按处数）→ 待复核的已定字 → 已判待收
        g1 = [r for r in rows if r["verdict"] == "open" and (r["conflict"] or not r["cands"])]
        g2 = sorted([r for r in rows if r["verdict"] == "open" and not (r["conflict"] or not r["cands"])], key=lambda r: -r["count"])
        g3 = [r for r in rows if r["verdict"] == "char" and "复核" in r["note"]]
        g4 = [r for r in rows if r["verdict"] == "pending"]
        for g, k in ((g1, "1 未定·先看（候选不一致/无候选）"), (g2, "2 未定"), (g3, "3 复核已定字"), (g4, "4 已判待收")):
            for r in g:
                r["_kind"] = k
        rows = g1 + g2 + g3 + g4
    Z = zipfile.ZipFile(a.v2zip)
    txt = {}
    def text_rows(ch):
        if ch not in txt:
            txt[ch] = {str(r["p"]): r for r in map(json.loads, gzip.open(io.BytesIO(Z.read(f"96mid1ogzk/{ch}/text.jsonl.gz")), "rt", encoding="utf-8"))}
        return txt[ch]
    wk = {} if a.no_wiki else wiki_thumbs([r["wiki_img"] for r in rows], out / "wiki")
    items = []
    for r in rows:
        cands = []
        for c in r["cands"]:
            if c["char"] not in [x[0] for x in cands]:
                cands.append([c["char"], "、".join(sorted({y["src"] for y in r["cands"] if y["char"] == c["char"]}))])
        pre = (r["char"] if r["verdict"] == "char" and r["char"] else (cands[0][0] if cands and r["verdict"] == "open" else "？"))
        if r["verdict"] == "char" and r["char"] and r["char"] not in [x[0] for x in cands]:
            cands = [[r["char"], "现定"]] + cands
        shown = 0
        locs = list(r["v2_locs"]) or EXTRA_LOCS.get(r["code"], [])
        for k, (ch, p, idx) in enumerate(locs):
            if shown >= a.n:
                break
            pr = text_rows(str(ch)).get(str(p))
            if not pr or idx >= len(pr["x"]):
                continue
            x, y, w, h = pr["x"][idx], pr["y"][idx], pr["w"][idx], pr["hgt"][idx]
            try:
                im = Image.open(io.BytesIO(Z.read(f"96mid1ogzk/{ch}/pages/{int(p):03d}.png"))).convert("L")
            except KeyError:
                continue
            pad = 8
            crop = im.crop((max(0, x - pad), max(0, y - pad), min(im.width, x + w + pad), min(im.height, y + h + pad)))
            crop = crop.resize((max(8, round(crop.width * 96 / crop.height)), 96), Image.LANCZOS)
            cp = out / "crops" / f"{r['code'].split(':')[1]}_{k}.png"; crop.save(cp)
            ctx = (pr["c"][max(0, idx - 8):idx] + "【〓】" + pr["c"][idx + 1:idx + 9])
            it = {"id": f"{r['code']}#{ch}-{int(p)}-{idx}", "pre": pre, "img": str(cp), "ctx": ctx,
                  "cands": cands,
                  "note": f"{r['code']} 共{r['count']}处 · 维基SKQS_{r['sk_no']:04d}"
                          + (f" · 维基描述：{r['wiki_desc']}" if r["wiki_desc"] else "") + ("；候选不一致，请看图" if r["conflict"] else "")
                          + {"char": f" · 现定「{r['char']}」", "pending": " · 已判待收（点「页上字对」无意义，认不出点「认不出」保持待收，认得出就填字）", "open": ""}[r["verdict"]],
                  "kind": r.get("_kind") or ("码位候选不一致" if r["conflict"] else ("无候选" if not cands else "有候选"))}
            wi = wk.get(r["wiki_img"])
            if wi:
                it["ref_img"] = str(wi); it["ref_label"] = f"维基 SKQS_{r['sk_no']:04d}"
            items.append(it); shown += 1
        if shown == 0:  # 没有本书切图的码：也出一格，只带维基图和上下文
            sm = r["samples"][0] if r["samples"] else ""
            it = {"id": f"{r['code']}#none", "pre": pre, "img": "", "ctx": sm, "cands": cands,
                  "note": f"{r['code']} 共{r['count']}处 · 没有对上 v2 的切图 · 维基SKQS_{r['sk_no']:04d}", "kind": r.get("_kind") or "无切图"}
            wi = wk.get(r["wiki_img"])
            if wi:
                it["ref_img"] = str(wi); it["ref_label"] = f"维基 SKQS_{r['sk_no']:04d}"
            items.append(it)
    with open(out / "items.jsonl", "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(f"{len(rows)} 码 → {len(items)} 格，维基图 {len(wk)} 张 → {out/'items.jsonl'}")


if __name__ == "__main__":
    main()
