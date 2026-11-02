# ensure_manager — 开工时把 guji-manager 装好并跟到 main 最新（拆分 P0，2026-11-02）。由 rerun_prep.sh、guji_jobs.sh source。
#
# 云端快照的 setup 脚本已把 manager 克隆到 /opt/guji-manager-seed 并 editable 装进 /opt/guji-venv，但快照不会自己更新；
# 这里每 10 分钟最多拉一次 main。cv 删掉搬走的包之后，没装 manager 的会话会缺命令，所以缺了就当场克隆安装。
# 失败只警告、不拦（manager 用旧 cv 也能跑：guji_manager._cv 兜底）。可覆盖：GUJI_MANAGER_DIR、GUJI_MANAGER_PY。
ensure_manager() {
  local d=${GUJI_MANAGER_DIR:-/opt/guji-manager-seed} py=${GUJI_MANAGER_PY:-/opt/guji-venv/bin/python}
  local stamp=${GUJI_JOBS_HOME:-$HOME/.guji-jobs}/manager_fresh
  mkdir -p "$(dirname "$stamp")"
  if [ ! -d "$d/.git" ]; then
    git clone -q --depth 1 https://github.com/open-guji/guji-manager "$d" 2>/dev/null \
      || { echo "ⓘ guji-manager 克隆失败（$d），先用 cv 自带的命令" >&2; return 0; }
  elif [ -z "$(find "$stamp" -mmin -10 2>/dev/null)" ]; then
    { git -C "$d" fetch -q --depth 1 origin main && git -C "$d" checkout -q --detach FETCH_HEAD; } 2>/dev/null \
      || echo "ⓘ guji-manager 没拉成新的，用 $d 现有的" >&2
  fi
  touch "$stamp"
  if ! "$py" -c "import guji_manager, os, sys; sys.exit(os.path.realpath(guji_manager.__file__).startswith(os.path.realpath('$d')) is False)" 2>/dev/null; then
    { command -v uv >/dev/null && uv pip install -q --python "$py" --no-deps -e "$d"; } \
      || "$py" -m pip install -q --no-deps -e "$d" 2>/dev/null \
      || { echo "ⓘ guji-manager 没装上（$d），先用 cv 自带的命令" >&2; return 0; }
  fi
  echo "guji-manager $(git -C "$d" rev-parse --short HEAD 2>/dev/null)"
}
