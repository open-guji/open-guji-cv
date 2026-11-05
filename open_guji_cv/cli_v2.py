"""四个抽象的 CLI：`guji` 入口，也以非冲突名注册进 `python -m open_guji_cv`。

    guji pipeline <pipeline> <book> [--from S] [--to S] [--pages dev_set|all|3-6,9] [--force] [--params JSON]
    guji step <step> <book> [--pages …] [--force]          # 只跑一步
    guji status <book> [--pipeline P] [--pages …] [--json]
    guji console [--port 8640] [--no-browser]                # 装了 guji-console 才有（入口点 guji.commands）
    guji cache usage|prune [--limit-gb N]
    guji cache build-rare-index --book <book> [--jobs 4]   # 云端预建 Step5-b embedding 索引，供服务器分发命中
    guji cache warm --book <book> [--pages all] [--jobs 4]  # 多进程预渲字块缓存（快照导入后用）
    guji cache build-font-index [--book <book>]            # 云端预建控制台 HOG 字体模板索引，供服务器分发命中
    guji cache pull-rare-index [--book <book>] [--charset unicode-cjk-ab]  # 从全字表向量包（R2，按版本）落成 Step5-b 索引，不用现建
    guji cache build-emb-pack [--jobs 4]                   # 建一版全字表向量包（清单进 config/hanzi/emb/）

旧 `python -m open_guji_cv run …`（v1 一键管线）名字不动，这里的「跑一条 pipeline」叫 `pipeline`。
本模块顶层不 import 任何重依赖，保证 CLI 冷启动快。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .core import hooks
from .utils.image_io import imread as cv_imread  # 中文路径安全的读图（裸 cv2.imread 遇中文路径静默返回 None）

DEFAULT_PIPELINE = "keben_body_v2"


# ── handlers ─────────────────────────────────────────────────────────
def _engine(book_id: str, pipeline_id: str, params: str | None = None, quiet: bool = False):
    from .core.book import load_book
    from .core.engine import Engine
    from .core.pipeline import load_pipeline
    pl = load_pipeline(pipeline_id)
    book = load_book(book_id)
    overrides = json.loads(params) if params else None
    from .core.book_config import run_override_params
    ov_params = run_override_params()           # `--override` 里的 params：当调用方显式参数，压过册 yaml
    if ov_params:
        from .core.book_config import merge
        overrides = merge(overrides or {}, ov_params)
    return Engine(book, pl, params=overrides, log=(lambda s: None) if quiet else None)


def cli_steps(eng, from_step: str | None, to_step: str | None) -> list[str]:
    """`guji pipeline` 要跑的步骤：按 --from/--to 切片，再套**可选步骤开关**（`Engine._enabled`）。

    2026-09-15 实锤：`Engine._default_steps` 只在 steps=None 时应用可选步骤开关，而这里总是
    先切片再传显式列表——当年 Step5-c OCR 候选（已于 2026-10-18 删除）因此照跑不误。
    控制台同一条 pipeline 走的是 steps=None，开关生效，CLI 与控制台不同参不同输出。
    只有 `guji step rare_candidates`（from == to == 那一步，人手工点名）才不套开关。"""
    steps = eng.pipeline.slice(from_step, to_step)
    if from_step is not None and from_step == to_step:
        return steps
    enabled = eng._enabled(steps)
    skipped = [s for s in steps if s not in enabled]
    if skipped:
        print(f"按可选步骤开关跳过：{', '.join(skipped)}（"
              "rare_candidates 无下游在读时自动跳过，点名 `guji step rare_candidates` 才跑）", flush=True)
    return enabled


def isolated_step_argv(args, sid: str, workspace: str) -> list[str]:
    """`--isolate-steps`：把 `guji pipeline` 里的一步翻译成 `guji step <sid>` 的子进程命令行。

    只透传会影响这一步怎么跑的参数（页范围、force、stop-on-error、params、jobs、sample-db），
    不透传 `--json`／`--wait`（锁由父进程持有，见 `_run_steps_isolated`）。"""
    argv = [sys.executable, "-m", "open_guji_cv", "step", sid, args.book,
            "--pipeline", args.pipeline, "--pages", str(args.pages), "-w", workspace,
            "--no-isolate-steps", "--no-prep"]   # 备输入由父进程在起子进程前做过（或 --no-prep 跳过），子进程不再备
    if args.force:
        argv.append("--force")
    if args.stop_on_error:
        argv.append("--stop-on-error")
    if getattr(args, "params", None):
        argv += ["--params", args.params]
    if getattr(args, "jobs", None):
        argv += ["--jobs", str(args.jobs)]
    if getattr(args, "allow_sample_db", False):
        argv.append("--allow-sample-db")
    if getattr(args, "allow_cv_mismatch", False):
        argv.append("--allow-cv-mismatch")
    if getattr(args, "why", None):
        argv += ["--why", args.why]
    if getattr(args, "allow_missing_deps", False):
        argv.append("--allow-missing-deps")
    return argv


def _run_steps_isolated(args, steps: list[str]) -> int:
    """`--isolate-steps`：每个 Step 一个子进程，跑完整个进程退出，操作系统回收它加载的
    一切（torch、字形库匹配器、embedding／HOG 矩阵、OCR 引擎……）。

    动机（GUJI-555，`doc/research/pipeline单进程内存诊断-2026-10-17.md`）：单进程连跑多步时，
    各 Step 惰性加载的大对象跑完不释放、逐步叠加，服务器 3G 软上限下被节流到每页几分钟。
    闸跟着它挂的 Step 在子进程里自动跑（与 `Engine.run` 同一规矩）。
    步序、产物落点、指纹都与单进程一致——这里只改「进程怎么切」，不碰任何 Step。
    父进程持有书级跑批锁，子进程设 `GUJI_NO_RUN_LOCK=1` 免得自己抢自己；子进程不再进批处理切片
    （父进程已经在里面，cgroup 随子进程继承）。

    返回码：第一个非零的子进程返回码，全过 0；**遇到非零就停**（2026-10-20 起隔离是缺省）。子进程
    只在两种情况下非零：`--stop-on-error` 且有页失败，或者整步崩了（异常、护栏拒跑）——后者以前不加
    `--stop-on-error` 时会被吞掉、接着用缺了的上游跑下游，最后返回 0；单进程连跑时同样的崩溃是直接抛出。"""
    import os
    import signal
    import subprocess
    ws = os.environ["GUJI_WORKSPACE"]
    env = {**os.environ, "GUJI_NO_RUN_LOCK": "1", "GUJI_NO_BATCH_SLICE": "1"}
    if not env.get("GUJI_PERF_GROUP"):    # 每步一个子进程、各写一份耗时记录：用同一个组号串起来
        import time
        import uuid
        env["GUJI_PERF_GROUP"] = time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    cur: dict = {"p": None}

    def _forward(signum, _frame):
        # 控制台取消工单只 terminate 父进程（console/jobs.py）：转给正在跑的那一步，别留孤儿接着写产物。
        # 这里不能 wait：主线程正卡在同一个 Popen.wait 里，它的锁不可重入，会死锁；等子进程收尾放在 finally
        p = cur["p"]
        if p is not None and p.poll() is None:
            p.send_signal(signum)
        raise SystemExit(128 + signum)
    try:
        old = signal.signal(signal.SIGTERM, _forward)
    except ValueError:                    # 不在主线程（嵌在别的程序里调）：不接管信号
        old = None
    rc = 0
    try:
        for i, sid in enumerate(steps, 1):
            print(f"── [{i}/{len(steps)}] {sid}（独立子进程）", flush=True)
            cur["p"] = subprocess.Popen(isolated_step_argv(args, sid, ws), env=env)
            code = cur["p"].wait()
            cur["p"] = None
            if code != 0:
                rc = code
                print(f"✗ {sid} 返回码 {code}，后面的步不跑了", file=sys.stderr)
                break
    finally:
        if old is not None:
            signal.signal(signal.SIGTERM, old)
        p = cur["p"]
        if p is not None:                 # 被信号打断：等转过去的信号让这一步停下，停不下来就杀
            try:
                p.wait(timeout=30)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
    return rc


def _guard_cv_version(book, allow: bool = False, warn_only: bool = False, why: str | None = None,
                      eng=None) -> None:
    """册配置固定了 `cv_version`、装的 cv 不是这个版本：写产物的命令拒跑（退出码 2），
    只读命令只提醒（设计 §2a 第 6 条，GUJI-577）。

    放行只有两条路（2026-10-23 起），都照样提醒，理由记进环境变量 `GUJI_CV_OVERRIDE`、随每条 manifest 落盘：
    - 在中心库实验分支上跑（`GUJI_DATA_BRANCH=exp/*`，产物、glyph.db 落该分支自己的目录）：自动放行；
    - `--allow-cv-mismatch --why "<理由>"`：不写理由不放行。
    给了 `eng` 就把理由补进它已算好的 manifest 字段（引擎先于护栏建）。"""
    import os
    from .core.cv_version import OVERRIDE_ENV, frozen_mismatch, isolated_branch, mismatch
    # 冻结册另按冻结时的提交比（M10·D7，GUJI-694）：冻结册顶层常没写 cv_version，以前在 main 上照样能跑
    msg = mismatch(getattr(book, "cv_version", None)) or frozen_mismatch(getattr(book, "freeze", None))
    if not msg:
        return
    if warn_only:
        print(f"⚠️ {msg}", file=sys.stderr, flush=True)
        return
    why = (why or "").strip() or os.environ.get(OVERRIDE_ENV, "").strip()
    branch = isolated_branch()
    if branch and not allow:
        why = f"exp-branch:{branch}"
    if branch or (allow and why):
        os.environ[OVERRIDE_ENV] = why
        if eng is not None:
            eng._cv["cv_override"] = why
        print(f"⚠️ {msg}\n   放行（{why}）：产物 manifest 记装的版本与这条理由", file=sys.stderr, flush=True)
        return
    if allow:
        print(f"✗ {msg}\n   --allow-cv-mismatch 要同时写 --why \"<理由>\"（记进产物 manifest）", file=sys.stderr, flush=True)
    else:
        print(f"✗ {msg}", file=sys.stderr, flush=True)
    sys.exit(2)


def _preflight_deps(eng, steps: list[str], allow: bool = False) -> None:
    """起跑前查这次要跑的步骤本机缺不缺依赖（`preflight.py`，GUJI-654）；缺了拒跑，`--allow-missing-deps` 放行。"""
    import os
    from . import preflight
    allow = allow or os.environ.get("GUJI_ALLOW_MISSING_DEPS") == "1"
    missing = preflight.check(eng, steps)
    if not missing:
        return
    head = "⚠ 本机缺依赖（--allow-missing-deps 放行，照跑）：" if allow else "✗ 本机缺依赖，拒跑（退出码 2）："
    print(head, file=sys.stderr)
    for m in missing:
        print(f"  - {m}", file=sys.stderr)
    print(f"  装齐：{preflight.INSTALL_HINT}；确实要在缺东西的机器上跑加 --allow-missing-deps", file=sys.stderr)
    if not allow:
        sys.exit(2)


def _prepare(eng, steps: list[str], jobs: int = 1) -> None:
    """开跑前备输入（钉版字形库、模型、语料、生僻字索引）：由 manager 经钩子 `prepare` 做（`core/hooks.py`）。
    没装 manager 而册钉了这些输入 → 拒跑（退出码 2）；`--no-prep` 放行。"""
    if hooks.has("prepare"):
        hooks.call("prepare", eng.book, steps, jobs)
        return
    pinned = hooks.pinned_inputs(eng.book)
    if pinned:
        print(f"✗ 册钉了{'、'.join(pinned)}，开跑前要 guji-manager 备好这些输入，本机没装 manager（或版本太旧）。\n"
              f"   装法见 scripts/ensure_manager.sh；确定本机文件已齐、要照跑加 --no-prep", file=sys.stderr)
        sys.exit(2)


def cmd_pipeline(args) -> None:
    if getattr(args, "allow_sample_db", False):
        import os
        os.environ["GUJI_ALLOW_SAMPLE_DB"] = "1"
    if getattr(args, "force", False):
        # --force 一并关掉格级复用（2026-10-24）。复用只认本步 self_hash，而字形库指纹是软参数：
        # 殿本 vol07 在空 g2 上跑过一次，修好库后 `--from glyph_match --force` 重跑，引擎确实重跑了每一页，
        # 可 glyph_match 每格都从旧产物（对空库判的 diff、无候选）原样搬回，seed_admit 送审 86→15,559。
        # 「强制重算」就该每格重算；要复用就别加 --force。设在建引擎之前：本进程的 RunContext
        # 与 --isolate-steps 的每步子进程（继承环境）都读得到。
        import os
        os.environ["GUJI_NO_REUSE"] = "1"
        print("  --force：格级复用关闭（GUJI_NO_REUSE=1），每格重算", flush=True)
    from .core.workspace import assert_workspace_declared
    assert_workspace_declared()
    eng = _engine(args.book, args.pipeline, getattr(args, "params", None))
    _guard_cv_version(eng.book, allow=getattr(args, "allow_cv_mismatch", False), why=getattr(args, "why", None),
                      eng=eng)
    steps = cli_steps(eng, getattr(args, "from_step", None), getattr(args, "to_step", None))
    pages = eng.book.resolve_pages(args.pages)
    if not getattr(args, "no_prep", False):
        _prepare(eng, steps, jobs=max(1, getattr(args, "jobs", 1) or 1))
    _preflight_deps(eng, steps, allow=getattr(args, "allow_missing_deps", False))
    # 书级跑批锁：同一产物目录同一本书只许一个跑批在写（overview 进度/并行分工.md §三）
    from .core.runlock import book_run_lock, RunLockHeld
    isolate = getattr(args, "isolate_steps", None)
    if isolate and getattr(args, "json", False):
        print("✗ --isolate-steps 不支持 --json（每步一个子进程，没有合并报告）", file=sys.stderr)
        sys.exit(2)
    if isolate is None:          # 缺省：多于一步、不要 JSON 报告时每步一个子进程（GUJI-647）
        isolate = len(steps) > 1 and not getattr(args, "json", False)
    if isolate:
        try:
            with book_run_lock(eng.book.id, wait=getattr(args, "wait", False)):
                rc = _run_steps_isolated(args, steps)
        except RunLockHeld as e:
            print(f"✗ {e}", file=sys.stderr)
            sys.exit(3)
        ok = False
        if rc == 0:
            failed = _failed_pages(eng, steps, pages)
            if failed:
                print(f"  ⚠ {len(failed)} 页失败（如 {'、'.join(failed[:5])}），没自动存包；"
                      f"见上面各步的「失败」行", file=sys.stderr)
            else:
                ok = True
        hooks.call("finished", args, eng, steps, ok)
        sys.exit(rc)
    try:
        with book_run_lock(eng.book.id, wait=getattr(args, "wait", False)):
            rep = eng.run(steps=steps, pages=pages, force=args.force, stop_on_error=args.stop_on_error,
                          jobs=getattr(args, "jobs", 1))
    except RunLockHeld as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(3)
    n_failed = sum(1 for o in rep.outcomes if o.status == "failed")
    if getattr(args, "json", False):
        print(json.dumps(rep.to_dict(), ensure_ascii=False))
    else:
        hooks.call("finished", args, eng, steps, not n_failed)
    sys.exit(1 if n_failed and args.stop_on_error else 0)


def _failed_pages(eng, steps: list[str], pages: list[int]) -> list[str]:
    """隔离跑完后，这几步（连同挂着的闸）这批页里 manifest 记失败的页：`["seed_admit p3", …]`。

    子进程里某页失败（不加 `--stop-on-error`）照样返回 0，父进程只看返回码就会当成全过——vol08 开了
    shadow_veto 却没装 joblib，seed_admit 69 页全失败，整册照样自动存了包（10-21 基线重跑）。单进程连跑时
    是数 `RunReport` 里的失败页，这里读子进程写下的 manifest（新开 ProductStore，不用父进程缓存的旧表）。"""
    from .core.spec import page_key
    from .core.step import STEPS
    from .products.store import ProductStore
    store = ProductStore(eng.store.root)
    out = []
    for sid in steps:
        gate = STEPS[sid].spec.gate if sid in STEPS else None
        for s in (sid, gate.id) if gate else (sid,):
            m = store.manifest(eng.book.id, s)
            out += [f"{s} p{pg}" for pg in pages
                    if (e := m.get(page_key(pg))) is not None and e.status == "failed"]
    return out


def cmd_step(args) -> None:
    args.from_step = args.to_step = args.step
    cmd_pipeline(args)


def _expand_books(spec: str) -> list[str]:
    import re
    out: list[str] = []
    for part in spec.split(","):
        part = part.strip()
        m = re.fullmatch(r"([A-Za-z]+)(\d+)-(?:\1)?(\d+)", part)
        if m:
            w = len(m.group(2))
            out += [f"{m.group(1)}{i:0{w}d}" for i in range(int(m.group(2)), int(m.group(3)) + 1)]
        elif part:
            out.append(part)
    return out


def _cmd_book_split(args) -> None:
    from .core.book import _book_yaml_path
    from .core.book_config import defaults_path
    from .core.book_split import SplitError, split, write_split
    if not args.books:
        print("✗ split 要 --books vol51-vol99（或逗号清单）", file=sys.stderr); sys.exit(2)
    ids = _expand_books(args.books)
    books_dir = _book_yaml_path(ids[0]).parent
    try:
        res = split(books_dir, ids, header="# 殿本共用配置（工作区基础配置）。各册 yaml 只写自己不同的部分；设计见 cv doc/design/册配置分层与运行覆盖.md\n")
    except SplitError as e:
        print(f"✗ {e}", file=sys.stderr); sys.exit(1)
    base_path = defaults_path(books_dir / f"{ids[0]}.yaml")
    n = len(res["base"].splitlines())
    print(f"共 {len(ids)} 册；基础配置 {n} 行 → {base_path}；强校验通过（每册合并结果与拆前逐字段相等）")
    for b in ids[:3] + (["…"] if len(ids) > 3 else []):
        if b != "…":
            print(f"  {b}: {res['lines_before'][b]} 行 → {res['lines_after'][b]} 行")
    if not args.apply:
        print("（干跑，没写。加 --apply 才写本机数据目录；之后 `guji db push` 推库）")
        return
    write_split(books_dir, res, base_path)
    print("已写本机数据目录。推库：guji db push -w <工作区>")


def cmd_book(args) -> None:
    if args.action == "split":
        return _cmd_book_split(args)
    if not args.book:
        print("✗ show 要册号", file=sys.stderr); sys.exit(2)
    from .core.book import _book_yaml_path
    from .core.book_config import effective_book_dict, provenance
    from .core.book_config import params_provenance
    path = _book_yaml_path(args.book)
    d = effective_book_dict(path)
    src = provenance(path)
    try:                                # 管线 yaml、套书缺省的 params 也列出来（都在册配置之下）；选不出管线就只列册配置各层
        from .core.book import load_book
        from .core.pipeline import base_param_layers, load_pipeline
        _bk = load_book(args.book)
        pl = load_pipeline(_bk.default_pipeline_id())
        pl_id, base_layers = pl.id, base_param_layers(pl, _bk)
    except Exception:
        pl_id, base_layers = None, []
    psrc = params_provenance(path, base_layers=base_layers)
    try:                                # 字形库来源：借库钉在 workspace.yaml（五层之外），这里一并列出
        from .core.book import load_book as _lb
        from .core.glyph_pin import glyph_sources
        gsrc = glyph_sources(_lb(args.book))
    except Exception as e:              # noqa: BLE001 —— 只是展示，读不了不挡 show
        gsrc = {"error": str(e)}
    if args.json:
        print(json.dumps({"book": args.book, "effective": d, "source": src, "pipeline": pl_id,
                          "params_source": {k: {"value": v, "layer": ly} for k, (v, ly) in psrc.items()},
                          "glyph_sources": gsrc},
                         ensure_ascii=False, indent=1, default=str))
        return
    print(f"# 册 {args.book} 生效配置（{path}）")
    for k in sorted(d):
        v = json.dumps(d[k], ensure_ascii=False, default=str)
        print(f"{k}: {v if len(v) <= 160 else v[:157] + '…'}    # {src.get(k, '?')}")
    print(f"\n# Step 参数逐字段（管线 {pl_id or '?'}；优先级 Step 默认 < 管线 yaml < 套书缺省 < 基础配置 < 册 yaml < 运行覆盖；"
          f"--params 另在最上层；没列出的字段 = Step 默认）")
    for k, (v, ly) in psrc.items():
        vs = json.dumps(v, ensure_ascii=False, default=str)
        print(f"params.{k}: {vs if len(vs) <= 120 else vs[:117] + '…'}    # {ly}")
    print("\n# 字形库来源（借库写在 workspace.yaml 的 glyph_lib.borrow，不在册配置五层里，整个工作区共用）")
    if gsrc.get("error"):
        print(f"  读不了：{gsrc['error']}")
        return
    ps = gsrc.get("pin")
    if gsrc.get("effective") == "pinned":
        pb = "、".join(f"{k}（{n} 个文件）" for k, n in gsrc["pinned_borrow"].items()) or "无"
        print(f"  钉 g{ps['n']}（快照 {ps['digest']}）：本书库与借库都按快照内容；快照里的借库：{pb}")
    elif ps:
        print(f"  钉 g{ps['n']} 但没有快照（旧做法）：读当前 glyph.db，借库是本机拉到的那一版")
    else:
        print("  没钉 glyph_pin：读当前 glyph.db，借库是本机 db pull 时拉到的那一版")
    for b in gsrc.get("borrow") or []:
        rev = f"本机副本 rev {b['local_rev']}" if b.get("local_rev") is not None else "本机没有拉过（或是路径条目）"
        print(f"  借 {b['entry']}：{rev}    # {b['path']}")
    if not gsrc.get("borrow"):
        print("  不借库")


def cmd_status(args) -> None:
    eng = _engine(args.book, args.pipeline, quiet=True)
    _guard_cv_version(eng.book, warn_only=True)
    pages = eng.book.resolve_pages(args.pages)
    st = eng.status(pages=pages)
    extras = [x for rows in hooks.call("status", eng.book.id, pages, eng.store) for x in rows or ()]
    for key, val, _show in extras:     # manager 登记的报告项（收尾闸、裁放不一致、看图待审、没存包的产物）
        if key:
            st[key] = val
    if args.json:
        print(json.dumps(st, ensure_ascii=False))
        return
    print(f"{st['book']} · {st['pipeline']} · {len(pages)} 页")
    if getattr(eng.book, "glyph_pin", None):
        from .core.glyph_pin import pin_state
        ps = pin_state(eng.book) or {}
        if ps.get("snapshot"):
            rev = f"，中心库 rev {ps['rev']}" if ps.get("rev") is not None else ""
            print(f"  字形库钉在 g{ps['n']}（{ps['digest']}{rev}；库文件"
                  f"{'在' if ps['db_ok'] else '缺，下次 pipeline 起跑前自动建'}）：本册用这一版的内容跑，"
                  f"要吃新人裁先 guji glyph-db snapshot 出新号，再把册 yaml 的 glyph_pin 改过去")
        else:
            print(f"  字形库钉在 g{eng.book.glyph_pin}，但没有这一版的快照：只钉指纹、跑时读当前库（旧做法）；"
                  f"guji glyph-db snapshot 出快照后改钉，本册才按版本用库")
    for sid, d in st["steps"].items():
        c = d["counts"]
        drift = f"  漂移 {d['drift']:3d}" if d.get("drift") else ""
        print(f"  {sid:16s} 新鲜 {c['fresh']:3d}  过期 {c['stale']:3d}  缺失 {c['missing']:3d}  "
              f"失败 {c['failed']:3d}  阻塞 {c['blocked']:3d}{drift}")
        # 过期原因（#174）：上游过期那条是连带的，只在没有别的原因时才印
        rs = d.get("stale_reasons") or {}
        own = {r: n for r, n in rs.items() if r != "上游过期"} or rs
        for r, n in sorted(own.items(), key=lambda kv: -kv[1]):
            tail = "，须重跑" if r.startswith("册配置") else ""
            print(f"      ↳ 过期 {n:3d} 页：{r}{tail}")
        # 开关开着、可选上游没产物（overview#429）：步骤照跑，但那一路通道在这些页没生效
        for g in d.get("optional_gaps") or ():
            sw = "/".join(g["switches"])
            print(f"      ⚠ {sw} 开着但 {g['producer']} 缺 {len(g['missing']):3d} 页，"
                  f"这些页 {sw} 通道未生效（先跑 --from {g['producer']} --to {g['producer']}）")
    if any(d.get("drift") for d in st["steps"].values()):
        print("  （漂移 = 产物对着旧的外部状态判的，如字形库变了；不算过期、不自动重跑。"
              "要重算点名格用 `guji recheck`）")
    for _key, val, show in extras:
        show(val)


def cmd_export(args) -> None:
    """`guji export md|format <册>`：把 runbook 里两条易错的散脚本收成固定口径（overview#413 C2）。

    md     → scripts/render_guji_markdown.py（全部页逐个列出，不用手抄页号）→ reports/<册>/<册>.md
    format → scripts/export_guji_format.py（章号、meta、拆页表按约定自动填）→ lines/pages/norm
    两者都只读产物。子进程跑原脚本，口径与直接调脚本完全一致。
    """
    import subprocess
    from .core.workspace import products_root, reports_root
    repo = Path(__file__).resolve().parents[1]
    scripts = repo / "scripts"
    eng = _engine(args.book, args.pipeline, quiet=True)
    pages = eng.book.resolve_pages(args.pages)
    book = eng.book.id
    out_dir = Path(args.out) if args.out else reports_root() / book
    out_dir.mkdir(parents=True, exist_ok=True)
    # 只导有 Step7 产物的页（目录、空白页等没跑到 seed_admit 的页跳过，免得整条命令因缺产物退出）
    have = {int(f.stem[1:]) for f in (products_root() / book / "seed_admit").glob("p*.json")}
    skipped = [p for p in pages if p not in have]
    pages = [p for p in pages if p in have]
    if skipped:
        print(f"（跳过 {len(skipped)} 页：没有 seed_admit 产物 {skipped[:10]}{'…' if len(skipped) > 10 else ''}）",
              file=sys.stderr)
    if not pages:
        print("✗ 没有可导出的页（seed_admit 产物为空）", file=sys.stderr); sys.exit(1)
    if args.action == "md":
        cmd = [sys.executable, str(scripts / "render_guji_markdown.py"), book, *map(str, pages),
               "--out", str(out_dir / f"{book}.md")]
    else:
        from .core.volume_id import chapter_of
        chapter = chapter_of(book, args.chapter)
        if not chapter:
            print(f"✗ 册号 {book} 推不出章号：册 yaml 写上 volume，或给 --chapter NNN", file=sys.stderr); sys.exit(2)
        meta = Path(args.meta) if args.meta else repo / "doc/formats/samples/guji_format_v0.1" / f"meta_{book}.json"
        if not meta.exists():
            print(f"✗ 没有 meta：{meta}。照同目录 meta_vol03.json 改 volume 两项另存，或用 --meta 指定", file=sys.stderr)
            sys.exit(2)
        split = Path(args.split_table) if args.split_table else repo / "doc/formats/samples/guji_page_v0.2/split_table_siku.json"
        cmd = [sys.executable, str(scripts / "export_guji_format.py"), "--products", str(products_root()),
               "--book", book, "--chapter", chapter, "--meta", str(meta), "--out", str(out_dir),
               "--pages", ",".join(map(str, pages))]
        if split.exists():
            cmd += ["--split-table", str(split)]
    print("→ " + " ".join(cmd[1:]), file=sys.stderr)
    sys.exit(subprocess.run(cmd).returncode)


def cmd_fp_migrate(args) -> None:
    """路径参数出指纹后，把 manifest 的指纹改写成新公式（不重算产物；默认干跑）。
    见 `products/fp_migrate.py` 模块头。"""
    from .core.runlock import RunLockHeld, book_run_lock
    from .products.fp_migrate import migrate_book, parse_old_paths
    try:
        old = parse_old_paths(args.old_path)
    except ValueError as e:
        raise SystemExit(str(e))
    eng = _engine(args.book, args.pipeline, quiet=True)
    pages = eng.book.resolve_pages(args.pages)
    steps = [s for s in (args.steps or "").split(",") if s] or None
    try:
        with book_run_lock(eng.book.id, wait=False):
            if getattr(args, "code_formula", False) and (old or args.trust):
                raise ValueError("--code-formula 不与 --old-path / --trust 混用")
            rep = migrate_book(eng, pages, old_paths=old, trust=args.trust,
                               apply=args.apply, steps=steps, explain=getattr(args, 'explain', False),
                               code_formula=getattr(args, "code_formula", False))
    except (RunLockHeld, ValueError) as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(3)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False))
        return
    print(f"{eng.book.id} · {eng.pipeline.id if hasattr(eng.pipeline, 'id') else args.pipeline} · "
          f"{len(pages)} 页 · {'已写入' if args.apply else '干跑（加 --apply 才写）'}")
    from .products.fp_migrate import format_diff, rare_fingerprint_parts
    for sid, r in rep.items():
        if "na" in r:
            print(f"  {sid:16s} {r['na']}")
            if getattr(args, 'explain', False) and sid == "rare_candidates":
                print("      ↳ 指纹分量（★=可能随机器变）：")
                for part in rare_fingerprint_parts(eng):
                    print(f"        {'★' if part['machine'] else ' '} {part['name']}: {part['value']}"
                          + (f"  —— {part['note']}" if part.get("note") else ""))
            continue
        print(f"  {sid:16s} 改写 {r['migrated']:3d}  本来就新 {r['already']:3d}")
        for why, n in sorted(r["skipped"].items(), key=lambda kv: -kv[1]):
            print(f"      ↳ 跳过 {n:3d} 页：{why}")
        for pg, d in sorted(r.get("detail", {}).items()):
            print(f"        p{pg:04d} {d['why']}")
            for df in d["diffs"]:
                print(f"            · {format_diff(df)}")


def cmd_locate_gutter(args) -> None:
    """版心定位（给拆页用，#174）：输入原图，输出版心 x 与置信度。只定位、不裁图、不接管线。
    判据见 `seg/locate_gutter.py`（竖线复用 Step1 的 find_vertical_lines）。"""
    import cv2
    from .utils.image_io import imread
    from .seg.locate_gutter import locate_gutter
    gray = imread(args.image, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise SystemExit(f"读不了图：{args.image}")
    band = None
    if args.band:
        a, _, b = args.band.partition(",")
        band = (int(a), int(b))
    r = locate_gutter(gray, band=band, ink_threshold=args.ink_threshold)
    if args.json:
        print(json.dumps({"image": str(args.image), **r.to_dict()}, ensure_ascii=False, indent=2))
    elif r.x is None:
        print(f"✗ 没找到版心：{r.note}")
    else:
        print(f"版心 x={r.x:.1f}（{r.x_left:.1f}–{r.x_right:.1f}，宽 {r.x_right - r.x_left:.0f}）"
              f"  置信度 {r.confidence:.2f}  列距 {r.pitch:.0f}  竖线 {r.n_lines} 条"
              + (f"  ⚠ {r.note}" if r.note else ""))
        for c in r.candidates:
            print(f"  候选 {c.x_left:7.1f}–{c.x_right:7.1f}  居中 {c.central:.2f} × 空 {c.blank:.2f} = {c.score:.2f}")
    if r.x is None:
        sys.exit(1)


def cmd_split(args) -> None:
    """Step0 分页：按 book.yaml 的 page_split 段把扫描页裁成逻辑页，写进 raw_dir。

    一张扫描页装着多页原书（上下两栏拼一页）时用；逻辑页才是管线的「原图」。
    `--pages` 是**扫描页**号（不是逻辑页）。见 utils/page_split.py。
    """
    from .core.book import load_book
    from .utils.page_split import split_book

    book = load_book(args.book)
    pages = None
    if args.pages:
        pages = book.resolve_pages(args.pages)      # 只当页号表达式用；dev_set 之类的名字不适用
    recs = split_book(book, pages=pages, force=args.force)
    n_empty = sum(1 for r in recs if r.empty)
    print(f"分出 {len(recs)} 个逻辑页（其中空栏 {n_empty}），产物在 {book.raw_dir}")


def cmd_witness_align(args) -> None:
    """列级证人对齐：`line_is_column` 的整理本 → 逐字位候选标签（utils/witness_align.py）。

    影印页码与扫描页的对应由 `--first-page`（扫描页 1 对应的影印页码）给；不给则读
    book.yaml `references[0].first_page_no`。
    """
    from .core.book import load_book
    from .core.workspace import corpus_path, products_root
    from .utils.witness_align import align_book

    book = load_book(args.book)
    ref = (book.references or [{}])[0]
    first = args.first_page if args.first_page is not None else ref.get("first_page_no")
    if first is None:
        print("需要 --first-page（扫描页 1 对应的影印页码），或在 book.yaml references[0] 写 first_page_no")
        sys.exit(1)
    witness = Path(args.witness) if args.witness else corpus_path(ref["file"])
    stats = align_book(book, first_page_no=int(first), witness=witness, products_root=products_root())
    print(json.dumps(stats, ensure_ascii=False))


def cmd_witness_align_stream(args) -> None:
    """字流证人对齐：换行与刻本不同的证人（`line_is_column: false`）→ 逐字位标签
    （utils/witness_align_stream.py）。同书异版用这条，列级那条对不上。

    OCR 只当锚，标签一律取证人字；只收长度 ≥ `--min-block` 的 `equal` 块。
    """
    from .core.book import load_book
    from .core.workspace import corpus_path, products_root
    from .utils.witness_align_stream import align_stream, write_labels

    book = load_book(args.book)
    ref = (book.references or [{}])[0]
    witness = Path(args.witness) if args.witness else corpus_path(ref["file"])
    res = align_stream(book, witness=witness, products_root=products_root(),
                       min_block=args.min_block)
    out = products_root() / book.id / "witness_align" / "labels.jsonl"
    write_labels(res, out)
    blocks = sorted(res.blocks, reverse=True)
    stats = {
        "n_cells": res.n_cells, "n_witness": res.n_witness, "n_ocr": res.n_ocr,
        "n_equal": res.n_equal, "n_labeled": res.n_labeled,
        "coverage": round(res.n_labeled / max(1, res.n_cells), 4),
        "ocr_agree_at_labels": res.ocr_agree,
        "n_blocks": len(blocks), "longest_blocks": blocks[:10],
        "min_block": args.min_block,
    }
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    print(f"→ {out}")


def cmd_calibrate(args) -> None:
    """册级先验复核：把 `measure_*` 跑一遍，和 `books/<id>.yaml` 里的现值对照。

    **只印表，不改 yaml**（理由见 `books/siku_zongmu/calibrate.py` 模块头：自动回写会让一次
    坏标定悄悄固化，还容易冲掉人写的 note）。
    """
    from .core.book import load_book
    from .products.store import ProductStore
    from .books.siku_zongmu.calibrate import calibrate, format_table

    book = load_book(args.book)
    pages = book.resolve_pages(args.pages) if args.pages else None
    rows, diag = calibrate(book, ProductStore(), pages=pages,
                           with_bottom_gap=args.with_bottom_gap)
    print(format_table(rows, diag, book.id))
    if args.json:
        payload = {"book": book.id, "diag": diag,
                   "rows": [{"field": r.field, "current": r.current, "measured": r.measured,
                             "verdict": r.verdict, "drift_pct": r.drift_pct, "note": r.note}
                            for r in rows]}
        Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        print("")
        print("已写 " + str(args.json))


def cmd_survey(args) -> None:
    """Step0 页面预检：原图尺寸 → 按册中位数标异常页（任务卡 #54 第22条）。

    与跑管线是两条独立的路：这条命令**只读原图尺寸**，不需要先有任何产物，
    开新书第一件事就能跑；管线里的 `page_survey` Step 与 `border_detect_gate`
    的闸走的是同一份判据函数（`steps.page_survey.survey_book`），CLI 这里
    只是给人一份不用先跑管线就能看的清单。
    """
    from .core.book import load_book
    from .steps.page_survey import PageSurveyParams, survey_book

    book = load_book(args.book)
    pages = book.resolve_pages(args.pages) if args.pages else None
    ratio_high = args.ratio_high or PageSurveyParams().ratio_high
    ratio_low = args.ratio_low or PageSurveyParams().ratio_low
    rows = survey_book(book, pages, ratio_high, ratio_low)
    whitelist = (book.params.get("page_survey", {}) or {}).get("whitelist", {}) or {}
    whitelist = {int(k): v for k, v in whitelist.items()}
    odd = [r for r in rows if r.odd or r.p1_suspect]
    for r in odd:
        reason = (whitelist.get(r.page) or "").strip()
        tag = f"（白名单：{reason}）" if reason else ""
        if r.p1_suspect and not r.odd:
            print(f"p{r.page}：页1，未按尺寸判异常，人核对是否书脊/封面{tag}")
        else:
            print(f"p{r.page}：{r.kind}，{r.width}×{r.height}（册中位 "
                 f"{r.median_width:.0f}×{r.median_height:.0f}，宽{r.ratio_w:.2f}×/"
                 f"高{r.ratio_h:.2f}×）{tag}")
    print(f"共 {len(rows)} 页，{len(odd)} 页异常/待核（阈值 {ratio_low}~{ratio_high}）")
    if args.json:
        payload = {"book": book.id, "ratio_high": ratio_high, "ratio_low": ratio_low,
                   "n_pages": len(rows), "odd": [r.model_dump() for r in odd]}
        Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        print("已写 " + str(args.json))


def cmd_calibrate_font(args) -> None:
    """字体判定（三模式方案 §五.1）：拿 witness-align / 人裁的标签当查询，逐套字体量
    recall@1/@5 与可分性 margin（utils/font_calibrate.py）。字体字形先用
    `glyph-db import-font --manifest <工作区清单>` 导进工作区库。"""
    from .clustering.glyph_db import GlyphDB
    from .core.book import load_book
    from .core.workspace import cache_root, glyph_db_path, products_root
    from .utils.font_calibrate import format_table, load_labels, score_fonts

    book = load_book(args.book)
    labels_path = Path(args.labels) if args.labels else products_root() / book.id / "witness_align" / "labels.jsonl"
    labels = load_labels(labels_path, max_per_char=args.per_char, max_chars=args.max_chars)
    if args.manifest:
        # 直接比对（不经库）：字体按书的笔宽加粗后再比，见 utils/font_calibrate_direct.py
        from .clustering.font_glyphs import load_charset, load_manifest
        from .utils.font_calibrate_direct import score_fonts_direct
        specs, data = load_manifest(args.manifest)
        if args.editions:
            want = args.editions.split(",")
            specs = [sp for sp in specs if sp.edition_tag in want]
        charset = load_charset(args.charset or data["charset"])
        strokes = None
        if args.strokes:
            strokes = {kv.split("=")[0]: int(kv.split("=")[1]) for kv in args.strokes.split(",")}
        scores = score_fonts_direct(book.id, labels, cache_root(), specs, charset, k=args.k,
                                    strokes=strokes, match_stroke=not args.no_stroke_match,
                                    norm_stroke=args.norm_stroke)
    else:
        db = GlyphDB(glyph_db_path())
        try:
            editions = args.editions.split(",") if args.editions else [
                r[0] for r in db.conn.execute("SELECT DISTINCT edition_tag FROM sources WHERE kind='font' ORDER BY 1")]
            scores = score_fonts(db, book.id, labels, cache_root(), editions, k=args.k,
                                 exclude_self=args.exclude_self)
        finally:
            db.close()
    print(format_table(scores))
    if args.json:
        Path(args.json).write_text(json.dumps([s.__dict__ for s in scores], ensure_ascii=False, indent=1),
                                   encoding="utf-8")
        print(f"→ {args.json}")


def cmd_seed_witness(args) -> None:
    """从证人标签播种字形库（utils/seed_witness.py）：证人字 × 字体 top-1 一致才进
    `modern:<book>`。先跑 witness-align 与 glyph-db import-font。"""
    from .clustering.glyph_db import GlyphDB
    from .core.book import load_book
    from .core.workspace import cache_root, glyph_db_path, products_root
    from .utils.seed_witness import seed_from_witness

    book = load_book(args.book)
    # 不显式传就用册配置的（与 Step5-a 读同一个字段）——两边必须同一把尺子，
    # 否则库被一把尺子筛、又被另一把尺子查，等于白播。
    if args.norm_stroke is None and getattr(book, "norm_stroke", None):
        args.norm_stroke = int(book.norm_stroke)
        print(f"[seed] --norm-stroke 取册配置 {args.norm_stroke}")
    labels_path = Path(args.labels) if args.labels else products_root() / book.id / "witness_align" / "labels.jsonl"
    db = GlyphDB(glyph_db_path())
    try:
        stats = seed_from_witness(db, book, labels_path=labels_path, cache_root=cache_root(),
                                  font_editions=args.fonts.split(","), edition_tag=args.edition,
                                  limit=args.limit, products_root=products_root(),
                                  norm_stroke=args.norm_stroke, jobs=args.jobs,
                                  only_chars=args.only_chars, source_kind=args.source_kind,
                                  binarize=not args.keep_gray)
    finally:
        db.close()
    out = products_root() / book.id / "witness_align" / "seed_stats.json"
    out.write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.items() if k != "reject_samples"}, ensure_ascii=False))
    print(f"→ {out}")


def _pdf_embedded_image(doc, pg):
    """扫描页里那张**唯一的内嵌图**的 (xref, 宽, 高)；不是「一页一张图」就返回 None。

    扫描 PDF 的正常形态是一页一张整版位图。有多张（或没有）的页多半是矢量/文字页
    或拼贴页，只能走渲染。
    """
    try:
        imgs = pg.get_images(full=True)
    except Exception:
        return None
    if len(imgs) != 1:
        return None
    xref = imgs[0][0]
    try:
        info = doc.extract_image(xref)
    except Exception:
        return None
    return xref, info.get("width", 0), info.get("height", 0)


def _salvage_jpx(raw: bytes) -> bytes:
    """JPEG2000 末 tile 残缺时的抢救：在最后一个 SOT 处截断、补 EOC。

    国图北行日錄刻本实测：某页 25 个 tile-part 的最后一个数据不全，**MuPDF 渲染
    出一张全白图并且 exit 0**（静默坏页），OpenCV 报 `Stream too short`。丢掉残缺
    的那个 tile 就能解出其余的——丢的那块通常只占页面一小角。
    """
    sots: list[int] = []
    i = 0
    while i < len(raw) - 1:
        if raw[i] == 0xFF and raw[i + 1] == 0x90:          # SOT
            lsot = int.from_bytes(raw[i + 2:i + 4], "big")
            sots.append(i)
            i += 2 + max(lsot, 2)
            continue
        i += 1
    if not sots:
        return raw
    return raw[:sots[-1]] + b"\xff\xd9"


def _warn_downscale(problems: list, page_no: int, pg, got, dpi) -> None:
    """渲染出来比内嵌图小很多时告警——这是「静默降分辨率」那个坑的正面拦截。"""
    if got is None or not got[1]:
        return
    pr = pg.rect
    if not pr.width:
        return
    eff = (dpi / 72.0) if dpi else 1.0
    ratio = got[1] / (float(pr.width) * eff)
    if ratio > 1.2:
        problems.append(
            f"页 {page_no}：**渲染结果比内嵌图小 {ratio:.2f} 倍**"
            f"（页框 {pr.width:.0f}×{pr.height:.0f} pt vs 内嵌图 {got[1]}×{got[2]} px）"
            f"——分辨率丢了，改用 --mode embedded，或 --dpi {int(round(72 * ratio * eff))}")


def cmd_import_pdf(args) -> None:
    """把 PDF 逐页抽成灰度 PNG（`<out>/<页号>.png`，从 1 起）。

    ## 默认取**内嵌图**，不是渲染

    扫描 PDF 的页框尺寸（pt）**不一定**等于内嵌图像的像素数。北行日錄刻本那两个
    PDF 页框 672×562 pt、内嵌图 2801×2343 px——按页框 1:1 渲染只有原生分辨率的
    1/4.17，字身从 71px 缩到 17px，Step3 根本没法切，而且 exit 0 不报任何警告。

    所以默认路径是 `extract_image` 取内嵌码流（`--mode embedded`，缺省）：
    一页一张图时直接拿原始像素，拿不到才退回渲染并**明确告知**。
    `--mode render` 强制渲染（矢量/文字 PDF、或内嵌图是分块拼的）；给了 `--dpi`
    即隐含 render。

    ## 每页都体检

    抽完逐页报「尺寸异常 / 近乎全白全黑」——**静默坏页是最难发现的一类坏数据**，
    全白页会一路往下跑，到 Step3 才莫名其妙零列。见 `_salvage_jpx`。
    """
    from pathlib import Path
    import numpy as np
    import pymupdf
    from .utils.image_io import imwrite

    doc = pymupdf.open(args.pdf)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sel = None
    if args.pages:
        sel = set()
        for part in args.pages.split(","):
            a, _, b = part.partition("-")
            sel.update(range(int(a), int(b or a) + 1))

    mode = args.mode
    if args.dpi and mode == "embedded":
        mode = "render"                      # 显式给了 dpi 就是要渲染

    def _render(pg) -> np.ndarray:
        if args.dpi:
            pix = pg.get_pixmap(dpi=args.dpi, colorspace=pymupdf.csGRAY)
        else:
            pix = pg.get_pixmap(matrix=pymupdf.Matrix(1, 1), colorspace=pymupdf.csGRAY)
        return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)

    n = n_skip = 0
    n_embedded = n_render = n_salvaged = 0
    problems: list[str] = []
    tmp = out / "_import_tmp.bin"

    for i in range(len(doc)):
        page_no = i + 1
        if sel is not None and page_no not in sel:
            continue
        target = out / f"{page_no}.png"
        if target.exists() and not args.force:
            n_skip += 1
            continue
        pg = doc[i]
        img = None

        if mode == "embedded":
            got = _pdf_embedded_image(doc, pg)
            if got is not None:
                xref, iw, ih = got
                import cv2
                raw = doc.extract_image(xref)["image"]
                tmp.write_bytes(raw)
                img = cv_imread(str(tmp), cv2.IMREAD_UNCHANGED)
                if img is None:                      # 码流坏了，试抢救
                    tmp.write_bytes(_salvage_jpx(raw))
                    img = cv_imread(str(tmp), cv2.IMREAD_UNCHANGED)
                    if img is not None:
                        n_salvaged += 1
                        problems.append(f"页 {page_no}：内嵌码流残缺，已截断末 tile 抢救"
                                        f"（丢失部分通常在页面一角，**务必目视核对**）")
                if img is not None:
                    if img.ndim == 3:
                        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                    n_embedded += 1
                else:
                    problems.append(f"页 {page_no}：内嵌图解不开（抢救也失败），退回渲染")
            if img is None:
                img = _render(pg)
                n_render += 1
                _warn_downscale(problems, page_no, pg, got, args.dpi)
        else:
            img = _render(pg)
            n_render += 1
            _warn_downscale(problems, page_no, pg,
                            _pdf_embedded_image(doc, pg), args.dpi)

        if img is None:
            problems.append(f"页 {page_no}：抽不出图，已跳过")
            continue

        ink = float((img < 192).mean())
        if ink < 0.002:
            problems.append(f"页 {page_no}：**近乎全白**（墨占比 {ink:.4f}）——疑似坏页或空页")
        elif ink > 0.98:
            problems.append(f"页 {page_no}：近乎全黑（墨占比 {ink:.4f}）——疑似扫描背面或封面")
        imwrite(str(target), img)
        n += 1

    tmp.unlink(missing_ok=True)

    sizes: dict[tuple[int, int], int] = {}
    for f in out.glob("*.png"):
        try:
            import cv2
            im = cv_imread(str(f), cv2.IMREAD_UNCHANGED)
            if im is not None:
                sizes[(im.shape[1], im.shape[0])] = sizes.get((im.shape[1], im.shape[0]), 0) + 1
        except Exception:
            pass

    print(f"抽出 {n} 页（内嵌 {n_embedded} / 渲染 {n_render}"
          f"{f' / 抢救 {n_salvaged}' if n_salvaged else ''}），"
          f"跳过 {n_skip} 页 → {out}（PDF 共 {len(doc)} 页）")
    if len(sizes) > 1:
        top = sorted(sizes.items(), key=lambda kv: -kv[1])
        print("  ⚠️ 尺寸不一致：" + "；".join(f"{w}×{h} × {c} 页" for (w, h), c in top[:4]))
    for p in problems:
        print("  ⚠️ " + p)


def cmd_binarize(args) -> None:
    """整页二值副本：灰度扫描 → `binarized/<book>/<page>.png`（白底黑字）。

    进字形库的图一定是二值的（用户 2026-09-16），审阅时看二值的也更准。
    这条把二值化统一到**页级**做一次落盘，而不是每个消费点各二值各的。
    默认 Sauvola 31/0.2 —— 固定阈 128 会砍掉一半界行，见 `utils/binarized.py`。
    """
    from .core.book import load_book
    from .utils.binarized import binarized_root, build_binarized

    book = load_book(args.book)
    pages = book.resolve_pages(args.pages) if args.pages else book.all_pages()
    written = build_binarized(book, pages, force=args.force,
                              window=args.window, k=args.k)
    print(json.dumps({"book": book.id, "pages": len(pages), "written": len(written),
                      "dir": str(binarized_root() / book.id),
                      "window": args.window, "k": args.k}, ensure_ascii=False))


def cmd_preclean(args) -> None:
    """Step0：按 book.yaml 的 preclean 段生成修好的页图，落在 precleaned/<book>/。

    只处理登记过的页；其余页碰都不碰。生成后 Step1 起自动读修好的那张。
    `--calibrate` 是另一条路：不生成产物，在没登记 preclean 的「正常页」上量
    正文本底的墨占比分布（中位/p95/p99），换书时用它重新标 `utils/preclean.py`
    里的 `BODY_INK_GATE` 等常量。
    """
    from .core.book import load_book

    book = load_book(args.book)
    rules = getattr(book, "preclean", {}) or {}

    if getattr(args, "calibrate", False):
        import numpy as np
        from .utils.preclean import BODY_INK_GATE, sample_body_baseline

        pages = book.resolve_pages(args.pages) if args.pages else book.all_pages()
        normal_pages = [p for p in pages if p not in rules]
        skipped = sorted(set(pages) - set(normal_pages))
        if skipped:
            print(f"跳过已登记 preclean 的页（本来就不是「正常页」）: {skipped}")
        ratios = sample_body_baseline(book, normal_pages)
        if ratios.size == 0:
            print("没量到任何窗口——检查 --pages 是不是给对了")
            return
        med, p95, p99 = np.percentile(ratios, [50, 95, 99])
        over = int((ratios > BODY_INK_GATE).sum())
        print(f"{book.id} 本底标定：{len(normal_pages)} 个正常页，{len(ratios)} 个窗口")
        print(f"  中位 {med:.3f} / p95 {p95:.3f} / p99 {p99:.3f} / 最大 {ratios.max():.3f}")
        print(f"  当前闸阈 BODY_INK_GATE={BODY_INK_GATE:.3f}："
              f"{over}/{len(ratios)}（{over / len(ratios):.2%}）个正常窗口会被误拦")
        return

    from .utils.preclean import build_precleaned, precleaned_root

    if not rules:
        print(f"{book.id} 没登记任何预清理页（books/{book.id}.yaml 的 preclean 段是空的）")
        return
    pages = book.resolve_pages(args.pages) if args.pages else None
    print(f"{book.id} 登记的预清理页: {sorted(rules)}")
    written = build_precleaned(book, pages, force=args.force)
    print(f"写出 {len(written)} 页 -> {precleaned_root() / book.id}")


# ── C5：把控制台能干的事开到命令行 ────────────────────────────────────
#
# 控制台重构方案 §二 实测出来的那个数字：**本地专属面积 = 0/46**。46 条路由
# 在无 HTTP、无浏览器、无 GPU、无人在场的云端各真调了一次，45 条跑通，唯一
# 失败那条是缺数据不是耦合。也就是说「控制台现在能干的事，云端道现在就能干，
# 只差一层 CLI 出口」——下面这几个子命令就是那层出口。
#
# 纪律：**每个命令与对应路由调的是同一个领域函数**，不另写一份。
# 「同参同输出」是 C5 的验收判据（tests/test_console_routes.py::test_cli_matches_routes
# 逐条比对 CLI 的 JSON 与路由的返回值）。


def _out(d) -> None:
    """统一出 JSON。管道接 jq 用。"""
    print(json.dumps(d, ensure_ascii=False, indent=1, default=str))


def cmd_rare(args) -> None:
    """生僻字候选：单查一个字位，或 `--slots` 批量。

    引擎在 `clustering/rare_panel.py`，与控制台同一份。**不需要 GPU**
    （CNN checkpoint 走 CPU 前向）。⚠️ 首次要建字体索引，方案 §十一·4 实测
    112 秒，之后 0.1 秒——别当它挂了。
    """
    from .clustering.rare_panel import ids_fallback, rare_batch, rare_for, rare_patch

    if args.top or args.slot_comp or args.comp:
        # IDS 兜底：`rare vol01 --top ⿰ --slot-comp L=言 --comp 俞 [page col slot]`
        slots = dict(x.split("=", 1) for x in args.slot_comp)
        img = rare_patch(args.book, args.page, args.col, args.slot, args.sub) if args.page else None
        _out({"query": {"top": args.top, "slots": slots, "components": args.comp},
              "with_image": img is not None,
              "candidates": ids_fallback(args.top, slots, args.comp, img, args.k, args.book)})
        return
    if args.slots:
        _out(rare_batch(args.book, [x.strip() for x in args.slots.split(",") if x.strip()], args.k))
        return
    img = rare_patch(args.book, args.page, args.col, args.slot, args.sub)
    if img is None:
        print(f"没有字块 p{args.page:04d}c{args.col:02d}s{args.slot}{args.sub or ''}")
        sys.exit(1)
    _out({"id": f"{args.book}:{args.page}:{args.col}:{args.slot}{args.sub or ''}",
          "candidates": rare_for(img, args.k)})


def cmd_variants(args) -> None:
    """本书用字账（只读）。账本由 `scripts/build_book_variants.py` 派生，这里不算任何东西。"""
    from .variant_ledger import DEFAULT_EDITION, ledger_path
    p = ledger_path(args.edition or DEFAULT_EDITION)
    if not p.exists():
        print(f"没有用字账 {p.name}——先跑 python scripts/build_book_variants.py "
              f"--edition {args.edition or DEFAULT_EDITION}")
        sys.exit(1)
    _out(json.loads(p.read_text(encoding="utf-8")))


def cmd_snapshot(args) -> None:
    """把一本书若干步的产物冻结成快照，供下游用 GUJI_PRODUCTS_DIR 读（并行分工 §三·2）。"""
    from .core.runlock import make_snapshot, snapshots_root, RunLockHeld
    if args.action == "list":
        root = snapshots_root() / args.book
        for d in sorted(root.iterdir()) if root.is_dir() else []:
            meta = d / "SNAPSHOT.json"
            info = json.loads(meta.read_text(encoding="utf-8")) if meta.is_file() else {}
            print(f"{d}  steps={','.join(info.get('steps', []))}  rev={info.get('code_rev')}  {info.get('created', '')}")
        return
    steps = [s for s in (args.steps or "").split(",") if s] or None
    try:
        out = make_snapshot(args.book, steps, args.name)
    except RunLockHeld as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(3)
    print(f"快照：{out}")
    print(f"下游这样读：GUJI_PRODUCTS_DIR='{out}'")


def cmd_version(args) -> None:
    """装着的 pipeline 版本与契约版本（manager 用它核兼容；`--json` 是契约的一部分，见 doc/契约.md）。"""
    from .api import version_info
    info = version_info()
    if getattr(args, "json", False):
        print(json.dumps(info, ensure_ascii=False))
    else:
        print(f"cv {info['cv_version']}（commit {info['cv_commit'] or '—'}），契约 v{info['contract_version']}，{len(info['steps'])} 个 Step")


COMMANDS_V2 = {
    "version": cmd_version,
    "preclean": cmd_preclean,
    "binarize": cmd_binarize,
    "split": cmd_split,
    "locate-gutter": cmd_locate_gutter,
    "import-pdf": cmd_import_pdf,
    "witness-align": cmd_witness_align,
    "witness-align-stream": cmd_witness_align_stream,
    "calibrate": cmd_calibrate,
    "survey": cmd_survey,
    "calibrate-font": cmd_calibrate_font,
    "seed-witness": cmd_seed_witness,
    "pipeline": cmd_pipeline,
    "step": cmd_step,
    "status": cmd_status,
    "book": cmd_book,
    "export": cmd_export,
    "fp-migrate": cmd_fp_migrate,
    "rare": cmd_rare,
    "variants": cmd_variants,
    "snapshot": cmd_snapshot,
}


WORKSPACE_HELP = ("工作区仓根（含 books/<book>.yaml、products/、cache/、output/）。**必填**——"
                  "凡带 book 的命令都不再读 GUJI_WORKSPACE 环境变量兜底：那个变量漏设/设错都不报错，"
                  "产物会静默写到别的工作区（2026-09-19 一天里两次栽在这上面）。")


def _needs_workspace(sp: argparse.ArgumentParser) -> bool:
    return any(a.dest == "book" for a in sp._actions)


#: `status`／`collate` 只读、不写产物——认 `GUJI_WORKSPACE` 兜底顶多让人看错报告，
#: 不会像 `pipeline`/`step` 那样把真产物静默写进错的工作区，所以任务卡 #54 第10条
#: 单给这两条开例外，其余命令仍照 2026-09-19 定的规矩必须显式 `-w`。
ENV_FALLBACK_COMMANDS = {"status", "collate", "pagekinds"}


def resolve_workspace(args, parser: argparse.ArgumentParser, command: str = "") -> Path | None:
    """带 book 的命令：`--workspace` 必填、必须存在、必须有这册书的定义；解析结果写进
    `GUJI_WORKSPACE` 供下游（`core.workspace.workspace_root` 及其之下一切）使用。

    环境变量若已设且指向别处，以 `--workspace` 为准并提示——环境变量常是上一本书留下的。
    `command` 在 `ENV_FALLBACK_COMMANDS` 里时，缺 `-w` 改成读 `GUJI_WORKSPACE`，不报错
    （仍然打印在用哪个工作区，不悄悄用）。
    """
    if not hasattr(args, "book"):
        return None
    import os
    ws = getattr(args, "workspace", None)
    if not args.book:
        # 可选的 `--book` 没给（`cache usage|prune|build-font-index`、`batch list`）：没有书可校验，
        # 给了 -w 就只查目录在不在并导出，不给就不碰工作区。原先照「带 book 的命令」一律要
        # `-w` 且要 `books/.yaml`，`guji cache build-font-index` 不带 --book 怎么都跑不起来（overview#246）。
        if not ws:
            return None
        root = Path(ws).expanduser().resolve()
        if not root.is_dir():
            parser.error(f"--workspace {root} 不存在")
        os.environ["GUJI_WORKSPACE"] = str(root)
        print(f"  工作区 {root}（未指定册）", file=sys.stderr)
        return root
    if not ws and command in ENV_FALLBACK_COMMANDS:
        ws = os.environ.get("GUJI_WORKSPACE")
        if ws:
            print(f"  未给 -w，退回 GUJI_WORKSPACE={ws}", file=sys.stderr)
    if not ws:
        parser.error("缺 -w/--workspace：跑真书必须显式给工作区，例如 "
                     f"`-w D:/workspace/<book>-workspace`（books/{args.book}.yaml 所在的仓根）。"
                     "不再读 GUJI_WORKSPACE 兜底。")
    root = Path(ws).expanduser().resolve()
    from .core.workspace import books_dir
    spec = books_dir(root) / f"{args.book}.yaml"
    if not spec.exists():
        parser.error(f"--workspace {root} 下没有 books/{args.book}.yaml——路径给错了，或这不是「{args.book}」的工作区")
    env = os.environ.get("GUJI_WORKSPACE")
    if env and Path(env).expanduser().resolve() != root:
        print(f"  ⚠️  GUJI_WORKSPACE={env} 与 --workspace 不同，以 --workspace 为准", file=sys.stderr)
    os.environ["GUJI_WORKSPACE"] = str(root)
    print(f"  工作区 {root}  册 {args.book}", file=sys.stderr)
    return root


def _with_workspace(handler, sp: argparse.ArgumentParser, name: str = ""):
    def run(args):
        resolve_workspace(args, sp, command=name)
        return handler(args)
    run._workspace_wrapped = True     # type: ignore[attr-defined]
    run.__wrapped__ = handler         # type: ignore[attr-defined]
    return run


def install_workspace_option(sub: argparse._SubParsersAction) -> None:
    """给每个带 book 的子命令加 `-w/--workspace`（必填，见 WORKSPACE_HELP），并把它的
    处理函数包一层做校验。`register_subcommands` 末尾调用；两个入口（`guji` 与
    `python -m open_guji_cv`）都经这里，幂等。"""
    for name, sp in sub.choices.items():
        handler = COMMANDS_V2.get(name)
        if handler is None or not _needs_workspace(sp):
            continue
        # 参数每次都要加（每次调用建的是新的 parser 对象）；处理函数只包一层
        help_ = WORKSPACE_HELP
        if name in ENV_FALLBACK_COMMANDS:
            help_ += "（这条命令例外：不给也认 GUJI_WORKSPACE，只读不写产物，risk 小）"
        sp.add_argument("-w", "--workspace", default=None, help=help_)
        if not getattr(handler, "_workspace_wrapped", False):
            COMMANDS_V2[name] = _with_workspace(handler, sp, name=name)


# ── parsers ──────────────────────────────────────────────────────────
def _add_override(p: argparse.ArgumentParser) -> None:
    p.add_argument("--override", default=None, metavar="JSON",
                   help='运行覆盖：一段册配置片段（内存里叠在册 yaml 上，不改任何文件、不推库），如 '
                        '{"corpus": 23, "params": {"seed_admit": {"shadow_veto": false}}}；'
                        "生效值记进产物 manifest。详见 doc/design/册配置分层与运行覆盖.md")


def _add_pages(p: argparse.ArgumentParser) -> None:
    import os
    p.add_argument("--pages", default="dev_set",
                   help="dev_set（默认）| all | 3-6,9 之类的页号表达式")
    p.add_argument("--force", action="store_true", help="无视指纹，强制重跑")
    p.add_argument("--stop-on-error", action="store_true", help="一页失败就停")
    p.add_argument("--params", default=None, help='参数覆盖 JSON，如 {"column_gate": {"width_tol": 0.2}}')
    _add_override(p)
    p.add_argument("--json", action="store_true", help="结束时打印 JSON 报告")
    p.add_argument("--wait", action="store_true",
                   help="这本书正有别的跑批在写时排队等它跑完（默认直接报持有者并退出，退出码 3）")
    p.add_argument("--jobs", type=int, default=os.cpu_count() or 1,
                   help="页级并行进程数（默认=本机 CPU 数）。只对声明过 "
                        "`StepSpec.parallel_safe=True` 的 Step 生效，其余 Step 仍串行，"
                        "混跑一条 pipeline 时不用分开调。别超过 CPU 数——超订只会更慢，"
                        "有一次性初始化（模型/字形库）的 Step 并行时这部分开销按进程数摊，"
                        "不是按页摊，进程数越多单个 worker 越快建好摊得越薄，但仍不该超核数")
    p.add_argument("--isolate-steps", action=argparse.BooleanOptionalAction, default=None,
                   help="每个 Step 一个独立子进程跑：跑完进程退出、内存整体回收，免得 torch／字形库／索引／"
                        "语言模型逐步叠在一个进程里（GUJI-555；殿本 vol06 单进程连跑到 seed_admit 主进程 3.5 GB）。"
                        "2026-10-20 起 `guji pipeline` 跑多于一步、不要 --json 时缺省就隔离（GUJI-647），"
                        "代价是每步多付一次 import 与模型加载；--no-isolate-steps 退回单进程连跑。不支持 --json")
    p.add_argument("--allow-cv-mismatch", action="store_true",
                   help="册配置固定的 cv_version 与装的版本不同时仍然跑（默认拒跑，退出码 2；GUJI-577），"
                        "须同时给 --why。做实验优先在中心库实验分支上跑（GUJI_DATA_BRANCH=exp/*，自动放行、产物隔离）；"
                        "产物 manifest 照实记装的版本和理由（cv_override）")
    p.add_argument("--why", default=None,
                   help="配 --allow-cv-mismatch：为什么要用非钉定版本在这里跑，记进每条产物 manifest 的 cv_override")
    p.add_argument("--allow-missing-deps", action="store_true",
                   help="这次要跑的步骤本机缺依赖（torch／权重／shadow_veto 要的 joblib）时仍然跑（默认拒跑，退出码 2；GUJI-654）。"
                        "缺的东西会让 Step 悄悄退回旧办法或整页失败，只在明知后果时加")
    p.add_argument("--allow-sample-db", action="store_true",
                   help="没设 GUJI_WORKSPACE 时，显式声明「就是要用仓内那份几百条的示例库」再跑"
                        "（不加这个、又没设 GUJI_WORKSPACE，直接报错——2026-09-09 吃过亏：漏设变量"
                        "对着示例库跑了一批，产物 status:ok 但库匹配全错，锚不上整理本）")


PLUGIN_GROUP = "guji.commands"


#: 由插件（而非 cv 自带）登记进 COMMANDS_V2 的命令名
_PLUGIN_ADDED: set[str] = set()


def load_plugin_commands(sub: argparse._SubParsersAction) -> list[str]:
    """装了 guji-manager（或别的插件）时，把它提供的子命令并进 `guji`（拆分 M4，doc/design/拆分-pipeline与manager.md）。

    入口点组 `guji.commands`，每个入口点指向一个有 `COMMANDS: dict[str, (add_parser, handler)]` 的模块，
    `add_parser(sub)` 往 `sub` 上登记子命令，`handler(args)` 执行。**本仓自带的同名命令优先**（过渡期同一条命令
    两边都有时，不重复登记、不覆盖）；插件加载失败只提示，不影响 `guji` 本身。返回新并进来的命令名。"""
    from importlib.metadata import entry_points
    added: list[str] = []
    try:
        eps = entry_points(group=PLUGIN_GROUP)
    except Exception:  # noqa: BLE001
        return added
    for ep in eps:
        try:
            module = ep.load()
            commands = module.COMMANDS
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ 插件 {ep.name} 加载失败（{type(e).__name__}: {e}），略过", file=sys.stderr)
            continue
        called = set()    # 几条命令共用一个 add_parser 时只调一次；任一条 cv 自带就整个 add_parser 让给 cv
        for name, (add_parser, handler) in commands.items():
            # COMMANDS_V2 里上回由插件登记的不算 cv 自带（同一进程多次建 parser 时，如测试、控制台）
            if (name in COMMANDS_V2 and name not in _PLUGIN_ADDED) or _plugin_too_old(module, name):
                continue
            if add_parser not in called:
                if any(n in sub.choices for n, (ap, _) in commands.items() if ap is add_parser):
                    continue
                add_parser(sub)
                called.add(add_parser)
            COMMANDS_V2[name] = handler
            _PLUGIN_ADDED.add(name)
            added.append(name)
    return added


#: 已搬去 guji-manager 的子命令（拆分 P2–P5，每批 cv 删除 PR 里登记）。没装 manager 时 `guji <它>` 给出装法，
#: 而不是 argparse 的 invalid choice。只许增不许删（老脚本、老文档还会这么调）。
MOVED_TO_MANAGER: dict[str, str] = {
    "opinions": "拆分 P2，2026-11-02；意见池 M11",
    "source": "拆分 P2 第二批，2026-11-02；原图 R2",
    "cellvotes": "拆分 P2 第二批，2026-11-02；网站格级投票",
    "freeze": "拆分 P2 第二批，2026-11-02；冻结登记",
    "exp": "拆分 P2 第三批，2026-11-04",
    "snap": "拆分 P2 第三批，2026-11-04",
    "archive": "拆分 P2 第三批，2026-11-04",
    "release": "拆分 P2 第三批，2026-11-04",
    "deploy": "拆分 P2 第三批，2026-11-04",
    "events": "拆分 P2 第三批，2026-11-04",
    "gold": "拆分 P2 第三批，2026-11-04",
    "batch": "拆分 P2 第三批，2026-11-04",
    "label-batch": "拆分 P2 第三批，2026-11-04",
    "eval": "拆分 P2 第三批，2026-11-04",
    "check": "拆分 P2 第三批，2026-11-04",
    "groups": "拆分 P2 第三批，2026-11-04",
    "cards": "拆分 P2 第三批，2026-11-04",
    "progress": "拆分 P2 第三批，2026-11-04",
    "collate": "拆分 P2 第三批，2026-11-04",
    "close-check": "拆分 P2 第四批，2026-11-04",
    "exit-check": "拆分 P2 第四批，2026-11-04",
    "audit": "拆分 P2 第四批，2026-11-04",
    "char-diff": "拆分 P2 第四批，2026-11-04",
    "db": "拆分 P2 第四批，2026-11-04",
    "store": "拆分 P2 第四批，2026-11-04",
    "recheck": "拆分 P2 第四批，2026-11-04",
    "glyphlib": "拆分 P2 第四批，2026-11-04",
    "rekey-cells": "拆分 P2 第四批，2026-11-04",
    "promote": "拆分 P2 第四批，2026-11-04",
    "corpus": "拆分 P2 第四批，2026-11-04",
    "glyph-db": "拆分 P2 第四批，2026-11-04",
    "model": "拆分 P2 第四批，2026-11-04",
    "font": "拆分 P2 第四批，2026-11-04",
    "job": "拆分 P3 jobs，2026-11-04",
    "rerun": "拆分 P4 第六批，2026-11-04",
    "pagekinds": "拆分 P4 第六批，2026-11-04",
    "cache": "拆分 P4 第六批，2026-11-04",
    "product": "拆分 P4 第六批，2026-11-04",
    "products": "拆分 P4 第六批，2026-11-04",
    "perf": "拆分 P4 第六批，2026-11-04",
}
#: 搬走的命令要 guji-manager 至少哪一版（`guji_manager.__version__`）。旧版 manager 里可能留着早先复制的过期副本
#: （如云端快照 10-27 的种子带着当时的 opinions），版本不够就不认它的这条命令、提示更新，免得悄悄跑旧逻辑。
MIN_MANAGER_VERSION: dict[str, str] = {
    "opinions": "0.1.0",
    "source": "0.2.0",
    "cellvotes": "0.2.0",
    "freeze": "0.2.0",
    "exp": "0.3.0",
    "snap": "0.3.0",
    "archive": "0.3.0",
    "release": "0.3.0",
    "deploy": "0.3.0",
    "events": "0.3.0",
    "gold": "0.3.0",
    "batch": "0.3.0",
    "label-batch": "0.3.0",
    "eval": "0.3.0",
    "check": "0.3.0",
    "groups": "0.3.0",
    "cards": "0.3.0",
    "progress": "0.3.0",
    "collate": "0.3.0",
    "close-check": "0.3.1",
    "exit-check": "0.3.1",
    "audit": "0.3.1",
    "char-diff": "0.3.1",
    "db": "0.3.1",
    "store": "0.3.1",
    "recheck": "0.3.1",
    "glyphlib": "0.3.1",
    "rekey-cells": "0.3.1",
    "promote": "0.3.1",
    "corpus": "0.3.1",
    "glyph-db": "0.3.1",
    "model": "0.3.1",
    "font": "0.3.1",
    "job": "0.3.2",
    "rerun": "0.3.3",
    "pagekinds": "0.3.3",
    "cache": "0.3.3",
    "product": "0.3.3",
    "products": "0.3.3",
    "perf": "0.3.3",
}

MANAGER_INSTALL_HINT = ("git clone --depth 1 https://github.com/open-guji/guji-manager <目录> && "
                        "pip install --no-deps -e <目录>（云端：uv pip install --python /opt/guji-venv/bin/python …）")


def moved_command_hint(argv: list[str], registered) -> str | None:
    """`guji <已搬走的命令>` 而本机没装 manager（命令没登记上）→ 提示文字；否则 None。"""
    cmd = next((a for a in argv if not a.startswith("-")), None)
    if cmd is None or cmd in registered or cmd not in MOVED_TO_MANAGER:
        return None
    need = MIN_MANAGER_VERSION.get(cmd)
    return (f"`guji {cmd}` 已搬到 guji-manager（{MOVED_TO_MANAGER[cmd]}），本机没装"
            + (f"或版本低于 {need}（已装的就在它的目录 git pull 到 main）" if need else "")
            + f"。装法：{MANAGER_INSTALL_HINT}；装好后命令不变。")


def _version_tuple(v: str) -> tuple[int, ...]:
    import re
    return tuple(int(x) for x in re.findall(r"\d+", v.split("+")[0])[:3])


def _plugin_too_old(module, name: str) -> bool:
    """插件提供的这条命令要求的 manager 版本（MIN_MANAGER_VERSION）够不够；不够就当没装。"""
    need = MIN_MANAGER_VERSION.get(name)
    if not need:
        return False
    import importlib
    try:
        have = getattr(importlib.import_module(module.__name__.split(".")[0]), "__version__", "0")
    except Exception:  # noqa: BLE001
        have = "0"
    return _version_tuple(have) < _version_tuple(need)


def register_subcommands(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("pipeline", help="[v2] 跑一条 pipeline（或其中一段）")
    p.add_argument("pipeline", help=f"pipeline id，如 {DEFAULT_PIPELINE}")
    p.add_argument("book", help="books/<id>.yaml 里的书 id")
    p.add_argument("--from", dest="from_step", default=None, help="起始步骤 id")
    p.add_argument("--to", dest="to_step", default=None, help="终止步骤 id（含）")
    p.add_argument("--no-prep", action="store_true",
                   help="不在开跑前备输入（建钉版字形库、备 Step5-b 模板索引）；由 manager 先 prep（拆分 M2，doc/契约.md）")
    p.add_argument("--no-pack", action="store_true",
                   help="整册（--pages all）从头跑到尾时缺省自动把产物打包存 R2；加这个不存（也可 GUJI_AUTO_PACK=0）")
    _add_pages(p)

    p = sub.add_parser("step", help="[v2] 只跑一步")
    p.add_argument("step", help="步骤 id")
    p.add_argument("book")
    p.add_argument("--pipeline", default=DEFAULT_PIPELINE)
    p.add_argument("--no-prep", action="store_true", help="不在开跑前备输入（同 pipeline 的 --no-prep）")
    _add_pages(p)


    p = sub.add_parser("binarize",
                       help="[v2] 整页二值副本 → binarized/<book>/（进库与人裁看的都是它）")
    p.add_argument("book", help="books/<id>.yaml 里的书 id")
    p.add_argument("--pages", default=None, help="只做这些页（默认全书）")
    p.add_argument("--force", action="store_true", help="已有也重做")
    from .clustering.normalize import SAUVOLA_K, SAUVOLA_WINDOW
    p.add_argument("--window", type=int, default=SAUVOLA_WINDOW,
                   help=f"Sauvola 窗口（默认 {SAUVOLA_WINDOW}，与 normalize_patch 同一组常数）")
    p.add_argument("--k", type=float, default=SAUVOLA_K,
                   help=f"Sauvola k（默认 {SAUVOLA_K}，与 normalize_patch 同一把尺子；"
                        "旧版这里写死 0.2，是常数改成 0.10 时漏改的）")

    p = sub.add_parser("preclean",
                       help="[v2] Step0：生成预清理后的页图（只处理 yaml 里登记的页）")
    p.add_argument("book", help="books/<id>.yaml 里的书 id")
    p.add_argument("--pages", default=None,
                   help="只做这些页（默认：不带 --calibrate 时是 yaml 里登记的全部，"
                        "带 --calibrate 时是全书）")
    p.add_argument("--force", action="store_true", help="已有产物也重做")
    p.add_argument("--calibrate", action="store_true",
                   help="不生成产物，改在没登记 preclean 的正常页上标定闸0阈值"
                        "（本底墨占比的中位/p95/p99），换书时用")

    p = sub.add_parser("split",
                       help="[v2] Step0 分页：按 yaml 的 page_split 段把扫描页裁成逻辑页（上下两栏拼一页的影印本）")
    p.add_argument("book", help="books/<id>.yaml 里的书 id")
    p.add_argument("--pages", default=None, help="只做这些**扫描页**（页号表达式，如 1-5,9）；默认全部")
    p.add_argument("--force", action="store_true", help="已有产物也重做")

    p = sub.add_parser("locate-gutter",
                       help="[v2] 版心定位（拆页用）：整叶扫描图 → 版心 x 与置信度（原图坐标，左原点）")
    p.add_argument("image", help="原图路径")
    p.add_argument("--band", default=None, help="只看这段高度 y0,y1（一张图上下两叶时分开找）")
    p.add_argument("--ink-threshold", type=int, default=128)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("witness-align",
                       help="[v2] 列级证人对齐：一行一列的整理本 → 逐字位候选标签（现代链播种/评测用）")
    p.add_argument("book")
    p.add_argument("--first-page", type=int, default=None, help="扫描页 1 对应的影印页码")
    p.add_argument("--witness", default=None, help="整理本文件；默认 references[0].file")

    p = sub.add_parser("witness-align-stream",
                       help="[v2] 字流证人对齐：换行与刻本不同的证人（同书异版）→ 逐字位标签")
    p.add_argument("book")
    p.add_argument("--witness", default=None, help="证人文件；默认 references[0].file")
    p.add_argument("--min-block", type=int, default=8,
                   help="只收长度 ≥ 这个的 equal 块（默认 8，与 align_label 的 8-gram 同量级）")

    p = sub.add_parser("calibrate",
                       help="[v2] 册级先验复核：measure_* 实测 vs books/<id>.yaml 现值的对照表（不改 yaml）")
    p.add_argument("book")
    p.add_argument("--pages", default=None, help="页号表达式；默认 yaml 的 pages")
    p.add_argument("--with-bottom-gap", action="store_true",
                   help="连 bottom_gap 一起量（要读整册原图，慢）")
    p.add_argument("--json", default=None)

    p = sub.add_parser("survey",
                       help="[v2] Step0 页面预检：原图尺寸 → 按册中位数标异常页（任务卡 #54 第22条）")
    p.add_argument("book")
    p.add_argument("--pages", default=None, help="页号表达式；默认全书（book.pages 或 all_pages）")
    p.add_argument("--ratio-high", type=float, default=None, help="默认 1.3（>= 这个倍数算偏大）")
    p.add_argument("--ratio-low", type=float, default=None, help="默认 0.7（<= 这个倍数算偏小）")
    p.add_argument("--json", default=None)

    p = sub.add_parser("calibrate-font",
                       help="[v2] 字体判定：标签字位在各套字体来源里的 recall@1/@5 与可分性 margin")
    p.add_argument("book")
    p.add_argument("--labels", default=None, help="labels.jsonl；默认 products/<book>/witness_align/labels.jsonl")
    p.add_argument("--editions", default=None, help="逗号分隔的 edition_tag；默认库里全部 kind=font 的来源")
    p.add_argument("--per-char", type=int, default=3)
    p.add_argument("--max-chars", type=int, default=600)
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--exclude-self", action="store_true",
                   help="留一法：查询字位自己已在库里（modern:<book>）时摘掉再检索")
    p.add_argument("--manifest", default=None,
                   help="给了就走直接比对（不经库）：按清单渲染字体、按书的笔宽加粗后再比")
    p.add_argument("--charset", default=None, help="直接比对用的模板字表；默认清单里的")
    p.add_argument("--strokes", default=None, help="显式加粗值，如 font:simsun=2,font:zhonghuasong=4")
    p.add_argument("--no-stroke-match", action="store_true", help="直接比对时不按笔宽加粗")
    p.add_argument("--norm-stroke", type=int, default=None,
                   help="直接比对时两边都骨架化再统一细化到 N px（加粗那条路会饱和，见 font_calibrate_direct.py）")
    p.add_argument("--json", default=None)

    p = sub.add_parser("seed-witness",
                       help="[v2] 证人标签 × 字体 top-1 一致 → 播种 modern:<book> 字形库")
    p.add_argument("book")
    p.add_argument("--fonts", default="font:simsun,font:iming", help="逗号分隔的字体 edition_tag（任一 top-1 一致即可）")
    p.add_argument("--labels", default=None)
    p.add_argument("--edition", default=None, help="默认 modern:<book>")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--norm-stroke", type=int, default=None,
                   help="形状证人这一路两边骨架化再细化到 N px——要与管线 glyph_match.norm_stroke 一致（现代链 3）；"
                        "不给就走库检索（不归一，量的是粗细，字/旦/宣 会整批被拒）")
    p.add_argument("--jobs", type=int, default=1,
                   help="读图+归一并行进程数（检索本身不并行：matcher 带着上千模板的特征矩阵，"
                        "进程间传它比算还贵）")
    p.add_argument("--only-chars", default=None,
                   help="只播这些字头（连写，如 「」《》）。进库幂等，可反复补播——"
                        "修好某一类字的形状证人后补这一类，不必全量重播")
    p.add_argument("--keep-gray", action="store_true",
                   help="进库存灰度裁片（旧行为）。缺省存**二值**——用户 2026-09-16："
                        "最后进字形库的一定是二值的，灰度值会干扰")
    p.add_argument("--source-kind", default="print", choices=["print", "woodblock"],
                   help="这本书的来源类型（默认 print，现代排印本）。**刻本必须传 woodblock**："
                        "候选检索默认只查 kinds=('woodblock',)，记成 print 会让播进去的字形"
                        "在检索里静默查不到")

    p = sub.add_parser("import-pdf", help="[v2] PDF 逐页抽成灰度 PNG（<out>/<页号>.png）")
    p.add_argument("pdf")
    p.add_argument("--out", required=True, help="输出目录")
    p.add_argument("--mode", choices=["embedded", "render"], default="embedded",
                   help="embedded（缺省）= 取内嵌图原始像素，扫描 PDF 用这个；"
                        "render = 按页框渲染，矢量/文字 PDF 用这个（给了 --dpi 即隐含 render）")
    p.add_argument("--dpi", type=int, default=None,
                   help="渲染 dpi（隐含 --mode render）；不给且走 render 时按页框 1:1——"
                        "⚠️ 页框 pt 数不一定等于内嵌图像素数，那样会静默降分辨率")
    p.add_argument("--pages", default=None, help="只抽这些页，如 1-5,9")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("snapshot", help="[v2] 冻结一本书若干步的产物，供下游用 GUJI_PRODUCTS_DIR 读")
    p.add_argument("action", choices=["make", "list"])
    p.add_argument("book")
    p.add_argument("--steps", default=None, help="逗号分隔的步骤 id，默认该书已有的全部步")
    p.add_argument("--name", default=None, help="快照名，默认 <日期-时刻>-<commit>")


    p = sub.add_parser("version", help="[v2] 装着的 cv 版本与 pipeline/manager 契约版本（--json 给 manager 用）")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("status", help="[v2] 各步各页的新鲜 / 过期 / 缺失")
    p.add_argument("book")
    p.add_argument("--pipeline", default=DEFAULT_PIPELINE)
    p.add_argument("--pages", default="dev_set")
    p.add_argument("--json", action="store_true")
    _add_override(p)

    p = sub.add_parser("book", help="[v2] 册配置：show 看合并后的生效配置与来源层；split 把一组册相同的部分抽成基础配置")
    p.add_argument("action", choices=["show", "split"])
    p.add_argument("book", nargs="?", default=None, help="show：册号")
    p.add_argument("--books", default=None, help="split：册号清单，逗号分隔或 vol51-vol99 区间")
    p.add_argument("--apply", action="store_true", help="split：真写（缺省只干跑，列计划）")
    p.add_argument("--effective", action="store_true", help="show：打印合并后的完整配置并标注来源层")
    p.add_argument("--json", action="store_true")
    _add_override(p)


    p = sub.add_parser("export", help="[v2] 导出：md = Step9 文本；format = lines.md/pages.json/norm.json（只读产物）")
    p.add_argument("action", choices=["md", "format"])
    p.add_argument("book")
    p.add_argument("--pipeline", default=DEFAULT_PIPELINE)
    p.add_argument("--pages", default="all")
    p.add_argument("--out", default=None, help="输出目录；缺省 reports/<册>/")
    p.add_argument("--chapter", default=None, help="format：章号 NNN，缺省按 volNN 推")
    p.add_argument("--meta", default=None, help="format：缺省 doc/formats/samples/guji_format_v0.1/meta_<册>.json")
    p.add_argument("--split-table", default=None, help="format：合扫拆页裁剪表，缺省四庫的 split_table_siku.json")


    p = sub.add_parser("fp-migrate",
                       help="[v2] 路径参数出指纹后只改写 manifest 指纹、不重算（默认干跑）")
    p.add_argument("book")
    p.add_argument("--pipeline", default=DEFAULT_PIPELINE)
    p.add_argument("--pages", default="all")
    p.add_argument("--steps", default=None, help="只迁这几步（逗号分隔）；默认所有带路径参数的步")
    p.add_argument("--old-path", action="append", default=[], metavar="STEP.FIELD=老值",
                   help="产出这批产物那台机器上的路径，如 glyph_match.db_path=/home/user/ws/output/glyph.db；"
                        "可重复。给了就按老路径重算老指纹、逐位相等才改（能证明只有路径变了）")
    p.add_argument("--trust", action="store_true",
                   help="不验老指纹（老路径说不清时）：只查上游 sha 与产物 sha。"
                        "发现不了代码/参数变了，慎用")
    p.add_argument("--code-formula", action="store_true",
                   help="2026-10-06 代码指纹改成「只认代码、不认注释和 docstring」后的迁移：每一步按老口径回放指纹，"
                        "逐位相等（代码、参数、册配置、上游都没变）才改写成新公式，免得各书白白重算")
    p.add_argument("--apply", action="store_true", help="真写 manifest（缺省干跑）")
    p.add_argument("--explain", action="store_true",
                   help="对每个被跳过的页打印 manifest 记录的 upstream 与现算 upstream 的逐键差异"
                        "（键、两边 sha、现由哪个步产出、记录的 sha 现对应哪个步的产物）；"
                        "--steps 点到 rare_candidates 时另列其指纹里随机器变的分量")
    p.add_argument("--json", action="store_true")


    p = sub.add_parser("rare", help="[v2] 生僻字候选（单查或 --slots 批量）")
    p.add_argument("book")
    p.add_argument("page", nargs="?", type=int, default=0)
    p.add_argument("col", nargs="?", type=int, default=0)
    p.add_argument("slot", nargs="?", type=int, default=0)
    p.add_argument("--sub", default="")
    p.add_argument("-k", type=int, default=10, help="出几个候选")
    p.add_argument("--slots", default="", help='批量："24:1:10,24:2:3a"')
    p.add_argument("--top", default="", help="IDS 兜底：顶层结构，如 ⿰ ⿱ ⿸")
    p.add_argument("--slot-comp", action="append", default=[], metavar="槽=部件",
                   help="IDS 兜底：某槽位的部件，如 L=言（可重复）")
    p.add_argument("--comp", action="append", default=[], help="IDS 兜底：任意位置含此部件（可重复）")


    p = sub.add_parser("variants", help="[v2] 本书用字账（只读）")
    p.add_argument("action", nargs="?", default="book", choices=["book"])
    p.add_argument("--edition", default="")


    load_plugin_commands(sub)
    install_workspace_option(sub)


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        from .utils.batch_slice import enter_batch_slice
        enter_batch_slice(sys.argv[1:])   # 服务器上跑批自动进内存额度切片
    parser = argparse.ArgumentParser(prog="guji", description="open-guji-cv 四个抽象的 CLI")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    register_subcommands(sub)
    hint = moved_command_hint(sys.argv[1:] if argv is None else argv, sub.choices)
    if hint:
        print(hint, file=sys.stderr)
        raise SystemExit(2)
    args = parser.parse_args(argv)
    if getattr(args, "override", None):         # 运行覆盖：环境变量传，子进程（隔离步骤）自动继承
        from .core.book_config import merge_override_env
        os.environ["GUJI_BOOK_OVERRIDE"] = merge_override_env(args.override)   # 叠在已有的覆盖上（准备脚本记的改值），同键 --override 胜
    hooks.call("startup", args.command)   # manager 登记：派生缓存取件器、耗时记录与步内分段计时
    handler = COMMANDS_V2.get(args.command)
    if handler is None:
        parser.print_help()
        return
    handler(args)


if __name__ == "__main__":
    main()
