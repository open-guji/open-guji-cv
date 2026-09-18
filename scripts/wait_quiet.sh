#!/bin/bash
# 等仓库安静：管线相关文件 10 分钟没被改动、且工作区没有未提交的 code_deps，才放行。
cd "$(dirname "$0")/.." || exit 1
for i in $(seq 1 60); do
  recent=$(find open_guji_cv/steps open_guji_cv/utils open_guji_cv/clustering open_guji_cv/core \
            -name "*.py" -newermt "-10 minutes" 2>/dev/null | wc -l)
  dirty=$(git status --short | grep -vE "^\?\?" | grep -cE "steps/|utils/|clustering/|core/")
  if [ "$recent" -eq 0 ] && [ "$dirty" -eq 0 ]; then
    echo "QUIET at $(date +%H:%M) (head=$(git rev-parse --short HEAD))"
    exit 0
  fi
  sleep 60
done
echo "TIMEOUT: still busy after 60min (recent=$recent dirty=$dirty)"
exit 1
