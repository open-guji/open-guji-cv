# 看图结论重绑脚本（Eden，GUJI-208eo 件二）

`rebind_lookups.py`：旧格表＋新格表（带页坐标框）＋看图结论 CSV → 新格号结论 CSV＋「要人看」清单。纯标准库、离线、只读，不写任何事件／绑定表。
`selftest.py`：合成数据自测（一对一未变／改号、拆分、合并、无对应、部分重合、id 串被复用、夹注 a/b），`自测/` 下是合成输入与输出，已跑通。

## 真数据上怎么一键跑（Ethan 窗口日）
**坑**：现有 `exports/cell_table/volNN_base.jsonl.gz` 基线表**没有 bbox**（字段只有 id,admit,channel,char,iron,doubts,verdict,cov,provenance），不能直接当输入。要用**产物根目录**：

| 输入 | 在哪 | 怎么给 |
|---|---|---|
| 旧格表 | 窗口前的 products 快照根（`<根>/vol05/cell_shrink/pNNNN.json`，Ethan 沙箱基线产物；窗口前**必须先留一份**，步骤 1 备份时一并留） | `--old <旧产物根> --book vol05` |
| 新格表 | hint 开后重生的 products 根（同结构） | `--new <新产物根>` |
| 看图结论 CSV | 由 `feedback/vision/*.jsonl` 或 Lucian／Ezio 看图文件导出：列 `cell,v,char,shown,judge,note`（`cell` 为旧格号）；196 条的原始来源待 Eliot 在本机确认 | `--lookups` |

```
python rebind_lookups.py --old <旧产物根> --new <新产物根> --book vol05 \
    --lookups vol05_看图结论_旧号.csv --out-dir out_vol05 --emit-vision-jsonl
```
新旧两个产物根须是**同一书**；`--old/--new` 也可给带 `bbox_page`／`bbox`／`bbox_xywh_tl` 的 jsonl(.gz)。
产出：`*.新结论.csv`（自动重绑）、`*.要人看.csv`（拆分／合并／无对应／部分重合，给 Lucian／Ezio 人看）、`*.摘要.json`、`*.import-vision.jsonl`（交 H 道用 `guji events import-vision` 追加；新号写原结论、旧号追加 `unsure` 退役行）。

## 阈值（`--iou` 0.5、`--low` 0.6、`--ov` 0.5、`--gone` 0.15）——10-14 Mila 定：IoU 用 0.5
- `--iou 0.5`：**配对下限**，与 `research/y1_admit/remap_gold.py` 缺省相同，金标与看图结论走同一把尺（Mila 定）。
- `--low 0.6`：**自动重绑下限**。`0.5 ≤ IoU < 0.6` 的一对一配对单列「**低置信配对**」，**不自动重绑**，进 `*.要人看.csv` 交看图（与绑定表 `IOU_OK=0.6` 同值）。`IoU ≥ 0.6` 才自动搬。
- `--ov 0.5`：重叠系数（交/较小者），用来抓「被切开／被并入」；0.5＝一半以上落在对方里。
- `--gone 0.15`：与 `bindings.IOU_GONE` 同。
- 只有「一对一」（且 IoU≥0.6）才自动重绑；**拆分、合并、低置信、部分重合、无对应一律不自动搬**（合并后的新格是新字，旧结论不能搬——与绑定表对 `review` 的处理一致）。
- **低置信配对的数量：待证据。** 合成表上的数没有意义；真数要用 vol05 hint 关/开两份产物根（`cell_shrink` 带 `bbox_page`）跑一遍，摘要 json 的 `by_status["低置信配对"]` 就是答案。现有可读材料（guji-workspace main 的格表、`vol05A_seed_admit.jsonl`）都**没有 bbox**，量不了。若该数相对 196 条占比大（例如 >10%），说明 0.5/0.6 这对阈值要再议。

## 208hj 改动（Elena C2）：`--emit-vision-jsonl` 两遍输出
看图日志（`vision.py:34-36`、`170-185`）同格按 `(ts, 批次, 行号)` 后到覆盖。旧版逐条交替写「新号、退役」，在**改号链**（旧 10→9、旧 9→8）上会让后写的「退役旧 9」把刚搬来的新 9 盖成 `unsure`；而且新号行沿用原判 ts、退役行用导入时刻，退役行即使写在前面也会赢。现在：**先全部退役行、后全部新号行**；旧号恰是别条新号目标时**不写退役行**；退役行 ts=T、新号行 ts=T+1s（`--ts` 指定 T，缺省现在 UTC），不沿用原判 ts（原判 ts 记进 `note`）；写完在脚本里按同样规则模拟一遍，不符就退出。`selftest.py` 新增「改号链」「同号复用」两个导出顺序用例（旧逻辑下改号链会得到 `10:1:9=unsure`，已验证）。

## 补（208jd）
- `selftest_hint27.py`：`hint_remap_27.py` 的合成自测（链式补行、主导候选竞争者数、低置信），`python3 -I selftest_hint27.py`。
