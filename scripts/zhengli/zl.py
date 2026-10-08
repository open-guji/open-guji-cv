#!/usr/bin/env python3
"""整理一册书：执行脚本（runbook v2 的机器化）。只用标准库，装好 venv 之前也能跑 `env` 步。

用法（详见 doc/runbook/整理一册书.md）：
  python scripts/zhengli/zl.py plan   --book vol05 --ws <ws>            # 看还剩哪些步
  python scripts/zhengli/zl.py run    --book vol05 --ws <ws> --bg       # 从头/断点续跑到第一个要人的闸
  python scripts/zhengli/zl.py run    --book vol05 --ws <ws> --only audit
  python scripts/zhengli/zl.py status --book vol05 --ws <ws>            # 看后台进度
  python scripts/zhengli/zl.py intervene --book vol05 --step S11 --why "..." --waited-min 5
  python scripts/zhengli/zl.py metrics --book vol05 --ws <ws>           # 度量表（markdown）

设计：
- 步骤按顺序列在 STAGES；每步幂等，成功后记入状态文件，重跑自动跳过；`--redo <步>` 强制重做该步。
- 长命令一律后台 nohup 跑（`--bg`），不受前台 9 分钟上限；脚本自己轮询，崩了可原样重跑续上。
- 失败分类（CLASSIFY）：缺依赖→自动补装重试；磁盘满→停；被 kill（疑似内存）→降并行重试；其余→停并写 NEXT.md。
- 要人的闸（GATES）不绕：脚本停在那里，把「谁、做什么、在哪」写进 reports/<册>/NEXT.md。
- 脚本总以 .venv 的 python 跑：一旦 .venv 在，自动换它重启；崩溃一律写 NEXT.md；「已跳过」的步不记完成。
- 不改 cv 引擎代码；不加 --force（唯一例外见 compute-b 的换库重落）；提交只 add 具体文件。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

CV = Path(__file__).resolve().parents[2]
STD_SEED_ADMIT = {
    "ji_yi_si_review": True, "ji_yi_si_ctx_rule": True, "rare_ref": True,
    "context_guard_diff": True, "context_guard_ref_blank": True,
    "context_guard_ref_prefer": True, "shadow_veto": True, "shadow_conf": 0.8,
    "lane_witness3": True, "lane_coord": True, "lane_seal": True,
}
#: 显式预设（默认不启用）。只在四庫 vol04／vol05 上验过，不并进标准配置。
#: variant_tie 组表 = doc/exp/variant_tie_groups-vol04-vol05.yaml 的 g6_097（不含 㫖旨：3 格放错），测试核对两处一致。
PRESETS = {
    "siku": {
        "juan_rule": True,
        "shadow_veto": True, "shadow_conf": 0.8, "shadow_veto_variant_abstain": False,
        "variant_tie": True, "variant_tie_cov": 0.97,
        "variant_tie_extra": "𫎇蒙䝉,㸃點,㕘參,䜟讖識,𨽾隸,慎愼",
    },
}


def seed_admit_want(preset: str | None = None, no_shadow_veto: bool = False) -> dict:
    """要补进书 yaml `params.seed_admit` 的开关：标准 11 键 ＋ 预设；`no_shadow_veto` 关掉影子否决（vol04 用）。"""
    if preset and preset not in PRESETS:
        raise SystemExit(f"未知预设 {preset!r}，可用：{', '.join(PRESETS)}")
    want = {**STD_SEED_ADMIT, **PRESETS.get(preset or "", {})}
    if no_shadow_veto:
        want["shadow_veto"] = False
        for k in ("shadow_conf", "shadow_veto_variant_abstain"):
            want.pop(k, None)
    return want


SELF_CHECK = "import torch, scipy, cv2, joblib, sklearn, yaml; print('torch', torch.__version__, 'sklearn', sklearn.__version__)"
# 失败分类：(正则, 动作, 说明)。动作：pip=补装模块重试；stop=停；retry-lowjobs=降并行重试一次
CLASSIFY = [
    (re.compile(r"ModuleNotFoundError: No module named '([\w\.]+)'"), "pip", "缺 Python 模块"),
    (re.compile(r"No space left on device|磁盘空间不足"), "stop", "磁盘满：删缓存/旧产物后重跑"),
    (re.compile(r"Killed|MemoryError|returned non-zero exit status -9|exit code -9"), "retry-lowjobs", "疑似内存不足"),
    (re.compile(r"sha256 对不上.*_manifest\.jsonl"), "stop", "快照行尾不一致：改用 zl.py import-snap（容忍 CRLF）"),
    (re.compile(r"rate limit|Connection (reset|aborted)|Temporary failure|timed out"), "retry", "网络抖动"),
]
PIP_NAME = {"joblib": "joblib", "sklearn": "scikit-learn==1.9.1", "cv2": "opencv-python-headless", "yaml": "pyyaml"}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Ctx:
    def __init__(self, a):
        self.book = a.book
        self.ws = Path(a.ws).resolve() if getattr(a, "ws", None) else None
        self.cv = CV
        self.jobs = int(getattr(a, "jobs", 0) or os.cpu_count() or 2)
        self.venv_py = self._venv_py()
        sd = Path(os.environ.get("ZL_STATE") or (self.ws.parent / "zhengli-state" if self.ws else CV / ".zhengli"))
        sd.mkdir(parents=True, exist_ok=True)
        self.state_f = sd / f"{self.book}.json"
        self.log_f = sd / f"{self.book}.log"
        self.st = json.loads(self.state_f.read_text()) if self.state_f.exists() else {"stages": {}, "interventions": []}
        self.reports = (self.ws / "reports" / self.book) if self.ws else None
        self.snap_branch = getattr(a, "snap", None)
        # 预设：本次命令行给的 > 上次记在状态里的（plan/status 不带参数也能说明用了哪个）
        self.preset = getattr(a, "preset", None) or self.st.get("preset")
        self.no_shadow_veto = bool(getattr(a, "no_shadow_veto", False) or self.st.get("no_shadow_veto"))

    def _venv_py(self):
        for p in (CV / ".venv/bin/python", CV / ".venv/Scripts/python.exe"):
            if p.exists():
                return str(p)
        return sys.executable

    def guji(self, *args):
        return [self.venv_py, "-m", "open_guji_cv.cli_v2", *map(str, args)]

    def save(self):
        self.state_f.write_text(json.dumps(self.st, ensure_ascii=False, indent=1))

    def log(self, msg):
        line = f"[{now()}] {msg}"
        print(line, flush=True)
        with self.log_f.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def sh(ctx: Ctx, cmd, cwd=None, env_extra=None, retries=2, lowjobs_fix=None, check=True, tail=4000):
    """跑一条命令：失败分类、自动重试。返回 (rc, 输出末 tail 字)；tail=None 返回全文（要解析 JSON 时用，别截断）。"""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", **(env_extra or {})}
    if ctx.ws:
        env.setdefault("GUJI_WORKSPACE", str(ctx.ws))
    cmd = [str(c) for c in cmd]
    for attempt in range(retries + 1):
        ctx.log("$ " + " ".join(cmd))
        p = subprocess.run(cmd, cwd=cwd or ctx.cv, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        out = (p.stdout or "") + (p.stderr or "")
        with ctx.log_f.open("a", encoding="utf-8") as f:
            f.write(out[-20000:] + "\n")
        if p.returncode == 0:
            return 0, (out if tail is None else out[-tail:])
        for rx, act, why in CLASSIFY:
            m = rx.search(out)
            if not m:
                continue
            ctx.log(f"失败分类：{why}（{act}）")
            if act == "pip" and attempt < retries:
                mod = m.group(1).split(".")[0]
                pkg = PIP_NAME.get(mod, mod)
                r = subprocess.run(pip_cmd(ctx, pkg), capture_output=True, text=True)
                ctx.log(f"补装 {pkg}：rc={r.returncode}")
                if r.returncode == 0:
                    break
            if act == "retry" and attempt < retries:
                time.sleep(2 ** (attempt + 1))
                break
            if act == "retry-lowjobs" and attempt < retries and lowjobs_fix:
                cmd = lowjobs_fix(cmd)
                break
            return fail(ctx, cmd, p.returncode, out, why, check, tail)
        else:
            return fail(ctx, cmd, p.returncode, out, "未分类失败", check, tail)
    return fail(ctx, cmd, 1, "", "重试用尽", check)


def pip_cmd(ctx, pkg):
    uv = shutil.which("uv")
    return [uv, "pip", "install", "--python", ctx.venv_py, pkg] if uv else [ctx.venv_py, "-m", "pip", "install", pkg]


class Stop(Exception):
    pass


class Skip(Exception):
    """这步没做、也不该算做完：记「已跳过」，继续往下走。"""


def fail(ctx, cmd, rc, out, why, check, tail=4000):
    ctx.log(f"✗ rc={rc}：{why}")
    if check:
        write_next(ctx, f"命令失败（{why}）", ["命令：`" + " ".join(cmd) + "`", "输出末尾：", "```", out[-1500:], "```"])
        raise Stop(why)
    return rc, (out if tail is None else out[-tail:])


def write_next(ctx, title, lines):
    if not ctx.reports:
        return
    ctx.reports.mkdir(parents=True, exist_ok=True)
    (ctx.reports / "NEXT.md").write_text(f"# {ctx.book} 下一步（{now()}）\n\n**{title}**\n\n" + "\n".join(lines) + "\n", encoding="utf-8")


def bg_wait(ctx, cmd, tag, poll=20, **kw):
    """长命令走后台 nohup：日志落文件，本脚本被杀后重跑能续上（已完成页由 guji 自己跳过）。"""
    lf = ctx.log_f.with_name(f"{ctx.book}.{tag}.log")
    cmd = [str(c) for c in cmd]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "GUJI_WORKSPACE": str(ctx.ws)}
    ctx.log(f"后台：{' '.join(cmd)} → {lf.name}")
    with lf.open("ab") as f:
        p = subprocess.Popen(cmd, cwd=ctx.cv, env=env, stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
    while p.poll() is None:
        time.sleep(poll)
    out = lf.read_text(encoding="utf-8", errors="replace")[-6000:]
    if p.returncode == 0:
        return out
    for rx, act, why in CLASSIFY:
        m = rx.search(out)
        if m and act == "pip":
            r = subprocess.run(pip_cmd(ctx, PIP_NAME.get(m.group(1).split(".")[0], m.group(1).split(".")[0])), capture_output=True)
            if r.returncode == 0 and not kw.get("_retried"):
                ctx.log("补装依赖后重试一次")
                return bg_wait(ctx, cmd, tag, poll, _retried=True)
    write_next(ctx, f"后台步 {tag} 失败 rc={p.returncode}", ["日志：" + str(lf), "```", out[-1500:], "```"])
    raise Stop(f"{tag} 失败")


def parse_json_tail(out: str):
    """从命令输出里取第一个能完整解析的 JSON 对象（前面可有日志行）；取不到返回 None。"""
    dec = json.JSONDecoder()
    i = out.find("{")
    while i >= 0:
        try:
            return dec.raw_decode(out, i)[0]
        except ValueError:
            i = out.find("{", i + 1)
    return None


def status_json(ctx):
    rc, out = sh(ctx, ctx.guji("status", ctx.book, "--pages", "all", "--json", "-w", ctx.ws), check=False, tail=None)
    js = parse_json_tail(out)
    if js is None:
        write_next(ctx, "status --json 解析失败", [f"rc={rc}，输出末尾：", "```", out[-1500:], "```"])
        raise Stop("status --json 解析失败")
    return js


# ───────── 各步 ─────────
def st_env(ctx):
    py = ctx.venv_py
    if "/.venv/" not in py.replace("\\", "/"):
        sh(ctx, ["uv", "venv", ".venv", "--python", "3.12"])
        ctx.venv_py = ctx._venv_py()
    cpu_only = not shutil.which("nvidia-smi")
    uv = shutil.which("uv")
    if cpu_only:
        sh(ctx, [uv, "pip", "install", "--python", ctx.venv_py, "torch", "--index-url", "https://download.pytorch.org/whl/cpu"])
    sh(ctx, [uv, "pip", "install", "--python", ctx.venv_py, "-e", ".[console,torch,dev,shadow]", "ruamel.yaml"])
    sh(ctx, [ctx.venv_py, "-c", SELF_CHECK])


WS_URL = "https://github.com/open-guji/guji-workspace"


def in_git_repo(path: Path) -> bool:
    """path 是某个 git 仓的工作树里（含仓内子目录）就算已有 ws，不再克隆。"""
    if not path.is_dir():
        return False
    r = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=path, capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == "true"


def st_ws(ctx):
    if not in_git_repo(ctx.ws):
        url = os.environ.get("ZL_WS_URL", WS_URL)
        sh(ctx, ["git", "clone", "--filter=blob:none", "--sparse", url, str(ctx.ws)], cwd=ctx.ws.parent)
        # 只要本书原图：data_full/<册>，其余顶层目录照常
        sh(ctx, ["git", "sparse-checkout", "set", "--no-cone", "/*", "!/data_full/*/", f"/data_full/{ctx.book}/"], cwd=ctx.ws)
    pin = os.environ.get("ZL_WS_PIN")
    if pin:
        sh(ctx, ["git", "checkout", pin], cwd=ctx.ws)
    sh(ctx, ["git", "config", "user.email", os.environ.get("ZL_EMAIL", "noreply@users.noreply.github.com")], cwd=ctx.ws)
    ctx.st["pins"] = {
        "cv": sh(ctx, ["git", "rev-parse", "HEAD"])[1].strip(),
        "ws": sh(ctx, ["git", "rev-parse", "HEAD"], cwd=ctx.ws)[1].strip(),
    }


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_content(line: str) -> bool:
    t = line.strip()
    return bool(t) and not t.startswith("#")


def _block_end(lines: list[str], start: int, ind: int) -> int:
    """lines[start] 是 `key:`（缩进 ind）；返回它的块结束行（不含）。注释/空行不截断块。"""
    end = start + 1
    last = start + 1
    while end < len(lines):
        if _is_content(lines[end]):
            if _indent(lines[end]) <= ind:
                break
            last = end + 1
        end += 1
    return last


def _find_key(lines: list[str], lo: int, hi: int, key: str, ind: int | None = None):
    rx = re.compile(r"^(\s*)" + re.escape(key) + r"\s*:(.*)$")
    for i in range(lo, hi):
        m = rx.match(lines[i])
        if m and (ind is None or len(m.group(1)) == ind) and _is_content(lines[i]):
            return i
    return None


def _fmt(v) -> str:
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, str):                       # 字串一律加引号：含逗号、冒号、井号、非 ASCII 的裸写法 yaml 解析易出岔子
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _set_scalar(lines: list[str], i: int, v) -> str | None:
    """改 `key: old  # 注释` 这一行的值，保留注释；旧值是块/流式（不是标量）返回 None。返回旧值文本。"""
    m = re.match(r"^(\s*[\w\-]+\s*:\s*)([^#]*?)(\s*(#.*)?)$", lines[i].rstrip("\n"))
    if not m or m.group(2).strip() == "" or m.group(2).lstrip()[:1] in "{[|>&*!":
        return None
    old = m.group(2).strip()
    lines[i] = f"{m.group(1)}{_fmt(v)}{m.group(3)}\n"
    return old


def patch_yaml_text(text: str, want: dict, iron_gate: bool = True):
    """只补开关、不整体回写：逐行改/插，其余字节原样。返回 (新文本, 改动项 {键: (旧, 新)})，
    结构超出能安全处理的范围（流式 seed_admit 等）返回 (None, 原因)。"""
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    changed: dict = {}
    n = len(lines)
    # iron_gate（顶层）
    i = _find_key(lines, 0, n, "iron_gate", 0)
    if i is None:
        lines += ["iron_gate: true\n"]
        changed["iron_gate"] = (None, True)
    else:
        old = _set_scalar(lines, i, iron_gate) if not re.match(r"^iron_gate\s*:\s*true\s*(#.*)?$", lines[i].strip()) else "true"
        if old is None:
            return None, "iron_gate 不是标量"
        if old != "true":
            changed["iron_gate"] = (old, True)
    # params.seed_admit
    n = len(lines)
    pi = _find_key(lines, 0, n, "params", 0)
    if pi is not None and re.match(r"^params\s*:\s*(\{|\[|null|~)", lines[pi].strip()):
        return None, "params 是流式写法"
    if pi is None:
        body = ["params:\n", "  seed_admit:\n"] + [f"    {k}: {_fmt(v)}\n" for k, v in want.items()]
        lines += body
        changed.update({k: (None, v) for k, v in want.items()})
        return "".join(lines), changed
    pend = _block_end(lines, pi, 0)
    child = next((_indent(l) for l in lines[pi + 1:pend] if _is_content(l)), 2)
    si = _find_key(lines, pi + 1, pend, "seed_admit", child)
    if si is None:
        ins = [f"{' ' * child}seed_admit:\n"] + [f"{' ' * (child * 2)}{k}: {_fmt(v)}\n" for k, v in want.items()]
        lines[pend:pend] = ins
        changed.update({k: (None, v) for k, v in want.items()})
        return "".join(lines), changed
    if re.match(r"^\s*seed_admit\s*:\s*(\{|\[)", lines[si]):
        return None, "seed_admit 是流式写法"
    send = _block_end(lines, si, child)
    kid = next((_indent(l) for l in lines[si + 1:send] if _is_content(l)), child * 2)
    add = []
    for k, v in want.items():
        j = _find_key(lines, si + 1, send, k, kid)
        if j is None:
            add.append(f"{' ' * kid}{k}: {_fmt(v)}\n")
            changed[k] = (None, v)
            continue
        cur = re.match(r"^\s*[\w\-]+\s*:\s*([^#]*?)\s*(#.*)?$", lines[j].rstrip("\n"))
        curv = cur.group(1).strip() if cur else None
        if curv == _fmt(v) or (isinstance(v, str) and curv is not None and curv.strip("\"'") == v) or (isinstance(v, float) and curv is not None and _is_float(curv) and float(curv) == v):
            continue
        old = _set_scalar(lines, j, v)
        if old is None:
            return None, f"{k} 不是标量"
        changed[k] = (old, v)
    lines[si + 1:si + 1] = add
    return "".join(lines), changed


def _is_float(x: str) -> bool:
    try:
        float(x)
        return True
    except ValueError:
        return False


def preset_label(ctx) -> str:
    return (f"预设 {ctx.preset}" if ctx.preset else "标准配置（无预设）") + ("，关 shadow_veto" if ctx.no_shadow_veto else "")


def st_yaml(ctx):
    """把标准 Step7 开关补进书 yaml：已有键保留（同名项以标准值为准），其余文字、注释、排版一字不动。"""
    f = ctx.ws / "books" / f"{ctx.book}.yaml"
    if not f.exists():
        write_next(ctx, "缺书 yaml", [f"`{f}` 不存在。拷一份同类册的 yaml 改册号、page_split、版面先验；缺 `period_prior` 会被闸 2/3 拦。"])
        raise Stop("缺书 yaml")
    old_t = f.read_bytes().decode("utf-8")
    want = seed_admit_want(ctx.preset, ctx.no_shadow_veto)
    ctx.st["preset"], ctx.st["no_shadow_veto"] = ctx.preset, ctx.no_shadow_veto
    ctx.log(f"yaml 开关：{preset_label(ctx)}")
    new_t, changed = patch_yaml_text(old_t, want)
    if new_t is None:
        snip = ctx.reports / "yaml-标准开关.片段.yaml"
        ctx.reports.mkdir(parents=True, exist_ok=True)
        snip.write_text("iron_gate: true\nparams:\n  seed_admit:\n" + "".join(f"    {k}: {_fmt(v)}\n" for k, v in want.items()), encoding="utf-8")
        write_next(ctx, "书 yaml 需手贴标准开关", [f"yaml 写法超出自动补丁范围（{changed}）。把 `{snip}` 里的键合并进 `{f}`，然后原样重跑。"])
        raise Stop("书 yaml 需手贴开关")
    if changed:
        f.write_bytes(new_t.encode("utf-8"))
        ctx.log(f"yaml 已补标准开关（只动这些行），改动项：{changed}")
    else:
        ctx.log("yaml 已是标准开关")
    txt = new_t
    missing = [k for k in ("period_prior", "bottom_gap") if k not in txt]
    if missing:
        ctx.log(f"⚠ yaml 缺 {missing}：S5 跑完 column_gate 后用 calibrate 值补")


def st_survey(ctx):
    sh(ctx, ctx.guji("survey", ctx.book, "-w", ctx.ws))


def st_import_snap(ctx):
    """从已有快照分支起步（本地做过前几步）。无 --snap 时跳过。"""
    if not ctx.snap_branch:
        ctx.log("无 --snap，跳过")
        return
    sh(ctx, [ctx.venv_py, str(CV / "scripts/zhengli/snap_import.py"), ctx.snap_branch, "-w", ctx.ws, "--ws-repo", ctx.ws, "--cv-repo", ctx.cv])


def _pages_all(ctx):
    return ["--pages", "all", "-w", ctx.ws]


def st_compute_a(ctx):
    # 一条命令后台整册；与建库错开（4 核上并行会互拖，T2 实测 row_segment 14s/页 vs 3s/页）
    bg_wait(ctx, ctx.guji("pipeline", "keben_body_v2", ctx.book, *_pages_all(ctx), "--to", "cell_shrink", "--jobs", ctx.jobs), "compute-a")


def st_calibrate(ctx):
    sh(ctx, ctx.guji("calibrate", ctx.book, "-w", ctx.ws, "--pages", "all", "--with-bottom-gap"))
    ctx.log("calibrate 只出对照表；与 yaml 差距大再手工抄值（脚本不改 yaml 的版面先验）")


def st_glyphdb(ctx):
    sh(ctx, ctx.guji("glyph-db", "rebuild", "-w", ctx.ws, "--no-borrow"))
    for ed in ("font:jigmo", "font:iming"):
        bg_wait(ctx, ctx.guji("glyph-db", "import-font", "-w", ctx.ws, "--edition", ed, "--jobs", ctx.jobs), "import-" + ed.split(":")[1])
    sh(ctx, ctx.guji("glyph-db", "stats", "-w", ctx.ws))


def st_cache_verify(ctx):
    sh(ctx, ctx.guji("cache", "verify", "--book", ctx.book, "-w", ctx.ws), retries=0, check=False)
    rc, out = sh(ctx, ctx.guji("cache", "verify", "--book", ctx.book, "--fix", "-w", ctx.ws), retries=0, check=False)


def st_rare(ctx):
    js = status_json(ctx)
    need = "rare_candidates" in json.dumps(js, ensure_ascii=False)
    if not need:
        ctx.log("无 rare_candidates 步，跳过")
        return
    sh(ctx, ctx.guji("cache", "build-rare-index", "--book", ctx.book, "--jobs", ctx.jobs, "-w", ctx.ws))  # 已有表自动跳过
    sh(ctx, ctx.guji("cache", "warm", "--book", ctx.book, "--pages", "all", "--jobs", ctx.jobs, "-w", ctx.ws))
    bg_wait(ctx, ctx.guji("pipeline", "keben_body_v2", ctx.book, *_pages_all(ctx), "--from", "rare_candidates", "--to", "rare_candidates"), "rare")


def st_compute_b(ctx):
    # S5-b 已在前：一次 --from glyph_match 到 seed_admit，少一次重落
    bg_wait(ctx, ctx.guji("pipeline", "keben_body_v2", ctx.book, *_pages_all(ctx), "--from", "glyph_match", "--jobs", ctx.jobs), "compute-b", poll=30)
    js = status_json(ctx)
    ctx.st["after_compute"] = {"closure_gaps": js.get("closure_gaps"), "closure_mismatches": js.get("closure_mismatches")}


def st_snap_pack(ctx):
    if os.environ.get("ZL_CLOUD") == "1":
        raise Skip("云端（ZL_CLOUD=1）不打快照")
    if os.environ.get("ZL_SNAP_PACK") != "1":
        raise Skip("未设 ZL_SNAP_PACK=1，不打快照")
    env = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.sparseCheckout", "GIT_CONFIG_VALUE_0": "false"}
    sh(ctx, ctx.guji("snap", "pack", ctx.book, "-w", ctx.ws, "--ws-repo", ctx.ws), env_extra=env)


def st_audit(ctx):
    sh(ctx, ctx.guji("collate", ctx.book, "--console", "", "-w", ctx.ws))
    sh(ctx, ctx.guji("audit", "admitted", ctx.book, "-w", ctx.ws))
    out = ctx.reports / "_export"
    sh(ctx, ctx.guji("export", "format", ctx.book, "-w", ctx.ws, "--out", out), check=False)  # 只为出 lines.md 给 jys 用
    sh(ctx, ctx.guji("audit", "jys", ctx.book, "-w", ctx.ws, "--export-dir", out), check=False)


# ───────── S8 看图联系页 ─────────
CELL_ID = re.compile(r"^(?P<book>[^:]+):(?P<page>\d+):(?P<col>\d+):(?P<slot>\d+)(?P<sub>[ab])?$")


def parse_cell_id(cid: str):
    """`vol06:12:3:5` / `…:5a` → (page, col, slot, sub)；格式不对返回 None。"""
    m = CELL_ID.match(cid or "")
    return (int(m["page"]), int(m["col"]), int(m["slot"]), m["sub"] or "") if m else None


def contact_window(boxes: list, pos: int, around: int = 1, pad: int = 6, height: int | None = None):
    """boxes = 同列按 slot 排好的 bbox_col；取第 pos 格及其上下各 around 格的 y 范围（列图坐标）。"""
    lo, hi = max(0, pos - around), min(len(boxes), pos + around + 1)
    ys = [b[1] for b in boxes[lo:hi]] + [b[3] for b in boxes[lo:hi]]
    y0, y1 = int(min(ys)) - pad, int(max(ys)) + pad
    if height is not None:
        y0 = max(0, min(height - 1, y0))
        y1 = max(y0 + 1, min(height, y1))
    return max(0, y0), y1


def contact_rows(admitted_json: dict) -> list[dict]:
    """放行错穷举 JSON 里「认字差异」档（要逐格看图的）。"""
    return [r for r in admitted_json.get("rows", []) if r.get("tier") == "real"]


def render_contact_tile(col_img, y0: int, y1: int, box, num: int, tile_h: int = 360):
    """列图（灰度）切 y0..y1，目标格 box 画框，左上角写序号；高度统一成 tile_h。返回 BGR ndarray。"""
    import cv2
    crop = cv2.cvtColor(col_img[y0:y1], cv2.COLOR_GRAY2BGR) if col_img.ndim == 2 else col_img[y0:y1].copy()
    cv2.rectangle(crop, (int(box[0]), int(box[1]) - y0), (int(box[2]), int(box[3]) - y0), (0, 0, 255), 2)
    sc = tile_h / max(1, crop.shape[0])
    crop = cv2.resize(crop, (max(1, int(crop.shape[1] * sc)), tile_h), interpolation=cv2.INTER_AREA)
    cv2.putText(crop, str(num), (2, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
    return crop


def compose_contact(tiles: list, per_row: int = 8, gap: int = 6):
    """把等高的 tile 横排成行、行再竖叠，白底。"""
    import numpy as np
    rows = [tiles[i:i + per_row] for i in range(0, len(tiles), per_row)]
    h = tiles[0].shape[0]
    W = max(sum(t.shape[1] for t in r) + gap * (len(r) + 1) for r in rows)
    canvas = np.full(((h + gap) * len(rows) + gap, W, 3), 255, np.uint8)
    for ri, r in enumerate(rows):
        x = gap
        for t in r:
            y = gap + ri * (h + gap)
            canvas[y:y + h, x:x + t.shape[1]] = t
            x += t.shape[1] + gap
    return canvas


def contact_md(book: str, entries: list[dict], sheets: list[str]) -> str:
    out = [f"# {book} 看图联系页（S8：认字差异逐格看图）", "",
           f"- 共 {len(entries)} 格，{len(sheets)} 页；每格图 = 引擎列图（Step2 column_image，未收框），红框是被判的格，框上下各带一格；",
           "- 序号见图左上角；结论写 `看图结论.jsonl`（格式见 `open_guji_cv/feedback/vision.py`）。", "",
           "| 序号 | 联系页 | 字位 | 放行字 | 证人 | 上下文 |", "|---|---|---|---|---|---|"]
    for e in entries:
        sh_ = sheets[e["sheet_idx"]] if "sheet_idx" in e else "—"
        wit = "；".join(f"{k}:{v}" for k, v in (e.get("witness") or {}).items())
        out.append(f"| {e['n']} | {sh_} | `{e['id']}` | {e.get('char') or ''} | {wit} | {e.get('ctx') or ''} |"
                   + ("" if e.get("ok", True) else f" ⚠ {e.get('why','')}"))
    return "\n".join(out) + "\n"


#: 联系页单格失败占比超过它，整步判失败（全失败必然超）。个别格找不到字框是常事，成片失败说明环境或产物坏了。
CONTACT_MAX_FAIL = 0.2


def contact_verdict(entries: list[dict]) -> tuple[int, float, list[tuple[str, int]]]:
    """(失败格数, 失败率, 按原因计数从多到少)。"""
    from collections import Counter
    bad = [e for e in entries if not e.get("ok")]
    why = Counter(e.get("why") or "未知" for e in bad)
    return len(bad), (len(bad) / len(entries) if entries else 0.0), why.most_common()


def check_contact(ctx, entries: list[dict], md_path=None):
    nbad, rate, why = contact_verdict(entries)
    if not nbad:
        return
    if rate > CONTACT_MAX_FAIL:
        write_next(ctx, f"联系页失败 {nbad}/{len(entries)} 格（{rate:.0%}），超过 {CONTACT_MAX_FAIL:.0%}", [
            "失败原因（次数）：", *[f"- {w}：{n}" for w, n in why[:8]],
            f"明细见 `{md_path}`（⚠ 行）。常见原因：产物缺（先确认 cell_shrink 产物在 GUJI_PRODUCTS_DIR／<ws>/products）、列图缓存读不出来、环境缺件。修好后 `zl.py run --only contact`。"])
        raise Stop(f"联系页 {nbad}/{len(entries)} 格失败")
    ctx.log(f"⚠ 联系页 {nbad}/{len(entries)} 格失败（{rate:.0%}，未超 {CONTACT_MAX_FAIL:.0%}）：{why[:3]}")


def build_contact_sheets(ctx, per: int = 24) -> Path | None:
    """读 `<册>.放行错穷举.json`，给认字差异每格出一块「列图 + 上下各一格」，拼成联系页 PNG 并写索引 md。"""
    import cv2
    import open_guji_cv.steps  # noqa: F401  注册产物种类（char_index 等）；不 import 则每格 KeyError「未注册的产物种类」
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.spec import column_key, page_key
    from open_guji_cv.core.step import RunContext
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.store import ProductStore
    from open_guji_cv.utils.image_io import imread as cv_imread

    jf = ctx.reports / f"{ctx.book}.放行错穷举.json"
    if not jf.exists():
        raise Stop(f"没有 {jf.name}：先跑 audit 步")
    rows = contact_rows(json.loads(jf.read_text(encoding="utf-8")))
    outd = ctx.reports / "联系页"
    outd.mkdir(parents=True, exist_ok=True)
    if not rows:
        (outd / f"{ctx.book}.看图联系页.md").write_text(contact_md(ctx.book, [], []), encoding="utf-8")
        ctx.log("认字差异 0 格，无联系页")
        return None
    store, cache = ProductStore(), ImageCache()
    rc = RunContext(load_book(ctx.book), store, cache, log=lambda s: None)
    col_cache: dict = {}
    entries, tiles = [], []
    for n, r in enumerate(rows, 1):
        e = {"n": n, "id": r["id"], "char": r.get("char"), "witness": r.get("witness"), "ctx": r.get("ctx"), "ok": False}
        entries.append(e)
        pid = parse_cell_id(r["id"])
        if not pid:
            e["why"] = "字位格式不识"
            continue
        page, col, slot, sub = pid
        try:
            ci = store.read(ctx.book, "cell_shrink", page_key(page), "char_index")
            cc = ci.column(col) if ci else None
            recs = sorted(cc.chars, key=lambda x: (x.slot, x.sub or "")) if cc else []
            pos = next((k for k, x in enumerate(recs) if x.slot == slot and (x.sub or "") == sub), None)
            if pos is None:
                e["why"] = "没有这一格的字框"
                continue
            if (page, col) not in col_cache:
                col_cache[(page, col)] = cv_imread(str(rc.materialize("column_image", column_key(page, col))), cv2.IMREAD_GRAYSCALE)
            img = col_cache[(page, col)]
            if img is None:
                e["why"] = "列图读不出来"
                continue
            y0, y1 = contact_window([x.bbox_col for x in recs], pos, 1, height=img.shape[0])
            tiles.append(render_contact_tile(img, y0, y1, recs[pos].bbox_col, n))
            e["ok"] = True
        except Exception as ex:  # noqa: BLE001  单格失败只标注，不拖垮整册
            e["why"] = f"{type(ex).__name__}: {ex}"
    sheets = []
    ok_entries = [e for e in entries if e["ok"]]
    # 失败的格不出图：联系页按成功项分页，索引里的「联系页」列记各成功格落在哪一页
    for si in range(0, len(tiles), per):
        name = f"{ctx.book}.联系页{si // per + 1:02d}.png"
        cv2.imwrite(str(outd / name), compose_contact(tiles[si:si + per]))
        sheets.append(name)
    for k, e in enumerate(ok_entries):
        e["sheet_idx"] = k // per
    md = contact_md(ctx.book, entries, sheets)
    mdp = outd / f"{ctx.book}.看图联系页.md"
    mdp.write_text(md, encoding="utf-8")
    ctx.log(f"联系页：{len(ok_entries)}/{len(rows)} 格成图，{len(sheets)} 页 → {outd}")
    check_contact(ctx, entries, mdp)
    return mdp


def st_contact(ctx):
    """S8 机器部分之二：认字差异逐格出看图联系页（供会话/人看图）。"""
    os.environ.setdefault("GUJI_WORKSPACE", str(ctx.ws))
    build_contact_sheets(ctx)


def st_vision_gate(ctx):
    """闸：看图结论要模型或人看图。有 看图结论.jsonl 就导入，没有就停下写清要看什么。"""
    jl = ctx.reports / "看图结论.jsonl"
    if not jl.exists():
        write_next(ctx, "要看图（S8 / S10）", [
            f"1. 读 `reports/{ctx.book}/{ctx.book}.放行错穷举.md` 的「认字差异」档，逐格看图（带上下文、放大）；",
            f"2. 按 runbook S8 分层再抽 300 格；己已巳读 `{ctx.book}.己已巳.md` 按文意判；",
            f"3. 结论写 `reports/{ctx.book}/看图结论.jsonl`（`ts` 要填；格式见 `open_guji_cv/feedback/vision.py`），再 `zl.py run --only vision-gate`。",
        ])
        raise Gate("等看图结论")
    sh(ctx, ctx.guji("events", "import-vision", jl, "--book", ctx.book, "--dry-run", "-w", ctx.ws))
    sh(ctx, ctx.guji("events", "import-vision", jl, "--book", ctx.book, "-w", ctx.ws))


class Gate(Exception):
    pass


def st_sheet(ctx):
    sh(ctx, ctx.guji("audit", "sheet", ctx.book, "-w", ctx.ws))
    write_next(ctx, "请审单已生成，等用户审", [
        f"`reports/{ctx.book}/{ctx.book}.请审单.md`；第 4 节（看图改判/看不清）要手工追加。",
        f"审完：`zl.py run --only human-count --since <请审单时刻>`，再 `zl.py run --from export`。",
    ])
    raise Gate("等人审（请审单）")


def st_human_count(ctx):
    since = os.environ.get("ZL_SINCE")
    if not since:
        raise Stop("设 ZL_SINCE=<请审单发出的时间> 再跑")
    sh(ctx, ctx.guji("audit", "count", ctx.book, "-w", ctx.ws, "--since", since))


def products_dir(ctx) -> Path:
    """产物根：GUJI_PRODUCTS_DIR（沙箱/快照）> <ws>/products，与引擎同口径。"""
    env = os.environ.get("GUJI_PRODUCTS_DIR")
    return Path(env).expanduser() if env else ctx.ws / "products"


def st_export(ctx):
    if ctx.st.get("human_verdicts"):
        sh(ctx, ctx.guji("pipeline", "keben_body_v2", ctx.book, *_pages_all(ctx), "--from", "seed_admit"))
    num = re.sub(r"\D", "", ctx.book).zfill(3)
    out = ctx.reports / "_export"
    cmd = [ctx.venv_py, "scripts/export_guji_format.py", "--products", products_dir(ctx), "--book", ctx.book, "--chapter", num,
           "--out", out, "--format", "char-cord", "--keys", "cv"]
    meta = CV / f"doc/formats/samples/guji_format_v0.1/meta_{ctx.book}.json"
    if meta.exists():
        cmd += ["--meta", meta]
    split = CV / "doc/formats/samples/guji_page_v0.2/split_table_siku.json"
    if split.exists():
        cmd += ["--split-table", split]
    sh(ctx, cmd)
    sh(ctx, ctx.guji("export", "md", ctx.book, "-w", ctx.ws))


def st_taboo(ctx):
    """避諱改字表 v0：从 lines.md 数避諱三组与同字异码，生成归档表（不改任何放行字）。"""
    lines = next(iter((ctx.reports / "_export").glob("*.lines.md")), None)
    if not lines:
        raise Stop("没有 lines.md，先跑 audit")
    t = re.sub(r"<!--.*?-->|\s", "", lines.read_text(encoding="utf-8"))
    groups = [("玄→元（避玄燁）", "元", "玄"), ("弘→宏（避弘曆）", "宏", "弘"), ("曆→厯／歴", "厯歴", "曆歷")]
    rows = ["| 组 | 刻本字（计数） | 回改字（计数） |", "|---|---|---|"]
    for name, a, b in groups:
        rows.append(f"| {name} | " + "、".join(f"{c} {t.count(c)}" for c in a) + " | " + "、".join(f"{c} {t.count(c)}" for c in b) + " |")
    pairs = [("㫖", "旨"), ("卽", "即"), ("𠮓", "變"), ("淸", "清"), ("曰", "日"), ("啓", "啟")]
    rows += ["", "| 同字异码 | 计数 |", "|---|---|"] + [f"| {x} / {y} | {x} {t.count(x)}、{y} {t.count(y)} |" for x, y in pairs]
    nd = Path(os.environ.get("ZL_NOTES") or ctx.reports) / ("避諱改字表-v0.md")
    nd.parent.mkdir(parents=True, exist_ok=True)
    nd.write_text(f"# 避諱／改字对照表 v0：{ctx.book}\n\n- 数据：lines.md，{len(t)} 字元；本表只归档，不改放行字。计数是机器数，**抽读上下文判是否真避諱**由人/会话补。\n\n" + "\n".join(rows) + "\n", encoding="utf-8")
    ctx.log(f"避諱表 → {nd}")


def st_close(ctx):
    cmd = ctx.guji("close-check", ctx.book, "-w", ctx.ws, "--export-dir", ctx.reports / "_export")
    if os.environ.get("ZL_NOTES"):
        cmd += ["--notes", os.environ["ZL_NOTES"]]
    rc, out = sh(ctx, cmd, check=False, retries=0)
    (ctx.reports / "close-check.out.txt").write_text(out, encoding="utf-8")
    ctx.log("close-check rc=%s；输出在 reports/%s/close-check.out.txt" % (rc, ctx.book))


# (名, 函数, 说明, 云端/本地)  ——按顺序
STAGES = [
    ("env", st_env, "S1 装环境（含 shadow extra、自检 joblib/sklearn）"),
    ("ws", st_ws, "S2 稀疏克隆 ws、钉提交、设 noreply 邮箱"),
    ("yaml", st_yaml, "S3 合并标准 Step7 开关"),
    ("import-snap", st_import_snap, "（可选）从快照分支起步，容忍 CRLF"),
    ("survey", st_survey, "S4 预检"),
    ("compute-a", st_compute_a, "S5 Step1–4 整册（后台）"),
    ("calibrate", st_calibrate, "S3 回头核版面先验"),
    ("glyphdb", st_glyphdb, "S6 建库（与 Step1–4 错开）"),
    ("cache-verify", st_cache_verify, "S7 缓存校验"),
    ("rare", st_rare, "S5-b 备表、预渲、候选（有该步才跑）"),
    ("compute-b", st_compute_b, "S5 Step5–7 一次到 seed_admit（后台）"),
    ("snap-pack", st_snap_pack, "推快照（需 ZL_SNAP_PACK=1；ZL_CLOUD=1 时一律跳过）"),
    ("audit", st_audit, "S8/S9/S10 机器部分：对勘、穷举、己已巳"),
    ("contact", st_contact, "S8 看图联系页：认字差异每格（列图＋上下各一格）"),
    ("vision-gate", st_vision_gate, "【闸】看图结论：有 jsonl 就导入，没有就停"),
    ("sheet", st_sheet, "S11 请审单；停在【闸】等人"),
    ("human-count", st_human_count, "S12 人裁核数（用户审完后）"),
    ("export", st_export, "S16/S17 导出 char/cord/norm、md"),
    ("taboo", st_taboo, "第 7 项：避諱改字表 v0"),
    ("close", st_close, "S20 close-check"),
]
# 默认 run 跳过这些（要显式 --only 或 --from 才跑）
MANUAL = {"human-count"}


def child_args(a) -> list[str]:
    """`run --bg` 转发给后台子进程的参数：由解析结果重建（--bg 除外），不靠 sys.argv 切片——
    切片只带得走 `--bg` 之后的参数，`--only/--from/--to/--redo` 写在前面就丢了，整套重放。"""
    out = ["run", "--book", a.book, "--ws", str(a.ws)]
    if getattr(a, "jobs", 0):
        out += ["--jobs", str(a.jobs)]
    for flag, val in (("--snap", a.snap), ("--only", a.only), ("--from", a.from_), ("--to", a.to),
                      ("--redo", a.redo), ("--preset", getattr(a, "preset", None))):
        if val:
            out += [flag, str(val)]
    if getattr(a, "no_shadow_veto", False):
        out.append("--no-shadow-veto")
    return out


def ensure_venv_python(ctx):
    """已有 .venv 而当前不是它的 python 时，原参数换 venv 的 python 重启（状态文件让已完成步自动跳过）。
    ZL_NO_REEXEC=1 关闭（测试用）。"""
    if os.environ.get("ZL_NO_REEXEC") == "1" or not ctx.venv_py or ctx.venv_py == sys.executable:
        return
    if (CV / ".venv").exists() and Path(sys.prefix).resolve() != (CV / ".venv").resolve():
        ctx.log(f"换 venv python 重启：{ctx.venv_py}")
        os.execv(ctx.venv_py, [ctx.venv_py, *sys.argv])


def cmd_run(a):
    ctx = Ctx(a)
    ensure_venv_python(ctx)
    if a.bg:
        args = [ctx.venv_py, __file__, *child_args(a)]
        lf = ctx.log_f.with_name(f"{ctx.book}.driver.log")
        subprocess.Popen(args, stdout=lf.open("ab"), stderr=subprocess.STDOUT, start_new_session=True)
        print(f"已后台启动，日志 {lf}；看进度：zl.py status --book {a.book} --ws {a.ws}")
        return 0
    names = [s[0] for s in STAGES]
    if a.only:
        todo = [a.only]
    else:
        i = names.index(a.from_) if a.from_ else 0
        j = names.index(a.to) + 1 if a.to else len(names)
        todo = [n for n in names[i:j] if n not in MANUAL or a.from_ == n]
    for n in todo:
        fn = dict((s[0], s[1]) for s in STAGES)[n]
        rec = ctx.st["stages"].get(n, {})
        if rec.get("ok") and n != a.redo and not a.only:
            ctx.log(f"跳过 {n}（已完成 {rec['end']}）")
            continue
        ensure_venv_python(ctx)
        ctx.log(f"▶ {n}")
        t0 = time.time()
        rec = {"start": now()}
        try:
            fn(ctx)
            rec.update(ok=True, end=now(), sec=round(time.time() - t0))
        except Gate as e:
            rec.update(ok=False, gate=str(e), end=now(), sec=round(time.time() - t0))
            ctx.st["stages"][n] = rec
            ctx.save()
            ctx.log(f"■ 停在闸：{e}。看 reports/{ctx.book}/NEXT.md")
            return 0
        except Skip as e:
            rec.update(ok=False, skipped=str(e), end=now(), sec=round(time.time() - t0))
            ctx.st["stages"][n] = rec
            ctx.save()
            ctx.log(f"– 已跳过 {n}：{e}")
            continue
        except Stop as e:
            rec.update(ok=False, err=str(e), end=now(), sec=round(time.time() - t0))
            ctx.st["stages"][n] = rec
            ctx.save()
            ctx.log(f"✗ 停：{e}。看 reports/{ctx.book}/NEXT.md；修好后原样重跑即可续上")
            return 1
        except Exception as e:  # noqa: BLE001  未预料的崩溃也要落 NEXT.md，不能只留一屏 traceback
            import traceback
            tb = traceback.format_exc()
            rec.update(ok=False, err=f"崩溃 {type(e).__name__}: {e}", end=now(), sec=round(time.time() - t0))
            ctx.st["stages"][n] = rec
            ctx.save()
            write_next(ctx, f"步 {n} 崩溃（{type(e).__name__}）", ["```", tb[-2500:], "```"])
            ctx.log(f"✗ 崩溃：{n}：{e}。看 reports/{ctx.book}/NEXT.md")
            return 1
        ctx.st["stages"][n] = rec
        ctx.save()
    ctx.log("全部完成" + (f"（已跳过：{'、'.join(k for k, v in ctx.st['stages'].items() if v.get('skipped'))}）" if any(v.get('skipped') for v in ctx.st['stages'].values()) else ""))
    return 0


def cmd_plan(a):
    ctx = Ctx(a)
    print(f"配置：{preset_label(ctx)}")
    for n, _, d in STAGES:
        r = ctx.st["stages"].get(n, {})
        mark = "✓" if r.get("ok") else ("■" if r.get("gate") else ("✗" if r.get("err") else ("–" if r.get("skipped") else "·")))
        print(f"{mark} {n:13} {d}" + (f"  [{r.get('sec','')}s]" if r else ""))


def cmd_status(a):
    ctx = Ctx(a)
    cmd_plan(a)
    if ctx.log_f.exists():
        print("\n最近日志：\n" + "\n".join(ctx.log_f.read_text(encoding="utf-8", errors="replace").splitlines()[-8:]))


def cmd_intervene(a):
    ctx = Ctx(a)
    ctx.st["interventions"].append({"at": now(), "step": a.step, "why": a.why, "waited_min": a.waited_min})
    ctx.save()
    print("已记一次介入")


def cmd_metrics(a):
    ctx = Ctx(a)
    tot = sum(r.get("sec", 0) for r in ctx.st["stages"].values())
    print(f"| 步 | 开始 | 结束 | 秒 | 结果 |\n|---|---|---|---|---|")
    for n, _, _ in STAGES:
        r = ctx.st["stages"].get(n)
        if r:
            print(f"| {n} | {r['start']} | {r.get('end','')} | {r.get('sec','')} | {'ok' if r.get('ok') else ('已跳过：' + r['skipped'] if r.get('skipped') else r.get('gate') or r.get('err'))} |")
    print(f"\n纯算合计 {tot//60} 分；介入 {len(ctx.st['interventions'])} 次：")
    for i in ctx.st["interventions"]:
        print(f"- {i['at']} {i['step']}：{i['why']}（等 {i['waited_min']} 分）")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("run", cmd_run), ("plan", cmd_plan), ("status", cmd_status), ("intervene", cmd_intervene), ("metrics", cmd_metrics)):
        p = sp.add_parser(name)
        p.add_argument("--book", required=True)
        p.add_argument("--ws")
        p.add_argument("--jobs", type=int, default=0)
        p.add_argument("--snap")
        p.set_defaults(fn=fn)
        if name == "run":
            p.add_argument("--bg", action="store_true")
            p.add_argument("--only")
            p.add_argument("--from", dest="from_")
            p.add_argument("--to")
            p.add_argument("--redo")
            p.add_argument("--preset", choices=sorted(PRESETS), help="显式开关预设（默认不启用）；siku＝四庫 vol04/vol05 验过的一组")
            p.add_argument("--no-shadow-veto", action="store_true", help="预设里关掉 shadow_veto（vol04 用）")
        if name == "intervene":
            p.add_argument("--step", required=True)
            p.add_argument("--why", required=True)
            p.add_argument("--waited-min", type=float, default=0)
    a = ap.parse_args(argv)
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
