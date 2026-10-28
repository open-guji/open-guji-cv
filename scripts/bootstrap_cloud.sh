#!/usr/bin/env bash
# bootstrap_cloud.sh — 全新云端容器一条命令把 open-guji-cv 环境装到「自检通过」（GUJI-476 / Z1.4）
#
# 用法（在仓根或任意目录都行）：
#   bash scripts/bootstrap_cloud.sh              # 装 .[torch,dev] 到 $GUJI_VENV（控制台另装 guji-console），装完自检
#   bash scripts/bootstrap_cloud.sh --check      # 只自检，不装（rc 0＝可用，1＝不可用）
#   bash scripts/bootstrap_cloud.sh --force      # 删掉重装（仅在明说时才会动已有 venv）
# 环境变量（都可不设）：
#   GUJI_VENV     虚拟环境位置，默认 <仓根>/.venv
#   GUJI_EXTRAS   要装的 extras，默认 console,torch,dev
#   GUJI_TORCH_INDEX  torch 的 wheel 源，默认 https://download.pytorch.org/whl/cpu（云端无 GPU，免拖 CUDA 大包）；设成空串＝用默认 PyPI
#   GUJI_PYTHON   指定 python（默认 3.12，装不到就退而用 PATH 里 3.10–3.13 的 python3）
# 退出码：0＝环境就绪（自检通过）；1＝装失败或自检不过（原样再跑即可续装）；2＝参数错
#
# 幂等与续跑（杀进程后重跑不重复装）：
#   · 「就绪戳」$GUJI_VENV/.bootstrap_ok 只在自检通过后才写，内容是 依赖指纹（pyproject.toml＋uv.lock＋extras＋python 版本）。
#     重跑时：戳在、指纹没变、自检通过 → 直接打印「已就绪」退出，什么都不装。
#   · 被杀在半路：venv 与已下好的包留在原地，没有戳；重跑复用同一个 venv，uv 只补没装上的（已装的 uv 自己跳过）。
#     不会 rm 掉半成品 venv，也不会因 venv 目录已存在而报错。
#   · 依赖指纹变了（拉了新 pyproject／uv.lock）：同一个 venv 上增量补装，不重建。
#   · 并发两次同时跑：用 flock 排队，后者等前者装完后见到就绪戳就直接退出。
#   · 唯一会删 venv 的是 --force。
# 自检：python -c "import torch, scipy, cv2"（CLAUDE.md 规定的那句；缺件不报错只会悄悄降级，所以必须真 import）
#
# 不做的事：不拉书的工作区（GUJI_WORKSPACE 另行挂 guji-workspace）、不装 paddle（CPU/GPU 轮子不同，见 install_gpu.sh）、
#           不下模型 checkpoint、不碰任何产物目录。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${GUJI_VENV:-$ROOT/.venv}"
EXTRAS="${GUJI_EXTRAS:-console,torch,dev}"
TORCH_INDEX="${GUJI_TORCH_INDEX-https://download.pytorch.org/whl/cpu}"
WANT_PY="${GUJI_PYTHON:-3.12}"
MODE=install
case "${1:-}" in
  "") ;;
  --check) MODE=check ;;
  --force) MODE=force ;;
  *) echo "用法：bash scripts/bootstrap_cloud.sh [--check|--force]（头部有说明）" >&2; exit 2 ;;
esac
log() { echo "[bootstrap $(TZ=America/Los_Angeles date +%m-%d\ %H:%M:%S)] $*"; }

# —— 依赖指纹：哪一项变了都该补装 ——
fingerprint() {
  { cat "$ROOT/pyproject.toml"; [ -f "$ROOT/uv.lock" ] && cat "$ROOT/uv.lock"; echo "extras=$EXTRAS torch_index=$TORCH_INDEX"; } | sha256sum | cut -c1-16
}
selfcheck() { [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c "import torch, scipy, cv2" 2>/dev/null; }
READY="$VENV/.bootstrap_ok"
ready_ok() { selfcheck && [ -f "$READY" ] && [ "$(cat "$READY")" = "$(fingerprint)" ]; }

if [ "$MODE" = check ]; then
  if selfcheck; then log "自检通过：$VENV"; exit 0; else log "自检不过（venv 缺失或缺件）：$VENV"; exit 1; fi
fi

# —— 排队：同一个 venv 同一时刻只有一个安装在跑 ——
mkdir -p "$(dirname "$VENV")" "${TMPDIR:-/tmp}"
LOCK="${TMPDIR:-/tmp}/guji-bootstrap-$(printf '%s' "$VENV" | sha256sum | cut -c1-10).lock"   # 锁只在装的过程中有意义，放 /tmp，不往仓里留文件
exec 9>"$LOCK"
if ! flock -n 9; then log "另一个 bootstrap 正在装，排队等它…"; flock 9; fi

if [ "$MODE" = force ]; then
  [ -n "$VENV" ] && [ "$VENV" != "/" ] && [ "$VENV" != "$HOME" ] && { log "--force：删掉重装 $VENV"; rm -rf -- "$VENV"; }
fi

if ready_ok; then log "已就绪（指纹未变、自检通过），不重装：$VENV"; exit 0; fi

# —— 1. uv ——
if ! command -v uv >/dev/null 2>&1; then
  log "装 uv（pip install --user uv）…"
  python3 -m pip install -q --user uv || python3 -m pip install -q --user --break-system-packages uv || { log "装 uv 失败"; exit 1; }
  export PATH="$HOME/.local/bin:$PATH"
  command -v uv >/dev/null 2>&1 || { log "装了 uv 但不在 PATH"; exit 1; }
fi

# —— 2. venv（已存在就复用；不存在才建）——
if [ ! -x "$VENV/bin/python" ]; then
  log "建 venv：$VENV（python $WANT_PY，装不到就退到系统 python3）"
  if uv venv "$VENV" --allow-existing --python "$WANT_PY" -q 2>/dev/null; then :; else
    log "uv 取不到 python $WANT_PY，退用系统 python3"
    uv venv "$VENV" --allow-existing --python "$(command -v python3)" -q || { log "建 venv 失败"; exit 1; }
  fi
  # venv 不能建在别处再 mv（bin 脚本的 shebang 写死路径）；uv venv 很快，被杀留下的半个 venv 下次 --allow-existing 补全
else
  log "复用已有 venv：$VENV"
fi

# —— 3. 装依赖（uv 自己跳过已装的）——
log "装 .[${EXTRAS}]（已装的会被跳过）…"
cd "$ROOT" || exit 1
INST=(uv pip install --python "$VENV/bin/python" -e ".[${EXTRAS}]")
if [ -n "$TORCH_INDEX" ]; then INST+=(--extra-index-url "$TORCH_INDEX" --index-strategy unsafe-best-match); fi
"${INST[@]}" || { log "安装失败（网络？）——原样再跑一遍即可续装，已装的不会重装"; exit 1; }

# —— 4. 自检，通过才写就绪戳 ——
if selfcheck; then
  fingerprint > "$READY.tmp" && mv "$READY.tmp" "$READY"
  log "自检通过：python -c \"import torch, scipy, cv2\" OK → $VENV/bin/python"
  log "用法：source $VENV/bin/activate 或直接 $VENV/bin/guji …；带 book 的命令别忘了 -w <工作区>"
  exit 0
fi
log "装完但自检不过："; "$VENV/bin/python" -c "import torch, scipy, cv2" 2>&1 | tail -3
exit 1
