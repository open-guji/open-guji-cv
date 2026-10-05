# -*- coding: utf-8 -*-
"""四庫總目整册标点层（A4）＋实体层（A5）流水线。逻辑在 `open_guji_cv/render/siku_extract.py`。

    # 跑一册：NNN.punct.json / .entity.json / .rich.md / .new_candidates.tsv / .extract_report.json
    python scripts/siku_volume_extract.py run --vol 2 \\
        --lines-md <book-text>/Book/k/z/g/96mid1ogzk/original/002.lines.md \\
        --book-index <book-index> --out <输出目录> [--cache <缓存目录>] \\
        [--provider glm --model glm-4.5-flash] [--workers 4] [--pages 3-15]

    # 抽检核对表：标点 200 处、命中实体 50 个（TSV，带上下文与书影坐标）
    python scripts/siku_volume_extract.py sample --vol 2 --lines-md … --out <输出目录> --book-index …

    # 人裁完收回：一致率 / 误挂率
    python scripts/siku_volume_extract.py score <核对表.tsv>

缓存默认 `<lines.md 所在目录>/.punct_cache`（与 vol02 前 15 页那版同处），断点续跑即命中。
云端 `glm` 走代理注入密钥：环境里没有 GLM_API_KEY 时填一个占位值即可（代理会替换）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from open_guji_cv.render.entity_extract import BookIndexMatcher  # noqa: E402
from open_guji_cv.render import siku_extract as sx  # noqa: E402

BOOK_ID = "96mid1ogzk"
TITLE = "欽定四庫全書總目"
_PAGE = re.compile(r"^\s*<!--\s*p(\d+)\s*-->\s*$")


def select_pages(text: str, spec: str | None) -> str:
    """`--pages 3-15` 只留这些页（演练用）；不给就整册。"""
    if not spec:
        return text
    a, _, b = spec.partition("-")
    lo, hi = int(a), int(b or a)
    keep, cur = [], None
    for ln in text.splitlines():
        m = _PAGE.match(ln)
        if m:
            cur = int(m.group(1))
        if cur is not None and lo <= cur <= hi:
            keep.append(ln)
    return "\n".join(keep) + "\n"


def make_client(args):
    from open_guji_cv.render.punct_llm import ENDPOINTS, PunctClient
    env = ENDPOINTS[args.provider][0]
    if args.provider == "glm" and not os.environ.get(env):
        os.environ[env] = "proxy-injected"
    extra = {"thinking": {"type": "disabled"}} if (args.model or "").startswith("glm-4.5") else None
    return PunctClient(args.provider, args.model, cache_dir=args.cache, timeout=args.timeout, extra=extra)


def cmd_run(args) -> int:
    text = select_pages(Path(args.lines_md).read_text(encoding="utf-8"), args.pages)
    args.cache = Path(args.cache) if args.cache else Path(args.lines_md).parent / ".punct_cache"
    client = make_client(args)
    matcher = BookIndexMatcher(args.book_index)
    matcher.load_index()
    print(f"book-index: Work {len(matcher.works)}，Entity {len(matcher.people)}")
    t0 = time.time()

    def progress(i: int, n: int) -> None:
        if i == n or i % 20 == 0:
            print(f"  块 {i}/{n}  {time.time() - t0:.0f}s", flush=True)

    res = sx.run_volume(text, client, matcher, limit=args.limit, workers=args.workers,
                        max_bad_ratio=args.max_bad_ratio, source=f"{args.provider}:{client.model}",
                        count_blank_columns=args.count_blank_columns, progress=progress)
    res.report.update({"vol": args.vol, "lines_md": str(args.lines_md), "pages": args.pages,
                       "model": f"{args.provider}:{client.model}", "seconds": round(time.time() - t0, 1)})
    paths = sx.write_outputs(res, Path(args.out), args.vol, book_id=BOOK_ID,
                             title=f"{TITLE}·第{args.vol}册", creator=f"{args.provider}:{client.model}")
    r = res.report
    print(f"字 {r['chars']}（底本对不上 {r['unmatched_chars']}）；段 {r['paragraphs']}；块 {r['chunks']}"
          f"（作废 {r['chunks_failed']}，{r['chars_unpunctuated']} 字未标点）")
    print(f"标点 {r['points']}，分段 {r['breaks']}；实体 {r['entities']}（命中 {r['matched']}，"
          f"新候选 {r['new_candidate']}）{r['by_type']}")
    for k, p in paths.items():
        print(f"  {k}: {p}")
    return 0


def cmd_sample(args) -> int:
    out = Path(args.out)
    stem = f"{args.vol:03d}"
    chars, _ = sx.load_render_chars(select_pages(Path(args.lines_md).read_text(encoding="utf-8"), args.pages))
    pj = json.loads((out / f"{stem}.punct.json").read_text(encoding="utf-8"))
    ej = json.loads((out / f"{stem}.entity.json").read_text(encoding="utf-8"))
    matcher = None
    if args.book_index:
        matcher = BookIndexMatcher(args.book_index)
        matcher.load_index()
    p_rows = sx.sample_punct(pj, chars, args.n_punct, args.seed)
    e_rows = sx.sample_entities(ej, chars, matcher, args.n_entity, args.seed)
    sx.write_tsv(p_rows, out / f"{stem}.check_punct.tsv")
    sx.write_tsv(e_rows, out / f"{stem}.check_entity.tsv")
    print(f"标点核对表 {len(p_rows)} 行 → {out / f'{stem}.check_punct.tsv'}")
    print(f"实体核对表 {len(e_rows)} 行 → {out / f'{stem}.check_entity.tsv'}")
    return 0


def cmd_score(args) -> int:
    print(json.dumps(sx.score_tsv(Path(args.tsv)), ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--vol", type=int, required=True, help="册号（输出文件名 NNN）")
        p.add_argument("--lines-md", required=True, help="底本 NNN.lines.md")
        p.add_argument("--out", required=True, help="输出目录")
        p.add_argument("--pages", help="只跑这些页，如 3-15（演练用）")

    r = sub.add_parser("run", help="整册标点＋实体")
    common(r)
    r.add_argument("--book-index", required=True, help="book-index 仓根目录")
    r.add_argument("--cache", help="LLM 缓存目录（默认 lines.md 同目录 .punct_cache）")
    r.add_argument("--provider", default="glm", choices=["glm", "qwen"])
    r.add_argument("--model", default="glm-4.5-flash")
    r.add_argument("--workers", type=int, default=4)
    r.add_argument("--limit", type=int, default=300, help="每块字数上限")
    r.add_argument("--max-bad-ratio", type=float, default=0.02, help="改字超过此比例整块作废")
    r.add_argument("--timeout", type=int, default=180)
    r.add_argument("--count-blank-columns", action="store_true", help="空行也占一个列号")
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("sample", help="出抽检核对表")
    common(s)
    s.add_argument("--book-index", help="给实体核对表补条目信息（朝代、生卒）")
    s.add_argument("--n-punct", type=int, default=200)
    s.add_argument("--n-entity", type=int, default=50)
    s.add_argument("--seed", type=int, default=0)
    s.set_defaults(func=cmd_sample)

    c = sub.add_parser("score", help="收回人裁核对表，算一致率/误挂率")
    c.add_argument("tsv")
    c.set_defaults(func=cmd_score)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
