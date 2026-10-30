"""任务定义（spec）：规整、校验、算指纹。纯函数，不连库、不跑命令（解析 cv 引用除外，见 `resolve_cv`）。

一条任务就是一个 JSON 对象。提交时规整成全字段的标准形（缺省值补齐、cv 引用解析成 40 位提交），
再算 `spec_hash`：同一指纹 = 同一次计算，只跑一次（重复提交记成 duplicate，指向已有那条）。

    kind            rerun（重跑一册，可接对比）| ab（同 rerun，必须给 compare_to）| eval | command（一串 guji 命令）
    book            册，如 vol10（eval 可空）
    cv              tag／分支／提交；提交时解析成 40 位提交（cv_ref 留原文）
    pipeline        缺省 keben_body_v2
    steps           {"from": 起步, "to": 止步}，缺省整条
    pages           缺省 all
    force           缺省 true（重跑就是要重算）；no_reuse 缺省跟 force
    book_overrides  {"corpus": N, "glyph_pin": N}：只改执行会话本机的册配置，不推中心库
    pin_args        guji corpus pin 的参数串（追加语料钉子账）
    base            先取哪个产物包铺底：main｜包标签｜null；从中间某步起跑缺省 main
    checks          {"human_chars": N}：开跑前人裁绑定后必须正好 N 格，不对就 blocked 不跑
    env             只收 GUJI_ 开头、不像凭据的变量
    params          guji pipeline --params 的 JSON 对象
    compare_to      跑完和谁比：main｜包标签｜{"job": 任务号}
    output          {"change": 包改动名, "note": 说明, "pack": true}；永不标 main
    run             command／eval 用：[[guji 子命令, 参数…], …]，可用 {book} {ws}
    ws_glob         缺省 96mid1ogzk-*（殿本工作区）
    ws_repo         <owner>/<repo>：这部书自己一个仓（仓根即工作区）；缺省走 guji-workspace 里 ws_glob 匹配的目录

不进指纹：why、priority、output（换个包名也是同一次计算）、cv_ref（已解析成提交）。
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess

KINDS = ("rerun", "ab", "eval", "command")
STATUSES = ("queued", "running", "succeeded", "failed", "blocked", "cancelled", "duplicate")
ACTIVE = ("queued", "running")
CV_REPO = "https://github.com/open-guji/open-guji-cv"
DEFAULT_PIPELINE = "keben_body_v2"
DEFAULT_WS_GLOB = "96mid1ogzk-*"

#: command／eval 的 run 里允许的 guji 子命令。不收会推库、改中心库、标 main 的（db、promote 等）。
RUN_SUBCOMMANDS = frozenset({
    "pipeline", "step", "recheck", "status", "eval", "collate", "cache", "corpus", "glyph-db", "source",
    "products", "close-check", "gold", "report", "product",
})
#: run 里不许出现的参数（推中心库、标 main）
RUN_FORBIDDEN_ARGS = frozenset({"--main", "promote", "push", "push-index", "sync", "migrate"})
_ENV_KEY = re.compile(r"^GUJI_[A-Z0-9_]+$")
_ENV_SECRETISH = re.compile(r"TOKEN|SECRET|KEY|PASS|DSN|URL|AUTH", re.I)
_STEP = re.compile(r"^[a-z][a-z0-9_]*$")
_BOOK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_OVERRIDES = {"corpus": int, "glyph_pin": int}     # 有类型要求的两个；其余册级字段不限类型（执行方 `--override` 原样叠上去）


def _override_keys() -> set[str]:
    """能覆盖的册级字段：BookSpec 的字段，去掉身份与图源（`core/book_config.FORBIDDEN_IN_OVERRIDE`）。"""
    import dataclasses
    from ..core.book import BookSpec
    from ..core.book_config import FORBIDDEN_IN_OVERRIDE
    return {f.name for f in dataclasses.fields(BookSpec)} - FORBIDDEN_IN_OVERRIDE
_KEYS = {"kind", "book", "cv", "cv_ref", "pipeline", "steps", "pages", "force", "no_reuse", "book_overrides",
         "pin_args", "base", "checks", "env", "params", "compare_to", "output", "run", "ws_glob", "ws_repo", "why"}
_NOT_HASHED = ("why", "output", "cv_ref")


class SpecError(ValueError):
    """任务定义不合规。消息直接给提交人看。"""


def normalize(raw: dict, *, resolve=None) -> dict:
    """规整成标准形并校验；`resolve(ref) -> 40 位提交` 缺省 `resolve_cv`（测试里传假的）。"""
    if not isinstance(raw, dict):
        raise SpecError("任务定义要是 JSON 对象")
    extra = set(raw) - _KEYS
    if extra:
        raise SpecError(f"不认识的字段：{', '.join(sorted(extra))}（可用：{', '.join(sorted(_KEYS))}）")
    s = copy.deepcopy(raw)
    kind = s.get("kind") or "rerun"
    if kind not in KINDS:
        raise SpecError(f"kind 只能是 {'/'.join(KINDS)}，不是 {kind!r}")
    s["kind"] = kind
    book = s.get("book")
    if kind in ("rerun", "ab") and not book:
        raise SpecError(f"{kind} 要给 book（册，如 vol10）")
    if book is not None and not (isinstance(book, str) and _BOOK.match(book)):
        raise SpecError(f"book 不合规：{book!r}")
    s["book"] = book or None

    ref = s.get("cv_ref") or s.get("cv")
    if not ref or not isinstance(ref, str):
        raise SpecError("要给 cv（tag、分支或提交，如 v0.5.16、dev、1ed2599）：跑哪版代码必须写明")
    s["cv_ref"] = ref
    s["cv"] = ref if _HEX40.match(ref) else (resolve or resolve_cv)(ref)
    if not _HEX40.match(s["cv"] or ""):
        raise SpecError(f"cv {ref!r} 解析不出 40 位提交")

    s["pipeline"] = s.get("pipeline") or DEFAULT_PIPELINE
    st = s.get("steps") or {}
    if not isinstance(st, dict) or set(st) - {"from", "to"}:
        raise SpecError('steps 写成 {"from": 起步, "to": 止步}')
    for k in ("from", "to"):
        if st.get(k) is not None and not _STEP.match(str(st[k])):
            raise SpecError(f"steps.{k} 不像步骤 id：{st[k]!r}")
    s["steps"] = {"from": st.get("from"), "to": st.get("to")}
    pages = s.get("pages", "all")
    if not isinstance(pages, str) or not re.match(r"^(all|dev_set|[0-9][0-9,\-]*)$", pages):
        raise SpecError(f"pages 只能是 all、dev_set 或 3-6,9 这样的页号：{pages!r}")
    s["pages"] = pages
    s["force"] = bool(s.get("force", True))
    s["no_reuse"] = bool(s.get("no_reuse", s["force"]))

    ov = s.get("book_overrides") or {}
    if not isinstance(ov, dict):
        raise SpecError("book_overrides 要是 JSON 对象")
    bad = set(ov) - _override_keys()
    if bad:
        raise SpecError(f"book_overrides 不收 {', '.join(sorted(bad))}（身份与图源只能改册 yaml；可覆盖的见 doc/design/册配置分层与运行覆盖.md）")
    try:
        s["book_overrides"] = {k: (_OVERRIDES[k](v) if k in _OVERRIDES else v)
                               for k, v in sorted(ov.items()) if v is not None}
    except (TypeError, ValueError):
        raise SpecError("book_overrides 里 corpus、glyph_pin 的值要是整数") from None
    pa = s.get("pin_args")
    if pa is not None and (not isinstance(pa, str) or re.search(r"[;&|`$<>\n]", pa)):
        raise SpecError("pin_args 是一串普通参数，不能带 shell 符号")
    s["pin_args"] = pa or None

    base = s.get("base", "main" if s["steps"]["from"] else None)
    if base is not None and not (isinstance(base, str) and _LABEL.match(base)):
        raise SpecError(f"base 是 main 或包标签：{base!r}")
    s["base"] = base

    ck = s.get("checks") or {}
    if not isinstance(ck, dict) or set(ck) - {"human_chars"}:
        raise SpecError("checks 目前只收 human_chars")
    if "human_chars" in ck and not isinstance(ck["human_chars"], int):
        raise SpecError("checks.human_chars 要是整数")
    s["checks"] = dict(sorted(ck.items()))

    env = s.get("env") or {}
    if not isinstance(env, dict):
        raise SpecError("env 要是对象")
    for k, v in env.items():
        if not _ENV_KEY.match(k) or _ENV_SECRETISH.search(k):
            raise SpecError(f"env 只收 GUJI_ 开头、不是凭据的变量：{k}（凭据由执行会话自己的环境给）")
        if not isinstance(v, (str, int, float, bool)):
            raise SpecError(f"env.{k} 要是字符串或数字")
    s["env"] = {k: str(v) for k, v in sorted(env.items())}

    params = s.get("params")
    if params is not None and not isinstance(params, dict):
        raise SpecError("params 要是 JSON 对象（同 guji pipeline --params）")
    s["params"] = params or None

    cmp_ = s.get("compare_to")
    if isinstance(cmp_, dict):
        if set(cmp_) != {"job"} or not isinstance(cmp_["job"], int):
            raise SpecError('compare_to 是 main、包标签，或 {"job": 任务号}')
    elif cmp_ is not None and not (isinstance(cmp_, str) and _LABEL.match(cmp_)):
        raise SpecError(f"compare_to 不合规：{cmp_!r}")
    if kind == "ab" and not cmp_:
        raise SpecError("ab 要给 compare_to（和谁比）")
    s["compare_to"] = cmp_

    out = s.get("output") or {}
    if not isinstance(out, dict) or set(out) - {"change", "note", "pack"}:
        raise SpecError("output 只收 change、note、pack")
    if out.get("change") is not None and not _LABEL.match(str(out["change"])):
        raise SpecError(f"output.change 只能用 ASCII 字母数字和 ._-：{out['change']!r}")
    s["output"] = {"change": out.get("change"), "note": out.get("note"),
                   "pack": bool(out.get("pack", kind in ("rerun", "ab")))}

    run = s.get("run")
    if kind in ("command", "eval"):
        if kind == "eval" and not run:
            run = [["eval", "run", "--json"]]
        if not run:
            raise SpecError("command 要给 run：[[guji 子命令, 参数…], …]")
        s["run"] = [_check_argv(a) for a in run]
    elif run:
        raise SpecError("run 只给 command／eval 用；rerun 用 steps／pages／params")
    else:
        s["run"] = None
    s["ws_glob"] = s.get("ws_glob") or DEFAULT_WS_GLOB
    if not re.match(r"^[A-Za-z0-9_*.-]+$", s["ws_glob"]):
        raise SpecError(f"ws_glob 不合规：{s['ws_glob']!r}")
    s["ws_repo"] = s.get("ws_repo") or None
    if s["ws_repo"] and not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", s["ws_repo"]):
        raise SpecError(f"ws_repo 不合规（要 owner/repo）：{s['ws_repo']!r}")
    s["why"] = s.get("why") or None
    return s


def _check_argv(a) -> list[str]:
    if not isinstance(a, list) or not a or not all(isinstance(x, (str, int, float)) for x in a):
        raise SpecError(f"run 里每条是参数列表（不经 shell），如 [\"eval\", \"run\"]：{a!r}")
    a = [str(x) for x in a]
    if a[0] == "guji":
        a = a[1:]
    if not a or a[0] not in RUN_SUBCOMMANDS:
        raise SpecError(f"run 只许这些 guji 子命令：{', '.join(sorted(RUN_SUBCOMMANDS))}（不是 {a[:1]}）")
    if a[0] == "products" and len(a) > 1 and a[1] == "pack" and (len(a) < 3 or a[2] not in ("fetch", "list")):
        raise SpecError("run 里 products pack 只许 fetch／list；存包写 output.pack")
    bad = RUN_FORBIDDEN_ARGS.intersection(a[1:])
    if bad:
        raise SpecError(f"run 里不许 {', '.join(sorted(bad))}（推中心库、标 main 要用户亲口说）")
    return a


def spec_hash(spec: dict) -> str:
    """标准形去掉不进指纹的字段后，按键排序的 JSON 的 sha256。"""
    core = {k: v for k, v in spec.items() if k not in _NOT_HASHED}
    blob = json.dumps(core, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def resolve_cv(ref: str, repo: str = CV_REPO, local: str | None = "/opt/guji-cv-seed") -> str:
    """tag／分支／短提交 → 40 位提交。先问远端（tag 取剥开后的提交），短提交再问本机仓。"""
    try:
        out = subprocess.run(["git", "ls-remote", repo, ref, f"refs/tags/{ref}^{{}}"],
                             capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    rows = [ln.split("\t") for ln in out.splitlines() if "\t" in ln]
    for want in (f"refs/tags/{ref}^{{}}", f"refs/heads/{ref}", f"refs/tags/{ref}", ref):
        for sha, name in rows:
            if name == want:
                return sha
    if re.match(r"^[0-9a-f]{7,40}$", ref) and local:
        for args in (["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],):
            try:
                r = subprocess.run(["git", "-C", local, *args], capture_output=True, text=True, timeout=60)
                if r.returncode != 0:
                    subprocess.run(["git", "-C", local, "fetch", "-q", "origin", "dev", "main"],
                                   capture_output=True, timeout=300)
                    r = subprocess.run(["git", "-C", local, *args], capture_output=True, text=True, timeout=60)
            except (OSError, subprocess.SubprocessError):
                break
            if r.returncode == 0 and _HEX40.match(r.stdout.strip()):
                return r.stdout.strip()
    raise SpecError(f"cv {ref!r} 在 {repo} 找不到（tag、分支名，或已推上去的提交）")


def summary(spec: dict) -> str:
    """一行概要，给 ls 用。"""
    if spec["kind"] in ("command", "eval"):
        body = " ; ".join(" ".join(a) for a in spec["run"] or [])
    else:
        st = spec["steps"]
        body = f"{spec['pipeline']} {st['from'] or '头'}→{st['to'] or '尾'} {spec['pages']}"
        if spec["book_overrides"]:
            body += " " + ",".join(f"{k}={v}" for k, v in spec["book_overrides"].items())
        if spec["env"]:
            body += " " + ",".join(f"{k}={v}" for k, v in spec["env"].items())
        if spec["compare_to"]:
            c = spec["compare_to"]
            body += f" 比 {'#' + str(c['job']) if isinstance(c, dict) else c}"
    return f"cv {spec['cv_ref']}({spec['cv'][:7]}) {body}"
