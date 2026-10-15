# longrun job：GUJI-208ex 件二 2b——「窄对合并分支（开关关）」对「main 代码」的全册产物字节对比（Step1＋闸1＋Step2＋闸2）。
# 首个用例（GUJI-508）。用法见 doc/longrun.md。必须设置的环境变量（start 时用 --env 传下去，resume 自动带）：
#   CVA   main 代码的 cv 检出（如 4eed859 的 worktree）      CVB   分支代码的 cv 检出（如 claude/narrow-pair-merge-1014）
#   SBX   沙箱根（产物 prodA／prodB、缓存 cacheA／cacheB 都写这里；不碰正式 products/）
#   WS    沙箱工作区（SBX/ws：books、data_full 等指向真工作区的软链，不含 products/cache/runs）
# 可选：BOOKS（默认 vol01..vol07）、JOBS（页级并行，默认 4）
: "${CVA:?}" "${CVB:?}" "${SBX:?}" "${WS:?}"
: "${BOOKS:=vol01 vol02 vol03 vol04 vol05 vol06 vol07}"; : "${JOBS:=4}"
STEPS=border_detect,border_detect_gate,column_warp,column_gate
CHK="$LONGRUN_SCRIPTS/longrun_fresh_check.py"
for side in A B; do
  cv=$CVA; [ $side = B ] && cv=$CVB
  for v in $BOOKS; do
    envs="PYTHONPATH=$cv GUJI_PRODUCTS_DIR=$SBX/prod$side GUJI_CACHE_DIR=$SBX/cache$side"
    step "${side}_${v}" \
      "env $envs guji pipeline keben_body_v2 $v -w $WS --from border_detect --to column_warp --pages all --jobs $JOBS" \
      "env $envs guji status $v -w $WS --pages all --json 2>/dev/null | python3 -I $CHK $STEPS"
  done
done
# 最后一步只出对比，不论有无差异都算步骤完成（差异是结果，不是故障）
step compare "bash $LONGRUN_SCRIPTS/longrun.sh compare $SBX/prodA $SBX/prodB | tee $SBX/compare_A_vs_B.txt; true"
