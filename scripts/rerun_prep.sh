#!/usr/bin/env bash
# rerun_prep.sh — 云端新会话一条命令备好一册重跑（A30「一会话一册」，2026-10-24）
#
#   rerun_prep.sh <册> [--cv <tag/分支/提交>] [--corpus N] [--pin-args "<guji corpus pin 的参数>"]
#                 [--glyph-pin N] [--ws-glob 96mid1ogzk-*] [--base]
#
# 依次：cv 切到需求单版本 → 克隆 guji-workspace → guji db pull → 改册 yaml（corpus／glyph_pin）
# → 追加语料钉子账 → 建钉版字形库并核刻例非 0 → 取原图并合扫检查 → 预拉 Step5-b 模板索引（fp32）
# → 语料校验 → guji status。每步计时，最后打印汇总和开跑命令。任何一步失败即停（退出码非 0）。
# 只做准备，不跑 pipeline、不推库、不存包。环境：/opt/guji-cv-seed + /opt/guji-venv（Default 环境快照）。
set -euo pipefail
VOL=${1:?用法见脚本头}; shift
CV= CORPUS= PIN_ARGS= GPIN= WSGLOB='96mid1ogzk-*' BASE=0
while [ $# -gt 0 ]; do case $1 in
  --cv) CV=$2; shift 2;; --corpus) CORPUS=$2; shift 2;; --pin-args) PIN_ARGS=$2; shift 2;;
  --glyph-pin) GPIN=$2; shift 2;; --ws-glob) WSGLOB=$2; shift 2;; --base) BASE=1; shift;;
  *) echo "不认识的参数 $1" >&2; exit 2;; esac; done
G=/opt/guji-venv/bin/guji; SEED=/opt/guji-cv-seed; GW=$HOME/guji-workspace; SUM=()
# 面板里写的 GUJI_DATA_TOKEN=$GUJI_DATA_TOKEN_PROD 不展开（字面量 401）；旧版 cv 不认，这里先展开
case "${GUJI_DATA_TOKEN:-}" in \$*) r=${GUJI_DATA_TOKEN#\$}; r=${r#\{}; r=${r%\}}
  if [ -n "${!r:-}" ]; then export GUJI_DATA_TOKEN=${!r}; else unset GUJI_DATA_TOKEN; fi;; esac
[ -n "${GUJI_DATA_TOKEN:-}" ] || export GUJI_DATA_TOKEN=${GUJI_DATA_TOKEN_READ:?缺读令牌}
t() { local s=$SECONDS n=$1; shift; echo "== $n"; "$@"; SUM+=("$(printf '%-14s %4ss' "$n" $((SECONDS-s)))"); }

if [ -n "$CV" ]; then
  t cv git -C $SEED fetch -q --tags origin "$CV"
  git -C $SEED checkout -q "$CV" 2>/dev/null || git -C $SEED checkout -q FETCH_HEAD
fi
echo "cv $(git -C $SEED rev-parse --short HEAD) $(git -C $SEED describe --tags 2>/dev/null || true)"
[ -d $GW/.git ] || t 克隆工作区 git clone -q --depth 1 https://github.com/open-guji/guji-workspace $GW
WS=$(ls -d $GW/$WSGLOB | head -n 1); export GUJI_WORKSPACE=$WS; echo "WS=$WS"
t db-pull $G db pull -w "$WS"
Y=$(ls /root/.guji-data/main/*/books/"$VOL".yaml | head -n 1)   # 数据目录里的册配置（db pull 落的）
[ -n "$CORPUS" ] && sed -i "s/^corpus: .*/corpus: $CORPUS/" "$Y"
[ -n "$GPIN" ] && { grep -q '^glyph_pin:' "$Y" && sed -i "s/^glyph_pin: .*/glyph_pin: $GPIN/" "$Y" || echo "glyph_pin: $GPIN" >> "$Y"; }
echo "册 yaml $Y：$(grep -E '^(corpus|glyph_pin):' "$Y" | tr '\n' ' ')"
[ -n "$PIN_ARGS" ] && t 钉子账 $G corpus pin --vol "$VOL" $PIN_ARGS -w "$WS"
GP=$(sed -n 's/^glyph_pin: *//p' "$Y")
if [ -n "$GP" ]; then
  t 建字形库g$GP $G glyph-db pin-build -w "$WS" --pin "$GP"
  python3 - "$WS/output/glyph-g$GP.db" <<'PY'
import sqlite3, sys
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
n = {t: c.execute(f"select count(*) from {t}").fetchone()[0] for t in ("instances", "exemplars", "glyphs")}
print("字形库", n); sys.exit(0 if n["exemplars"] and n["glyphs"] else "字形库没有刻例／字头：别开跑，先查建库")
PY
fi
t 取原图 $G source pull "$VOL" -w "$WS"
BK=$(basename "$WS"); BK=${BK%%-*}; VN=${VOL#vol}
t 合扫检查 $G source check "$BK" "$VN" -w "$WS" || echo "⚠️ source check 有报（题签页报疑似合扫属正常），请看上面"
t 模板索引 $G cache pull-rare-index --book "$VOL" -w "$WS" --precision fp32
[ -n "$CORPUS" ] && t 语料校验 $G corpus verify --vol "$VOL" -w "$WS"
[ $BASE = 1 ] && t 基线包 $G products pack fetch "$VOL" --to "$HOME/base/$VOL"
t status $G status "$VOL" -w "$WS"
echo; echo "== 准备耗时"; printf '%s\n' "${SUM[@]}"
echo "开跑：guard_run $VOL -- $G pipeline keben_body_v2 $VOL -w \"$WS\" --pages all --no-pack"
