#!/bin/bash
# 快循环基准（用户定的迭代纪律：先测试集、后整册）：
# 只在金标涉及的页子集上重跑 chars 并评测，~2 分钟出全套数字。
#
#   bash scripts/quick_bench.sh            # chars 阶段改动的快验
#
# 原理：chars 逐页独立（无书级共识），子集结果与整册逐字节一致。
# 注意 chars --range 会整写 index.jsonl（只剩子集页），所以先把金标页
# 的 phase3/页图**符号链接**进临时书目录，在那里跑，不碰 output/。
# segment 阶段改动不能用本脚本（书级共识依赖整册），用病例页装具
# （显式传书级先验）或整册跑。
set -euo pipefail
cd "$(dirname "$0")/.."
export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True PYTHONIOENCODING=utf-8
DS=${DS:-../open-guji-dataset}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# 金标涉及页：instances + page-geometry + column-layout
python - "$DS" "$TMP" <<'PY'
import json, sys, glob
from pathlib import Path
ds, tmp = sys.argv[1], sys.argv[2]
pages = set()
for e in json.loads(Path(ds, 'char-segmentation/instances/expected.json').read_text(encoding='utf-8')):
    pages.add((e['book'], e['page']))
for f in glob.glob(f'{ds}/page-geometry/samples/*.json') + \
         glob.glob(f'{ds}/column-layout/samples/*.json'):
    d = json.loads(Path(f).read_text(encoding='utf-8'))
    if 'book' in d and 'page' in d:
        pages.add((d['book'], str(d['page'])))
for book in ('vol01', 'vol02'):
    bdir = Path(tmp, 'output', book)
    (bdir / 'phase3_char_grid').mkdir(parents=True)
    src = Path('output', book).resolve()
    (bdir / 'profile.json').symlink_to(src / 'profile.json')
    n = 0
    for b, p in pages:
        if b != book:
            continue
        g = src / 'phase3_char_grid' / f'{p}_char_grid.json'
        img = src / f'{p}.png'
        if g.exists() and img.exists():
            (bdir / 'phase3_char_grid' / g.name).symlink_to(g)
            (bdir / f'{p}.png').symlink_to(img)
            n += 1
    print(book, n, '页')
PY

for b in vol01 vol02; do
  python -m open_guji_cv -o "$TMP/output" chars "$TMP/output/$b" \
    > "$TMP/chars_$b.log" 2>&1 || { echo "chars $b 失败"; tail "$TMP/chars_$b.log"; exit 1; }
done

cd "$TMP"
ln -sfn "$OLDPWD/scripts" scripts
export PYTHONPATH="$OLDPWD"
echo "===== instances ====="
python scripts/eval_instance_quality.py "$OLDPWD/$DS/char-segmentation/instances" 2>/dev/null | sed -n '6,9p' || true
echo "===== recrop ====="
python scripts/eval_recrop.py "$OLDPWD/$DS/char-segmentation/instances" 2>/dev/null | tail -2
echo "===== QUICK_BENCH_DONE ====="
