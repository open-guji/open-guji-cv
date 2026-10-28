#!/usr/bin/env bash
# guji_jobs — 任务库命令（2026-10-25）：交任务、看进展、执行方领单跑单。
#
#   guji_jobs submit …｜ls｜show <号>｜wait <号>｜cancel｜bump｜retry   # 同 guji job …，见 open_guji_cv/jobs/cli.py
#   guji_jobs start [work 的参数]     # 执行方：后台起 work（脱离本 shell，日志 ~/.guji-jobs/worker.log）
#   guji_jobs follow [秒]             # 跟着看执行方日志，执行方退出或到时就返回（缺省 6600 秒）
#
# 跑的总是 cv dev 最新的 jobs 模块（单独检出在 /opt/guji-runner），与 /opt/guji-cv-seed 当前切到哪版无关：
# 任务要的 cv 版本切的是 seed，执行方自己不会被切没。执行方在跑时不刷新 runner 检出。
# 环境：Default 环境快照（/opt/guji-cv-seed、/opt/guji-venv）；连库要 NEON_DATABASE_URL，测试分支 GUJI_JOBS_BRANCH=ci。
set -euo pipefail
R=${GUJI_JOBS_RUNNER:-/opt/guji-runner}; SEED=${GUJI_JOBS_SEED:-/opt/guji-cv-seed}
H=${GUJI_JOBS_HOME:-$HOME/.guji-jobs}; PY=${GUJI_JOBS_PY:-/opt/guji-venv/bin/python}
mkdir -p "$H"
# guji-manager（cv 拆出来的 manager，私有仓，快照里没有）：这个会话还没装就提示怎么装，不拦（目前 cv 自带的命令都还在；
# cv 删掉已搬走的包之后会真的缺命令）。装法：add_repo open-guji/guji-manager → git clone --depth 1 → uv pip install --no-deps -e
manager_hint() {
  /opt/guji-venv/bin/python -c "import importlib.metadata as m; m.version('guji-manager')" >/dev/null 2>&1 && return 0
  echo "ⓘ 本会话没装 guji-manager：add_repo open-guji/guji-manager，git clone --depth 1 https://github.com/open-guji/guji-manager ~/guji-manager，" >&2
  echo "  uv pip install --python /opt/guji-venv/bin/python --no-deps -e ~/guji-manager（详见 ai-team 通用/经验-云端装guji-manager.md）" >&2
}
busy() { [ -e "$H/worker.lock" ] && ! flock -n "$H/worker.lock" true; }
refresh() {
  if [ ! -d "$R/open_guji_cv" ]; then
    git -C "$SEED" fetch -q origin dev && git -C "$SEED" worktree add -f --detach "$R" origin/dev >/dev/null 2>&1
    touch "$H/runner_fresh"
  elif ! busy && [ -z "$(find "$H/runner_fresh" -mmin -10 2>/dev/null)" ]; then
    git -C "$SEED" fetch -q origin dev && git -C "$R" checkout -q --detach origin/dev || echo "（runner 没刷新成，用旧的）" >&2
    touch "$H/runner_fresh"
  fi
}
case "${1:-}" in
  start)
    shift; refresh; manager_hint
    if busy; then echo "执行方已在跑（$H/worker.lock）"; exit 0; fi
    PYTHONPATH="$R" setsid nohup "$PY" -m open_guji_cv.jobs work "$@" >> "$H/worker.log" 2>&1 < /dev/null &
    echo "执行方已起（pid $!），日志 $H/worker.log；guji_jobs follow 跟着看";;
  follow)
    end=$((SECONDS + ${2:-6600})); touch "$H/worker.log"
    tail -n 20 -f "$H/worker.log" & T=$!
    sleep 3; while busy && [ $SECONDS -lt $end ]; do sleep 20; done
    kill $T 2>/dev/null || true
    busy && echo "（到时返回，执行方还在跑）" || echo "（执行方已退出）";;
  *)
    refresh
    PYTHONPATH="$R" exec "$PY" -m open_guji_cv.jobs "$@";;
esac
