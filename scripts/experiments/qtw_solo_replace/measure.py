"""D 道（overview#155）：全唐文 match_solo / match_replace 两个放行通道单独核。

  python measure.py --products <products 根> --events <feedback/events> --corpus-dir <corpus>
                    --books v006[,v007..] --out <out 目录> [--channels match_solo,match_replace]

对指定通道放行的**全部**格，按三路真值量错：

1. **人裁**：`feedback/events/*.jsonl` 里 `actor=="user"` 的 `confirm`（`payload.v=="confirm"`，
   `payload.shape` 是字形）——即 H 写入时的 `source:"human"` 口径；`actor=="model"`
   （`payload.source=="auto"`）的机器刻例**不算**真值。同格多条取最后一条。
2. **维基锚定**：`align_ref` 锚定页的 `equal`/`replace` 对齐字（H #64 的口径）。
3. **夹心锚**（本道补的，match_solo 用）：match_solo 的格按定义**没有**整理本对齐字
   （`corpus_char is None` 才走得到这条通道），上两路对它几乎全空。这里在页内读序串上
   取该格左右各 K 个字（放行字或库 top1），在维基语料（语义归一、去非汉字）里找
   「左 K + ? + 右 K」——出现 ≥1 次且所有出现处中间字一致，就拿它当真值。
   邻字本身认错只会让它**找不到**（漏），几乎不会让它**找错**，所以它只在覆盖率上吃亏。

判错分两层：**语义错**（`vmap.semantic` 不同，字认错了）与**码位不符**（语义同、码位不同；
人裁真值才能判，维基真值是整理本的形，不代表刻本字形）。

报每通道：放行 n、各路真值覆盖、错数、单侧 95% Clopper-Pearson 上界；match_replace
另报「放行字 ≠ 库 top1 字面」的格（码位跟整理本走了异体）。全部格落 `cells.jsonl`。
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import re
import sys
from pathlib import Path

from scipy.stats import beta

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from open_guji_cv.clustering.variants import VariantMap  # noqa: E402

_HAN = re.compile(r"[㐀-鿿\U00020000-\U0003134f豈-﫿]")


def upper95(k: int, n: int) -> float | None:
    """单侧 95% Clopper-Pearson 上界。0 错时 = 1 - 0.05^(1/n)。"""
    if n == 0:
        return None
    if k >= n:
        return 1.0
    return float(beta.ppf(0.95, k + 1, n - k))


def load_page_products(root: Path, book: str, step: str) -> dict[int, dict]:
    out = {}
    for f in sorted(glob.glob(str(root / book / step / "p*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        out[int(Path(f).stem[1:])] = d[next(iter(d))]
    return out


def cells_of(page_doc: dict) -> list[dict]:
    return [r for col in page_doc.get("columns") or [] for r in col.get("chars") or []]


def human_truth(events_dir: Path) -> dict[str, dict]:
    """{key: {"shape":…, "v":…, "src":…}}；只收 actor=user（source:"human"），同格取最后一条。"""
    out: dict[str, dict] = {}
    rows = []
    for f in sorted(glob.glob(str(events_dir / "*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            e = json.loads(line)
            p = e.get("payload") or {}
            if e.get("actor") != "user" or p.get("source") == "auto":
                continue
            if e.get("kind") != "confirm":
                continue
            rows.append((e.get("ts") or "", e.get("seq") or 0, e))
    for _ts, _seq, e in sorted(rows, key=lambda t: (t[0], t[1])):
        p = e["payload"]
        out[e["target"]["key"]] = {"shape": p.get("shape"), "v": p.get("v"),
                                   "src": e.get("batch")}
    return out


class Corpus:
    """语义归一、只留汉字的维基语料，带 K-gram 索引。"""

    def __init__(self, paths: list[Path], vmap: VariantMap, k: int):
        raw = "".join(open(p, encoding="utf-8").read() for p in paths)
        self.text = "".join(_HAN.findall(raw))
        self.norm = vmap.normalize_text(self.text)
        self.k = k
        self.idx: dict[str, list[int]] = collections.defaultdict(list)
        for i in range(len(self.norm) - k + 1):
            self.idx[self.norm[i:i + k]].append(i)

    def sandwich(self, left: str, right: str) -> tuple[str | None, int]:
        """「左 K + ? + 右 K」→ (中间字（原形）, 出现次数)；中间字不唯一返回 (None, n)。"""
        k = self.k
        if len(left) < k or len(right) < k:
            return None, 0
        mids = set()
        n = 0
        for i in self.idx.get(left[-k:], ()):
            j = i + k
            if self.norm[j + 1:j + 1 + k] == right[:k]:
                mids.add(self.text[j])
                n += 1
        if len(mids) == 1:
            return mids.pop(), n
        return None, n

    def col_anchor(self, col: list[str], i: int, g: int = 3, min_votes: int = 3,
                   ) -> tuple[str | None, dict]:
        """列级放宽锚：本列（语义归一）的 g-gram 投票定整理本位置——**不含目标格 i 的
        gram 才投票**（目标格自己的读法不参与定位），最高票偏移 ≥ min_votes 且 ≥ 次高簇
        2 倍才算锚上；再用 difflib 对齐本列与该段语料，取第 i 格对到的语料字（equal 或
        等长 replace 块）。返回 (语料原形字 | None, 诊断)。"""
        import difflib
        votes: collections.Counter = collections.Counter()
        for s in range(len(col) - g + 1):
            if s <= i < s + g:
                continue
            gram = "".join(col[s:s + g])
            if "□" in gram:
                continue
            for cp in self._gidx(g).get(gram, ()):
                votes[cp - s] += 1
        if not votes:
            return None, {"votes": 0}
        # 相邻偏移（±2，插删字）并簇
        best_off, best = None, 0
        for off in votes:
            v = sum(votes.get(off + d, 0) for d in range(-2, 3))
            if v > best:
                best_off, best = off, v
        second = max((sum(votes.get(off + d, 0) for d in range(-2, 3))
                      for off in votes if abs(off - best_off) > 4), default=0)
        diag = {"votes": best, "second": second}
        if best < min_votes or best < 2 * second:
            return None, diag
        lo = max(0, best_off - 3)
        win = self.norm[lo:best_off + len(col) + 3]
        sm = difflib.SequenceMatcher(None, col, list(win), autojunk=False)
        for tag, a0, a1, b0, b1 in sm.get_opcodes():
            if a0 <= i < a1 and (tag == "equal" or (tag == "replace" and a1 - a0 == b1 - b0)):
                diag["op"] = tag
                return self.text[lo + b0 + (i - a0)], diag
        diag["op"] = "gap"
        return None, diag

    def _gidx(self, g: int) -> dict[str, list[int]]:
        cache = self.__dict__.setdefault("_gcache", {})
        if g not in cache:
            idx: dict[str, list[int]] = collections.defaultdict(list)
            for j in range(len(self.norm) - g + 1):
                idx[self.norm[j:j + g]].append(j)
            cache[g] = idx
        return cache[g]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--products", required=True)
    ap.add_argument("--events", required=True)
    ap.add_argument("--corpus-dir", required=True)
    ap.add_argument("--books", default="v006")
    ap.add_argument("--books-dir", default="", help="books/<id>.yaml 所在目录（读 references）；缺省 = products 的兄弟 books/")
    ap.add_argument("--channels", default="match_solo,match_replace")
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--out", required=True)
    ap.add_argument("--calibrate", action="store_true",
                    help="在有维基锚定真值的全部格上量列级放宽锚与 align_ref 的一致率")
    a = ap.parse_args()

    import yaml
    root = Path(a.products)
    books_dir = Path(a.books_dir) if a.books_dir else root.parent / "books"
    chans = a.channels.split(",")
    vmap = VariantMap.load()
    H = human_truth(Path(a.events))
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cells_out = []
    summary: dict = {"books": a.books.split(","), "k": a.k,
                     "truth_human": "events actor=user confirm（source:human），机器刻例不算",
                     "channels": {}}
    agg = {c: collections.Counter() for c in chans}
    admit_all = collections.Counter()
    calib = collections.Counter()
    drift = collections.Counter()        # 放行字与库 top1 语义同、字面不同：（通道, 库判）
    drift_pairs = collections.Counter()
    for book in a.books.split(","):
        by = yaml.safe_load(open(books_dir / f"{book}.yaml", encoding="utf-8"))
        corpus = Corpus([Path(a.corpus_dir) / r["file"] for r in by.get("references") or []],
                        vmap, a.k)
        SA = load_page_products(root, book, "seed_admit")
        GM = load_page_products(root, book, "glyph_match")
        AR = load_page_products(root, book, "align_ref")
        for pg, sa in SA.items():
            m = {r["id"]: r for r in cells_of(GM.get(pg) or {})}
            ar = AR.get(pg) or {}
            al = ({c["id"]: c for c in ar.get("chars") or []
                   if c.get("align_op") in ("equal", "replace") and c.get("align_char")}
                  if ar.get("anchored") else {})
            seq = []   # 页内读序（产物里的列序 × 列内序即读序；夹注 a/b 按产物顺序）
            for r in cells_of(sa):
                mr = m.get(r["id"]) or {}
                top = (mr.get("candidates") or [[None]])[0][0]
                seq.append((r, mr, top, r.get("char") if r.get("admit") else top))
            norm_seq = [vmap.semantic(x[3]) if x[3] else "□" for x in seq]
            col_of = [r["id"].rsplit(":", 2)[1] for r, *_ in seq]
            for i, (r, mr, top, _c) in enumerate(seq):
                admit_all[(book, r.get("admit"))] += 1
                if (r.get("admit") and top and r.get("char") and r["char"] != top
                        and vmap.semantic(r["char"]) == vmap.semantic(top)):
                    drift[(r.get("channel"), mr.get("verdict"))] += 1
                    drift_pairs[f"{r['char']}←{top}"] += 1
                ch = r.get("channel")
                if a.calibrate and r["id"] in al:
                    cj = [j for j, c in enumerate(col_of) if c == col_of[i]]
                    ca, _d = corpus.col_anchor([norm_seq[j] for j in cj], i - cj[0])
                    if ca is None:
                        calib["miss"] += 1
                    else:
                        calib["hit"] += 1
                        calib["agree"] += vmap.semantic(ca) == vmap.semantic(al[r["id"]]["align_char"])
                if not r.get("admit") or ch not in chans:
                    continue
                left = "".join(norm_seq[max(0, i - a.k):i])
                right = "".join(norm_seq[i + 1:i + 1 + a.k])
                sw, sw_n = corpus.sandwich(left, right) if "□" not in left + right else (None, 0)
                cj = [j for j, c in enumerate(col_of) if c == col_of[i]]
                ca, ca_diag = corpus.col_anchor([norm_seq[j] for j in cj], i - cj[0])
                h = H.get(r["id"])
                w = al.get(r["id"])
                rec = {"id": r["id"], "channel": ch, "char": r.get("char"),
                       "lib_top": top, "verdict": mr.get("verdict"), "cov": mr.get("cov"),
                       "cands": (mr.get("candidates") or [])[:3],
                       "human": h, "wiki": (w or {}).get("align_char"),
                       "wiki_op": (w or {}).get("align_op"),
                       "sandwich": sw, "sandwich_n": sw_n,
                       "col_anchor": ca, "col_anchor_diag": ca_diag,
                       "ctx": "".join(x[3] or "□" for x in seq[max(0, i - 6):i]) + "【"
                              + (r.get("char") or "?") + "】"
                              + "".join(x[3] or "□" for x in seq[i + 1:i + 7])}
                sem = vmap.semantic(r.get("char") or "")
                # 判定：人裁 > 维基锚定 > 夹心锚
                if h and h["v"] == "confirm" and h["shape"]:
                    rec["truth_src"], t = "human", h["shape"]
                elif w:
                    rec["truth_src"], t = "wiki", w["align_char"]
                elif ca:
                    rec["truth_src"], t = "col_anchor", ca
                elif sw:
                    rec["truth_src"], t = "sandwich", sw
                else:
                    rec["truth_src"], t = None, None
                if t is not None:
                    rec["sem_ok"] = vmap.semantic(t) == sem
                    rec["cp_ok"] = (t == r.get("char")) if rec["truth_src"] == "human" else None
                rec["cp_vs_libtop"] = (r.get("char") != top)
                cells_out.append(rec)
                c = agg[ch]
                c["n"] += 1
                c[f"truth_{rec['truth_src']}"] += 1
                if t is not None:
                    c["judged"] += 1
                    c["sem_bad"] += (not rec["sem_ok"])
                    c[f"sem_bad_{rec['truth_src']}"] += (not rec["sem_ok"])
                if rec.get("cp_ok") is False:
                    c["cp_bad_human"] += 1
                c["char_ne_libtop"] += rec["cp_vs_libtop"]
    for ch, c in agg.items():
        summary["channels"][ch] = {**dict(c),
                                   "sem_err_rate": (round(c["sem_bad"] / c["judged"], 4)
                                                    if c["judged"] else None),
                                   "sem_err_upper95": (round(upper95(c["sem_bad"], c["judged"]), 4)
                                                       if c["judged"] else None)}
    if a.calibrate:
        summary["col_anchor_calibration"] = dict(calib)
    summary["codepoint_drift_by_channel"] = {f"{c}|{v}": n for (c, v), n in drift.most_common()}
    summary["codepoint_drift_pairs"] = dict(drift_pairs.most_common(40))
    summary["cells"] = {f"{b}:{'admit' if ok else 'not'}": v for (b, ok), v in sorted(admit_all.items())}
    with open(out_dir / "cells.jsonl", "w", encoding="utf-8") as f:
        for rec in cells_out:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    json.dump(summary, open(out_dir / "summary.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
