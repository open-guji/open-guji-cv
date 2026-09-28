#!/bin/bash
# 用法: run3.sh <cv代码根> <书目录ws> <book> <products_dir> <sandbox根(glyph.db/fb/cache)> <params-json> [pages]
set -e
CODE=$1; WS=$2; BOOK=$3; PD=$4; SBX=$5; PARAMS=$6; PAGES=${7:-all}
export GUJI_PRODUCTS_DIR=$PD GUJI_GLYPH_DB=$SBX/glyph.db GUJI_FEEDBACK_DIR=$SBX/fb GUJI_CACHE_DIR=$SBX/cache
export PYTHONPATH=$CODE PYTHONIOENCODING=utf-8
PY=${PY:-$CODE/.venv/bin/python}
cd $CODE
for st in align_ref context_decide seed_admit; do
  echo "== $st $(date -u +%T)"
  $PY -m open_guji_cv step $st $BOOK -w $WS --pages $PAGES --force --jobs 1 --params "$PARAMS" 2>&1 | tail -3
done
echo "RUN3 DONE $(date -u +%T)"
