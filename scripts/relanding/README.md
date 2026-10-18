# vol01 重落后核对（给 Owen；一页）

前提：重落前已留快照（`products_snapshot.py <products根> vol01 --out <目录>`，汇总 sha256 贴 GUJI-364）；
交付态副本放 `$BEFORE`（快照解出的 products 根），重落后的正式 products 为 `$AFTER`。命令不带沙箱变量。

```
# 1 params_hash / 指纹 / 上游（vol01 标准字形库口径 params_hash=7347f2f885382c6d；若本次开了 shadow_veto 会不同，先报）
python manifest_cmp.py $BEFORE $AFTER vol01 --expect-params 7347f2f885382c6d
# 2 code_hash（19 步）：fp_dump.py 在 overview 项目进展/CV放行规则/计划/窗口手册校对附/；参考值=ws main exports/sandbox_products/fp_9587e67c_vol01.json
python fp_dump.py <cv树> <正式ws> vol01 > fp_after.json
python manifest_cmp.py $BEFORE $AFTER vol01 --fp-json fp_after.json --fp-ref fp_9587e67c_vol01.json
# 3 新放行数 / 与交付态差异格 / 红线格
python relanding_diff.py $BEFORE $AFTER vol01 --list vol01_diff.tsv --json vol01_diff.json
```

## 判读（用户 10-17 口径：只报数，不因个别格停线）
- 退出码 0：无系统性迹象，把「待审→放行 N、放行→待审 M、按通道」和 `vol01_diff.tsv` 行数报 Mila。
- 退出码 3：某通道新放行 ≥30 或某页 ≥5（阈值可调 `--max-new-per-channel/--max-new-per-page`）→ 停线报 Mila，不继续其他册。
- 「放行字被改」应为 0；非 0 报。红线格只列 vol01 内的（redlines.txt 里 vol01 无则不显示，属正常）。
- manifest_cmp：params_hash 与期望一致、fingerprint 不同页=0 即「同配置同代码」；有差异先看是配置（yaml/字形库）还是 code_hash，code_hash 不同说明树不对，停下问。
