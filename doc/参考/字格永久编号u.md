# 字格永久编号 u：cv 侧

> 2026-11-26 整理（CV0）。u 的发号、身份账格式、存量迁移都在 guji-manager：[doc/参考/字格身份账.md](https://github.com/open-guji/guji-manager/blob/dev/doc/参考/字格身份账.md)、Wiki [字格永久编号 u 与身份账](https://github.com/open-guji/guji-manager/wiki/字格永久编号u与身份账)。本篇只写 cv 读什么、怎么开、各版本线到哪。介绍见本仓 Wiki [字格永久编号 u（cv 侧）](https://github.com/open-guji/open-guji-cv/wiki/字格永久编号u)。

## 一、一句话

格号（`册:页:列:格`）是切分位置，重切就挪；**u** 是册内唯一正整数，跟着字走、永不复用。cv **只读** u，不发号、不写账：产物里不带 u（只留 `cell_ref()` 格号），u 由 manager 在标 main 时按 main 包入账。

## 二、cv 读 u 的地方

| 地方 | 读什么 | 开关 | 代码 |
|---|---|---|---|
| 文意裁定（`_vis_ruling_pass`、fold 遍） | 窗口键、版本等价、格锚点都没中后，按本格 u 查同组同册同 u 的裁定 | 书级 `seed_admit.ruling_by_u` | `RulingStore.get_by_u` |
| 字组文意在线问前查缓存 | 窗口精确键没中，按 u 查**版本完全相同**的那条 | 同上（开着时本页设 `UMAP_SCOPE`） | `RulingCache.lookup` → `RulingStore.get_by_u_ver` |
| 身份账 | `<feedback>/uid/<册>.jsonl` 里本页当前 `cells_sha` 那一行的 `map`（格号→u） | 同上 | `feedback.rulings.UidLedger`（只读） |
| 人裁绑定 | **不按 u 绑**：仍按锚框／指纹／补锚档（见 [裁定事件规范 §7](../formats/裁定事件规范.md)） | — | `feedback/bindings.py` |
| 字形库刻例 | **不读 u、不改键** | — | 见第五节 |

查裁定的顺序（每档没中才往下）：

1. 窗口键 `(组, prompt_ver, sha256(前文末 20 字 | 后文首 20 字))`
2. 版本等价表 `feedback/rulings/ver_equiv.yaml`（`get_equiv`）
3. 格锚点（`get_anchor`；书级 `ruling_anchor_loose` 放宽）
4. **u**（`get_by_u`，书级 `ruling_by_u`）

u 档的口径同格锚点宽松档：版本认本组 `validate` 认的任意版本（减 `void`），同格多条取最新、字不一致记 `ruling_conflict` 不放行，只收 `conf=high`，前后 2 字至少一侧与裁定记的窗口相同；另要裁定字在库候选里或＝整理本对位字。命中证据记 `ruling_key="u"`、`u`、`ruling_ver`、`win_sides`。账里查不到本页这次切分（`cells_sha` 不在账上）就当这页没有 u，**不回退格号**。

## 三、怎么开

写在中心库数据目录的书级缺省（`config/book_defaults.yaml`）或册配置里：

```yaml
params:
  seed_admit:
    ruling_by_u: true
```

- 缺省关；关时不进参数 dump，产物与没有这个开关时逐字节相同（code_equiv 已登）。开的册从 `seed_admit` 起往下过期（L1）。
- 账和裁定都是**数据**，不进指纹：账变了（标 main 入了新页）或新写了带 u 的裁定，要显式 force 重放 `seed_admit`（任务库 `--from seed_admit` 缺省 force）。
- 2026-11-25 起殿本、史記、全唐文三部书已开（书级）。

## 四、各版本线

| 线 | 带 `ruling_by_u` 的最早版本 | 换单导出带 u 的版本 | 配 manager |
|---|---|---|---|
| dev／v0.9.x（脈經、北行等跟 0.9 的书） | dev #1848＋#1856；0.9 线 v0.9.1 | dev 本就走 manager 导出 | — |
| 殿本 patch 线 | v0.7.102（现行 v0.7.105／106） | v0.7.108（republish）、v0.7.110（proof_cycle、zl） | ≥0.6.20／≥0.6.21 |
| 史記 patch 线 | v0.7.103 | v0.7.107（republish）、v0.7.112（proof_cycle、zl） | ≥0.6.20／≥0.6.21 |
| 全唐文 patch 线 | v0.7.104 | v0.7.109（republish）、v0.7.111（proof_cycle、zl） | ≥0.6.20／≥0.6.21 |

**换单导出**：patch 线的 `scripts/zhengli/republish.py`、`proof_cycle.py`、`zl.py` 出 char 导出改走 guji-manager 的 `guji_manager.output.guji_format_export`；册有身份账时 char 每格带 `u`（book-text char v0.6，顶层 `u_max`、`u_retired`）。没装 manager 才退回 cv 自带的 `scripts/export_guji_format.py`（**不写 u**）。用旧版导出推 book-text，`local_check` 会报「旧版已有 u，新版把 u 全丢了」，`guji feedback swap book-text` 推标点也会报 u 对不上：遇到先查 cv 版本够不够上表、`_cycle/*/export` 是不是旧版出的（要重出）。这几处改动只动脚本，23 步指纹不变，钉旧版的册不用改钉。

## 五、字形库刻例键为什么不按 u 改

刻例 id 是入库那一刻的格号（`v2:册:页:列:格`），**重切后不改键**：

- cv 读库时 `bindings.rebind_library_shapes` 拿刻例的原格号去找**同一格号**的人裁事件（事件也不改键），按那条事件的绑定状态（`valid`／`rebound`／…）落到现在该落的格。库键与事件键同步，顺移才对得上。
- 只改库键、不改事件键，库里那条就会对上新格号上**别的字**的事件，绑错。
- `guji feedback rekey-cells` 只在换图源时用（那时事件也一起迁）；平常重切、格号平移不要 rekey。

## 六、人裁绑定与 u

manager 写人裁时在 `target.anchor` 里盖 `u`，但 cv 的 `bindings.py` **不按 u 绑格**，仍按锚框 `bbox`、指纹、补锚档、旧版切分与字形库图块。所以：

- u 迁移时抄出的 `~u` 件（id、批次名加 `~u`）必须带齐锚；只带 `{source_rev, u}`、没有框的件会判 `unanchored`，旧裁就不采信（2026-11-25 殿本 vol16 等实测：人裁退回待审）。
- manager `guji uid anchor-fill`（v0.6.18）按身份账给 `~u` 件补了现行框，全库已补；之后再迁事件也要带锚。
- 查一格的 u、看来历：`guji uid show <册> --cell <格号>`／`--u N`（manager）。

## 七、自检

- 跑完看产物 `evidence.ruling_key == "u"` 的格就是 u 档新命中；`human_unbound.status == "unanchored"` 而事件 id 带 `~u` 的，多半是锚没补。
- 标 main 后账尾应有这份包的行：切分变了是 `src=advance`（新页），没变是册级 `src=sync`（`page 0`、空 `map`、`label`＝包名）。缺了用 manager `guji uid sync <册> --label <包>` 补。
