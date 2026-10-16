#!/usr/bin/env bash
# 度量损失实验矩阵。每档只改损失，其余超参与 r4 的训练命令一致：
#   --epochs 60 --font-per-class 24 --extra-real zitools p1 印,楷 --extra-per-class 4
# （r4 原命令是 160 epoch；本实验为了扫超参统一压到 60，
#   所以**档与档之间可比，与线上 r4 的绝对值不可比**——r4 的数字另有
#   baseline_r4.json 用现役 checkpoint 直接测出来。）
set -u
cd "$(dirname "$0")/../.."
PY=./.venv/Scripts/python.exe
export PYTHONIOENCODING=utf-8
OUT=experiments/metric_loss/out
EXTRA="zitools:D:/data/glyph-sources/zitools/p1:印,楷"
COMMON="--epochs 60 --font-per-class 24 --extra-real $EXTRA --extra-per-class 4 \
  --heldout $OUT/split_eval.json --eval-every 10"

run () {  # run <name> <extra args...>
  local name=$1; shift
  if [ -f "$OUT/$name/history.json" ] && grep -q '"ep": 60' "$OUT/$name/history.json"; then
    echo "[skip] $name 已跑完"; return
  fi
  echo "=== $name ==="
  $PY experiments/metric_loss/train.py $COMMON --out "$OUT/$name" "$@" \
    > "$OUT/$name.log" 2>&1
  tail -5 "$OUT/$name.log"
}

# A 档：基线（现役损失形式）
run ce_base        --loss ce
# B 档：只换严格余弦头（隔离「换头」本身的影响，不加 margin）
run ce_coshead     --loss ce --cosine-head
# C 档：CosFace 扫 margin
run cosface_m010   --loss cosface --margin 0.10
run cosface_m020   --loss cosface --margin 0.20
run cosface_m035   --loss cosface --margin 0.35
# D 档：ArcFace 扫 margin
run arcface_m020   --loss arcface --margin 0.20
run arcface_m030   --loss arcface --margin 0.30
run arcface_m050   --loss arcface --margin 0.50
# E 档：方案 C（部件头权重）——06 卡说的「一小时基线对照」
run ce_compw10     --loss ce --comp-w 1.0
run ce_compw20     --loss ce --comp-w 2.0
# F 档：最好的 margin 档 + 加大部件权重（叠加是否还有增量）
run cosface_m020_compw10 --loss cosface --margin 0.20 --comp-w 1.0
