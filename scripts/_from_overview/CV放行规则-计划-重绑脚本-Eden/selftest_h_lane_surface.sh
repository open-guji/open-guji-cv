#!/usr/bin/env bash
# GUJI-208ks 干跑：合成工作区，S4 记 sha／建 .s0_stamp／S27 自检各跑一遍，再改一个／增一个／删一个。不用真产物。
# 用法：bash selftest_h_lane_surface.sh   （脚本无 set -e；每步显式打印 rc）
H="$(cd "$(dirname "$0")" && pwd)/h_lane_surface.py"
T=$(mktemp -d /tmp/h208ks.XXXXXX); WS=$T/ws; SBX=$T/sbx; SNAP=$T/snap; CV=$T/cv; mkdir -p $T/win1020
mk(){ mkdir -p "$(dirname "$WS/$1")"; printf '%s\n' "$2" > "$WS/$1"; }
mk feedback/events/b1.jsonl '{"e":1}'; mk feedback/consumed/gold_add.jsonl '{"c":1}'; mk feedback/routes.yaml 'a: b'
mk feedback/verdicts/00/items.jsonl '{"v":1}'; mk feedback/bindings/vol04/p0001.json '{"cells_sha":"x"}'
mk feedback/anchors/vol04.jsonl '{"a":1}'; mk feedback/anchor_patches/p.json '{}'
mk config/crop_exclusions.jsonl '{"id":"vol01:1:1:1"}'; mk config/crop_exclusions_retired.jsonl '{}'; mk config/other.yaml 'ignored'
mk output/glyph_store/a.jsonl '{"g":1}'; mk output/glyph.db 'SQLITE-FAKE'; mk feedback/lists/l.txt 'x'
mkdir -p $SBX/vol04/seed_admit $SNAP/vol04/seed_admit; echo '{}' > $SBX/vol04/seed_admit/p0001.json; echo '{}' > $SNAP/vol04/seed_admit/p0001.json
run(){ echo "\$ $*"; "$@"; echo "  rc=$?"; }
echo "== S4：记 sha／建 .s0_stamp =="
echo "\$ sha256sum \"\${GUJI_EXCLUSIONS:-\$WS/config/crop_exclusions.jsonl}\" \$CV/config/crop_exclusions.jsonl 2>&1"
sha256sum "${GUJI_EXCLUSIONS:-$WS/config/crop_exclusions.jsonl}" $CV/config/crop_exclusions.jsonl 2>&1; echo "  rc=$?  （\$CV 没有该文件：报 No such file、rc=1，剧本说记「无」不算失败）"
run touch $T/win1020/.s0_stamp
run python3 -I $H snap $WS --out $T/win1020/h_surface_s4.json --extra SBX=$SBX --extra SNAP=$SNAP
echo "== S27 ①没动 =="; run python3 -I $H check $WS --base $T/win1020/h_surface_s4.json --extra SBX=$SBX --extra SNAP=$SNAP
echo "== S27 ②改一个（事件）=="; echo '{"e":2}' >> $WS/feedback/events/b1.jsonl
run python3 -I $H check $WS --base $T/win1020/h_surface_s4.json --extra SBX=$SBX --extra SNAP=$SNAP; echo '{"e":1}' > $WS/feedback/events/b1.jsonl
echo "== S27 ③增一个（排除名单）=="; echo '{}' > $WS/config/crop_exclusions_released.jsonl
run python3 -I $H check $WS --base $T/win1020/h_surface_s4.json --extra SBX=$SBX --extra SNAP=$SNAP; rm $WS/config/crop_exclusions_released.jsonl
echo "== S27 ④删一个（字形库 glyph.db）=="; mv $WS/output/glyph.db $T/gdb.bak
run python3 -I $H check $WS --base $T/win1020/h_surface_s4.json --extra SBX=$SBX --extra SNAP=$SNAP; mv $T/gdb.bak $WS/output/glyph.db
echo "== S27 ⑤只改 bindings 缓存（seed_admit 读路径会重写它）=="; echo '{"cells_sha":"y"}' > $WS/feedback/bindings/vol04/p0001.json
run python3 -I $H check $WS --base $T/win1020/h_surface_s4.json --extra SBX=$SBX --extra SNAP=$SNAP; echo '{"cells_sha":"x"}' > $WS/feedback/bindings/vol04/p0001.json
echo "== S27 ⑥额外根：沙箱产物被改 =="; echo '{"x":1}' > $SBX/vol04/seed_admit/p0001.json
run python3 -I $H check $WS --base $T/win1020/h_surface_s4.json --extra SBX=$SBX --extra SNAP=$SNAP; echo '{}' > $SBX/vol04/seed_admit/p0001.json
echo "== S27 ⑦环境变量覆盖：直接停 rc=2 =="; GUJI_FEEDBACK_DIR=/elsewhere run python3 -I $H check $WS --base $T/win1020/h_surface_s4.json
echo "== 对照：旧 v2.7 的 find -newer 在『改了内容但 mtime 被还原』时漏判 =="
touch -d '2020-01-01' $WS/feedback/bindings/vol04/p0001.json
touch -d '2020-01-01' $WS/feedback/events/b1.jsonl; echo '{"e":9}' >> $WS/feedback/events/b1.jsonl; touch -d '2020-01-01' $WS/feedback/events/b1.jsonl
echo "\$ find \$WS/feedback \$WS/config \$WS/output -newer .s0_stamp -type f   （旧写法）"; find $WS/feedback $WS/config $WS/output -newer $T/win1020/.s0_stamp -type f; echo "  （上一行之后无任何输出＝漏判；而 sha 比对见下）"
run python3 -I $H check $WS --base $T/win1020/h_surface_s4.json
echo; echo "######## 208kv 新增：--extra 零文件守卫四情形（原七情形上面不变）########"
G=$T/win1020/g.json
echo "== G1 符号链接根（应 rc=2）=="; ln -s $SBX $T/lnk
run python3 -I $H snap $WS --out $G --extra LNK=$T/lnk
echo "== G2 空目录根（应 rc=2）=="; mkdir $T/emptyroot
run python3 -I $H snap $WS --out $G --extra EMPTY=$T/emptyroot
echo "== G3 不存在的根（应 rc=2）=="
run python3 -I $H snap $WS --out $G --extra NOPE=$T/does-not-exist
echo "== G4 正常根（应 rc=0；再 check 也 rc=0）=="
run python3 -I $H snap $WS --out $G --extra SBX=$SBX --extra SNAP=$SNAP
run python3 -I $H check $WS --base $G --extra SBX=$SBX --extra SNAP=$SNAP
echo "== G5（check 侧）基线里 SBX 有文件，现在被清空 → rc=2 并点明基线文件数 =="; mv $SBX $T/sbx.bak; mkdir $SBX
run python3 -I $H check $WS --base $G --extra SBX=$SBX --extra SNAP=$SNAP
rm -rf $SBX; mv $T/sbx.bak $SBX
echo "== G6（check 侧）符号链接根 / 不存在根 → rc=2 =="
run python3 -I $H check $WS --base $G --extra SBX=$T/lnk --extra SNAP=$SNAP
run python3 -I $H check $WS --base $G --extra SBX=$T/does-not-exist --extra SNAP=$SNAP
rm -rf $T
