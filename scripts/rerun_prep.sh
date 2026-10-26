#!/usr/bin/env bash
# rerun_prep.sh — 云端新会话一条命令备好一册重跑（A30「一会话一册」，2026-10-24）
#
#   rerun_prep.sh <册> [--cv <tag/分支/提交>] [--corpus N] [--pin-args "<guji corpus pin 的参数>"]
#                 [--glyph-pin N] [--ws-glob 96mid1ogzk-*] [--base] [--reset]
#
# --reset：本机数据目录已被上一次准备改过（册 yaml、钉子账）时先 db pull --force 还原（并重建 glyph.db），再按这次的参数改。
#          任务库执行方（guji_jobs）在同一会话接第二张单时用；本机有没推的人裁别加。
#
# 依次：cv 切到需求单版本 → 克隆 guji-workspace → guji db pull → 改册 yaml（corpus／glyph_pin；给了 --cv 时 cv_version 跟着改）
# → 追加语料钉子账 → 建钉版字形库并核刻例非 0 → 取原图并合扫检查 → 预拉 Step5-b 模板索引（fp32）
# → 语料校验 → guji status。每步计时，最后打印汇总和开跑命令。任何一步失败即停（退出码非 0）。
# 只做准备，不跑 pipeline、不推库、不存包。环境：/opt/guji-cv-seed + /opt/guji-venv（Default 环境快照）。
set -euo pipefail
VOL=${1:?用法见脚本头}; shift
CV= CORPUS= PIN_ARGS= GPIN= WSGLOB='96mid1ogzk-*' BASE=0 RESET=0
while [ $# -gt 0 ]; do case $1 in
  --cv) CV=$2; shift 2;; --corpus) CORPUS=$2; shift 2;; --pin-args) PIN_ARGS=$2; shift 2;;
  --glyph-pin) GPIN=$2; shift 2;; --ws-glob) WSGLOB=$2; shift 2;; --base) BASE=1; shift;; --reset) RESET=1; shift;;
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
# --reset 也要重建 glyph.db：上一次准备若在拉库前就失败（如克隆工作区失败），本机 glyph.db 还没建过，
# --no-rebuild 会留下空库，建钉版库时报 no such table: sources（10-25 #3–#6）
if [ $RESET = 1 ]; then t db-pull $G db pull -w "$WS" --force; else t db-pull $G db pull -w "$WS"; fi
Y=$(ls /root/.guji-data/main/*/books/"$VOL".yaml | head -n 1)   # 数据目录里的册配置（db pull 落的）
# 册配置分层后（config/book_defaults.yaml），corpus／glyph_pin／cv_version 可能不在册 yaml 里而在基础配置里：
# 改值 = 册 yaml 里有就替换、没有就追加（册 yaml 压过基础配置）；读值 = 读合并后的生效值，不能再 grep 册 yaml
eff() { /opt/guji-venv/bin/python -c "import sys;from pathlib import Path;from open_guji_cv.core.book_config import effective_book_dict;d=effective_book_dict(Path(sys.argv[1]),apply_override=False);v=d.get(sys.argv[2]);print('' if v is None else v)" "$Y" "$1"; }
setkey() { grep -q "^$1:" "$Y" && sed -i "s/^$1: .*/$1: $2/" "$Y" || echo "$1: $2" >> "$Y"; }
[ -n "$CORPUS" ] && setkey corpus "$CORPUS"
[ -n "$GPIN" ] && setkey glyph_pin "$GPIN"
# 册 yaml 钉了 cv_version、装的又不是它，pipeline 会拒跑（要 --allow-cv-mismatch）。给了 --cv 就是需求单点名的版本：
# 本地册配置跟着改成装上的版本（只改本机数据目录，不推中心库）；没给 --cv 而对不上就只提醒
CVV=$(/opt/guji-venv/bin/python -c "from open_guji_cv.core.cv_version import describe;print(describe()[0] or '')")
OLD=$(eff cv_version)
if [ -n "$CV" ] && [ -n "$CVV" ] && [ "$OLD" != "$CVV" ]; then
  setkey cv_version "\"$CVV\""
  echo "册 yaml cv_version ${OLD:-（未钉）} → $CVV（跟 --cv）"
elif [ -n "$OLD" ] && [ "$OLD" != "$CVV" ]; then
  echo "⚠️ 册 yaml 钉 cv_version=$OLD，装的是 $CVV：用 --cv v$OLD 重跑本脚本，或按需求单给 --cv"
fi
echo "册配置 $Y（生效值）：corpus=$(eff corpus) glyph_pin=$(eff glyph_pin) cv_version=$(eff cv_version)"
[ -n "$PIN_ARGS" ] && t 钉子账 $G corpus pin --vol "$VOL" $PIN_ARGS -w "$WS"
GP=$(eff glyph_pin)
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
# 语料号和这版代码的字组文件对不上：设了 GUJI_CORPUS_DRIFT=warn（跑 pipeline 也照此放行）就只提醒不停
if [ -n "$CORPUS" ]; then
  if [ "${GUJI_CORPUS_DRIFT:-}" = warn ]; then
    echo "== 语料校验"; $G corpus verify --vol "$VOL" -w "$WS" || echo "⚠️ 语料与代码有漂移，按 GUJI_CORPUS_DRIFT=warn 放行"
  else
    t 语料校验 $G corpus verify --vol "$VOL" -w "$WS"
  fi
fi
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
# 换图源（GUJI-748）：册 yaml 钉了 source_rev，本机产物却是别的页表 rev（旧图）——这些产物和新页号的人裁不在一个坐标系，
# 拿它认格必然「认不出」。等同还没有切分产物。
from open_guji_cv.core.book import load_book
want = getattr(load_book(v), "source_rev", None)
have = ProductStore().source_rev(v)
if want is not None and have != int(want):
    sys.exit(print(f"人裁 {v}：按编号 {n0}（本机产物是页表 rev {have}，册 yaml 钉 rev {want}：换图源后还没有新图产物，"
                   f"绑定自检等跑完 Step3 再看）"))
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
