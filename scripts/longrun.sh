#!/usr/bin/env bash
# longrun.sh — 长跑任务的断点续跑包装（GUJI-508；基于 bootstrap_cloud.sh）
# 解决的事：云端容器空闲会被回收——磁盘保留、后台进程全死。会话一被叫醒，一条命令让没跑完的长任务从断点接着跑，
#           已完成的步骤不重算、已完成的页由 guji 自己的指纹跳过。
#
# 用法（一页版见 doc/longrun.md）：
#   bash scripts/longrun.sh start  <job文件> [名字] [--env VAR1,VAR2]   起任务（后台；已在跑／已完成则只报告，不重起）
#   bash scripts/longrun.sh resume [名字|--all]                         被叫醒后就这一条：没跑完且 runner 不在的任务，从断点续
#   bash scripts/longrun.sh status [名字]                               看进度：状态、当前步、已完成步数、日志最后一条进度行
#   bash scripts/longrun.sh stop   <名字>                               停（杀 runner 及其子进程；已完成的步不受影响）
#   bash scripts/longrun.sh compare <目录A> <目录B> [--exclude 正则]    逐文件 sha256 对比两个目录树；rc 0＝逐文件一致，1＝有差异
# 环境变量：GUJI_LONGRUN_DIR（默认 $HOME/guji-longrun，放任务状态与日志；要放在容器回收后还在的盘上）
#           GUJI_VENV（默认 <仓根>/.venv；runner 会把它的 bin 放进 PATH，并在缺件时先跑 bootstrap_cloud.sh）
#
# job 文件是 bash，用 step 声明步骤（按顺序立即执行，可在循环里生成）：
#   step <步骤名> '<命令>' ['<验证命令>']
#   · 命令必须**幂等**（原样重跑安全）：guji pipeline／step 只重算过期或缺失的页，满足这条；
#   · 验证命令可省；写了就必须 rc 0 才算这一步完成（用来挡「rc 0 但有页失败」——cmd_exp 就是这样的）；
#   · 步骤名＋命令＋验证命令的哈希进完成戳；改了命令，这一步下次会重跑，其余步骤不受影响。
# 续跑规则：
#   · 完成戳 $JOB/done/<步骤名> 只在命令 rc 0 且验证过才写（原子 mv）；被杀在半路没有戳，重跑该步（页级进度靠命令自己跳过）。
#   · runner 是否在跑以 flock 为准（$JOB/lock），不靠 pid 文件：容器回收后锁自然消失，不会误判「还在跑」。
#   · 步骤失败：runner 停在该步（状态 failed，日志有原因），不会往下跑；排除后 resume 原样续。
#   · 只写 $GUJI_LONGRUN_DIR；产物落哪由 job 里的命令决定（用沙箱 GUJI_PRODUCTS_DIR，别写正式 products/）。
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SELF="$ROOT/scripts/longrun.sh"
LR="${GUJI_LONGRUN_DIR:-$HOME/guji-longrun}"
export GUJI_VENV="${GUJI_VENV:-$ROOT/.venv}"
now() { TZ=America/Los_Angeles date '+%m-%d %H:%M:%S'; }
die() { echo "longrun: $*" >&2; exit 2; }
is_running() { ( exec 8>"$1/lock" 2>/dev/null && ! flock -n 8 ); }   # 拿不到锁＝runner 在跑
hashof() { printf '%s' "$*" | sha256sum | cut -c1-16; }

cmd_status_one() {
  local jd="$LR/$1" st cur ndone last
  [ -d "$jd" ] || { echo "$1: 没有这个任务"; return 1; }
  cur="$(cat "$jd/current" 2>/dev/null || true)"; ndone=$(ls "$jd/done" 2>/dev/null | wc -l)
  if [ -f "$jd/COMPLETE" ]; then st="完成"
  elif is_running "$jd"; then st="运行中"
  elif [ -f "$jd/FAILED" ]; then st="失败（$(cat "$jd/FAILED")）"
  else st="已中断（runner 不在；resume 可续）"; fi
  last="$(ls -t "$jd"/logs/*.log 2>/dev/null | head -1)"
  echo "$1｜$st｜已完成 ${ndone} 步｜当前步：${cur:--}｜续跑 $(cat "$jd/restarts" 2>/dev/null || echo 0) 次"
  [ -n "$last" ] && echo "   最后日志 $(basename "$last")（$(TZ=America/Los_Angeles date -r "$last" '+%m-%d %H:%M:%S')）：$( { grep -E '\] [0-9]+% ' "$last" | tail -n1; tail -n1 "$last"; } | head -n1 | cut -c1-110)"
  return 0
}

