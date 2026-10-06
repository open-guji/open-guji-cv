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


def sh(ctx: Ctx, cmd, cwd=None, env_extra=None, retries=2, lowjobs_fix=None, check=True):
    """跑一条命令：失败分类、自动重试。返回 (rc, 输出末 4000 字)。"""
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
            return 0, out[-4000:]
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
            return fail(ctx, cmd, p.returncode, out, why, check)
        else:
            return fail(ctx, cmd, p.returncode, out, "未分类失败", check)
    return fail(ctx, cmd, 1, "", "重试用尽", check)


def pip_cmd(ctx, pkg):
    uv = shutil.which("uv")
    return [uv, "pip", "install", "--python", ctx.venv_py, pkg] if uv else [ctx.venv_py, "-m", "pip", "install", pkg]


class Stop(Exception):
    pass


def fail(ctx, cmd, rc, out, why, check):
    ctx.log(f"✗ rc={rc}：{why}")
    if check:
        write_next(ctx, f"命令失败（{why}）", ["命令：`" + " ".join(cmd) + "`", "输出末尾：", "```", out[-1500:], "```"])
        raise Stop(why)
    return rc, out[-4000:]


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


def status_json(ctx):
    rc, out = sh(ctx, ctx.guji("status", ctx.book, "--pages", "all", "--json", "-w", ctx.ws), check=False)
    i = out.find("{")
    return json.loads(out[i:]) if i >= 0 else {}


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


def st_ws(ctx):
    if not (ctx.ws / ".git").exists():
        url = os.environ.get("ZL_WS_URL", "https://github.com/open-guji-core/guji-workspace")
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


def st_yaml(ctx):
    """把标准 Step7 开关合并进书 yaml（ruamel 往返，保留注释与排版）：已有键保留，标准键覆盖同名项。"""
    try:
        from ruamel.yaml import YAML
    except ImportError:
        sh(ctx, pip_cmd(ctx, "ruamel.yaml"))
        write_next(ctx, "已补装 ruamel.yaml", ["请用 venv 的 python 重跑本脚本（`.venv/bin/python scripts/zhengli/zl.py run ...`）。"])
        raise Stop("需用 venv python 重跑")
    import io
    f = ctx.ws / "books" / f"{ctx.book}.yaml"
    if not f.exists():
        write_next(ctx, "缺书 yaml", [f"`{f}` 不存在。拷一份同类册的 yaml 改册号、page_split、版面先验；缺 `period_prior` 会被闸 2/3 拦。"])
        raise Stop("缺书 yaml")
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    d = y.load(f.read_text(encoding="utf-8"))
    changed = {}
    if d.get("iron_gate") is not True:
        changed["iron_gate"] = (d.get("iron_gate"), True)
        d["iron_gate"] = True
    if d.get("params") is None:
        d["params"] = {}
    if d["params"].get("seed_admit") is None:
        d["params"]["seed_admit"] = {}
    sa = d["params"]["seed_admit"]
    for k, v in STD_SEED_ADMIT.items():
        if sa.get(k) != v:
            changed[k] = (sa.get(k), v)
            sa[k] = v
    if changed:
        import difflib
        buf = io.StringIO()
        y.dump(d, buf)
        old_t = f.read_text(encoding="utf-8")
        removed = [l for l in difflib.unified_diff(old_t.splitlines(), buf.getvalue().splitlines(), lineterm="", n=0) if l.startswith("-") and not l.startswith("---")]
        if removed:  # 往返会重排原文：不写，交人（或会话）用 Edit 手贴最小片段，免得 diff 淹没真改动
            snip = ctx.reports / "yaml-标准开关.片段.yaml"
            ctx.reports.mkdir(parents=True, exist_ok=True)
            snip.write_text("iron_gate: true\nparams:\n  seed_admit:\n" + "".join(f"    {k}: {str(v).lower() if isinstance(v, bool) else v}\n" for k, v in STD_SEED_ADMIT.items()), encoding="utf-8")
            write_next(ctx, "书 yaml 需手贴标准开关", [f"自动改会重排原文 {len(removed)} 行，已放弃。把 `{snip}` 里的键合并进 `{f}`（已有同名键以片段为准，其余键与注释保持原样），然后原样重跑。"])
            raise Stop("书 yaml 需手贴开关")
        f.write_text(buf.getvalue(), encoding="utf-8")
        ctx.log(f"yaml 已合并标准开关，改动项：{changed}")
    else:
        ctx.log("yaml 已是标准开关")
    txt = f.read_text(encoding="utf-8")
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
    if os.environ.get("ZL_CLOUD") != "1":
        ctx.log("非云端（未设 ZL_CLOUD=1），不打快照")
        return
    env = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.sparseCheckout", "GIT_CONFIG_VALUE_0": "false"}
    sh(ctx, ctx.guji("snap", "pack", ctx.book, "-w", ctx.ws, "--ws-repo", ctx.ws), env_extra=env)


