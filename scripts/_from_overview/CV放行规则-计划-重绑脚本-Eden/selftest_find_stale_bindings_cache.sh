#!/usr/bin/env bash
# GUJI-208kx 合成自测：缓存相符／缓存陈旧／缓存缺失 三情形 + 证明脚本只读（运行前后 h_lane_surface snap 一致，且整个 WS 树的 sha 清单一致）。不用真数据。
HERE="$(cd "$(dirname "$0")" && pwd)"; F="$HERE/find_stale_bindings_cache.py"; H="$HERE/h_lane_surface.py"
T=$(mktemp -d /tmp/f208kx.XXXXXX); WS=$T/ws; mkdir -p $WS/feedback/events $WS/feedback/bindings/vol01 $WS/feedback/bindings/vol02 $WS/products/vol01/row_segment $WS/products/vol02/row_segment
for p in 1 2 3; do echo "{\"page\":$p}" > $WS/products/vol01/row_segment/p000$p.json; done
echo '{"page":1}' > $WS/products/vol02/row_segment/p0001.json
python3 - "$WS" <<'PY'
import sys, json, hashlib
ws = sys.argv[1]
ev = []
def e(i, batch, seq, key, unit="cell", kind="confirm", ts="2026-10-01T00:00:0%dZ"):
    return {"id": i, "ts": ts % seq, "batch": batch, "seq": seq, "kind": kind, "payload": {"shape": "字"}, "target": {"step": "seed_admit", "unit": unit, "key": key, "book": key.split(":")[0], "page": int(key.split(":")[1])}}
rows = [e("evt_a_1", "a", 1, "vol01:1:1:1"), e("evt_a_2", "a", 2, "vol01:2:1:1"), e("evt_a_3", "a", 3, "vol01:3:1:1"), e("evt_a_4", "a", 4, "vol02:1:1:1")]
open(ws + "/feedback/events/a.jsonl", "w", encoding="utf-8").write("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
def cache(book, page, sig, cells=None):
    cells = cells or sha(f"{ws}/products/{book}/row_segment/p{page:04d}.json")
    open(f"{ws}/feedback/bindings/{book}/p{page:04d}.json", "w").write(json.dumps({"v": 6, "cells_sha": cells, "sig": sig, "rows": []}))
cache("vol01", 1, "1:evt_a_1")                       # 相符
cache("vol01", 2, "1:evt_a_2", cells="0" * 64)        # 陈旧：cells_sha 不同（Step3 产物变了）
# vol01 p3：不写缓存 → 缺失
cache("vol02", 1, "1:evt_a_4")                       # vol02 全部相符
PY
manifest(){ (cd $WS && find . -type f | sort | xargs sha256sum | sha256sum); }
M0=$(manifest); python3 -I $H snap $WS --out $T/s0.json > /dev/null; echo "运行前 WS 树摘要：$M0"
echo "== 情形一：相符（只查 vol02）应 rc=0 =="; python3 -I $F $WS vol02; echo "  rc=$?"
echo "== 情形二+三：陈旧（vol01 p2：cells_sha 不同）＋缺失（vol01 p3：无缓存）应 rc=1 =="; python3 -I $F $WS vol01; echo "  rc=$?"
echo "== 同时查两册 =="; python3 -I $F $WS vol01 vol02 | sed -n '/== vol/p;/结论/p'; echo "  rc=${PIPESTATUS[0]}"
echo "== 环境变量覆盖 → rc=2 =="; GUJI_FEEDBACK_DIR=/x python3 -I $F $WS vol01; echo "  rc=$?"
echo "== 册没有事件目录 → rc=2 =="; rm -rf $T/ws2; mkdir -p $T/ws2/feedback; python3 -I $F $T/ws2 vol01; echo "  rc=$?"
M1=$(manifest); echo "运行后 WS 树摘要：$M1"; [ "$M0" = "$M1" ] && echo "→ 整个 WS 树 sha 清单一致（脚本没改任何文件）" || echo "→ 不一致！"
echo "== h_lane_surface：snap（运行前）对 check（运行后） =="; python3 -I $H check $WS --base $T/s0.json; echo "  rc=$?"
rm -rf $T
