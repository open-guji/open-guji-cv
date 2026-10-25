#!/usr/bin/env bash
# rerun_prep.sh — 云端新会话一条命令备好一册重跑（A30「一会话一册」，2026-10-24）
#
#   rerun_prep.sh <册> [--cv <tag/分支/提交>] [--corpus N] [--pin-args "<guji corpus pin 的参数>"]
#                 [--glyph-pin N] [--ws-glob 96mid1ogzk-*] [--base]
#
# 依次：cv 切到需求单版本 → 克隆 guji-workspace → guji db pull → 改册 yaml（corpus／glyph_pin；给了 --cv 时 cv_version 跟着改）
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
# 册 yaml 钉了 cv_version、装的又不是它，pipeline 会拒跑（要 --allow-cv-mismatch）。给了 --cv 就是需求单点名的版本：
# 本地册配置跟着改成装上的版本（只改本机数据目录，不推中心库）；没给 --cv 而对不上就只提醒
CVV=$(/opt/guji-venv/bin/python -c "from open_guji_cv.core.cv_version import describe;print(describe()[0] or '')")
OLD=$(sed -n 's/^cv_version: *"\{0,1\}\([^" #]*\).*/\1/p' "$Y")
if [ -n "$CV" ] && [ -n "$CVV" ] && [ "$OLD" != "$CVV" ]; then
  grep -q '^cv_version:' "$Y" && sed -i "s/^cv_version: .*/cv_version: \"$CVV\"/" "$Y" || echo "cv_version: \"$CVV\"" >> "$Y"
  echo "册 yaml cv_version ${OLD:-（未钉）} → $CVV（跟 --cv）"
elif [ -n "$OLD" ] && [ "$OLD" != "$CVV" ]; then
  echo "⚠️ 册 yaml 钉 cv_version=$OLD，装的是 $CVV：用 --cv v$OLD 重跑本脚本，或按需求单给 --cv"
fi
echo "册 yaml $Y：$(grep -E '^(corpus|glyph_pin|cv_version):' "$Y" | tr '\n' ' ')"
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
# 人裁自检（2026-10-25）：读事件看 GUJI_WORKSPACE（不看 GUJI_DATA_HOME）；老人裁要现格字块图才认得了格，
# 只重跑 seed_admit、cache/ 是空的会话里旧版 cv 会静默丢（vol10 78/146）。新版 cv 现切字块，旧版要先 cache warm。
t 人裁自检 /opt/guji-venv/bin/python - "$VOL" <<'PY'
import collections, sys
from open_guji_cv.feedback.bindings import book_bindings, usable
from open_guji_cv.feedback.lookup import human_chars
from open_guji_cv.products.store import ProductStore
from open_guji_cv.report.slots import cells_step
v = sys.argv[1]
n0 = len(human_chars(v, bind=False))
if not ProductStore().step_dir(v, cells_step(v)).is_dir():
    sys.exit(print(f"人裁 {v}：按编号 {n0}（还没有切分产物，绑定自检等跑完 Step3 再看）"))
lost = {}
n = len(human_chars(v, lost=lost))
rows = book_bindings(v)
st = collections.Counter(r["status"] for r in rows.values())
why = collections.Counter(r.get("why") or r["status"] for r in rows.values() if usable(r) is None)
print(f"人裁 {v}：绑定后 {n}（应与基线包 seed_admit 里 provenance=human 的格数一致），按编号 {n0}，"
      f"绑丢 {len(lost)} {dict(why)}；绑定状态 {dict(st)}")
if why.get("no_patch") or why.get("unanchored", 0) > 3:
    print("⚠️ 有人裁因 cache/ 里没有字块图认不了格。旧版 cv（v0.5.15 及以前）先跑 "
          "ai-team domain/CV/脚本/warm_human_patches.py 再自检；dev（#540 起）会自己现切")
PY
{ echo "export GUJI_WORKSPACE='$WS'"; } > "$HOME/.guji_env"
echo; echo "== 准备耗时"; printf '%s\n' "${SUM[@]}"
echo "之后的命令先 source ~/.guji_env（设 GUJI_WORKSPACE；人裁事件只认它）"
echo "开跑：guard_run $VOL -- $G pipeline keben_body_v2 $VOL -w \"$WS\" --pages all --no-pack"
