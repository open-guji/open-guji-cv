#!/usr/bin/env python3
"""找「bindings 缓存陈旧」的页（GUJI-208kx）。**纯只读、纯标准库**：只 open(..., 'r')／读文件算 sha256，不 import 任何 open_guji_cv 模块
（它们的读路径 `book_bindings`→`page_bindings` 会在缓存陈旧时**写** `feedback/bindings/<册>/pNNNN.json`，所以这里自己复刻缓存键）。

  python3 -I find_stale_bindings_cache.py <WS> <册> [<册> …] [--products <产物根>] [--cells-step row_segment] [--version 6]

缓存键（终头 1deec56，`feedback/bindings.py`）：缓存页 = {v, cells_sha, sig, rows…}，`page_bindings` 读缓存时三者全对才用，任一不对就**重算并写回**：
  v          == _VERSION（终头＝6）
  cells_sha  == sha256(`<产物根>/<册>/<cells 步>/pNNNN.json` 文件字节)（缺文件＝None）
  sig        == f"{len(裁决事件)}:{最后一条事件id}" [+ "|bf:"+补锚摘要（补锚档非空时）] [+ f"|{len(打回事件)}:{最后一条id}"（有打回事件时）]
裁决事件＝`feedback/events/*.jsonl` 里 kind=confirm、target.unit=cell、不是看图结论（kind≠vision_check 且 payload.source≠vision）、
cell key 形如 `册:页:列:格[a|b]` 且册名相同，按页分组、按 (ts,batch,seq) 排序；打回事件＝kind∈{cutline,n_body_slots,return_resolve} 且 target.book＝册、page 非空。
补锚档＝`feedback/anchors/<册>.jsonl`。要核的页＝裁决事件页 ∪ 打回事件页（`book_bindings` 就是这么遍历的）。

产物根缺省：环境变量 `GUJI_PRODUCTS_DIR`（引擎实际用的）> `<WS>/products`。**窗口里 seed_admit 读缓存时比的是「默认产物根」，不是 exp 的 --root／--snapshot**，
所以演练要用沙箱副本里实际生效的那个产物根，用 `--products` 明说。

注意：`book_bindings` 一次遍历**整本书**的所有页——只要有一页陈旧，seed_admit 读这本书的人裁时会把这册所有陈旧页一并重写（不是只重写你挑的那页）。

退出码：0 全部一致（seed_admit 读路径不会重写）；1 有陈旧或缺失页（读路径会重写——可用来在**沙箱副本**里演练 `h_lane_surface.py check` 的 rc=3）；
        2 用法错／WS 不存在／路径环境变量（GUJI_FEEDBACK_DIR 等）被设致查不准／册无事件目录／读文件失败。
"""
import hashlib, json, os, re, sys
from pathlib import Path

