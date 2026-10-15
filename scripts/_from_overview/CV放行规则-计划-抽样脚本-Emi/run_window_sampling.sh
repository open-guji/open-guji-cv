#!/usr/bin/env bash
# 窗口当日抽样一键脚本（GUJI-208gq，Emi）。用法见同目录 README.md。
# 顺序：自测 → 主跑（sample_newadmit.py） → 自测。任一步非 0 即停，退出码原样报告，不吞。
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PYTHON:-python3}"
SCRIPT="$HERE/sample_newadmit.py"

if [ $# -lt 4 ]; then
  echo "用法：$0 <基线表> <A臂表目录> <force名单> <输出目录> [对位表.tsv]" >&2
  exit 64
fi
BASE="$1"; ARMDIR="$2"; FORCE="$3"; OUT="$4"; REMAP="${5:-}"

hint() {
  case "$1" in
    1) echo "退出码 1｜自测失败：脚本本身不可信，停止，不出清单。" ;;
    2) echo "退出码 2｜需人定：force＋hint＋juan_rule 超上限，或抽样后仍超上限。请人定调高上限或收窄规则，不要自行放宽。" ;;
    3) echo "退出码 3｜红线停线：红线格缺失、已放行或从待审变放行（或红线集合为空）。须人工核实，不得继续出清单。" ;;
    4) echo "退出码 4｜无对位超线：A 臂放行格对不上基线。先由 remap 产出方（Ethan／Eden）给对位表，再重跑。" ;;
    5) echo "退出码 5｜强制名单格式不合：force 名单有行不是 volNN:页:列:行（stderr 与摘要里逐行列出）。输出已写出但不可直接用，修正名单后重跑。" ;;
    *) echo "退出码 $1｜异常，原样报告，不当作成功。" ;;
  esac >&2
}

step_selftest() {
  echo "== [$1] 自测：sample_newadmit.py --selftest"
  "$PY" -I "$SCRIPT" --selftest
  rc=$?
  if [ "$rc" -ne 0 ]; then hint "$rc"; exit "$rc"; fi
}

for p in "$BASE" "$FORCE"; do
  if [ ! -f "$p" ]; then echo "找不到文件：$p" >&2; exit 66; fi
done
if [ ! -d "$ARMDIR" ]; then echo "找不到 A 臂表目录：$ARMDIR" >&2; exit 66; fi
if [ -n "$REMAP" ] && [ ! -f "$REMAP" ]; then echo "找不到对位表：$REMAP" >&2; exit 66; fi

step_selftest 1/3

# 把 A 臂目录下各册表合并成一份（册头行无 id，脚本读取时会跳过）。合并件放 _work，不进输出根目录。
WORK="$OUT/_work"
mkdir -p "$WORK"
ARM="$WORK/arm_combined.jsonl"
shopt -s nullglob
files=("$ARMDIR"/*.jsonl "$ARMDIR"/*.jsonl.gz)
shopt -u nullglob
if [ ${#files[@]} -eq 0 ]; then
  echo "A 臂目录里没有 .jsonl 或 .jsonl.gz：$ARMDIR" >&2
  exit 66
fi
: > "$ARM"
for f in "${files[@]}"; do
  case "$f" in
    *.gz) gzip -dc "$f" >> "$ARM" ;;
    *)    cat "$f" >> "$ARM" ;;
  esac
done
echo "== A 臂合并：${#files[@]} 个文件 → $ARM"

echo "== [2/3] 主跑：sample_newadmit.py"
ARGS=(--base "$BASE" --arm "$ARM" --out "$OUT" --force-all "$FORCE")
if [ -n "$REMAP" ]; then ARGS+=(--remap "$REMAP"); fi
"$PY" -I "$SCRIPT" "${ARGS[@]}"
rc=$?
if [ "$rc" -ne 0 ]; then hint "$rc"; exit "$rc"; fi

step_selftest 3/3

echo "== 完成：输出 $OUT（看图清单见 抽样.tsv／cells.txt，摘要见 摘要.md）"
exit 0
