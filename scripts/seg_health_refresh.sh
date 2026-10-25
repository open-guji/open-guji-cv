#!/usr/bin/env bash
# 发版后刷新后台数据控制台「切分」栏：取各册 main 产物包和原图，跑切分体检，推到 progress.metric。
#
# 用法（云端 Default 环境，有 NEON_DATABASE_URL；约 15 册 10 分钟）：
#   bash scripts/seg_health_refresh.sh vol06 vol07 … vol20
#   SEG_NO_PUSH=1 bash scripts/seg_health_refresh.sh vol20     # 只算不推
# 产物和原图落在 $SEG_DIR（缺省 /tmp/seg-health），中心库数据（格位表、整理本）要先 guji db pull，没拉过会自动拉。
set -euo pipefail
[ $# -ge 1 ] || { echo "用法：bash scripts/seg_health_refresh.sh <册>…" >&2; exit 2; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIR="${SEG_DIR:-/tmp/seg-health}"
WS_ID="${SEG_WS:-siku-zongmu}"
mkdir -p "$DIR/ws" "$DIR/prod" "$DIR/raw"
[ -f "$DIR/ws/.central.json" ] || echo "{\"ws\":\"$WS_ID\",\"branch\":\"main\"}" > "$DIR/ws/.central.json"
export GUJI_WORKSPACE="$DIR/ws"
python3 -c "from open_guji_cv.core.workspace import corpus_path; import sys; sys.exit(0 if (corpus_path('daizhige')/'layout_slots.jsonl').exists() else 1)" \
  || guji db pull
for b in "$@"; do
  guji products pack fetch "$b" --to "$DIR/prod" --force
  guji source pull "$b" --to "$DIR/raw/$b"
done
python3 "$HERE/eval_seg_health.py" --root "$DIR/prod" --books "$@" --raw "$DIR/raw/{vol}/{page}.png" \
  --ws "$WS_ID" --json "$DIR/seg_health.json" $([ -n "${SEG_NO_PUSH:-}" ] || echo --push)