def st_audit(ctx):
    sh(ctx, ctx.guji("collate", ctx.book, "--console", "", "-w", ctx.ws))
    sh(ctx, ctx.guji("audit", "admitted", ctx.book, "-w", ctx.ws))
    out = ctx.reports / "_export"
    sh(ctx, ctx.guji("export", "format", ctx.book, "-w", ctx.ws, "--out", out), check=False)  # 只为出 lines.md 给 jys 用
    sh(ctx, ctx.guji("audit", "jys", ctx.book, "-w", ctx.ws, "--export-dir", out), check=False)


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


def st_export(ctx):
    if ctx.st.get("human_verdicts"):
        sh(ctx, ctx.guji("pipeline", "keben_body_v2", ctx.book, *_pages_all(ctx), "--from", "seed_admit"))
    num = re.sub(r"\D", "", ctx.book).zfill(3)
    out = ctx.reports / "_export"
    cmd = [ctx.venv_py, "scripts/export_guji_format.py", "--products", ctx.ws / "products", "--book", ctx.book, "--chapter", num,
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
    ("snap-pack", st_snap_pack, "云端：推快照（ZL_CLOUD=1）"),
    ("audit", st_audit, "S8/S9/S10 机器部分：对勘、穷举、己已巳"),
    ("vision-gate", st_vision_gate, "【闸】看图结论：有 jsonl 就导入，没有就停"),
    ("sheet", st_sheet, "S11 请审单；停在【闸】等人"),
    ("human-count", st_human_count, "S12 人裁核数（用户审完后）"),
    ("export", st_export, "S16/S17 导出 char/cord/norm、md"),
    ("taboo", st_taboo, "第 7 项：避諱改字表 v0"),
    ("close", st_close, "S20 close-check"),
]
# 默认 run 跳过这些（要显式 --only 或 --from 才跑）
MANUAL = {"human-count"}


def cmd_run(a):
    ctx = Ctx(a)
    if a.bg:
        args = [sys.executable, __file__, "run", "--book", a.book, "--ws", str(a.ws)] + [x for x in sys.argv[sys.argv.index("--bg") + 1:] if x != "--bg"]
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
        except Stop as e:
            rec.update(ok=False, err=str(e), end=now(), sec=round(time.time() - t0))
            ctx.st["stages"][n] = rec
            ctx.save()
            ctx.log(f"✗ 停：{e}。看 reports/{ctx.book}/NEXT.md；修好后原样重跑即可续上")
            return 1
        ctx.st["stages"][n] = rec
        ctx.save()
    ctx.log("全部完成")
    return 0


def cmd_plan(a):
    ctx = Ctx(a)
    for n, _, d in STAGES:
        r = ctx.st["stages"].get(n, {})
        mark = "✓" if r.get("ok") else ("■" if r.get("gate") else ("✗" if r.get("err") else "·"))
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
            print(f"| {n} | {r['start']} | {r.get('end','')} | {r.get('sec','')} | {'ok' if r.get('ok') else r.get('gate') or r.get('err')} |")
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
        if name == "intervene":
            p.add_argument("--step", required=True)
            p.add_argument("--why", required=True)
            p.add_argument("--waited-min", type=float, default=0)
    a = ap.parse_args(argv)
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
