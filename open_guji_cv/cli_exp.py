# -*- coding: utf-8 -*-
"""`guji exp`：A/B 实验（overview#457）。框架在 `open_guji_cv/exp/`，这里只管命令行。

    guji exp run    <exp.yaml> -w <工作区> [--snapshot <产物根>] [--root <实验根>] [--only B] [--jobs N]
    guji exp run    --base A.yaml --var B.yaml --books vol05 --from seed_admit --snapshot … -w …
    guji exp report <exp名|exp目录> -w <工作区> [--root …]
    guji exp flips  <exp> sample|page|harvest [verdicts.jsonl] [--n 60] [-o …]
    guji exp list   -w <工作区> [--root …]
"""
from __future__ import annotations

import os
from pathlib import Path


def _set_ws(args) -> None:
    if getattr(args, "workspace", None):
        os.environ["GUJI_WORKSPACE"] = str(Path(args.workspace).expanduser().resolve())


def _edir(args) -> Path:
    from .errors import BadRequest
    from .exp.runner import default_root
    if not args.exp:
        raise BadRequest(f"{args.action} 要给实验名或实验目录")
    p = Path(args.exp).expanduser()
    if p.is_dir() and (p / "exp.yaml").exists():
        return p.resolve()
    root = Path(args.root).expanduser() if args.root else default_root()
    return (root / args.exp).resolve()


def _summary(rep: dict) -> None:
    for vn, comp in rep["comparisons"].items():
        b = comp["overall"]["body"]
        g = comp["guardrails"]
        print(f"[{rep['base']} vs {vn}] 正文 {b['cells']} 格：放行率 {_p(b['admit_rate']['A'])} → "
              f"{_p(b['admit_rate']['B'])}，送审率 {_p(b['review_rate']['A'])} → {_p(b['review_rate']['B'])}；"
              f"判准 {sum(x['verdict'] == 'pass' for x in g)}/{len(g)} 达标")


def _p(x) -> str:
    return "—" if x is None else f"{x * 100:.2f}%"


def cmd_exp(args) -> None:
    # 影子模型（sklearn HistGradientBoosting）逐格预测，缺省按核数开 OpenMP 线程；按变体并行开几个进程时
    # 线程互相抢，vol05 实测每页 244s，限单线程后 ~1s（overview#457）。用户显式设了就不动。
    for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(k, "1")
    from .errors import BadRequest
    from .exp import config as EC
    from .exp import flips as FL
    from .exp import report as RP
    from .exp import runner as RN

    _set_ws(args)
    if args.action == "run":
        if args.exp:
            cfg = EC.load(args.exp)
        elif args.var:
            if not args.books:
                raise BadRequest("短写法要给 --books")
            cfg = EC.from_pair(args.base, args.var, books=args.books.split(","),
                               from_step=args.from_step or "seed_admit", to_step=args.to_step or "seed_admit",
                               name=args.name)
        else:
            raise BadRequest("要给实验 yaml，或 --var（短写法）")
        if args.from_step and args.exp:
            cfg.from_step = args.from_step
        if args.to_step and args.exp:
            cfg.to_step = args.to_step
        if args.pages:
            cfg.pages = args.pages
        st = RN.run(cfg, snapshot=args.snapshot, root=args.root, variants=args.only, jobs=args.jobs,
                    force=args.force)
        edir = RN.exp_dir(cfg, args.root)
        print(f"跑完：{edir}")
        for k, v in st["runs"].items():
            print(f"  {k}: {v['pages']} 页 {v['counts']} {v['elapsed']}s")
        if not args.no_report:
            rep = RP.build(edir)
            _summary(rep)
            print(f"报告：{edir / 'report.md'}")
    elif args.action == "report":
        edir = _edir(args)
        rep = RP.build(edir)
        _summary(rep)
        print(f"报告：{edir / 'report.md'}")
    elif args.action == "flips":
        edir = _edir(args)
        if args.flips_action == "sample":
            cards = FL.sample(edir, n=args.n, seed=args.seed, resample=args.resample)
            print(f"{len(cards)} 张卡 → {edir / FL.CARDS}")
        elif args.flips_action == "page":
            fn = None if args.no_images else FL.cache_image_fn()
            out = FL.build_page(edir, args.out, image_fn=fn)
            print(f"审查页：{out}（用 Artifact 发布，capabilities 带 artifact，见 skill review-artifact）")
        else:
            if not args.verdicts:
                raise BadRequest("harvest 要给裁决 jsonl（harvest_verdicts.py -o 的输出）")
            print(FL.harvest(edir, args.verdicts), f"→ {edir / FL.EXTRA}；再 guji exp report {edir.name}")
    else:
        root = Path(args.root).expanduser() if args.root else RN.default_root()
        for e in RN.list_experiments(root):
            print(f"  {e['name']:30s} {','.join(e['books'] or []):16s} {'/'.join(e['variants']):12s} "
                  f"{e['ran_at']} {e['code_rev'] or ''} {'有报告' if e['report'] else ''}")


def add_parser(sub) -> None:
    p = sub.add_parser("exp", help="[v2] A/B 实验：run | report | flips | list（overview#457）")
    p.add_argument("action", choices=["run", "report", "flips", "list"])
    p.add_argument("exp", nargs="?", default=None,
                   help="run：实验 yaml；report/flips：实验名或实验目录")
    p.add_argument("flips_action", nargs="?", choices=["sample", "page", "harvest"], default="sample")
    p.add_argument("verdicts", nargs="?", default=None, help="flips harvest：裁决 jsonl")
    p.add_argument("-w", "--workspace", default=None, help="工作区（册配置、人裁事件、实验根缺省在 <工作区>/experiments）")
    p.add_argument("--root", default=None, help="实验根；缺省 <工作区>/experiments。不得落在 products/ 之内")
    p.add_argument("--snapshot", default=None, help="上游产物根（快照；含 <book>/<step>/），只读")
    p.add_argument("--base", default=None, help="短写法：基线变体 yaml（省略 = 当前默认参数）")
    p.add_argument("--var", action="append", default=None, help="短写法：变体 yaml，可多次")
    p.add_argument("--books", default=None, help="短写法：册，逗号分隔")
    p.add_argument("--from", dest="from_step", default=None, help="第一个受影响的步（缺省 seed_admit）")
    p.add_argument("--to", dest="to_step", default=None, help="跑到哪一步（缺省 seed_admit）")
    p.add_argument("--name", default=None, help="短写法：实验名")
    p.add_argument("--pages", default=None, help="覆盖 yaml 的 pages：all | body | 页号表达式")
    p.add_argument("--only", action="append", default=None, help="run：只跑这几个变体")
    p.add_argument("--jobs", type=int, default=1)
    p.add_argument("--force", action="store_true", help="run：删掉变体已有的本段产物重跑")
    p.add_argument("--no-report", action="store_true", help="run：跑完不出报告")
    p.add_argument("--n", type=int, default=60, help="flips sample：抽几格")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--resample", action="store_true", help="flips sample：已有 cards.jsonl 也重抽（id 会变）")
    p.add_argument("--no-images", action="store_true", help="flips page：不带字块图")
    p.add_argument("-o", "--out", default=None, help="flips page：输出 html")