ENV_OVERRIDES = ["GUJI_FEEDBACK_DIR", "GUJI_VERDICTS_DIR", "GUJI_EXCLUSIONS", "GUJI_GLYPH_STORE", "GUJI_GLYPH_DB", "GUJI_BATCHES_DIR"]
KEY = re.compile(r"^(?P<book>[^:]+):(?P<page>\d+):(?P<col>\d+):(?P<slot>-?\d+)(?P<sub>[ab]?)$")
RETURN_KINDS = ("cutline", "n_body_slots", "return_resolve")
MODEL_JUDGMENT_SOURCES = {"vision"}


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def read_events(events_dir):
    """复刻 EventLog.iter_all：批次名升序，批内按 (batch, seq)。"""
    out = []
    for f in sorted(Path(events_dir).glob("*.jsonl")):
        evs = []
        with open(f, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    evs.append(json.loads(line))
        evs.sort(key=lambda e: (e["batch"], e["seq"]))
        out.extend(evs)
    return out


def counts_as_human(e):
    if e.get("kind") == "vision_check":
        return False
    return (e.get("payload") or {}).get("source") not in MODEL_JUDGMENT_SOURCES


def group_events(all_events, book):
    verdict, ret = {}, {}
    ordered = sorted(all_events, key=lambda e: (e["ts"], e["batch"], e["seq"]))
    for e in ordered:
        t = e.get("target") or {}
        if e.get("kind") == "confirm" and t.get("unit") == "cell" and counts_as_human(e):
            m = KEY.match(t.get("key") or "")
            if m and m["book"] == book:
                verdict.setdefault(int(m["page"]), []).append(e)
        if e.get("kind") in RETURN_KINDS and t.get("book") == book and t.get("page") is not None:
            ret.setdefault(t["page"], []).append(e)
    return verdict, ret


def load_backfill(path):
    out = {}
    p = Path(path)
    if not p.exists():
        return out
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if d.get("anchor"):
                out[d["event"]] = d["anchor"]
    return out


def page_signature(anchors, event_ids):
    h = hashlib.sha1()
    for eid in event_ids:
        a = anchors.get(eid)
        if a is not None:
            h.update(eid.encode())
            h.update(json.dumps(a, sort_keys=True, ensure_ascii=False).encode())
    return h.hexdigest()[:16]


def make_sig(events, return_events, backfill):
    base = f"{len(events)}:{events[-1]['id'] if events else ''}"
    if backfill:
        base = f"{base}|bf:{page_signature(backfill, [e['id'] for e in events])}"
    if not return_events:
        return base
    return f"{base}|{len(return_events)}:{return_events[-1]['id']}"


def check_book(ws, book, products, step, version):
    ws = Path(ws)
    ev_dir = ws / "feedback" / "events"
    if not ev_dir.is_dir():
        return None, f"册 {book}：没有事件目录 {ev_dir}"
    verdict, ret = group_events(read_events(ev_dir), book)
    backfill = load_backfill(ws / "feedback" / "anchors" / f"{book}.jsonl")
    rows = []
    for page in sorted(set(verdict) | set(ret)):
        key = f"p{page:04d}"
        prod = Path(products) / book / step / f"{key}.json"
        now_cells = sha256_file(prod) if prod.exists() else None
        now_sig = make_sig(verdict.get(page, []), ret.get(page), backfill)
        cache = ws / "feedback" / "bindings" / book / f"{key}.json"
        if not cache.exists():
            rows.append(dict(page=page, status="缺失", fields=["缓存文件不存在（读路径会算出来并写入）"], cells_now=now_cells, sig_now=now_sig))
            continue
        try:
            with open(cache, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception as ex:
            rows.append(dict(page=page, status="陈旧", fields=[f"缓存读不开（{ex.__class__.__name__}）"], cells_now=now_cells, sig_now=now_sig))
            continue
        diff = []
        if d.get("v") != version:
            diff.append(f"v：缓存 {d.get('v')} ≠ 现行 {version}")
        if d.get("cells_sha") != now_cells:
            diff.append(f"cells_sha：缓存 {str(d.get('cells_sha'))[:12]} ≠ 现行 {str(now_cells)[:12]}")
        if d.get("sig") != now_sig:
            diff.append(f"sig：缓存 {d.get('sig')} ≠ 现行 {now_sig}")
        rows.append(dict(page=page, status="陈旧" if diff else "一致", fields=diff, cells_now=now_cells, sig_now=now_sig))
    return rows, None


def main(argv):
    if len(argv) < 3 or argv[1].startswith("-"):
        print(__doc__); return 2
    ws, books = argv[1], []
    products = os.environ.get("GUJI_PRODUCTS_DIR") or None
    step, version = "row_segment", 6
    a = argv[2:]; i = 0
    while i < len(a):
        if a[i] == "--products": products = a[i + 1]; i += 2
        elif a[i] == "--cells-step": step = a[i + 1]; i += 2
        elif a[i] == "--version": version = int(a[i + 1]); i += 2
        elif a[i].startswith("-"): print("未知参数", a[i]); return 2
        else: books.append(a[i]); i += 1
    if not books:
        print("至少给一个册名"); return 2
    if not Path(ws).is_dir():
        print("WS 不是目录:", ws); return 2
    ov = {k: os.environ[k] for k in ENV_OVERRIDES if os.environ.get(k)}
    if ov:
        print("【停】路径环境变量被设，引擎读的位置可能不在 WS 下，本脚本查不准：", ov); return 2
    products = products or str(Path(ws) / "products")
    print(f"WS={ws}；产物根={products}（cells 步＝{step}；缓存版本期望 v={version}）")
    total_stale = 0
    for book in books:
        rows, err = check_book(ws, book, products, step, version)
        if err:
            print("【停】" + err); return 2
        stale = [r for r in rows if r["status"] != "一致"]
        total_stale += len(stale)
        print(f"\n== {book}：要核的页 {len(rows)}，陈旧／缺失 {len(stale)} ==")
        print("| 页 | 状态 | 不一致字段 |\n|---|---|---|")
        for r in rows:
            if r["status"] != "一致":
                print(f"| p{r['page']:04d} | {r['status']} | {'；'.join(r['fields'])} |")
        ok = [r["page"] for r in rows if r["status"] == "一致"]
        if ok:
            print(f"（一致的页 {len(ok)} 个，例：{', '.join('p%04d' % p for p in ok[:8])}{' …' if len(ok) > 8 else ''}）")
    print()
    if total_stale:
        print(f"结论：有 {total_stale} 页陈旧／缺失——seed_admit 读这些册的人裁时会重写它们（这册所有陈旧页一并重写）；可在**沙箱副本**里拿来演练 check rc=3。")
        return 1
    print("结论：全部一致——seed_admit 读路径不会重写 bindings 缓存（rc=0 路径）。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
