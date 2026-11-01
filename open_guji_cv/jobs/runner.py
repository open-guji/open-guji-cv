"""执行方：从任务库领单，按 spec 一口气跑完（准备 → 铺底 → 检查 → 跑 → 对比 → 存包），每步记进库。

只在云端执行会话里跑（Default 环境：/opt/guji-cv-seed 是 cv 检出、/opt/guji-venv 是装好的环境）。
本模块自己从另一份检出（/opt/guji-runner，跟 dev）运行：任务要的 cv 版本切的是 seed，不会把执行方自己切没了。
任务的每条命令都用 /opt/guji-venv/bin/guji、去掉 PYTHONPATH 跑，所以跑的是任务点名的那版 cv。

不推中心库、不标 main、不改仓库；存包只用 `--change`（缺省 job<号>）。凭据只从本进程环境取，不写进库与日志。
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

from . import board as BOARD
from . import spec as SP
from . import store as S

SEED = Path(os.environ.get("GUJI_JOBS_SEED", "/opt/guji-cv-seed"))
VENV = Path(os.environ.get("GUJI_JOBS_VENV", "/opt/guji-venv"))
HOME = Path(os.environ.get("GUJI_JOBS_HOME", str(Path.home() / ".guji-jobs")))
RUNNER_ROOT = Path(__file__).resolve().parents[2]       # 执行方自己的 cv 检出（rerun_prep.sh 取这里的，跟 dev）
HEARTBEAT_S = 60
#: rerun_prep.sh 里失败多半是网络／库的段（失败了换个会话重试）；其余段（钉子账、建字形库、语料校验…）是配置问题
_PREP_ENV_PARTS = {"cv", "克隆工作区", "db-pull", "取原图", "模板索引", "基线包"}
_TOKEN_RE = re.compile(r"(TOKEN|SECRET|KEY|PASS|DSN)[A-Z_]*=\S+|postgres(ql)?://\S+|Bearer \S+", re.I)


def resolve_ws_repo(sp: dict) -> str | None:
    """这单的工作区仓：单子存的 ws_repo 优先；空的（提交时没映射上、或书 ID 后来才登记）就按册 ID 现查 WS_REPOS。
    都没有返回 None，prep 退回 open-guji/guji-workspace 里 ws_glob 匹配的目录。"""
    return sp.get("ws_repo") or SP.WS_REPOS.get(SP.book_id(sp) or "") or None


class StageError(Exception):
    """一段没过。`env` 为真表示多半是网络／库的毛病，换个会话重试；否则是配置或代码问题，等人看。"""

    def __init__(self, outcome: str, msg: str, code: int | None = None, env: bool = False):
        super().__init__(msg)
        self.outcome, self.code, self.env = outcome, code, env


def _why(lines: list[str]) -> str:
    """失败输出里最能说明原因的一行：最后一条异常／✗ 行，没有就最后一行非空的。全文在日志里。"""
    keep = [ln.strip() for ln in lines if ln.strip()]
    for ln in reversed(keep[-200:]):
        if re.match(r"^([\w.]+(Error|Exception|Drift|Exit)\b|✗|SystemExit)", ln) or "错误" in ln:
            return redact(ln)[:1500]
    return redact(keep[-1])[:1500] if keep else "（没有输出）"


# 连库、连桥断了（Neon 休眠、443 桥掉线）：DB 包装层重连 6 次仍不通时异常会冒到这里，算环境类，换个会话再试
_CONN_ERRORS = {"OperationalError", "InterfaceError", "ConnectionClosed", "ConnectionClosedError", "ConnectionClosedOK"}


def _is_conn_error(e: BaseException) -> bool:
    return any(c.__name__ in _CONN_ERRORS for c in type(e).__mro__)


class Cancelled(Exception):
    pass


def redact(s: str) -> str:
    return _TOKEN_RE.sub(lambda m: m.group(0).split("=")[0] + "=***" if "=" in m.group(0) else "***", s)


def _token(name: str) -> str | None:
    v = os.environ.get(name)
    if v and v.startswith("$"):                 # 面板里写成 $GUJI_DATA_TOKEN_PROD 的字面量
        v = os.environ.get(v.strip("${}"))
    return v or None


class Job:
    """跑一条单。`db` 是主线程的库连接（`store.DB`，断线自动重连）；心跳另开一条连接在后台线程里。"""

    def __init__(self, job: dict, attempt: dict, db: S.DB, *, dry: bool = False):
        self.job, self.att, self.db, self.dry = job, attempt, db, dry
        self.spec = job["spec"]
        self.id, self.aid = job["id"], attempt["id"]
        self.dir = HOME / f"job{self.id}-a{attempt['n']}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.log = (self.dir / "run.log").open("a", encoding="utf-8")
        self.stage = "claimed"
        self.progress: str | None = None
        self.proc: subprocess.Popen | None = None
        self.cancel = threading.Event()
        self.ws: str | None = None
        self._stop = threading.Event()

    # ── 心跳 ──
    def _beat(self) -> None:
        db = S.DB(self.db.factory)
        while not self._stop.wait(HEARTBEAT_S):
            try:
                db(S.worker_seen, S.who(), state="busy", job_id=self.id)
                BOARD.publish(db)
                if db(S.heartbeat, self.aid, stage=self.stage, progress=self.progress):
                    self.cancel.set()
                    if self.proc and self.proc.poll() is None:
                        os.killpg(self.proc.pid, signal.SIGTERM)
            except Exception as e:      # noqa: BLE001 —— 断网时下一拍再续；租约 10 分钟，断几拍不丢单
                self._w(f"[心跳失败] {e}")
        db.close()

    def _w(self, line: str) -> None:
        self.log.write(redact(line).rstrip("\n") + "\n")
        self.log.flush()

    def ev(self, msg: str, *, level: str = "info", secs: float | None = None, data: dict | None = None) -> None:
        self._w(f"[{self.stage}] {msg}")
        self.db(S.event, self.id, self.aid, self.stage, redact(msg), level=level, secs=secs, data=data)

    # ── 跑一条命令 ──
    def env(self, *, write: bool = False) -> dict:
        e = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "VIRTUAL_ENV")}
        e.update(PYTHONIOENCODING="utf-8", PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK="True")
        e["PATH"] = f"{VENV / 'bin'}:{e.get('PATH', '')}"
        tok = _token("GUJI_DATA_TOKEN_PROD") if write else (_token("GUJI_DATA_TOKEN") or _token("GUJI_DATA_TOKEN_READ"))
        if tok:
            e["GUJI_DATA_TOKEN"] = tok
        if self.ws:
            e["GUJI_WORKSPACE"] = self.ws
        if self.spec.get("no_reuse"):
            e["GUJI_NO_REUSE"] = "1"
        e.update(self.spec.get("env") or {})
        return e

    def sh(self, argv: list[str], *, write: bool = False, ok=(0,), outcome: str = "failed") -> str:
        """跑一条命令（不经 shell），输出进日志，最后一行当进展。返回全部输出。"""
        if self.cancel.is_set():
            raise Cancelled()
        self._w("$ " + " ".join(shlex.quote(a) for a in argv))
        if self.dry:
            return ""
        self.proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                     env=self.env(write=write), cwd=str(self.dir), start_new_session=True,
                                     encoding="utf-8", errors="replace")
        buf: list[str] = []
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            buf.append(line)
            self._w(line)
            if line.strip():
                self.progress = redact(line.strip())[:300]
        code = self.proc.wait()
        self.proc = None
        if self.cancel.is_set():
            raise Cancelled()
        out = "".join(buf)
        if code not in ok:
            raise StageError(outcome, f"{argv[0].rsplit('/', 1)[-1]} {' '.join(argv[1:3])} 退出码 {code}：{_why(buf)}",
                             code)
        return out

    def guji(self, *args: str, **kw) -> str:
        return self.sh([str(VENV / "bin" / "guji"), *args], **kw)

    def step(self, name: str, fn) -> None:
        self.stage = name
        t0 = time.time()
        self.ev("开始")
        try:
            self.db(S.heartbeat, self.aid, stage=name, progress=None)
        except Exception:               # noqa: BLE001
            pass
        fn()
        self.ev("完成", secs=round(time.time() - t0, 1))

    # ── 各阶段 ──
    def prep(self) -> None:
        sp = self.spec
        sig = json.dumps({k: sp.get(k) for k in ("book", "cv", "book_overrides", "pin_args", "ws_glob", "ws_repo")},
                         sort_keys=True)
        mark = HOME / "prepped.json"
        try:
            last = json.loads(mark.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            last = {}
        if last.get("sig") == sig and last.get("ws") and Path(last["ws"]).is_dir():
            self.ws = last["ws"]
            self.ev(f"本会话已按同一配置备过（{sp['book']} cv {sp['cv'][:7]}），跳过准备")
            return
        if not sp.get("book"):          # eval／command 不带册：只切 cv
            self.checkout()
            return
        argv = ["bash", str(RUNNER_ROOT / "scripts" / "rerun_prep.sh"), sp["book"], "--cv", sp["cv"],
                "--ws-glob", sp["ws_glob"]]
        ws_repo = resolve_ws_repo(sp)
        if ws_repo:
            argv += ["--ws-repo", ws_repo]
        ov = sp.get("book_overrides") or {}
        if "corpus" in ov:
            argv += ["--corpus", str(ov["corpus"])]
        if "glyph_pin" in ov:
            argv += ["--glyph-pin", str(ov["glyph_pin"])]
        if sp.get("pin_args"):
            argv += ["--pin-args", sp["pin_args"]]
        if last:                        # 本会话备过别的：先把本机册配置、钉子账还原
            argv.append("--reset")
        if not self.dry:                # 先记「改过了」：准备半路失败，下一张单也要先还原
            mark.write_text(json.dumps({"sig": None, "ws": None}), encoding="utf-8")
        try:
            out = self.sh(argv, outcome="failed")
        except StageError as e:
            # 准备脚本每段先打「== 段名」：拉库、取图这类是环境问题（换会话重试），钉子账、建库、语料校验是配置问题（不重试）
            log = (self.dir / "run.log").read_text(encoding="utf-8", errors="replace")
            heads = re.findall(r"^== (\S+)", log, re.M)
            part = heads[-1] if heads else "?"
            raise StageError("failed", f"准备「{part}」段失败：{e}", e.code, env=part in _PREP_ENV_PARTS) from None
        m = re.search(r"^WS=(\S+)", out, re.M)
        self.ws = m.group(1) if m else self.ws
        if not self.dry and not self.ws:
            raise StageError("failed", "准备脚本没报出工作区（WS=）")
        human = re.search(r"人裁 \S+：.*", out)
        if human:
            self.ev(human.group(0)[:500])
        mark.write_text(json.dumps({"sig": sig, "ws": self.ws, "at": time.time()}), encoding="utf-8")

    def checkout(self) -> None:
        cv = self.spec["cv"]
        try:
            self.sh(["git", "-C", str(SEED), "fetch", "-q", "--tags", "origin", cv], outcome="failed")
        except StageError as e:
            e.env = True
            raise
        self.sh(["git", "-C", str(SEED), "checkout", "-q", cv], outcome="failed")

    def verify_cv(self) -> None:
        if self.dry:
            return
        head = subprocess.run(["git", "-C", str(SEED), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        if head != self.spec["cv"]:
            raise StageError("failed", f"cv 没切对：要 {self.spec['cv'][:12]}，装的是 {head[:12]}")
        ver = subprocess.run([str(VENV / "bin" / "python"), "-c",
                              "from open_guji_cv.core.cv_version import describe;print(describe()[0] or '')"],
                             capture_output=True, text=True, env=self.env(), cwd=str(self.dir)).stdout.strip()
        self.ev(f"cv {head[:12]}（{ver or '版本未知'}）", data={"commit": head, "version": ver})

    def base(self) -> None:
        label = self.spec["base"]
        args = ["products", "pack", "fetch", self.spec["book"], "--force", "-w", self.ws or ""]
        if label != "main":
            args += ["--label", label]
        out = self.guji(*args, outcome="failed")
        m = re.search(r"已取：(\S+)", out)
        self.ev(f"铺底包 {m.group(1) if m else label}")

    def checks(self) -> None:
        want = (self.spec.get("checks") or {}).get("human_chars")
        if want is None:
            return
        code = ("import sys;from open_guji_cv.feedback.lookup import human_chars;"
                "print(len(human_chars(sys.argv[1])))")
        out = self.sh([str(VENV / "bin" / "python"), "-c", code, self.spec["book"]], outcome="blocked")
        got = int(out.strip().splitlines()[-1]) if out.strip() else -1
        self.db(S.add_result, self.id, self.aid, "check", "human_chars", data={"want": want, "got": got})
        if not self.dry and got != want:
            raise StageError("blocked", f"人裁绑定后 {got} 格，单上写应为 {want}：不跑，先查人裁事件／字块图")
        self.ev(f"人裁 {got} 格，对上")

    def glyph_recheck(self) -> None:
        """改钉字形库后只点名受影响的格（`guji recheck --glyph-diff <旧号>`，见 doc/受控重跑.md 第五节）；
        接着的 pipeline 不加 --force，只重算点名的格和它们的下游。"""
        sp = self.spec
        out = self.guji("recheck", sp["book"], "--glyph-diff", str(sp["glyph_diff"]), "-w", self.ws or "")
        tail = "\n".join(out.strip().splitlines()[-8:])
        self.db(S.add_result, self.id, self.aid, "output", "recheck", data={"tail": redact(tail)[-2000:]})
        self.ev(f"按 g{sp['glyph_diff']}→g{sp['book_overrides'].get('glyph_pin')} 点名受影响的格")

    def run_pipeline(self) -> None:
        sp = self.spec
        args = ["pipeline", sp["pipeline"], sp["book"], "-w", self.ws or "", "--pages", sp["pages"], "--no-pack"]
        if sp["steps"]["from"]:
            args += ["--from", sp["steps"]["from"]]
        if sp["steps"]["to"]:
            args += ["--to", sp["steps"]["to"]]
        if sp["force"]:
            args.append("--force")
        if sp.get("params"):
            args += ["--params", json.dumps(sp["params"], ensure_ascii=False)]
        if sp.get("book_overrides"):      # 册级覆盖在内存里叠（corpus／glyph_pin 准备时另已改本机册 yaml，供钉子账用，值一致）
            args += ["--override", json.dumps(sp["book_overrides"], ensure_ascii=False)]
        out = self.guji(*args)
        lines = [ln for ln in out.strip().splitlines() if not re.match(r"^\s*\S+ p\d+: 完成", ln)]
        tail = "\n".join(lines[-20:])
        self.db(S.add_result, self.id, self.aid, "output", "pipeline", data={"tail": redact(tail)[-4000:]})

    def run_commands(self) -> None:
        for i, argv in enumerate(self.spec["run"]):
            a = [x.replace("{book}", self.spec.get("book") or "").replace("{ws}", self.ws or "") for x in argv]
            self.progress = " ".join(a)[:300]
            out = self.guji(*a)
            self.db(S.add_result, self.id, self.aid, "output", f"run{i + 1}: {' '.join(a)[:200]}",
                         data={"tail": redact(out)[-6000:]})

    def _compare_label(self) -> str:
        c = self.spec["compare_to"]
        if isinstance(c, dict):
            packs = self.db(S.results, c["job"], "pack")
            if not packs:
                raise StageError("blocked", f"compare_to 任务 #{c['job']} 没有存包结果")
            return packs[-1]["name"]
        return c

    def compare(self) -> None:
        label = self._compare_label()
        root = self.dir / "cmp"
        args = ["products", "pack", "fetch", self.spec["book"], "--to", str(root), "--force", "-w", self.ws or ""]
        if label != "main":
            args += ["--label", label]
        self.guji(*args, outcome="failed")
        out_dir = self.dir / "diff"
        self.guji("products", "diff", self.spec["book"], "--a", str(root), "--out", str(out_dir), "-w", self.ws or "")
        rep = out_dir / "report.md"
        text = rep.read_text(encoding="utf-8") if rep.is_file() else ""
        self.diff_dir = out_dir
        self.db(S.add_result, self.id, self.aid, "diff", f"vs {label}", location=str(rep),
                     data={"report_head": text[:6000]})
        self.ev(f"已和 {label} 对比")

    def push(self) -> None:
        sp = self.spec
        br = os.environ.get("GUJI_JOBS_BRANCH")
        change = sp["output"].get("change") or (f"job{self.id}" + (f"-{br}" if br and br != "main" else ""))
        if self.att["n"] > 1:
            change += f"-a{self.att['n']}"
        note = (sp["output"].get("note") or sp.get("why") or "").strip()
        note = f"{note}（任务 #{self.id}）".strip()
        args = ["products", "pack", "push", sp["book"], "--change", change, "--note", note, "-w", self.ws or ""]
        if getattr(self, "diff_dir", None):
            args += ["--report", str(self.diff_dir)]
        out = self.guji(*args, write=True, outcome="failed")
        m = re.search(r"已存：(\S+?)（([^）]*)）", out)
        name = m.group(1) if m else None
        label = name.rsplit("/", 1)[-1] if name else f"?-{change}"
        self.db(S.add_result, self.id, self.aid, "pack", label, location=name and f"r2:{name}",
                     data={"change": change, "info": m.group(2) if m else None})
        self.ev(f"已存包 {label}" + (f"（{m.group(2)}）" if m else ""))

    # ── 总流程 ──
    def run(self) -> str:
        hb = threading.Thread(target=self._beat, daemon=True)
        hb.start()
        sp = self.spec
        outcome, err, code = "succeeded", None, None
        try:
            self.step("prep", self.prep)
            self.step("cv", self.verify_cv)
            if sp["kind"] in ("rerun", "ab"):
                if sp["base"]:
                    self.step("base", self.base)
                self.step("check", self.checks)
                if sp.get("glyph_diff") is not None:
                    self.step("recheck", self.glyph_recheck)
                self.step("run", self.run_pipeline)
            else:
                if sp.get("checks"):
                    self.step("check", self.checks)
                self.step("run", self.run_commands)
            if sp.get("compare_to"):
                self.step("compare", self.compare)
            if sp["output"].get("pack") and sp.get("book"):
                self.step("push", self.push)
        except Cancelled:
            outcome, err = "cancelled", "有人要求停下"
        except StageError as e:
            outcome, err, code = e.outcome, f"{self.stage}：{e}", e.code
            if e.env or (self.stage in ("base", "push") and e.outcome == "failed"):
                err = "环境：" + err        # 取包、存包、拉库多是网络／库的毛病，换个会话再试
        except Exception as e:          # noqa: BLE001 —— 执行方自己的错也要落库，不能让单永远挂着
            outcome, err = "failed", f"{self.stage}：执行方出错 {type(e).__name__}: {e}"
            if _is_conn_error(e):
                err = "环境：" + err        # 连库断了不是 pipeline 的错，换个会话再试
        finally:
            self._stop.set()
            if self.proc and self.proc.poll() is None:
                os.killpg(self.proc.pid, signal.SIGTERM)
        self.log.close()
        tail = redact((self.dir / "run.log").read_text(encoding="utf-8", errors="replace")[-8000:])
        self.env_failed = bool(err and err.startswith("环境："))
        self.db(S.finish, self.id, self.aid, outcome, error=err and redact(err)[:4000], exit_code=code,
                 log_tail=tail)
        shutil.rmtree(self.dir, ignore_errors=True)      # 结果（含日志尾巴）已落库、产物已推完：本单目录不留
        return outcome


_RUNNER_PATHS = ("open_guji_cv/jobs", "scripts/rerun_prep.sh", "scripts/guji_jobs.sh")
_outdated_checked_at = 0.0


def _runner_outdated() -> bool:
    """dev 上执行方相关的代码（jobs 模块、准备脚本、启动器）和本执行方检出的不一样了没有。10 分钟查一次。

    执行方进程常驻几个小时，代码是起来时载入的；有修复合进 dev 后，空闲时自己退出，线程重新 start 就换上新代码。
    只在两张单之间查，不打断在跑的单。查不了（断网）当作没更新。
    """
    global _outdated_checked_at
    if time.time() - _outdated_checked_at < 600 or not (RUNNER_ROOT / ".git").exists():
        return False
    _outdated_checked_at = time.time()

    def tree(rev: str) -> list[str] | None:
        try:
            r = subprocess.run(["git", "-C", str(RUNNER_ROOT), "rev-parse", *[f"{rev}:{p}" for p in _RUNNER_PATHS]],
                               capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout.split() if r.returncode == 0 else None

    try:
        subprocess.run(["git", "-C", str(RUNNER_ROOT), "fetch", "-q", "origin", "dev"], capture_output=True,
                       timeout=120, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except (OSError, subprocess.SubprocessError):
        return False
    new, cur = tree("origin/dev"), tree("HEAD")
    return bool(new and cur and new != cur)


def _runner_commit() -> str | None:
    try:
        return subprocess.run(["git", "-C", str(RUNNER_ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, timeout=10).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def work(*, once: bool = False, until_empty: bool = True, idle_minutes: float = 0, poll_s: int = 30,
         only: int | None = None, kinds: list[str] | None = None, dry: bool = False, say=print) -> int:
    """领单跑单。缺省跑到队列空就退出；`idle_minutes` 给了就空闲这么久才退（常驻执行方用，见 doc 第「执行方」节）。

    每个执行方一个名字（GUJI_JOBS_WHO），在 jobs.worker 登记：空闲时每次轮询报到一次，领到单记 busy 和单号，
    退出记 stopped。同一台机只许一个执行方（本机锁），多开执行方就多开会话。
    """
    HOME.mkdir(parents=True, exist_ok=True)
    lock = (HOME / "worker.lock").open("w")
    import fcntl
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        say("本机已有一个执行方在跑（~/.guji-jobs/worker.lock），不另起")
        return 0
    worker = S.who()
    session = os.environ.get("CLAUDE_CODE_SESSION_ID")
    db = S.DB()
    done = 0
    idle_since = time.time()
    rc = _runner_commit()
    warned = None
    env_streak = 0                       # 连续几单环境类失败：本会话自己的毛病（令牌、网络）会让它一路失败，到 3 就暂停
    db(S.worker_seen, worker, state="idle", session=session, runner=rc, done=0, started=True, note="")
    say(f"执行方 {worker} 上线（runner {rc or '?'}，空闲 {idle_minutes or 0} 分钟后退出）")
    try:
        while True:
            for jid, st in db(S.reap):
                say(f"收回 #{jid} → {st}")
            if not (once or only or dry) and _runner_outdated():
                say("执行方代码在 dev 上有更新，退出让执行方线程重新 start（start 会刷新检出）")
                (HOME / "runner_fresh").unlink(missing_ok=True)     # 让下一次 start 一定刷新，不受 10 分钟节流
                return done
            bad = _preflight() or _disk_gate()
            if bad:
                # 本会话缺东西（多半是没挂 guji-workspace 私仓）：不领单，免得把每条单的重试次数在几秒内耗光
                if bad != warned:
                    say(f"不领单：{bad}")
                    warned = bad
                db(S.worker_seen, worker, state="idle", session=session, done=done, note=bad)
                time.sleep(poll_s)
                continue
            if warned:
                say("自检通过，开始领单")
                warned = None
                db(S.worker_seen, worker, state="idle", session=session, done=done, note="")
            got = db(S.claim, worker, session=session, affinity=_last_book(), kinds=kinds, only=only)
            if got is None:
                if (until_empty and not idle_minutes) or time.time() - idle_since > idle_minutes * 60:
                    say(f"没有可跑的单，退出（本轮跑了 {done} 条）")
                    return done
                db(S.worker_seen, worker, state="idle", session=session, done=done)
                time.sleep(poll_s)
                continue
            job, att = got
            db(S.worker_seen, worker, state="busy", session=session, job_id=job["id"], done=done)
            say(f"领到 #{job['id']} {job['kind']} {job['book'] or ''}：{SP.summary(job['spec'])}")
            BOARD.publish(db, force=True)
            jobrun = Job(job, att, db, dry=dry)
            outcome = jobrun.run()
            env_streak = env_streak + 1 if getattr(jobrun, "env_failed", False) else 0
            _remember_book(job["book"])
            say(f"#{job['id']} → {outcome}")
            done += 1
            db(S.worker_seen, worker, state="idle", session=session, done=done)
            BOARD.publish(db, force=True)
            idle_since = time.time()
            if once or only:
                return done
            if env_streak >= ENV_STREAK_PAUSE:
                note = f"连续 {env_streak} 单环境类失败，暂停领单 {ENV_PAUSE_MIN} 分钟，请检查本会话（数据令牌、网络、工作区仓）"
                say(note)
                db(S.worker_seen, worker, state="idle", session=session, done=done, note=note)
                time.sleep(ENV_PAUSE_MIN * 60)
                env_streak = 0
                idle_since = time.time()
                db(S.worker_seen, worker, state="idle", session=session, done=done, note="")
    finally:
        try:
            db(S.worker_seen, worker, state="stopped", session=session, done=done)
            BOARD.publish(db, force=True)
        except Exception:       # noqa: BLE001 —— 断网时退出就不报了，过几分钟自然算离线
            pass


ENV_STREAK_PAUSE = 3
ENV_PAUSE_MIN = 30
WORKSPACE_REPO = "https://github.com/" + SP.WS_REPOS[SP.book_id({})]      # 缺省书的工作区仓
LEGACY_WORKSPACE_REPOS = ["https://github.com/open-guji/guji-workspace"]   # 迁仓过渡期：会话还没挂新仓时 rerun_prep 退回旧总仓
_preflight_ok_at = 0.0


#: 领单前至少要有这么多剩余空间（GB）：准备要克隆工作区、取原图、跑 pipeline
MIN_FREE_GB = float(os.environ.get("GUJI_JOBS_MIN_FREE_GB") or 10)


def _clean_job_dirs() -> float:
    """删本机所有 job 工作目录（每台机同时只一个执行方，不在跑的都是旧的）。返回释放的 GB。"""
    before = shutil.disk_usage(HOME).free
    for d in HOME.glob("job*-a*"):
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
    return max(0, shutil.disk_usage(HOME).free - before) / 2**30


def _disk_gate() -> str | None:
    """领单前查剩余空间：先清旧的 job 目录，还不够就返回原因（不领单）。缓存不自动删，要人定。"""
    freed = _clean_job_dirs()
    free = shutil.disk_usage(HOME).free / 2**30
    if free >= MIN_FREE_GB:
        return None
    return (f"磁盘剩余 {free:.1f} GB，低于 {MIN_FREE_GB:g} GB（已清旧的 job 目录，释放 {freed:.1f} GB，仍不够），"
            "不领单；请清 ~/.cache 或扩盘")


def _preflight() -> str | None:
    """执行方领单前自检，返回缺什么（None 是都齐）。通过后 10 分钟内不再查。

    工作区仓是私仓，会话没挂（add_repo）时 git 要账号，每条单都会在准备阶段失败。
    已克隆过的（~/<仓名> 在）不查。新仓和旧总仓有一个读得了就领（旧总仓里殿本目录内容相同）。
    挂上之后不用重启执行方，下一轮轮询自动开始领单。
    """
    global _preflight_ok_at
    repos = [WORKSPACE_REPO, *LEGACY_WORKSPACE_REPOS]
    if time.time() - _preflight_ok_at < 600 or any((Path.home() / r.rsplit("/", 1)[-1] / ".git").is_dir() for r in repos):
        return None
    err = None
    for repo in repos:
        try:
            r = subprocess.run(["git", "ls-remote", "-q", repo, "HEAD"], capture_output=True, text=True,
                               timeout=60, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        except (OSError, subprocess.SubprocessError) as e:
            err = err or f"读不了 {repo.split('github.com/')[-1]}（{e}）"
            continue
        if not r.returncode:
            _preflight_ok_at = time.time()
            return None
    return err or f"本会话读不了 {WORKSPACE_REPO.split('github.com/')[-1]} 私仓（请在会话里 add_repo）"


def _last_book() -> str | None:
    try:
        return (HOME / "last_book").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _remember_book(book: str | None) -> None:
    if book:
        (HOME / "last_book").write_text(book, encoding="utf-8")
