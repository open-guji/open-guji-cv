#!/usr/bin/env bash
# rerun_prep.sh — 云端新会话一条命令备好一册重跑（A30「一会话一册」，2026-10-24）
#
#   rerun_prep.sh <册> [--cv <tag/分支/提交>] [--corpus N] [--pin-args "<guji corpus pin 的参数>"]
#                 [--glyph-pin N] [--ws-glob 96mid1ogzk-*] [--ws-repo owner/repo] [--base] [--reset]
#
# --ws-repo：这部书自己一个仓（仓根即工作区，2026-10-30 全唐文起）；缺省走 open-guji/guji-workspace 里 --ws-glob 匹配的目录。
# --reset：本机数据目录已被上一次准备改过（册 yaml、钉子账）时先 db pull --force 还原（并重建 glyph.db），再按这次的参数改。
#          任务库执行方（guji_jobs）在同一会话接第二张单时用；本机有没推的人裁别加。
#
# 依次：cv 切到需求单版本 → 克隆 guji-workspace → guji db pull → 改册 yaml（corpus／glyph_pin；给了 --cv 时 cv_version 跟着改）
# → 追加语料钉子账 → 建钉版字形库并核刻例非 0 → 取原图并合扫检查 → 预拉 Step5-b 模板索引（fp32）
# → 语料校验 → guji status。每步计时，最后打印汇总和开跑命令。任何一步失败即停（退出码非 0）。
# 只做准备，不跑 pipeline、不推库、不存包。环境：/opt/guji-cv-seed + /opt/guji-venv（Default 环境快照）。
set -euo pipefail
VOL=${1:?用法见脚本头}; shift
CV= CORPUS= PIN_ARGS= GPIN= WSGLOB='96mid1ogzk-*' WSREPO= BASE=0 RESET=0
while [ $# -gt 0 ]; do case $1 in
  --cv) CV=$2; shift 2;; --corpus) CORPUS=$2; shift 2;; --pin-args) PIN_ARGS=$2; shift 2;;
  --glyph-pin) GPIN=$2; shift 2;; --ws-glob) WSGLOB=$2; shift 2;; --ws-repo) WSREPO=$2; shift 2;; --base) BASE=1; shift;; --reset) RESET=1; shift;;
  *) echo "不认识的参数 $1" >&2; exit 2;; esac; done
