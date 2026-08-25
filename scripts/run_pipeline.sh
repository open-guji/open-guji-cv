#!/bin/bash
# 全流程：segment → chars → cluster → label，两册**并行**、逐阶段计时。
# 用法：bash scripts/run_pipeline.sh [vol01 vol02 ...]
set -u
export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True PYTHONIOENCODING=utf-8
cd "$(dirname "$0")/.."
books=("${@:-vol01 vol02}")
[ $# -eq 0 ] && books=(vol01 vol02)

# segment 页级并行度：多册并行时按册分核（2 册 × 满核在 4 核机上互相挤）
cores=$(nproc 2>/dev/null || echo 1)
GUJI_WORKERS=$(( cores / ${#books[@]} )); [ "$GUJI_WORKERS" -lt 1 ] && GUJI_WORKERS=1
export GUJI_WORKERS

run_book() {
  local b=$1
  # 注意：chars 之后必跑 replay_recrops —— segment/chars 会整份重写
  # index.jsonl 与 patches，人工重切的框就没了（实测 24 条归零）。真源在
  # 数据集 char-segmentation/instances（seed=review_recrop），贴回即可。
  # 幂等，没有可贴的就是个空操作。
  for step in "segment output/$b --chars-per-line 21" "chars output/$b" \
              "cluster output/$b" "label output/$b"; do
    local s=$(date +%s)
    python -m open_guji_cv $step > "/tmp/pipe_${b}_${step%% *}.log" 2>&1
    local rc=$?
    echo "[$b] ${step%% *}: $(( $(date +%s) - s ))s rc=$rc"
    if [ $rc -ne 0 ]; then
      echo "[$b] ${step%% *} 失败，日志 /tmp/pipe_${b}_${step%% *}.log"; return 1
    fi
    if [ "${step%% *}" = "chars" ]; then
      PYTHONPATH=. python scripts/replay_recrops.py "output/$b" --apply \
        >> "/tmp/pipe_${b}_chars.log" 2>&1 \
        && echo "[$b] replay_recrops: 人工重切已贴回" \
        || echo "[$b] replay_recrops 失败（人工重切没贴回！）日志 /tmp/pipe_${b}_chars.log"
    fi
  done
  # 注意不能写成 `[ $rc -ne 0 ] && {...}`：rc=0 时整个复合命令状态为 1，
  # 作为循环体最后一条命令会把成功的册误报成 fail=1
  return 0
}

t0=$(date +%s)
pids=()
for b in "${books[@]}"; do run_book "$b" & pids+=($!); done
fail=0
for p in "${pids[@]}"; do wait "$p" || fail=1; done
echo "总耗时 $(( $(date +%s) - t0 ))s  fail=$fail"
[ $fail -eq 0 ] && echo "=== PIPELINE_DONE" || echo "=== PIPELINE_FAILED"
