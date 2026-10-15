#!/usr/bin/env bash
# 建「沙箱工作区」：books／data_full／config 等以软链指向真工作区（只读用），不含 products／cache／runs／feedback／review／reports。
# 配合 GUJI_PRODUCTS_DIR／GUJI_CACHE_DIR 指到沙箱，跑长任务时不会往真工作区写任何东西。
# 用法：bash scripts/longrun_sandbox_ws.sh <真工作区> <沙箱ws目录>
set -eu
REAL="${1:?真工作区}"; SB="${2:?沙箱ws目录}"; mkdir -p "$SB"
for x in "$REAL"/*; do
  b="$(basename "$x")"
  case "$b" in products|cache|runs|reports|review|feedback) ;; *) ln -sfn "$x" "$SB/$b" ;; esac
done
echo "沙箱 ws：$SB（软链 $(ls "$SB" | wc -l) 项 → $REAL）；产物请用 GUJI_PRODUCTS_DIR／GUJI_CACHE_DIR 指到别处"