G=/opt/guji-venv/bin/guji; SEED=/opt/guji-cv-seed; GW=$HOME/guji-workspace; SUM=()
# 面板里写的 GUJI_DATA_TOKEN=$GUJI_DATA_TOKEN_PROD 不展开（字面量 401）；旧版 cv 不认，这里先展开
case "${GUJI_DATA_TOKEN:-}" in \$*) r=${GUJI_DATA_TOKEN#\$}; r=${r#\{}; r=${r%\}}
  if [ -n "${!r:-}" ]; then export GUJI_DATA_TOKEN=${!r}; else unset GUJI_DATA_TOKEN; fi;; esac
[ -n "${GUJI_DATA_TOKEN:-}" ] || export GUJI_DATA_TOKEN=${GUJI_DATA_TOKEN_READ:?缺读令牌}
EM="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/ensure_manager.sh"   # guji-manager：开工装好并跟到 main
if [ -f "$EM" ]; then . "$EM"; else ensure_manager() { :; }; fi
t() { local s=$SECONDS n=$1; shift; echo "== $n"; "$@"; SUM+=("$(printf '%-14s %4ss' "$n" $((SECONDS-s)))"); }

# 书仓 fetch origin main（网络抖动重试 3 次）。失败就保留旧检出、不动它：里面有可再生的 cache/、products/（殿本十几 GB）。
# git 的真实报错原样打进日志（2026-11-09：#1746 两台机都报「拉不到 origin main」，看不出原因）。
ws_fetch() {
  local d=$1 i err
  git -C "$d" sparse-checkout disable >/dev/null 2>&1 || true   # 稀疏检出会缺书级代码目录
  for i in 1 2 3; do
    if err=$(git -C "$d" fetch -q origin main 2>&1); then return 0; fi
    echo "fetch 工作区 $d 第 $i 次失败：$err" >&2; sleep $((i * 2))
  done
  return 1
}
# 重建书仓：旧目录先改名 .bak，克隆成功才删；克隆失败就改回去，旧目录原样保留
ws_rebuild() {
  local d=$1 bak="$1.bak.$$"
  [ -e "$d" ] && mv "$d" "$bak"
  if git clone -q --depth 1 "https://github.com/$WSREPO" "$d"; then rm -rf "$bak"; return 0; fi
  rm -rf "$d"; [ -e "$bak" ] && mv "$bak" "$d"
  return 1
}
# 清理被中断的重建留下的 <书仓>.bak.<pid>：只在书仓本身已在位（有 .git）且那个 pid 已不在时删，不删唯一一份
ws_clean_bak() {
  local d=$1 b pid
  [ -d "$d/.git" ] || return 0
  for b in "$d".bak.*; do
    [ -d "$b" ] || continue
    pid=${b##*.bak.}
    if [[ "$pid" =~ ^[0-9]+$ ]] && ! kill -0 "$pid" 2>/dev/null; then
      rm -rf "$b" && echo "清掉被中断重建的残留 $b" >&2
    fi
  done
}
# 书级代码 code/code.yaml：HEAD 里有、检出里没有（稀疏检出或旧克隆）＝seg_set 不认，直接停（2026-11-09 史記 #1736）
ws_code_check() {
  local p; p=$(git -C "$1" rev-parse --show-prefix 2>/dev/null) || return 0
  if git -C "$1" cat-file -e "HEAD:${p}code/code.yaml" 2>/dev/null && [ ! -f "$1/code/code.yaml" ]; then
    echo "⚠️ 工作区 $1 缺 code/code.yaml（HEAD 有；稀疏检出或旧克隆），请删掉本机那份重跑准备" >&2; return 1
  fi
}
if [ -n "$CV" ]; then
  t cv git -C $SEED fetch -q --tags origin "$CV"
  git -C $SEED checkout -q "$CV" 2>/dev/null || git -C $SEED checkout -q FETCH_HEAD
fi
ensure_manager
# v0.7 起 cv 仓不带 models/、fonts/ 和底库语料大文件（走 R2）：切到新版后这些文件已被检出删掉，要在「模板索引」等用到 checkpoint 的段之前取回，
# 否则 checkpoint 指纹是 nockpt，对不上已发布的向量包（2026-11-10 SJ r32 #1833/#1835/#1839 三单 prep 失败）。取不到只提醒，后面的段会报具体缺什么。
t 取回模型字体 /opt/guji-venv/bin/python -c "from open_guji_cv.manager_api import ensure_repo_models; ensure_repo_models()" || echo "⚠️ 从 R2 取回 models/fonts 失败（看上面；查 GUJI_DATA_TOKEN／_READ）" >&2
echo "cv $(git -C $SEED rev-parse --short HEAD) $(git -C $SEED describe --tags 2>/dev/null || true)"
if [ -n "$WSREPO" ]; then
  case "${WSREPO##*/}" in ""|.|..|*[!A-Za-z0-9._-]*) echo "⚠️ 工作区仓名不合规：$WSREPO" >&2; exit 1;; esac
  GW1="$HOME/${WSREPO##*/}"
  # fetch 不通（网络／凭据）：保留旧检出，直接停，不重克隆
  if [ -d "$GW1/.git" ]; then
    ws_fetch "$GW1" || { echo "⚠️ 拉不到 $WSREPO（网络或凭据），保留旧检出 $GW1，请看上方 git 报错" >&2; exit 1; }
    # fetch 成功但 reset 失败（检出损坏）：改名重建
    if ! err=$(git -C "$GW1" reset -q --hard origin/main 2>&1); then
      echo "⚠️ 旧检出 $GW1 reset 失败（$err），改名重克隆" >&2
      ws_rebuild "$GW1" || { echo "⚠️ 重克隆 $WSREPO 也失败，请看上方 git 报错" >&2; exit 1; }
    fi
  else
    # 不能用 t 包：t 末尾记耗时的赋值总返回 0，克隆失败也当成功（10-31 #1203）
    echo "== 克隆工作区"
    if ! ws_rebuild "$GW1"; then   # 会话没挂这个仓（迁仓过渡期）：退回旧总仓里同一本书的目录（内容相同）
      echo "⚠️ 读不了 $WSREPO（会话里 add_repo $WSREPO 就走新仓），退回 open-guji/guji-workspace" >&2
      WSREPO=
    fi
  fi
  ws_clean_bak "$GW1"
  if [ -n "$WSREPO" ]; then GW=$GW1; WS=$GW; export GUJI_WORKSPACE=$WS; fi
fi
if [ -z "$WSREPO" ]; then
  [ -d $GW/.git ] || t 克隆工作区 git clone -q --depth 1 https://github.com/open-guji/guji-workspace $GW
  # 快照里的旧克隆没有这之后新建的书目录（GUJI-全唐文 10-28：#891 找不到 995ejelvk0-*），匹配不到就先拉一次
  ls -d $GW/$WSGLOB >/dev/null 2>&1 || t 更新工作区 git -C $GW pull -q --ff-only origin main
  WS=$(ls -d $GW/$WSGLOB | head -n 1); export GUJI_WORKSPACE=$WS;
fi
[ -n "${WS:-}" ] && [ -d "$WS" ] || { echo "⚠️ 没找到册 $VOL 的工作区（ws_glob=$WSGLOB）" >&2; exit 1; }
ws_code_check "$WS" || exit 1
echo "WS=$WS"
# --reset 也要重建 glyph.db：上一次准备若在拉库前就失败（如克隆工作区失败），本机 glyph.db 还没建过，
# --no-rebuild 会留下空库，建钉版库时报 no such table: sources（10-25 #3–#6）
# 按需拉取（2026-11-02，中心库维护方案）：只跑 pipeline 用不着线上单（feedback/lists/proofing/，殿本 110 MB、常变），
# 缺省不拉；这样拉的数据目录不能 push／sync。要整拉：GUJI_PULL_EXCLUDE=- 。旧版 cv 不认这个变量，照旧整拉。
export GUJI_PULL_EXCLUDE=${GUJI_PULL_EXCLUDE-run}
if [ $RESET = 1 ]; then t db-pull $G db pull -w "$WS" --force; else t db-pull $G db pull -w "$WS"; fi
# 数据目录里的册配置（db pull 落的）。各书的册号会重名（vol01），按工作区自己的 .central.json 里的 ws id 找，不能取第一个
WSID=$(sed -n 's/.*"ws": *"\([^"]*\)".*/\1/p' "$WS/.central.json" 2>/dev/null | head -n 1)
Y=$(ls /root/.guji-data/main/${WSID:-*}/books/"$VOL".yaml | head -n 1)
# 文意 L2／L3 自检（2026-10-31，A24 查「ctx_l2 没挂上、裁定 no_api_key」）：venv 有没有 anthropic，密钥有没有，L2 小头落没落
if /opt/guji-venv/bin/python -c "import anthropic" 2>/dev/null; then echo "自检 anthropic：可导入"
else echo "⚠️ 自检 anthropic：装不上（llm 依赖缺）；有密钥时 L3 会按无密钥弃权，试着补装"
  if command -v uv >/dev/null && uv pip install -q --python /opt/guji-venv/bin/python 'anthropic>=2.3'; then echo "  已补装 anthropic"
  else echo "  补装失败，请看环境" >&2; fi
fi
echo "自检 GUJI_ANTHROPIC_API_KEY：$([ -n "${GUJI_ANTHROPIC_API_KEY:-}" ] && echo 已设 || echo 未设)"
echo "自检 l2model（数据目录 config/groups/l2model）：$(ls /root/.guji-data/main/${WSID:-*}/config/groups/l2model/ 2>/dev/null | tr '\n' ' ' || true)"
# 册配置分层后（config/book_defaults.yaml），corpus／glyph_pin／cv_version 可能不在册 yaml 里而在基础配置里。
eff() { /opt/guji-venv/bin/python -c "import sys;from pathlib import Path;from open_guji_cv.core.book_config import effective_book_dict;d=effective_book_dict(Path(sys.argv[1]));v=d.get(sys.argv[2]);print('' if v is None else v)" "$Y" "$1"; }
# 改值（2026-11-03）：装的 cv 认运行覆盖（core/book_config.py）就不动册 yaml，改值记进 GUJI_BOOK_OVERRIDE（JSON，
# 叠在原有覆盖上），本脚本后面的步骤和开跑的 pipeline 都读它；旧 tag 不认，才退回改本机册 yaml（册 yaml 里有就替换、没有就追加）。
# 读值 = 读合并后的生效值（含运行覆盖），不能再 grep 册 yaml
# 从空覆盖起：上一册 source ~/.guji_env 留下的覆盖不能带进这一册（别的覆盖项开跑时用 pipeline --override 给）
unset GUJI_BOOK_OVERRIDE
if /opt/guji-venv/bin/python -c "from open_guji_cv.core.book_config import OVERRIDE_ENV" 2>/dev/null; then OVMODE=env; else OVMODE=sed; fi
setkey() {
  if [ $OVMODE = env ]; then
    GUJI_BOOK_OVERRIDE=$(/opt/guji-venv/bin/python -c "import json,os,sys;d=json.loads(os.environ.get('GUJI_BOOK_OVERRIDE') or '{}');d[sys.argv[1]]=json.loads(sys.argv[2]);print(json.dumps(d,ensure_ascii=False))" "$1" "$2")
    export GUJI_BOOK_OVERRIDE
  else
    grep -q "^$1:" "$Y" && sed -i "s/^$1: .*/$1: $2/" "$Y" || echo "$1: $2" >> "$Y"
  fi
}
[ -n "$CORPUS" ] && setkey corpus "$CORPUS"
[ -n "$GPIN" ] && setkey glyph_pin "$GPIN"
# 册 yaml 钉了 cv_version、装的又不是它，pipeline 会拒跑（要 --allow-cv-mismatch）。给了 --cv 就是需求单点名的版本：
# 本地册配置跟着改成装上的版本（只改本机数据目录，不推中心库）；没给 --cv 而对不上就只提醒
CVV=$(/opt/guji-venv/bin/python -c "from open_guji_cv.core.cv_version import describe;print(describe()[0] or '')")
OLD=$(eff cv_version)
if [ -n "$CV" ] && [ -n "$CVV" ] && [ "$OLD" != "$CVV" ]; then
  setkey cv_version "\"$CVV\""
  echo "cv_version ${OLD:-（未钉）} → $CVV（跟 --cv；$([ $OVMODE = env ] && echo 记进运行覆盖 || echo 改本机册 yaml)）"
elif [ -n "$OLD" ] && [ "$OLD" != "$CVV" ]; then
  echo "⚠️ 册 yaml 钉 cv_version=$OLD，装的是 $CVV：用 --cv v$OLD 重跑本脚本，或按需求单给 --cv"
fi
echo "册配置 $Y（生效值）：corpus=$(eff corpus) glyph_pin=$(eff glyph_pin) cv_version=$(eff cv_version)"
# 任务库执行方从这一行取覆盖，开跑 pipeline 时原样带上（--override）
if [ $OVMODE = env ]; then echo "OVERRIDE=${GUJI_BOOK_OVERRIDE:-}"; fi
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
# 预热字块图缓存（2026-11-09 Ops：人裁所在格的字块图 cache/ 里没有、原图也切不出 → 整页失败）：原图取到后先预渲，人裁格才认得出
t 预热字块 $G cache warm --book "$VOL" -w "$WS" --jobs 4
# 钉了页表版（source_rev，换图源后）的册：原图目录归页表管，页表外的 <页号>.png 是旧图源残留，删掉（GUJI-748：vol04 新页表 218 页，
# worker 目录里留着旧的 219–221.png，被当正文跑了）。新版 cv 的 source pull 自己会删，这里兼顾旧 tag。
GUJI_WORKSPACE="$WS" /opt/guji-venv/bin/python - "$VOL" <<'PY'
import sys
from open_guji_cv.core.book import load_book
from guji_manager.datastore import sources as S
b = load_book(sys.argv[1])
if getattr(b, "source_rev", None) is None:
    sys.exit(0)
from open_guji_cv.datastore.client import WorkerSource
from guji_manager.datastore.packs import _ws_name
src = WorkerSource()
book_id, vol = S.resolve(src, _ws_name(), b.id)
want = {int(p["page"]) for p in S.read_table(src, book_id, vol, b.source_rev)["pages"]}
d = b.raw_path(next(iter(want))).parent
gone = sorted((f for f in d.glob("*.png") if f.stem.isdigit() and int(f.stem) not in want), key=lambda f: int(f.stem))
for f in gone:
    f.unlink()
print(f"页表 r{b.source_rev} {len(want)} 页；删掉页表外残留 {len(gone)} 张：{[f.name for f in gone][:10]}")
# 产物目录里也有旧图源残留：worker 上这册旧页号的页产物（旧页数多于新页表）会被 Step3 配页当正文页读，
# 找不到原图而停（GUJI-748：vol53 旧 183 页、新 182 页，row_segment 要 183.png）。页表外的页产物一并删。
import os, re
from pathlib import Path
root = Path(os.environ.get("GUJI_PRODUCTS_DIR") or (Path(os.environ["GUJI_WORKSPACE"]) / "products"))
n = 0
if (root / b.id).is_dir():
    for f in (root / b.id).rglob("p[0-9][0-9][0-9][0-9]*"):
        m = re.match(r"p(\d{4})(?:\D|$)", f.name)
        if m and f.is_file() and int(m.group(1)) not in want:
            f.unlink()
            n += 1
print(f"删掉产物目录里页表外的旧页产物 {n} 个")
PY
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
# 新书没有任何人裁事件，中心库里就没有 feedback/events 目录，db pull 不会建；这里只是自检，目录不在当没有（GUJI_ALLOW_NO_EVENTS=1），
# 不影响 pipeline 里 seed_admit 自己的检查（全唐文 10-28 #891 卡在这里）
t 人裁自检 env GUJI_ALLOW_NO_EVENTS=1 /opt/guji-venv/bin/python - "$VOL" <<'PY'
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
{ echo "export GUJI_WORKSPACE='$WS'"
  if [ $OVMODE = env ] && [ -n "${GUJI_BOOK_OVERRIDE:-}" ]; then echo "export GUJI_BOOK_OVERRIDE='$GUJI_BOOK_OVERRIDE'"; fi
} > "$HOME/.guji_env"
echo; echo "== 准备耗时"; printf '%s\n' "${SUM[@]}"
echo "之后的命令先 source ~/.guji_env（设 GUJI_WORKSPACE，人裁事件只认它；有改值时还设 GUJI_BOOK_OVERRIDE）"
echo "开跑：guard_run $VOL -- $G pipeline keben_body_v2 $VOL -w \"$WS\" --pages all --no-pack"
