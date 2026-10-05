# HANDOFF Q2 — 读图失败不许降级（overview#407）

分支 `claude/Q2-imread-1005`（基于 main `24769e7`），未合 main、未开 PR。

## 查到了什么

- 引擎里**没有**直接 `cv2.imread(` 了（`tests/test_image_io_guard.py` 一直守着）。
  日志里的 `imread_(...): can't open/read file` 来自 `utils/image_io.imread` 自己：它**先**
  调 `cv2.imread`，Windows 中文路径上必失败、必打警告，再退到 `np.fromfile + imdecode` 读成功。
  文件真不存在时 `np.fromfile` 本来就会抛 `FileNotFoundError`；只有「文件在但解不出来」才返回 None。
  所以 vol02 那 8,980 条（37 页 × 每页约 240 格，每读一个字块一条）**大概率全是假警告**。
- 真正的静默降级点：
  1. `steps/glyph_match.py`：读字块 `except Exception` → 记 `verdict=diff, guard=no_patch:…` 照常落盘；
     候选试切图块读不到直接 `continue`。
  2. `steps/seed_admit.py` 四处（铁证尺度 `_iron_page_scale`、铁证判定 `_iron_decide`、CNN 背书 `_cnn_top`、
     组内检索 `_image_ranks`）：用 `ImageCache().get()` 读字块——**不验页戳、不再生**，没图 `return None`，
     后两处还整段 `except Exception: return None`。缓存缺了，铁证/CNN 两路就悄悄关掉，放行结果变了而状态正常。
- ⚠️ **p20「魏王弼撰」→「理玉朝鑿」不像是「没读到图」**：没图在 glyph_match 里只会出 diff、出不了字。
  连着四格配成别的字，更像**读到了错位的旧字块**——即 10-01 vol03 那类「缓存没页戳、按名字放行」
  的邻格错位（`products/cache.py` 模块头）。本分支修不了这个，本地要核（见下「本地 Windows 怎么验」第 3 条）。

## 改了什么

| 文件 | 改动 |
|---|---|
| `open_guji_cv/utils/image_io.py` | `imread` 改为**直接字节读入 + imdecode**，不再碰 `cv2.imread`（假警告没了）。新增关键字参数 `strict=False` 与异常 `ImageReadError(OSError)`。默认口径与原来一致：不存在抛 `FileNotFoundError`、解不出来返回 None（150 多个调用方靠这个，没动）；`strict=True` 时解不出来也抛。已核 EXIF 旋转：`imdecode` 与 `imread` 结果一致 |
| `open_guji_cv/core/step.py` | `RunContext.image` 用 `strict=True`，读不出来抛 `FileNotFoundError`（带路径）；`raw_page` 只改报错文字 |
| `open_guji_cv/steps/glyph_match.py` | 本格字块读不到/再生不出 → 抛 `PatchUnavailable`，**整页失败**（引擎记 failed、旧产物不动），不再写 `no_patch` 记录。候选试切图块（`…_L0` 键，按设计不可再生）缓存里没有时仍跳过（只接 `KeyError/ValueError`），文件在却读不出（OSError）照样停页 |
| `open_guji_cv/steps/seed_admit.py` | 新 `_page_patch(src, page, col, slot, sub)`：管线里走 `ctx.image`（验页戳、缺了现算），读不到抛 `PatchUnavailable`；四处调用改用它，调用点传 `ctx`（离线脚本传册 id 字符串仍可用，只查缓存）。`_cnn_top` 先看 CNN 通道开没开（没 checkpoint/没 torch 不读图），开着才读、读不到抛。铁证对照图（别页/别册人裁刻例）缓存里没有仍跳过，文件在却坏了抛 |
| `tests/test_imread_strict.py` | 新增 11 个测试函数（参数化展开后 13 个用例）：中文路径读图且不调 `cv2.imread`、两种口径的缺文件/坏文件、`RunContext.image` 抛错、glyph_match 读不到整页抛错（冻结样页跑真 Step1→4）、候选试切的两种失败分开处理、seed_admit 四处抛错、册 id 模式 |
| `tests/test_cutline.py` | 原来桩打在 `cv2.imread` 上，现在读图不经它，桩改打在 `cv_imread` 引用上 |
| `tests/test_seed_admit_variant_indirect.py` | 组内定形要读本格字块，测试里摆一张空白字块（原来靠「读不到 → None」走过去） |

## 行为变化（要知道的）

- glyph_match / seed_admit 某页任何一个本格字块读不到，**这一页 failed**，日志里是
  `PatchUnavailable: pN 字块 pNNNNcCCsS 读不到: …`。以前同样情况会静默产出降级结果。
- seed_admit 在缓存缺字块时会**现算**（走 `ctx.image`），云端无 cache 的快照上跑 seed_admit 会比以前慢一些，
  但铁证/CNN 两路不再因为没缓存而悄悄关掉——**这意味着云端无 cache 时的 seed_admit 放行结果可能与以前不同（以前是少了这两路的结果）**。
- `scripts/audit_iron_recheck_0927.py` 传册 id 调 `_iron_page_scale`，缓存缺字块时现在抛错而不是跳过。

未改（看过、判断不属静默降级或不在本卡范围，列出供总管定）：
`ocr_candidates` 读不到字块记 `error` 并计入 `fail_threshold`（有记账，不静默）；
`rare_candidates` 读不到字块记一条空 `RareRec`（候选为空，是一路可选证据，属降级但不出错字）——要不要也停页，请拍板。

## 测试结果（云端 Linux）

```
python -m pytest tests/ -q -s -p no:cacheprovider
1 failed, 2644 passed, 30 skipped, 5 deselected
```
唯一失败 `test_cut_select.py::test_ckpt_fingerprint_empty_for_missing_file` 在 main 上同样失败
（云端没有 U-Net checkpoint，与本改动无关）。改动前同一命令曾红 18 条（seed_admit 测试只造产物不造图），已逐条处理。

## 本地 Windows 怎么验

1. 拉分支，跑 `python -m pytest tests/test_imread_strict.py tests/test_image_io_guard.py -q -s -p no:cacheprovider`。
2. 卡上的复现命令：
   `guji pipeline keben_body_v2 vol03 --pages 20,39,49 --from row_segment --to seed_admit`
   ——日志里应**不再有** `can't open/read file`；p20/p39/p49 产物应与改前逐字节相同（卡上说改前就相同）。
3. **p20 垃圾的真因要单独核**：先 `guji cache verify vol02`（拿渲染结果比对邻格，见 `ops/cache_verify.py`），
   看 vol02 的 `char_patch` 缓存是不是对着旧产物切的、有没有缺页戳。若查出错位，`--fix` 清掉再跑。
4. 再在**副本**上重做那次 vol02 `recheck` + `--from glyph_match`：若仍有读不到的字块，现在会是该页 failed +
   `PatchUnavailable` 报错（不会再出垃圾）；若 p20 仍出「理玉朝鑿」而无报错，就坐实是缓存错位而非读图问题。
