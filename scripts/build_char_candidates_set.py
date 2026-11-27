# -*- coding: utf-8 -*-
"""建识字候选测试集 open-guji-dataset/char-candidates（CV3，2026-11-27，Sheldon 定）。

## 为什么要

改 3c（按图给候选）、4b（按上下文排序并补字）、待审卡的候选时，要知道有没有变好，
又不想每次整册重跑。这个集把每格「当时的图、前后文、产线给的候选池、人最后定的字」冻住，
评测（`scripts/eval_cands.py`）只读这份文件，几分钟跑完。规格见 Claude Doc
「候选字线：待审格格式、3c／4b 接口与 benchmark」第五、六节。

## 两层

- **甲层 A（难格，图证）**：char-clustering 里已冻结的人裁生僻字格（004 殿本、005 史記、
  006／007 全唐文 的 `rare.jsonl`），字块图按路径引用（64×64 归一图，`crop.kind=norm64`）。
- **乙层 B（卡片回放）**：中心库待审条目里发过卡、且发卡之后有人裁的格。卡的样子取
  条目快照（lib_top、alt、ref、ctx…），字块图取卡上那张单格图
  （`https://data.openguji.com/proof/<书>/<册>/<名>`，96×96 webp，按名字里的 sha256 前缀核对，
  `crop.kind=sprite96`），金标取事件里人给的字。

两层都补：前后文（本页按读序接前后各一页，左右各 24 字，本格不放进去）、
产线候选池（3a glyph_match 前 5、3b rare_candidates、4b context_decide ranked）、参校字（align_ref），
都取自各册现行主版（★）产物包，包名写进每行。

## 纪律

1. **金标只收人裁**：事件 `actor=user`，且 reviewer／批次／来源都不带 AI（史記 11-27 的
   AI 看图落定批不收）。同一格多次裁决取最后一次。
2. 切坏、非字、插图、残损单列（`expected.status` ≠ `char`），不算字的命中率。
3. 不在建集时悄悄删格：对不上包的格照样收，`input.ctx` 为空并在 `notes` 里写原因。

用法（要先 `guji db pull --no-glyph --no-rebuild` 三本书的中心库；产物包缺的会用 `guji products pack fetch` 取）：

    PYTHONPATH=. python scripts/build_char_candidates_set.py \\
        --dataset ../open-guji-dataset --packs ~/packs \\
        --pack-list 988g3f0wsu=<pack list 输出> --pack-list 995ejelvk0=… --pack-list siku-zongmu=…
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_guji_cv.utils.jiazhu_order import order_keys  # noqa: E402

L = 24
DATA = "https://data.openguji.com"
UA = {"User-Agent": "open-guji-cv/char-candidates"}

# 书：中心库工作区 id → (书 id，书名，工作区目录名，pack 里册号写法)
BOOKS = {
    "988g3f0wsu": ("988g3f0wsu", "史記", "988g3f0wsu-shiji", lambda n: f"{n:02d}"),
    "995ejelvk0": ("995ejelvk0", "全唐文", "995ejelvk0-quan-tang-wen", lambda n: f"{n:03d}"),
    "siku-zongmu": ("96mid1ogzk", "殿本", "96mid1ogzk-欽定四庫全書總目武英殿刻本", lambda n: f"vol{n:02d}"),
}
RARE_SETS = {  # 甲层：char-clustering 分片 → 中心库工作区 id
    "004-siku-v2-human": "siku-zongmu",
    "005-shiji-human": "988g3f0wsu",
    "006-qtw-human": "995ejelvk0",
    "007-qtw-firstseen": "995ejelvk0",
}
STATUS = {"confirm": "char", "seg_defect": "seg", "figure": "figure", "not_a_char": "notchar", "damaged": "damaged"}
AI_RE = re.compile(r"AI|ai-")


def vol_num(v: str) -> int:
    return int(re.sub(r"^vol", "", str(v)))


def block(c: str) -> str:
    if not c or len(c) != 1:
        return "other"
    o = ord(c)
    if 0x4E00 <= o <= 0x9FFF:
        return "basic"
    if 0x3400 <= o <= 0x4DBF:
        return "extA"
    if 0xF900 <= o <= 0xFAFF or 0x2F800 <= o <= 0x2FA1F:
        return "compat"
    if o >= 0x20000:
        return "extB+"
    return "other"


# ───────────────────────── 产物包 ─────────────────────────

class Packs:
    """各册现行主版（★）产物包，只解 5 步。缺了用 guji 取。"""

    STEPS = "seed_admit,glyph_match,rare_candidates,context_decide,align_ref"

    def __init__(self, root: Path, lists: dict[str, Path], ws_root: Path, fetch: bool = True):
        self.root, self.ws_root, self.fetch = root, ws_root, fetch
        self.main: dict[tuple[str, str], str] = {}
        for ws, p in lists.items():
            book = BOOKS[ws][0]
            for line in Path(p).read_text(encoding="utf-8").splitlines():
                if "★" not in line:
                    continue
                m = re.search(rf"products/(?:{book}|{ws})/([^/\s]+)/([^\s/]+)", line)   # 殿本的包按工作区名 siku-zongmu 存
                if m:
                    self.main[(ws, m.group(1))] = m.group(2)
        self._page: dict = {}
        self.missing: set = set()

    def label(self, ws: str, vol: str) -> str | None:
        return self.main.get((ws, vol))

    def dir(self, ws: str, vol: str) -> Path | None:
        book = BOOKS[ws][0]
        lab = self.label(ws, vol)
        if not lab:
            self.missing.add((ws, vol))
            return None
        d = self.root / book / vol / lab               # 按包名分目录：主版换了不会误用旧包
        if glob.glob(str(d / "*" / "seed_admit")):
            return d
        if not self.fetch or (ws, vol) in self.missing:
            self.missing.add((ws, vol))
            return None
        env = dict(os.environ, GUJI_WORKSPACE=str(self.ws_root / BOOKS[ws][2]), PYTHONIOENCODING="utf-8")
        r = subprocess.run(["guji", "products", "pack", "fetch", vol, "--label", lab, "--steps", self.STEPS,
                            "--to", str(d)], env=env, capture_output=True, text=True)
        if not glob.glob(str(d / "*" / "seed_admit")):
            print(f"  ✗ 取包失败 {ws} {vol} {lab}: {r.stdout[-300:]} {r.stderr[-300:]}", flush=True)
            self.missing.add((ws, vol))
            return None
        return d

    def rows(self, ws: str, vol: str, kind: str, page: int) -> list[dict] | None:
        k = (ws, vol, kind, page)
        if k in self._page:
            return self._page[k]
        d = self.dir(ws, vol)
        out = None
        if d is not None:
            fs = glob.glob(str(d / "*" / kind / f"p{page:04d}.json"))
            if fs:
                doc = json.load(open(fs[0], encoding="utf-8"))
                inner = doc[list(doc)[0]]
                if isinstance(inner.get("chars"), list):
                    out = inner["chars"]
                else:
                    out = [dict(r, col=r.get("col", c.get("col")))
                           for c in inner.get("columns") or [] for r in (c.get("chars") or [])]
        self._page[k] = out
        return out

    def page_seq(self, ws: str, vol: str, page: int) -> list[tuple[str, str]]:
        rows = self.rows(ws, vol, "seed_admit", page)
        if not rows:
            return []
        bycol: dict[int, list] = {}
        for r in rows:
            bycol.setdefault(int(r["id"].split(":")[2]), []).append(r)
        seq = []
        for col in sorted(bycol):
            rs = bycol[col]
            ok = order_keys([(r["slot"], r.get("sub")) for r in rs])
            rs.sort(key=lambda r: ok[(r["slot"], r.get("sub") or "")])
            seq += [(r["id"], r.get("char") or "□") for r in rs]
        return seq

    def frozen_input(self, ws: str, vol: str, page: int, cell: str) -> dict:
        """cell = 页:列:格（不带册）。回 {ctx, pool, ref, pack, notes}。"""
        out: dict = {"pack": self.label(ws, vol)}
        seq = self.page_seq(ws, vol, page - 1) + self.page_seq(ws, vol, page) + self.page_seq(ws, vol, page + 1)
        ids = [x[0].split(":", 1)[1] for x in seq]
        if cell not in ids:
            out["notes"] = "包里找不到这格（切分变过或页没出）" if seq else "没有这册／页的主版包"
            return out
        pos = ids.index(cell)
        key = seq[pos][0]
        out["now"] = seq[pos][1]
        out["ctx"] = {"left": "".join(c for _, c in seq[max(0, pos - L):pos]),
                      "right": "".join(c for _, c in seq[pos + 1:pos + 1 + L])}
        pool: dict = {}
        for kind in ("glyph_match", "rare_candidates", "context_decide", "align_ref"):
            g = next((x for x in self.rows(ws, vol, kind, page) or [] if x.get("id") == key), None)
            if not g:
                continue
            if kind == "glyph_match":
                pool["lib"] = [[c, round(float(s), 4)] for c, s in (g.get("candidates") or [])[:5]]
                pool["lib_verdict"] = g.get("verdict")
            elif kind == "rare_candidates":
                pool["rare"] = [[c["char"], round(float(c["score"]), 4), c.get("font")] for c in g.get("candidates") or []]
            elif kind == "context_decide":
                pool["ctx_ranked"] = g.get("ranked")
            else:
                if g.get("align_char"):
                    out["ref"] = {"c": g["align_char"], "op": g.get("align_op")}
        out["pool"] = pool
        return out


# ───────────────────────── 人裁 ─────────────────────────

def human_events(data_home: Path, ws: str) -> dict[tuple[int, str], list[dict]]:
    """(册号, 页:列:格) → 人裁事件（按时间）。"""
    ev: dict = collections.defaultdict(list)
    for f in sorted(glob.glob(str(data_home / ws / "feedback" / "events" / "*.jsonl"))):
        if f.endswith("~u.jsonl"):
            continue
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            if r.get("actor") != "user":
                continue
            pl = r.get("payload") or {}
            if AI_RE.search(f"{r.get('reviewer')}{r.get('batch')}{pl.get('source')}"):
                continue
            key = (r.get("target") or {}).get("key") or ""
            if key.count(":") < 3:
                continue
            v, cell = key.split(":", 1)
            try:
                ev[(vol_num(v), cell)].append(r)
            except ValueError:
                continue
    for k in ev:
        ev[k].sort(key=lambda r: r.get("ts") or "")
    return ev


def web_votes(data_home: Path, ws: str) -> dict[str, dict]:
    out = {}
    for f in glob.glob(str(data_home / ws / "feedback" / "lists" / "web" / "*" / "items.jsonl")):
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            if r.get("item"):
                out[r["item"]] = r
    return out


SHEET_CACHE = Path.home() / ".cache" / "guji-proof-sprites"   # 拼图原件只缓存在本机，不进数据集


def fetch_sprite(book: str, vol: str, name: str, dest: Path) -> str | None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return "cached"
    req = urllib.request.Request(f"{DATA}/proof/{book}/{vol}/{name}", headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            b = r.read()
    except Exception as e:  # noqa: BLE001
        return f"err:{e}"
    want = name.split(".")[-2]                    # pNNNN.<sha 前 8>.webp 或 <一个字母><sha 前 16>.webp（a 字形、c 格图）
    if "." not in name[:-5] and len(want) == 17:
        want = want[1:]
    if not hashlib.sha256(b).hexdigest().startswith(want):
        return "sha_mismatch"
    dest.write_bytes(b)
    return None


# ───────────────────────── 两层 ─────────────────────────

def layer_a(ds: Path, packs: Packs) -> list[dict]:
    out = []
    for shard, ws in RARE_SETS.items():
        p = ds / "char-clustering" / "samples" / shard / "rare.jsonl"
        if not p.exists():
            print(f"  ✗ 没有 {p}")
            continue
        fmt = BOOKS[ws][3]
        for line in open(p, encoding="utf-8"):
            r = json.loads(line)
            parts = r["id"].split(":")            # v2:<册>:<页>:<列>:<格>
            vol = fmt(vol_num(parts[1]))
            page = int(parts[2])
            cell = ":".join(parts[2:])
            fi = packs.frozen_input(ws, vol, page, cell)
            strata = list(r.get("strata") or [])
            rec = {
                "id": f"{BOOKS[ws][0]}:{vol}:{cell}",
                "layer": "A",
                "book": BOOKS[ws][0], "book_title": BOOKS[ws][1], "vol": vol, "cell": cell,
                "crop": {"path": f"char-clustering/samples/{shard}/{r['png']}", "kind": "norm64"},
                "input": {k: fi[k] for k in ("ctx", "pool", "ref", "pack", "now") if k in fi},
                "expected": {"status": "char", "char": r["char"]},
                "label_origin": "human",
                "stratum": {"set": shard, "tags": strata, "block": block(r["char"]),
                            "selfcheck_flag": bool(r.get("selfcheck_flag"))},
                "history": [{"ts": TODAY, "change": "created", "why": f"甲层，取自 {shard}/rare.jsonl"}],
            }
            if r.get("card"):
                rec["input"]["card_1118"] = r["card"]
            if fi.get("notes"):
                rec["notes"] = fi["notes"]
            out.append(rec)
        print(f"  甲层 {shard}: 累计 {len(out)}", flush=True)
    return out


def layer_b(ds_out: Path, data_home: Path, packs: Packs, workers: int = 16) -> tuple[list[dict], collections.Counter]:
    out, stat = [], collections.Counter()
    crops = ds_out / "crops"
    crops.mkdir(parents=True, exist_ok=True)
    for old in crops.glob("*"):
        old.unlink()
    sheets = SHEET_CACHE
    jobs = []
    for ws, (book, title, _wsdir, fmt) in BOOKS.items():
        ev = human_events(data_home, ws)
        votes = web_votes(data_home, ws)
        for f in sorted(glob.glob(str(data_home / ws / "feedback" / "lists" / "pending" / "*" / "*.items.jsonl"))):
            pvol = Path(f).name.split(".")[0]          # 待审单的册号（三位）
            vol = fmt(vol_num(pvol))
            hist: dict = collections.defaultdict(list)
            for line in open(f, encoding="utf-8"):
                r = json.loads(line)
                hist[r["cell"]].append(r)
            for cell, rs in hist.items():
                rs.sort(key=lambda r: r.get("at") or "")
                opened = rs[0].get("at") or ""
                es = [e for e in ev.get((vol_num(pvol), cell), []) if (e.get("ts") or "") >= opened]
                if not es:
                    continue
                e = es[-1]
                pl = e.get("payload") or {}
                status = STATUS.get(pl.get("v"), "char" if pl.get("v") == "confirm" else str(pl.get("v")))
                gold = pl.get("shape")
                # 人看到的那张卡：人裁之前最后一份带图的快照
                snaps = [r for r in rs if (r.get("doc") or {}).get("img") and (r.get("at") or "") <= (e.get("ts") or "")]
                snap = snaps[-1] if snaps else next((r for r in reversed(rs) if (r.get("doc") or {}).get("img")), None)
                stat[f"{title}·有人裁"] += 1
                if snap is None:
                    stat[f"{title}·无卡图"] += 1
                    continue
                d = snap["doc"]
                card = {k: d[k] for k in ("lib_top", "ref", "refc", "ctx", "lib", "conf", "margin", "grp",
                                          "pending_reason", "pending_reason_detail", "why") if k in d}
                card["alt"] = [{k: a.get(k) for k in ("c", "p", "s", "src")} for a in d.get("alt") or []]
                shown = []
                for c in ([(d.get("ref") or {}).get("c")] + [x["c"] for x in (d.get("lib_top") or [])[:3]]):
                    if c and len(c) == 1 and c not in shown:
                        shown.append(c)
                card["shown_approx"] = shown[:3]
                page = int(cell.split(":")[0])
                fi = packs.frozen_input(ws, vol, page, cell)
                name = d["img"]["s"]
                sheet = sheets / book / pvol / name          # 单图可能是拼图：按 img 的 x,y,w,h 裁
                dest = crops / f"{book}_{vol}_{cell.replace(':', '_')}.png"
                box = [int(d["img"].get(k) or 0) for k in ("x", "y", "w", "h")]
                lib = [x["c"] for x in d.get("lib_top") or []]
                refc = (d.get("ref") or {}).get("c")
                rel = None
                if status == "char" and gold:
                    rel = ("lib1" if lib[:1] == [gold] else "ref" if gold == refc else
                           "lib2-5" if gold in lib else "alt" if gold in [a["c"] for a in card["alt"]] else "none")
                vote = votes.get(snap.get("id"))
                rec = {
                    "id": f"{book}:{vol}:{cell}",
                    "layer": "B",
                    "book": book, "book_title": title, "vol": vol, "cell": cell, "u": snap.get("u") or rs[-1].get("u"),
                    "anchor": {k: (e["target"].get("anchor") or {}).get(k) for k in ("bbox", "space")},
                    "crop": {"path": f"char-candidates/crops/{dest.name}", "kind": "sprite96", "src": name, "box": box},
                    "input": {**{k: fi[k] for k in ("ctx", "pool", "ref", "pack", "now") if k in fi},
                              "card": card, "card_rev": snap.get("src"), "item": snap.get("id")},
                    "expected": {"status": status, "char": gold},
                    "label_origin": "human",
                    "source_events": [x["id"] for x in es],
                    "stratum": {"set": "cards", "rel": rel, "block": block(gold or ""),
                                "gold_eq_ref": bool(gold and gold == refc)},
                    "history": [{"ts": TODAY, "change": "created", "why": "乙层，待审卡＋发卡后人裁"}],
                }
                if vote:
                    rec["input"]["vote"] = {k: vote.get(k) for k in ("char", "pick_src", "pick_rank", "shown", "choice")}
                if fi.get("notes"):
                    rec["notes"] = fi["notes"]
                out.append(rec)
                jobs.append((book, pvol, name, sheet, rec))
    print(f"  乙层 {len(out)} 格，取卡图 …", flush=True)
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(lambda j: fetch_sprite(j[0], j[1], j[2], j[3]), jobs))
    keep = []
    import cv2
    for (book, pvol, name, sheet, rec), err in zip(jobs, res):
        if err and err != "cached":
            stat[f"取图失败:{err.split(':')[0]}"] += 1
            continue
        im = cv2.imread(str(sheet), cv2.IMREAD_GRAYSCALE)
        x, y, w, h = rec["crop"]["box"]
        if im is None or w <= 0 or h <= 0 or y + h > im.shape[0] or x + w > im.shape[1]:
            stat["卡图裁不出"] += 1
            continue
        cv2.imwrite(str(ds_out.parent / rec["crop"]["path"]), im[y:y + h, x:x + w])
        keep.append(rec)
    return keep, stat


TODAY = _dt.date.today().isoformat()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--packs", type=Path, required=True)
    ap.add_argument("--pack-list", action="append", default=[], help="ws=文件（guji products pack list 的输出）")
    ap.add_argument("--data-home", type=Path, default=Path.home() / ".guji-data" / "main")
    ap.add_argument("--ws-root", type=Path, default=Path.home() / "guji-workspace")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--layers", default="A,B")
    a = ap.parse_args()
    lists = dict(x.split("=", 1) for x in a.pack_list)
    packs = Packs(a.packs, {k: Path(v) for k, v in lists.items()}, a.ws_root, fetch=not a.no_fetch)
    out_dir = a.dataset / "char-candidates"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    stat: collections.Counter = collections.Counter()
    if "A" in a.layers:
        rows += layer_a(a.dataset, packs)
    if "B" in a.layers:
        b, stat = layer_b(out_dir, a.data_home, packs)
        rows += b
    with open(out_dir / "items.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summ = collections.Counter()
    for r in rows:
        summ[(r["layer"], r["book_title"], r["expected"]["status"], "有前后文" if r["input"].get("ctx") else "无前后文")] += 1
    print(json.dumps({"n": len(rows), "build": dict(stat)}, ensure_ascii=False, indent=1))
    for k, v in sorted(summ.items()):
        print(" ", k, v)
    used = sorted({(r["book"], r["vol"], r["input"].get("pack")) for r in rows if r["input"].get("pack")})
    (out_dir / "packs.json").write_text(json.dumps([{"book": b, "vol": v, "pack": p} for b, v, p in used],
                                                   ensure_ascii=False, indent=1), encoding="utf-8")
    if packs.missing:
        print("缺包：", sorted(packs.missing))


if __name__ == "__main__":
    main()