launch() {  # $1=名字；调用前已确认不在跑、没完成
  local jd="$LR/$1"
  echo $(( $(cat "$jd/restarts" 2>/dev/null || echo -1) + 1 )) > "$jd/restarts"
  rm -f "$jd/FAILED"
  setsid nohup bash "$SELF" _run "$1" >> "$jd/runner.log" 2>&1 < /dev/null &
  echo "[$(now)] 已起 runner（第 $(cat "$jd/restarts") 次；pid $!）" | tee -a "$jd/runner.log"
}

case "${1:-}" in
  start)
    shift; jobfile="${1:-}"; [ -f "$jobfile" ] || die "用法：start <job文件> [名字] [--env VAR1,VAR2]"; shift
    name=""; envs=""
    while [ $# -gt 0 ]; do case "$1" in --env) envs="${2:-}"; shift 2;; *) name="$1"; shift;; esac; done
    [ -n "$name" ] || { name="$(basename "$jobfile")"; name="${name%.job.sh}"; name="${name%.sh}"; }
    jd="$LR/$name"; mkdir -p "$jd/done" "$jd/logs"
    if is_running "$jd"; then echo "$name 已在跑，不重起。"; cmd_status_one "$name"; exit 0; fi
    cp "$jobfile" "$jd/job.sh.tmp" && mv "$jd/job.sh.tmp" "$jd/job.sh"
    { for v in ${envs//,/ }; do [ -n "${!v+x}" ] && printf 'export %s=%q\n' "$v" "${!v}"; done; } > "$jd/env.sh.tmp" && mv "$jd/env.sh.tmp" "$jd/env.sh"
    chmod 600 "$jd/env.sh"   # 别往 --env 里放密码；这里只存路径之类的变量
    if [ -f "$jd/COMPLETE" ]; then echo "$name 已完成（$jd/COMPLETE）；要重来先删该目录。"; cmd_status_one "$name"; exit 0; fi
    launch "$name"; sleep 1; cmd_status_one "$name" ;;
  resume)
    shift; target="${1:---all}"; names=()
    if [ "$target" = "--all" ]; then for d in "$LR"/*/job.sh; do [ -f "$d" ] && names+=("$(basename "$(dirname "$d")")"); done
    else names=("$target"); fi
    [ ${#names[@]} -gt 0 ] || { echo "没有任务（$LR）"; exit 0; }
    uptime | sed 's/^/uptime:/'
    for n in "${names[@]}"; do
      jd="$LR/$n"; [ -f "$jd/job.sh" ] || { echo "$n: 没有 job.sh"; continue; }
      if [ -f "$jd/COMPLETE" ]; then echo "$n: 已完成，不动。"; continue; fi
      if is_running "$jd"; then echo "$n: 还在跑，不重起。"; cmd_status_one "$n"; continue; fi
      echo "$n: runner 不在、任务没完成 → 从断点续跑"; launch "$n"
    done
    sleep 1; for n in "${names[@]}"; do cmd_status_one "$n"; done ;;
  status)
    shift; if [ -n "${1:-}" ]; then cmd_status_one "$1"; else for d in "$LR"/*/job.sh; do [ -f "$d" ] && cmd_status_one "$(basename "$(dirname "$d")")"; done; fi ;;
  stop)
    shift; jd="$LR/${1:?名字}"; [ -d "$jd" ] || die "没有这个任务"
    pid="$(cat "$jd/runner.pid" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then pkill -TERM -g "$(ps -o pgid= -p "$pid" | tr -d ' ')" 2>/dev/null; sleep 1; echo "已发 TERM 给 runner 进程组（pgid $(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')）"; else echo "runner 不在。"; fi ;;
  compare)
    shift; A="${1:?目录A}"; B="${2:?目录B}"; shift 2; EX='(^|/)(_manifest\.jsonl|_raw_index\.json)$'   # 默认排除：manifest 带 ts／elapsed／code_rev，_raw_index 是图片索引，都不是产物；manifest 另按「页键→产物 sha256＋状态」语义比对（见下）
    [ "${1:-}" = "--exclude" ] && EX="${2:-}"
    python3 -I - "$A" "$B" "$EX" <<'PY'
import hashlib, json, os, re, sys
a, b, ex = sys.argv[1], sys.argv[2], sys.argv[3]
rx = re.compile(ex) if ex else None
def tree(r):
    out = {}
    for d, _, fs in os.walk(r):
        for f in fs:
            p = os.path.join(d, f); rel = os.path.relpath(p, r)
            if rx and rx.search(rel): continue
            h = hashlib.sha256()
            with open(p, "rb") as fh:
                for blk in iter(lambda: fh.read(1 << 20), b""): h.update(blk)
            out[rel] = h.hexdigest()
    return out
def manifest_sem(r):
    out = {}
    for d, _, fs in os.walk(r):
        if "_manifest.jsonl" in fs:
            step = os.path.relpath(d, r)
            last = {}
            for ln in open(os.path.join(d, "_manifest.jsonl"), encoding="utf-8"):
                ln = ln.strip()
                if ln:
                    try: e = json.loads(ln)
                    except ValueError: out[(step, "<坏行>")] = ("坏行", ""); continue
                    last[e.get("key")] = (e.get("sha256"), e.get("status"))   # 同页多条取最后一条（append-only，最后一条生效）
            for k, v in last.items(): out[(step, k)] = v
    return out
ta, tb = tree(a), tree(b)
ma, mb = manifest_sem(a), manifest_sem(b)
mdiff = sorted(k for k in set(ma) | set(mb) if ma.get(k) != mb.get(k))
print(f"manifest 语义（页键→产物sha256＋状态，忽略 ts／elapsed／code_rev／fingerprint）：A {len(ma)} 条｜B {len(mb)} 条｜不同 {len(mdiff)}")
for k in mdiff[:20]: print(f"  manifest不同: {k[0]}/{k[1]}  A={ma.get(k)}  B={mb.get(k)}")
only_a = sorted(set(ta) - set(tb)); only_b = sorted(set(tb) - set(ta))
diff = sorted(k for k in set(ta) & set(tb) if ta[k] != tb[k])
same = len(set(ta) & set(tb)) - len(diff)
print(f"A={a}  文件 {len(ta)}\nB={b}  文件 {len(tb)}\n逐字节相同 {same}｜不同 {len(diff)}｜仅 A 有 {len(only_a)}｜仅 B 有 {len(only_b)}｜排除规则：{ex or '无'}")
for tag, lst in (("不同", diff), ("仅A", only_a), ("仅B", only_b)):
    for k in lst[:20]: print(f"  {tag}: {k}")
    if len(lst) > 20: print(f"  {tag}: …另 {len(lst)-20} 个")
sys.exit(0 if not (diff or only_a or only_b or mdiff) else 1)
PY
    ;;
  _run)   # 内部：runner 本体
    name="${2:?}"; jd="$LR/$name"
    exec 9>"$jd/lock"; flock -n 9 || exit 0        # 已有 runner 就退出
    echo $$ > "$jd/runner.pid"
    [ -f "$jd/env.sh" ] && source "$jd/env.sh"
    [ -d "$GUJI_VENV/bin" ] && export PATH="$GUJI_VENV/bin:$PATH"
    if ! GUJI_VENV="$GUJI_VENV" bash "$ROOT/scripts/bootstrap_cloud.sh" --check >/dev/null 2>&1; then
      echo "[$(now)] env 自检不过，先跑 bootstrap_cloud.sh（装好才继续）"
      GUJI_VENV="$GUJI_VENV" bash "$ROOT/scripts/bootstrap_cloud.sh" || { echo "bootstrap 失败" > "$jd/FAILED"; exit 1; }
    fi
    export JOB_DIR="$jd" LONGRUN_SCRIPTS="$ROOT/scripts"   # job 文件里用 $LONGRUN_SCRIPTS 引用本目录的帮手脚本
    step() {
      local sn="$1" cmd="$2" ver="${3:-true}" h; h="$(hashof "$sn" "$cmd" "$ver")"
      if [ "$(cat "$jd/done/$sn" 2>/dev/null)" = "$h" ]; then echo "[$(now)] 跳过（已完成）：$sn"; return 0; fi
      echo "$sn" > "$jd/current"; echo "[$(now)] ▶ $sn"
      { echo "=== $(now) 开始 $sn"; } >> "$jd/logs/$sn.log"
      bash -c "set -o pipefail; $cmd" 9>&- >> "$jd/logs/$sn.log" 2>&1; local rc=$?
      if [ $rc -eq 0 ]; then bash -c "$ver" 9>&- >> "$jd/logs/$sn.log" 2>&1 || { rc=97; echo "验证命令未过" >> "$jd/logs/$sn.log"; }; fi
      if [ $rc -ne 0 ]; then echo "$sn rc=$rc" > "$jd/FAILED"; echo "[$(now)] ✗ $sn rc=$rc（日志 $jd/logs/$sn.log）"; exit $rc; fi
      echo "$h" > "$jd/done/$sn.tmp" && mv "$jd/done/$sn.tmp" "$jd/done/$sn"
      echo "=== $(now) 完成 $sn" >> "$jd/logs/$sn.log"; echo "[$(now)] ✓ $sn"
    }
    # shellcheck disable=SC1091
    source "$jd/job.sh"
    rm -f "$jd/current"; touch "$jd/COMPLETE"; echo "[$(now)] 全部完成 DONE" ;;
  *) sed -n 2,28p "$0"; exit 2 ;;
esac
