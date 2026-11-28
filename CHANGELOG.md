# Changelog

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号规矩见 `doc/版本号规矩.md`。
本文件记录**全部**版本（含 PATCH）；动代码的 PR 投 `dev`，在 `## [未发版]

- 新步骤 `glyph_vis`（3e 看图大模型（条件），缺省关 `enabled`；CV3 2026-11-28，接口草案经 CV4 审定。指纹变更：glyph_vis 新步骤自身新增、无旧产物；收尾 `glyph_analyzer` 代码改动登记 code_equiv（自造册 3 页逐字节相同＋测试冻结 dev 的 merge_cell 输出），没开 3e 的书各步不过期）：3a／3b 给不出好结论的少数格（3b 触发了 `groups` 里的组——缺省第四步现役 `registry.VIS_GROUPS` 8 组——且方法全弃权 `near_abstain`／方法分歧 `near_split`／概率口径方法分差小 `near_margin`／3a 组内两字相持 `a_margin`／组内校准 p 低 `p_low`），把 `char_patch` 字块图连同候选字（组字 ∪ 3a 前 5 ∪ 3b 方法给的字）交给大模型**只按刻形**判（新提示词 `vis-img-1`，不写书名、不给前后文与整理本；走 `ctx_llm.Client` 结构化输出＋拒答回落；真调只在 `GUJI_LLM_ONLINE=1` 且有密钥、`model` 非空时，缺省只读缓存、没命中出 `ask`）。产物 `PageVis`（每格 `VisRec`：trigger 记号、status＝hit／asked／pending／error／skipped:<原因>、char／other／conf／why／model／prompt_sha／cache_hit／legacy、页头 `cache_pin`）。缓存是新事件种类 `vis_glyph`，**单开目录 `<feedback>/vis_glyph/`**（`feedback/vis_glyph.SUBDIR`，不进 rulings/），target `unit="glyph_img"`、key＝img_sha，键 `(img_sha〔含形状〕, prompt_sha, 候选集合, model)`，读只认 `model`＋`accept_models`；不是人裁、不算钉（`event_level` 给 None），`core/event_files.GATE_EXEMPT_KINDS` 加 `vis_glyph`；缓存内容不进指纹（导新答案后从 glyph_vis 起 force）。收尾 `glyph_analyzer` 每格新字段 `vis`（空不落盘）、答出字的候选加 `evidence.v`，**不出 p、不改排序**。第四步一行未动。一次性脚本 `scripts/rekey_vis1_to_glyph_vis.py`：旧 vis1 ctx_ruling 缓存按当前字块重算 sha1 核对同图后转成 `legacy=true` 的 vis_glyph 记录（缺省 dry-run，只写本机），第三步缺省不认（`accept_legacy`）。**开 glyph_vis 写缓存、推中心库前须 guji-manager 含 #1239 的版本**（vis_glyph 目录归 events 表、不算钉、u_stamp 跳过、GATE_EXEMPT_KINDS）。阈值缺省是拍的，待殿本、全唐文各数一册触发量后定。新测 `tests/test_glyph_vis.py`。
- 参校本四维成唯一入口（Sheldon 11-28 定「按这四个维度走，新书开，旧书换配置不重跑，旧代码清干净」；CV0）：① seed_admit `reference_trust`／`ref_lib_coord`／`follow_ref_variants`／`ref_topk_follow` 不再从册配置读，一律由 `references[].accuracy`／`script`／`form`（段上可压低）推出（`derive_trust`），写了旧值且与推出值不同起跑 `FutureWarning`；#1979 的过渡开关 `trust_from_accuracy`、`ref_variants_off` 删除（写了也丢）；`reference_trust` 不再隐含照录异体。② 证人排序与主参照选取改看 `accuracy`（未标＝low），`Witness.quality` 改名 `accuracy`；列级对位看 `form: column`，旧键 `quality`／`line_is_column` 不再读（迁移期并存不报，段上写 `quality` 报不认识）。**指纹变更**：seed_admit 参数——史記、脉经推出值与原配置相同不变；全唐文、殿本、明別集参数变，按「出过 v0.1 不重跑」不重跑；align_ref／cell_state 代码改（cell_state 缺省关）。设计 `doc/design/参校本四维与准确度分档.md` 第四、六节。中心库各书补四维另做，旧键第二期删。
- 新步骤 `group_decision`（4d 字组，缺省关 `enabled`；CV4 P3c 2026-11-28，Sheldon 定「子步只出证据、收尾做全部判断」）：只出**原料**——①字组入口归属（待审口径，本版只出不读）；②3b `glyph_near` 看图判法快照（rr／wu／hou／part／pair_shape、book_knn、near_knn、stroke_veto，开关 `group_flow_near_from_3b`）；③字框宽高 `wh` 与按组 `aspect` 比值（`fold_aspect`）；另留空的按组 `handling` 位置（登记表字段定稿后用，收尾本版不读）。**不含**补放／改字／降审、字组文意各层、裁定缓存、`vis_ruling`（它们读邻格放行状态，只能在收尾）。收尾 `seed_admit` 可选读：`_near_from_3b`／`_near_by_model_from_3b` 先查快照（4d 步自己取快照传 `use_gd=False`），`_fold_pass(wh=…)` 先读 `wh`；没有就照旧现算。`seed_admit_groups` 把 `_group_flow_pass` 里的 `FlowConfig` 构造原样抽成 `_flow_config`，另加只够入口用的 `_entry_config`。`vis_ruling` 及其后各遍次序、`ask`、`evidence.vis_ctx`、`evidence.group` 位置不变（`tests/test_group_decision.py` 断言）。指纹变更：group_decision 新步骤自身新增、无旧产物；`seed_admit` 的 seed_admit／seed_admit_groups／seed_admit_shapes 三块改了（缺省关、关着逐字节不变），code_equiv 登记待 decide-bench 冻结包上逐字节核对后补（核对前别用本分支的册与基线产物混批）。依据：ai-team `domain/CV/A24/P3c-组判pass依赖清单-2026-11-28.md`）
- 新步骤 `cell_state`（4c 格况，缺省关 `enabled`；CV4 P3b 2026-11-28，Sheldon 定「格况判断拆成独立步骤」。指纹变更：cell_state 新步骤自身新增、无旧产物；`seed_admit` 组合 code_hash 经 code_equiv.SPLITS 块表换新哈希后与 dev 相同、各书现有产物不过期，decide-bench small 史記 03 共 231 页 seed_admit 逐页 JSON 全相同、翻转 0 格）：把 `seed_admit_cell_state` 里**不读放行状态**的六个探测器（遮挡 `_occluded`、盖章空栏 `page_seal_blank`、字框几何 `seg_box_bad`、墨迹格旗 `ink_mark_facts`、夹注分法不均列旗 `jiazhu_uneven_spans`、题列套语 `header_formula_lines`）抽成独立函数，算成产物 `cell_state`（逐格 `state`＝char／occluded／seal／seg_bad／non_char＋证据，另存各探测原值与 `ran`）；收尾 `seed_admit` 各 pass 多收一个可选参数，给了产物里的探测原值就用、不给就现算，升降仍按放行状态在收尾做；读放行状态的 `symbol_review`／`symbol_ref_blank`／`blank_ink` 不搬。关着时产物逐字节不变，开着时逐格相同（`tests/test_cell_state.py`）。依赖清单 ai-team `domain/CV/A24/P3b-格况pass依赖清单-2026-11-28.md`；新产物 kind 已告 GM2／GM3／GM4。
- PATCH（产物逐字节不变，各书不过期：row_segment、impl.keben.row_boundaries 登记 code_equiv，053 40 页对 dev 逐字节相同；CV2 2026-11-28）：缺省关的书级参数 `row_segment.jiazhu_edge_trim`——单格夹注判据落空时去上下边（×格高）再量，段判据与书级钩子同看去边后的图块。起因全唐文 053 75:3 开竖线后「學」脚压进「字闕」夹注格、夹注少一格；0.15 在 053 cut-bench 346→347、0 回退，031–120 layout_off 页只变 1 列（篆书印文，平）。
- PATCH（产物逐字节不变，各书不过期：row_segment、seg.profile 登记 code_equiv，053 40 页对 dev 逐字节相同；CV2 2026-11-28）：全唐文开 `border_detect.vline_track` 后切字适配，两个缺省关的书级参数：`row_segment.layout_off_always`（无先验格网不论别的候选劈不劈字都出场打分，配 `layout_off_tol` 用；起因 039 31:9、055 49:1、067 64:6 开竖线后有候选劈字为 0，无先验格网连出场都没有）；`row_segment.frame_edge_near`（列首／列尾「只有框线」格判空的贴框距离，×格高，缺省 0.2＝原常数；全唐文上框下细线在 0.2 边上，建议 0.3）。`seg.profile.frame_only_edge_cells` 加 `near_frac` 参数。全唐文 031–120 实测见开关登记表与 ai-team `domain/CV/A22/cut-bench/实验-全唐文竖线跟踪适配-1128.md`。
- PATCH（指纹变更：开了 3b 的书 glyph_near 起过期——`groups.near_methods` 改；收尾 glyph_analyzer 随 near_methods 一起过期；现行只有殿本开 3b，且殿本没挂 hou_shape；CV3 2026-11-28）：候𠋫 书级刻形判法 `hou_shape` 包成 3b 方法（照 rr_shape 样板）：吃 `char_patch`；`hou_shape/2`（小网）`sims`＝`{候: p, 𠋫: 1−p}`；`hou_shape/1`（几何量 v，不是概率）用与现役判定一致的单调映射 `候 = σ(ln9·(lo+hi−2v)/(hi−lo))`、`𠋫 = 1−候`（现役判 候 的格 候 ≥ 0.9、判 𠋫 的 ≤ 0.1、弃权在中间，`hi−lo<0.001` 时按判出的字给 1／0）；无墨弃权 `{}`。证据 `{method: "hou_shape", char, why, v|p}`，后三键＝`judge()` 整个返回值（第四步 `evidence.hou_shape` 那份，主遍与晚跑遍 `group_flow_hou_shape_late` 同一判法）；`model_sha` 与第四步参数指纹 `hs` 段同算法；校准表读口 `knots.候`，现在没有表、不出 p。书配置 `hou: {ref: hou, trigger: cands, methods: {hou_shape: config/groups/hou_shape.json}}`。哪些格用、主遍还是晚跑遍、改不改字留在 4d；现役第四步判法一行不动。
- PATCH（指纹变更：开了 3b 的书 glyph_near 起过期——`groups.near_methods` 改、`glyph_near.code_deps` 补 `groups.wu_shape`；收尾 glyph_analyzer 随 near_methods 一起过期；现行只有殿本开 3b，且殿本没挂 wu_shape；CV3 2026-11-28）：嗚鳴 书级刻形判法 `wu_shape` 包成 3b 方法（照 rr_shape 样板）：吃 `char_patch`，`sims`＝`{鳴: p, 嗚: 1−p}`（p 是 `wu_shape.judge` 已取 4 位的 鳴 概率），无墨弃权 `{}`；证据 `{method: "wu_shape", char, why, p}`，后三键＝`judge()` 整个返回值（第四步 `evidence.wu_shape` 存的那份）；`model_sha` 与第四步参数指纹 `ws` 段同算法；校准表读口 `<模型去 .json>.calib.json`（`knots.鳴`），现在没有表、不出 p。书配置 `wu: {ref: wu, trigger: cands, methods: {wu_shape: config/groups/wu_shape.json}}`。现役第四步判法一行不动。
- PATCH（产物逐字节不变，各书不过期：改动都在不属于任何 Step `code_deps` 的模块，`check_fp_change` 对 dev 0 步变；CV4 P3a-1 2026-11-28，Sheldon 定收尾步改名 `char_decide`）：`seed_admit`→`char_decide` 的**兼容读口**，产物仍写 `seed_admit`，Step id／产物种类／参数类不动。① 新 `core/decide_names.py`（`ADMIT_STEPS=("char_decide","seed_admit")`、`LEGACY_ADMIT_STEP`、`ADMIT_STEP_ACTIVE`〔改名那一版只翻这一个常量〕、`fold_admit_params`、`final_page_dict`、`final_dir`）；② 产物读口 `steps/decide_final.read_final(ctx, page)`、`products/final_read.read_final_store`，新目录与新页键优先、并存以 `char_decide/` 为准（`guji-cv status` 并存警告），pending-cells、slots、glyph_ledger、alt_view、llm_queue、ids_retrain、seg_screen_run、shadow/offline 的读点全改新旧并认；③ 事件读口 `feedback/decide_events`（`decided_view`／`ruling_by_u`／`invalidate_final`：两个步名当同一步、后到覆盖按写入时间、失效两个目录都标；D1 历史事件不改写）；④ 参数键 `params.char_decide.*` 与 `params.seed_admit.*` 都认（册配置、管线 yaml、套书缺省、`--params`／`--override`、page_kinds），同一层同时写报错；⑤ 新命令 `guji-cv decide migrate-name <册>`（`products/migrate_final.py`：目录与页顶层键原地改名不删、manifest 换 sha 并按新名 Step 换算指纹、下游 `upstream` 键换名、sha 清单存 `_migrate_char_decide.json`；本版只能 `--dry-run`，改名那一版起才能真迁）；⑥ `pending-cells` 每格加 `pending_reason`／`pending_reason_detail`／`form_src`（本版值一律 None，cv 将来直写的 15 个原因见 `doc/4-定字/pending_reason.md`）；⑦ `steps/char_decide` 导入入口（与 `SeedAdmitStep` 同一个类）；`manager_api` 导出以上读口。新测 `tests/test_decide_name_compat.py`（页键、ask／vis_ctx 位置不变，新旧事件名查询结果相同，参数并存报错，迁移只改名不删）。
- PATCH（指纹变更：开了 3b 的书 glyph_near 起过期——Step 模块与 `groups.near_methods` 改；现行只有殿本开 3b；CV3 2026-11-28，按 CV4《4d 接 3b 看图方法-接口要求》）：3b 新触发方式 `trigger: cands`（3a 首位或候选前 `topk` 名（缺省 5）里有组内任一字就跑，罩住第四步看图判法的触发格）；3b 产物 `PageNear.models` 记本页各方法的模型版本（`方法.model_sha`，rr_shape 与第四步参数指纹 `rs` 段同算法）；收尾 `glyph_analyzer` 每格新键 `near: {group, trigger, methods: {方法名: {method, …方法证据原样, model}}}`（rr_shape 证据＝`{method: "rr_shape", char, why, nn, score, geo}`，后五键同 `rr_shape.judge()`；4d 读口是 3b 产物本身，见 cv #1999），没触发的格不落盘，宫官 cnn_small 的 `evidence.b`／p／p_src 不变。3b 只管主切法格，备选切法列 4d 本地现算。
- 新步骤（只新增 gate，不影响别的步骤指纹：现役各步 code_hash 逐个核过不变；`decide_gate` 自己的指纹不过期任何东西，L0；CV4 2026-11-28，Sheldon 定「gate 只检测、不判断」）：第四步出口 gate `decide_gate`，挂在 `seed_admit` 出口、永远最后跑（照 `cut_gate`），读 `seed_admit`／`align_ref`／`glyph_match`／`context_decision`／`char_index`，每页出检测清单 `PageDecideGate`（`fail`／`flag` 两级）。首批检测：列报错、连续放行字等于参校本错开一位（`ref_shift`）、放行字没有任何出处、放行格是空白（fail）；参校本缺席／没锚上却靠它放行、坐标退回、备选切法、罕用码位、人裁绑丢、字组漏判、上游报错（flag）。不改任何格，没有 Step 读它。文档 `doc/4-定字/decide_gate.md`；量法 ai-team decide-bench `gate_bench.py`。

- 修复（缺省关；指纹变更：glyph_near 起过期——code_deps 补 `groups.hou_shape`，glyph_near 是 dev 上未发版的新步骤、缺省关，只有开了它的书（殿本）受影响，且它们未出过 v0.1 产物；CV3 2026-11-28）：#1997 把刻形判法 `rr_shape` 包进 glyph_near 后，`glyph_near.code_deps` 只列了 SPLITS 里 `rr_shape` 拆出的一块（hou_shape 漏列），`tests/test_seg_move.py::test_split_parts_listed_together_in_every_step` 报红；补上并重生成 doc/3-识字/步骤与产物.md。

- 读口改读形近字组登记表（产物逐字节不变：改的 `clustering/confusable.py` 不在任何 Step 的 `code_deps` 里，32 个 Step 的 code_hash 与 `stages_sha` 代码部分改前改后逐位相同，L0；CV3 W1 第二期 2026-11-28）：`confusable.NEVER_MATCH_FAMILIES`、`partners()` 改从 `config/near_groups/v2.json` 按字对 `src` 派生（手工表真源原样搬到 `config/near_groups/hand.json`，生成脚本与 `build_near_groups.py merge` 改读它），`match._PARTNER`、`seeding.NEAR_FORM_CHARS`、seed_admit（现 `seed_admit_pick`）三处 `partners()`、`shadow/signals` 源码不动、跟着改读；`manager_api` 加 `near_registry_pairs`（manager N01 用）。新测 `tests/test_near_registry_readers.py`：与搬家前字面量、人裁表、字体表逐项相等（各种 τ × `GUJI_CONFUSABLE`）。`NEVER_MATCH_FAMILIES` 顺序改按码位（只脚本用到顺序）。near_route／glyph_stages／glyph_rules／flow／shape_stage／pair_clf 名单这期没改，原因见 `doc/3-识字/形近字组登记表.md` 第五节。
- PATCH（纯搬家，产物与指纹不变，全部 Step code_hash 与合并前 dev 实算相同；CV4 P1a 2026-11-28，第四步定字子步重构）：`seed_admit.py` 按位置拆模块，3,464→1,178 行：新 `seed_admit_cell_state`（4c 格况，含从 lanes 搬来的墨点／字框几何／符号空白）、`seed_admit_groups`（4d 字组流程、看图判、折叠组）、`seed_admit_pick`（定字）、`seed_admit_veto`、`seed_admit_altcut`（备选切法挑列）、`seed_admit_reasons`（疑问码与护栏）、`seed_admit_page_params`；新 `steps/decide.py` 读口 `ref_of(ctx, page)`（`{格: {ref, via, op}}`），`_align`／`_coord_refs` 的 `PageAlignRef` 解析收进它。旧名全部从 `seed_admit` re-export；测试里换函数改用 `tests/helpers.patch_seed_admit`。`code_equiv.SPLITS` 重登（11-23／26 那条在 dev 上早已失效）。
- PATCH（指纹变更：开了 3b 的书 glyph_near 起过期——Step 模块改、code_deps 加 `groups.near_registry`／`groups.rr_shape`、consumes 加 `char_patch`；现行只有殿本开 3b；CV3 2026-11-28，Sheldon 11-26 分工）：3b `glyph_near` 新方法 `rr_shape`（入人八 书级刻形判法从第四步 group_flow 搬来的样板，包同一个 `groups.rr_shape.judge`、吃同一张 `char_patch` 字块图，证据与 seed_admit `evidence.rr_shape` 逐键相同；sims 八＝几何判 八，人／入＝σ(决策值)；模型直接指数据目录 `config/groups/rr_shape.json`，暂无校准表，`calibrate` 返回 None）。方法接口加可选 `ctx`／`cells`（`near_methods.score` 按签名传，老方法照用）、方法类属性 `patch` 定吃原图裁块还是切字字块图；3b 接上形近字组登记表 `expand_refs`（书配置 `groups.<组>: {ref: <组 id>, …}`，没写 `ref` 的书参数哈希逐位不变）。第四步现役判法一行没动。守卫 `tests/test_glyph_near_rr_shape.py`。
- 修复（产物逐字节不变，code_equiv 登记 row_segment_pagemap／utils.daizhige，L0；CV0 2026-11-28，殿本改名演练）：自动配页读的 corpus 表（daizhige `layout_slots`／`layout_overrides`、钉位表、`page_map_overrides`）按册过滤时认册 yaml 的 `aliases`（新 `core.volume_alias.names_for`），改格行用旧册名也盖到本册；`status` 的「参数变了」不再列改名时封存过的字段（MJ 建议）。没写 aliases 的册行为逐位不变。
- 新命令（不进任何 Step 指纹，engine.py／cli_v2.py 不在 code_deps，L0；CV0 2026-11-28，脉经第 1 册改名后 seed_admit 判「参数变了」）：`guji-cv rename-seal <册> [--keys …]`——册改名刚做完时跑一次，把只因改名改写了来源文件而变的参数指纹（如 `exclusions_fingerprint`：`crop_exclusions.jsonl` 的格号 01:→1:）记进改名标记 `sealed`（{步: {字段: [旧, 新]}}），`status` 的 `rename_only` 据此按条目记的参数比；封存后文件再变，新值对不上照常过期。只封 `*_fingerprint` 字段、各页旧值一致的；`human_fingerprint` 读字形库 `v2:` 实例 id、改名不碰，不该封（用 `--keys` 限定）。新测 3 条在 `tests/test_stale_reason.py`。
- PATCH（新步骤缺省关，现役各步 code_hash 不变；指纹变更：cell_traits（新步）、glyph_analyzer 起过期——3d 缺省关、glyph_analyzer 只有开了它的书过期，没跑 3d 时收尾产物逐字节不变；CV3 W3 2026-11-28，Sheldon 11-27 定「这格图有没有毛病」收到 3d）：3 识字加 3d `cell_traits`（字块图的其他特征）：每格 `cut`（字被切断）／`border`（混入边框）／`residue`（混入上下字残留）／`stain`（背景污染、印章）／`merged`（两字并一格）／`blank`（空格有墨、非字）各一个**原始分**（0～1，0.5≈原处判法的门槛，未校准、不是概率），`evidence` 按键记子判据与原始量。判法收自 cell_shrink flags、guji-manager `review/seg_defect`（同字对照只取本页 3a 判 same 的列中格、端区碎线／端条、并格低谷）、`steps/occlusion`（背景中等墨点密度、印章重叠）、seed_admit `_blank_ink_pass` 的图像部分，算法在新模块 `clustering/cell_traits.py`，现役代码不动。书配置 `cell_traits.enabled`（缺省 false）。收尾 `glyph_analyzer` 可选读它，原始分原样放进每格新字段 `traits`（空的不落盘），**不写 `p_map`**（没有校准来源）。殿本列端尺子 frame-end-crop（694 块）：`border` ≥0.5 检出 65/86、误报 38/591；`cut` 靠同字墨高比（尺子给的全册比值）≥0.5 检出 41/65、误报 14/612。量法与 vol02 分布见 ai-team `domain/CV/CV3/cell_traits-2026-11-28/量.md`。
- PATCH（缺省关、产物逐字节不变，code_equiv 登记；CV2 2026-11-28，朱楓林集 MBJ 报）：三个按书开的切字开关。① `row_segment.straddle_merge`（写 `{}` 开）：卷端「新安」「裔孫」这类写在两列之间界行上（界行在此断开）、被劈成两半的骑线字，合成一格放进右列（先读的那列）对应格位、左列那格记空（格旗 `straddle:`／`straddle_into:`），`cell_shrink` 见旗在原图上裁整字字块（render 也认）；判据 `straddle_pairs`（界行两侧墨满、两列本来的字位空、两列文字带够宽）。朱楓林集 01–05 册卷一至卷十 10 个卷端页 38 格全中、零误报。② `cell_shrink.ink_marks`：按原图墨打格旗 `ink_seal`（藏书印）／`ink_speck`（墨点）。③ `seed_admit.ink_marks`：印、墨点逐字对位无字判非字放行（seal／blank_ink 通道），对位有字或墨点贴着别的字（切坏的半字）送审——补上参校本不分行、没有坐标对位时 lane_seal coord_blank 走不到的缺口。新测 `tests/test_ink_marks_straddle.py`。
- 修复（产物逐字节不变，code_equiv 登记，L0；CV0 2026-11-28，册号位数统一）：`row_segment.load_layout` 读格位表／备选格表（`layout_prior`、`alt_cuts`）时，表行 `vol` 是本册 yaml `aliases` 里的旧名也归本册。脉经第 1 册改名 01→1 后继续用原 `maijing_yolo_alt_cells.jsonl`，不必另出一张表、不改参数，`status` 仍按 rename_only 判新鲜；殿本 vol01→01 的格位表同理。没写 aliases 的册行为逐位不变。新测 `test_load_layout_reads_old_volume_name_via_aliases`。
- 脚本／事件格式（不进任何 Step 指纹，events.py 不在 code_deps，L0；清理计划 2.4，用户 11-27 定）：`feedback/events.provenance(level, by, channel)`（与 manager `levels.provenance` 同口径）；cv 里写 `confirm` 的脚本接来源三字段：`build_newchar_review`（`human／--reviewer／console`）、`ingest_char_review.py`、`harvest_shadow_review.py`（**都新增必填 `--reviewer 账号`**，原来可以不带）、`book_lib_auto`（`machine／book_lib_auto／script`，含撤回）、`glyph_codepoint_unify`（按现行口径写 `ai`，改 human 要各书线先确认）、`mojibake_census`（按现行口径写 `human`，改 machine 会让该批不再算钉，先查影响）。`research/qtw_booklib/a4_import.py` 一次性、历史批次已写完，不改。
- PATCH（不进任何 Step 指纹，L0；CV0 2026-11-27，用户定册号位数统一、老书 cv 册名也改）：① `core/volume_id` 位数按全书册数——1–9 册 1 位、10–99 两位、100 起三位（`width_for` 最少 1 位，`vol_label` 按给的位数补），新增 `same_volume`（1、01、001 同一册）、`VolumeId.chapter_mismatch`；没写 `volume_width` 的老书缺省仍 2 位，不静默变号。② 新模块 `core/volume_alias`：册 yaml 写 `aliases: [旧名]`，`EventLog.read`／`iter_all_cached` 与 `core.event_files.iter_event_records`（过闸读）把事件里的旧册名（`target.book`、`target.key` 册名段、`payload.cell`／`instance_id`／`book`、uid 流顶层 `book`）在内存换成新名，旧记录不改写；`raw=True`、`gate=False` 的维护读口看原样。没有任何册写 `aliases` 时逐位不变。events.py、event_files.py 不在任何 Step 的 code_deps 里。方案：https://claude.ai/artifact/GFATExpvckttdKaHSHRuTz

- 文档／事件格式（不进任何 Step 指纹，events.py 不在 code_deps，L0；CV0 线程 2026-11-27，用户定「裁定事件要能区分来源」，清理计划 1.6）：裁定事件（`confirm`，格级）加来源三字段 `payload.level`（human／ai／machine）／`by`／`channel`（console／web_vote／opinion／script／llm／vision），写进规范 §4.1 与 `guji_feedback_event_v1.schema.json`；`EventLog.append` 缺字段或取值越界**只告警不拒**（`provenance_missing` 计数）；`payload.level=machine` 现在明确不算钉（`event_level` 给 None，同中心库 `events.level` 与 Worker 落定条件）。必填化留 2.4。
- 脚本（不进指纹，只加注释与文档；待审单清理 1.7）：`scripts/zhengli/republish.py`、`proof_cycle.py`、`auto_cycle.py` 文件头标 DEPRECATED（整张换单已被 `guji land` 取代）；调用方清单与退役条件见 `doc/design/整张换单脚本退役清单.md`。**未删**：guji-manager 的 `online_lists`（标 main 后自动重出）和 `swap run` 仍在调用。
- 修复（产物逐字节不变，code_equiv 登记，L0；CV0 2026-11-27，汉书 WYG #18261）：`border_detect` vline_track 淡线兜底 `_trk_gray_line` 取行号只封上界，页图比下框矮（汉书 26 册 p4/p5 是合扫拆坏的 120px 窄条）时不再抛 `IndexError: index 120 is out of bounds`。v0.9.2 起 vline_track 缺省开即有此错。

- PATCH（缺省关，产物逐字节不变，seed_admit 三模块 code_equiv 登记；CV2 2026-11-27，朱楓林集 MBJ 报）：①册 yaml 顶层 `chars_per_line_pages` 按页每列字数（如序页 `{"2-9": 14}`），border_detect／column_geometry／column_gate／row_segment／row_segment_gate／cut_gate 一处认（`core/step` 注册处换 `ctx.book.chars_per_line`，步代码不动）；写了表的册这几步指纹加 `cpl_pages`，没写的册不变。②`seed_admit.seg_box_check`（按书挑 sliver／frame_line／speck／split_pair／tall，`[all]` 全开）：碎格、框线扁条、墨点、一字劈两框、过高框退回待审，doubt `seg_defect`（待审原因 seg_defect）。
- 脚本（不进任何 Step 指纹；GM2 2026-11-27，CV0 采纳执行方建议）：`scripts/rerun_prep.sh` 切 cv 改走 `safe_checkout`：遇「未跟踪文件会被覆盖／删除」只处理 git 报出的那几个文件，先带时间戳备份到工作区外（缺省 `~/.guji-jobs/checkout-bak/<UTC 时间>-<pid>/<仓名>/`），再移走、重切，备份路径打进准备日志；不整仓 clean，清单里有仓外／已跟踪／不存在的路径就一个都不动。执行方取 dev 上的准备脚本，合进 dev 即生效。规则同 guji-manager `jobs/safe_checkout.py`。
- PATCH（产物逐字节不变，code_equiv 登记，L0；CV2 2026-11-27，CV4 算法待办 #13）：拆步前的旧产物包（各书钉 0.7.x 线的 main 包）没有 `column_bands`，现行 cv 再生 `column_image`／`char_patch` 时 `column_end` 报上游缺失、`seed_admit` 整页 PatchUnavailable。现在 `column_end` 读不到 2b 产物且 `column_windows` 带旧 `band` 时，经 `column_band.legacy_strip` 按拆步前 `clean_column` 前半在内存里现算（不带 `side_cut`，不写包、不进缓存），文字带用包里记的值；新包缺 2b 照旧报错。史記 42（v0.7.112 包）、全唐文 020（v0.7.104 包）各 12 页列图＋字块与包的原版本逐像素同。

- PATCH（产物逐字节不变，code_equiv 登记，L0；CV1 2026-11-26，CV0 定）：刻本链出口闸 `cut_gate` 也认 row_segment 列旗 `manual_cells_remapped`（钉子按列图几何换算、位移 >3px），列级 flags 记「待人核」，只记不拦，口径同 row_segment_gate；manager ≥ v0.6.38 按它出 S05 待审卡。

- PATCH（产物逐字节不变，code_equiv 登记，L0；CV1 2026-11-26，CV0 批的钉子护栏第二步）：`row_segment` 套整列钉子（manual-cells）前比钉子写入时记的列图几何底（manager v0.6.35 `column_basis.geom`）：一致照套；不一致经旧／新 `ColumnMapper` 把格框经原图换到新列图，角点最大位移 >3px 的列打 `manual_cells_remapped`，出口闸（row_segment_gate）记旗「待人核」。没记 geom 的老钉子照原坐标套、只在日志提示。开关登记表 outer_bar 记「直线页可能被记成三段，人钉切格的书慎开」。缘由：全唐文 031–060 outer_bar 让列图挪 10–32px，钉子照旧坐标套切偏。
- PATCH（缺省 `any` 产物逐字节不变，待 code_equiv 登记，L0；书上开 `no_ref` 为 D 档，只动 `seed_admit`；CV0 2026-11-26，Sheldon 定）：`seed_admit` 加 `solo_5b_scope: any|no_ref`。`no_ref`：无参照放行 `match_solo_5b` 只放①`reference_profile` 声明 `kind: none` 或 `page_kinds.no_ref` 的页、②有参校本页上坐标对位为缺字（〓／▣）的位；有参校本页上一个对位字都没拿到的格留待审（全唐文 main 包 8 册实数：有参校本页 94 格受影响，none 页 7,513 格不变）。缺省不进参数 dump。

- 文档／脚本（不进任何 Step 指纹；CV2 2026-11-26）：字间判官固定下来——`scripts/train_boundary_net.py`（出样本、训练，与推理同一窗口函数）、`doc/2-切字/字间判官.md`（参数、模型、借用或单独训、验收）、Wiki 2-切字「给一本书打开」。

- PATCH（产物逐字节不变，code_equiv 登记，L0；CV2 2026-11-26）：`row_segment` 加两个开关（缺省关、不进参数 dump）。`layout_off_tol`：无先验格网违表＋劈字只多 ≤tol、劈字／格高不匀／穿字严格更好时改选（全唐文 060:3:3 多出空格；053 册 L2 列全对 323→324、0 回退）。`boundary_net`／`boundary_net_p`：字间界线判官（新 `impl/keben/boundary_net`＋模型 `models/boundary_net_shiji_v1`），只重排全正文列内部低分切线、格数不变（史記 42 cut-lattice 线 789→808/874、错列修回 4、好列不坏）。史記 42 40 页 row_segment 逐字节同，新 code_dep 经 SPLITS 合回。

- PATCH（产物逐字节不变，code_equiv 登记，L0；CV0 2026-11-26，GM4 批量规则）：人裁事件分级 `events.event_level`（`payload.level` 优先；`actor=model` 没写 level 的按 9 个人授意批次认 human，其余 ai；看图结论/文意裁定/模型判断来源为 None）。新 `counts_as_pin`＝原 `counts_as_human` 口径（人裁或已放行 AI 钉），lookup/bindings/republish 改调它；`counts_as_human` 收紧为只认 human，只给统计评测用。史記 02、殿本 vol28、全唐文 020 共 54 页 seed_admit 逐字节同。

- PATCH（产物逐字节不变，code_equiv 登记，L0；CV1 2026-11-26）：`border_detect` 加开关 `outer_scale`（缺省关、不进参数 dump）：外框探测的像素量（搜索窗上限、墨条厚度上限、外延刹车、先验窗、条外纸带）按列距/220 放大，只对列距 >220px 的页（全唐文大图）起作用。全唐文外框粗条厚约 56px、外延离界行 80~95px，关着时压在殿本标的窗上限 78、或被厚度上限 40 挡掉，上下框判 none 或外延截在 78（046 p93）。layout-gold 79 页开着框型判对 287→289，殿本、史記 0 页变；关着 79 页逐页同。全唐文要用在册配置写 `params: {border_detect: {outer_scale: true}}`（书线定）。

- PATCH（指纹换算，产物不变，L0；CV4 11-26，QTW 全唐文 004–030 改钉 k13）：`engine._collapse_splits` 合回后的那一项按旧名记，后面的 SPLITS 条目能把它当一块再合；新 SPLITS 条目把全唐文书仓 k13 的 `guji_book.quantangwen.admit_lanes`（这一版）记成 cv 缺省 `impl.keben.admit_lanes`——没写 `book_lanes` 的册不调钩子，产物同 k11；写了的册参数指纹本就跟着变。效果：全唐文 k11→k13 各步指纹全同（改前 seed_admit 会过期）；殿本、史記、脉经书仓与无书仓、全唐文 k6／k8／k9／k10 各步指纹改前改后全同（27 步逐一比对）。

- 重构（PATCH，产物逐字节不变、指纹不变，code_equiv.SPLITS 合回；CV4 整理 PR3c，Sheldon 11-23「深度整理」）：`steps/seed_admit.py`（5,284 行）拆出三块——`seed_admit_lanes`（整理本／无参照放行通道与降审护栏 26 项：rare_ref、solo_5b、follow_ref、edge_pair、review_lanes、p_ref …）、`seed_admit_shapes`（字形判官 8 遍：rr／wu／hou／part／pair_shape、stroke_veto、book_knn、near_knn）、`seed_admit_common`（各遍共用的常量、小工具与字块读取 `_page_patch`），主模块剩 Step 壳、主循环与其余各遍（3,352 行）。代码原样搬，只把 `_page_patch`／`_edge_pair_excluded` 改成经 `seed_admit_common` 模块属性调用（测试换字块读取改 `setattr(seed_admit_common, "_page_patch", …)`）；对外名字照旧从 `steps.seed_admit` import。

- MINOR（用户 2026-11-25 定「接进 2b、缺省开」；动 `column_band`，从 2b 起过期）：2b 新开关 `column_band.side_cut`（缺省开）：整列竖直墨量投影（只取上下边框之间、各让 60 行）认出框线，在框线内侧 15% 列宽内取第一个够低处、往里缩 2px 为左右切点，切点外整列抹白（在旧算法抹界行之上再抹）。**文字带 `band` 仍用旧算法的值**：2d 对带宽极敏感，史記 42 测试集用新带列全对 287→264（不缩 274），只抹边 287→284；全唐文 053 新带 324→325、只抹边 324→323。`seg/side_cut` 换成验证版（界行衰减到谷、第一个够低处、半开区间），`cut_gate` L2c 探针随之变；更正 L2c 唯一命中 053 p148c9 是误报（双线细内线）。CV2。
- PATCH（W1 急修，产物逐字节不变，code_equiv 登记，L0）：`border._fit_head_raise`（head_raise_fit，v0.9.2 起缺省开）死循环——两邻列内框互吸、同值反复写，`while changed` 不结束（脈經 01 p67 单页卡 25 分钟以上，MJ 报）。改为值真变了才再来一轮，另加迭代上限 `HR_FIT_MAX_ROUNDS`×列数兜底。殿本 vol01／04、脈經 01／06 共 21 页逐字节同。CV1。

- PATCH（ZM→CV1 殿本列末「二／三」被判成「一」，11-25；改 `impl/keben/column.py::column_border_trim` 下端剥层，影响 `column_end` 起的产物，只在册配置 `frame_layers` 下端≥2 时走到）：下端外框＋内框剥完后再找的**第三道**线，改为只认边距证据（边距带满墨 ≥0.95，且比列内中位高 ≥0.3），除非它与上一道线隔着 ≥8 行白（vol02 的第三道虚线）；另外 Step1 说内框在某处而该处 ±10 行是白纸时、或候选起点在内框线外 30 行以远时，里面的墨一律当字（vol03 p64c1、vol05 p23c7）。殿本 vol03 全册 108 页比 dev：23 列变，全是末字下横被削回来，无内框残线退步；vol02 夹具 231 端 5 端变（都是旧深剥预警端，1 端 px 不变只改档位名）。上端同类（vol16 p164c3「三」首横离顶 9 行被当第一道框）本 PR 不修。
- PATCH（随上条，CV0）：`impl/keben/column.py` 登 code_equiv（上条新分支只在 `frame_layers.bottom>=2` 时走到，中心库只有殿本这样配，别的书按构造逐字节不变），另在 `core/engine._self_payload` 给 `column_end` 加 `frame_layer_rev`（`engine.FRAME_LAYER_REV=1`）：只有下端两层的册写这个键、从 column_end 起判过期（殿本 L3），别的册指纹逐位不变。以后改这段剥层判据：登 code_equiv＋把 `FRAME_LAYER_REV` 加一。
- PATCH（W1 v0.9.2，Sheldon 11-25 定；指纹变更：border_detect 起过期（W1 统一重跑））：版面 5 个开关改缺省开——`border_detect.outer_bar`、`vline_track`（含淡线兜底 #1890）、`inner_pull`（只对册配 `frame_layers: 2` 的边起作用）、`head_raise_fit`，`border_detect_gate.no_frame_skip`；都进参数 dump（border_detect 1.21、闸 1.4），不要的书在册配置写 false。79 页版面金标：界行 >5px 17→17、非正文放行 3→0；殿本 vol01–20 样页 200 页 A/B 看图 46 处开对 46（ai-team domain/CV/里程碑/W1-殿本版面开关AB.md）。CV1。

- 文档（无代码变化，产物与指纹不变，CV0）：`doc/参考/性能统计.md` 按四大步重整：任务库已在 D1、`top --remote` 先列任务阶段（含 prep 分段）再按版面／切字／识字／定字分组、第三轮分段名单（row_segment、column_band、cell_shrink、rare_candidates、读缓存图）与冷缓存再生小计；配 manager 同日 PR。
- PATCH（CV0 复核 #1891 余两格 vol04 p207c6、vol05 p149c6，11-25；改 `impl/keben/column.py` 下端第三道线，只在 `frame_layers` 下端≥2 时走到）：第三道候选离 Step1 内框线 >10 行的也只认边距证据（末字下横与内框线隔 13 行白，原先靠「隔白≥8 行」放过）。殿本 vol03 108 页比 #1891 版再变 2 列（8:8、17:3，末字下横回来）；vol02 夹具 1 端变（145:6 留残线）。登 code_equiv，`FRAME_LAYER_REV=2`。
- PATCH（脚本，不进指纹）：republish 读者侧冒烟查图改用 GET＋`Range: bytes=0-0`（200／206 都算到），不再用 HEAD——CDN 新对象 HEAD 常 403 好几分钟而 GET 已 200（史記 001-r2／013-r2 冒烟误报，11-25，CV0 u T1）。
- PATCH（指纹补漏，随 #1869／#1872 同一轮重跑，不另加重跑）：`steps._colview`（2a–2c 合并视图）补进 `column_geometry`、`column_gate`、`cell_shrink`、`cut_gate` 的 code_deps，`impl.keben.jiazhu_split` 补进 `cut_gate`——原先改这两个模块产物照报新鲜（manager `test_code_deps_coverage` 11-25 报红）。四步 code_hash 变，这四步今天已因 #1869／#1872 过期。CV0。
- MINOR（用户 2026-11-25 定；只动 `cut_gate`：从 cut_gate 起过期，切字各步产物逐字节不变）：出口闸加自检 L2c `cut_too_inward`：当前左/右切点比「框内缘之后最少墨处」（新 `seg/side_cut.side_cut_points`，算时忽略上下边框前后各 60 行）更靠里超过 `cut_inward_max_px`（缺省 10，0=关）→ 拒收。全唐文 053、殿本 vol01、脉经 共 1140 列实测偏差 99 分位 ≤0，命中只有全唐文 053 p148c9 左侧（30px）。

- 文档（无代码变化，产物与指纹不变）：2 切字新增五小步 2a–2e（拉直、定字带左右边、列端字、字间切分、字框压缩）的输入输出与代码对应表 `doc/2-切字/五小步.md`；README、骨架注释同步。
- MINOR（用户 2026-11-25 定，不怕指纹变）：切字出口闸放到最后。新增 `column_geometry`（2 列几何：字带、格线范围、页级字距，只算量、只记结构性不切）与 `cut_gate`（挂 `cell_shrink` 出口，读 2a–2e 全部产物，列级与格级判据并在一起，判据一字未改，产物仍叫 `gate_manifest`／`row_segment_gate_manifest`）；`row_segment` 改读 `column_geometry`，`column_gate` 不再挡 2a–2c、`row_segment_gate` 不再挂在 `row_segment`；引擎按管线判断闸是否适用（现代链不受影响，仍用 `column_crop`＋`column_gate`）；旧 `column_gate:` 参数自动复制到 `column_geometry`／`cut_gate` 里同名字段。

- MINOR（用户 2026-11-25 定，不怕指纹变）：切字五小步拆成独立 Step——`column_warp` 只留 2a 拉直去噪；新增 `column_band`（2b 定字带左右边、抹界行；产物 `column_bands`、`column_banded`）、`column_end`（2c 列端抹版框；产物 `column_ends`、`column_image`）。算法一字未改，殿本 bench 40 页 `cells`、`char_index` 与拆前逐字节相同。刻本链各书从 column_warp 起过期。册配置里 `column_warp:` 下的 `tight_rule_band`、`inner_bar_span` 自动搬到 `column_band`，不用改册配置。`column_gate` 暂挂 `column_end`，下一步移到最后一道出口闸。
- **MINOR**（Sheldon 11-24 定；史記、殿本、全唐文 参数指纹与产物不变，脉经 01–06、北行、幼學 seed_admit 起过期）：seed_admit 5 个参数缺省改成三本主力书都设的值——`consensus_fallback: true`、`group_flow_ctx_agree: [rr]`、`ref_lib_coord_dissent: true`、`edge_pair_group_seam: false`、`human_unbound_shift_ok: true`（`fold_ref_char` 不改）。参数指纹仍按旧缺省去键（新表 `_DUMP_DROP_HASH`，`params_hash`／`param_parts` 传 `context={"hash": True}` 时才去；重建参数用的普通 dump 保留这几个键，免得写死的旧值落回新缺省）。殿本、全唐文没设的键在中心库写死旧值（ZM、QTW 11-25）；脉经翻转清单 28 格里属这 5 键的 20 格（4 新放、16 撤回待审），MJ 同意。
- **MINOR**（L0：各书产物逐字节不变、指纹不变，code_equiv 登记；全唐文 001–003 要随书仓 k13 一起换）：seed_admit 加书级放行通道钩子 `impl/keben/admit_lanes.noref_lanes`（缺省 None，在 solo_5b 之后、ref_lib_5b_veto 之前调）与参数 `book_lanes`（dict，原样进参数指纹；`data` 路径表的文件内容哈希进 `book_lanes_fingerprint`；空不进 dump；写了而书仓没覆盖钩子就拒跑）。只有全唐文 001–003 用的四条无参照补放通道 solo_adapt／num_run／solo_cal／lead_5b 连同 28 个参数（`solo_adapt_*`、`num_run_*`、`solo_cal*`、`lead_5b*`）搬进全唐文书仓 `code/admit_lanes.py`（Sheldon 11-25 定「搬进全唐文书仓」，CV4）：册配置写原缺省值照读、写别的值报错并提示改写进 `book_lanes`。`scripts/char_cov_profile.py` 留 cv。

- PATCH（产物逐字节不变，code_equiv 登记，L0）：冷缓存再生列图护栏（CV4→CV0 11-25，殿本 frame_layers／outer_gap）：`RunContext.materialize` 现算前比产物 manifest 记的 `book_deps` 与现册配置，不同就报 `StaleRenderError`、不出图；`column_warp.render` 再生尺寸与产物 `warped_size` 不符也报错；`cell_shrink` 整页内框线记忆 `_INNER_MEMO` 键加 cells／column_windows 产物 sha 与参数，同进程换配置不再串。起因：改了册配置没重跑 column_warp 时，下游按旧格坐标裁新列图（ZM replay-1125 二→一 37 格）。CV0。
- PATCH（只影响开了 `glyph_match.stages.pair` 的册，即全唐文：5a 起过期）：5a.3 形近字对分类器起跑前核对它训练时用的嵌入模型（`pair_clf.json` 的 `sim_model`，sha 前缀或模型目录名）与当前 `glyph_match.sim_model` 一致，对不上（或没记）就拒跑——换 sim_model 不重训 pair_clf 会按乱分改字。`build_pair_clf.py --sim-model` 改为必填。CV3。
- PATCH（产物逐字节不变，code_equiv 登记，L0；开的册 L1）：`ruling_by_u` 扩到字组文意在线问前查缓存：开着时 seed_admit 跑字组流程期间设本页 {格号: u}（`rulings.UMAP_SCOPE`），`RulingCache.lookup` 窗口键没中再按 u 查**版本完全相同**的裁定（`get_by_u_ver`，二审小组各成员不串；前后 2 字一侧同），命中记 `ruling_key=u`。起因：殿本试点强制 u 回放里 7 格只靠字组缓存放行，重切后窗口一变就丢。三书 50 页逐字节同。
- PATCH（产物逐字节不变，code_equiv 登记，L0；开的册 L1）：新书级开关 `seed_admit.ruling_by_u`（字格永久编号 u 执行方案 T3，CV0；缺省关、关时不进参数 dump）：窗口键、版本等价、格锚点都没中后，按本格的 u（从本册字格身份账 `<feedback>/uid/<册>.jsonl` 按本页 cells_sha 取，新只读类 `feedback.rulings.UidLedger`）查同册同 u 的裁定，口径同格锚点宽松档（只收 high、前后 2 字一侧相同、字不一致不放行）、字在候选或＝整理本字。`RulingStore` 加 `get_by_u`／`has_u`／`uid_ledger`，`put` 加 `u` 参数（manager 写裁定带 u 用；不给时 payload 不变）。殿本 vol28、全唐文 020、史記 02 共 50 页 seed_admit 逐字节同，各步 code_hash 与 dev 同。

- PATCH（产物逐字节不变，code_equiv 登记；参数指纹 12,472 组全同）：seed_admit `solo_5b_min_n` 恢复成参数（脉经序页、牒文页经 `no_ref_params` 要设 1；缺省仍 3、缺省不进 dump）。

- 重构（产物逐字节不变，code_equiv 登记；参数指纹 12,472 组全同）：seed_admit 69 个门槛收成常量（CV4 整理 PR4，Sheldon 11-24 定）——414 册无一册改过，从 `SeedAdmitParams` 字段改为 `seed_admit_params._CONSTANTS` 里的常量、类上只读属性（代码照旧读 `p.<名>`）。老配置写原值照读、写别的值报错；原先进参数指纹的照原值补回 dump。`no_ref_params` 不能再覆盖这些键。测试换值用 `tests.helpers.seed_admit_consts`。

- CI（不动代码、不进指纹，L0）：新工作流 `指纹变更检查`＋`scripts/check_fp_change.py`：推 tag、开／改 PR 时比基线与本版各步规范指纹（已按 code_equiv 换算），变了却没登记、说明里也没写明「指纹变更：…」就红。起因 v0.7.83、v0.7.99 两次 patch 线漏登（GM2 11-24）。

- PATCH（缺省关，产物逐字节不变，code_equiv 登记）：seed_admit 书级开关 `ruling_anchor_loose`——格锚点后备键的宽松档（GM4 合并方案，GM3／CV0 确认 11-24，选 CV0 的 (b) 书级开关）：版本认本组 `rulings.validate` 认的任意版本、减 `ver_equiv.yaml` 新增的 `void`（O 组仍按目标版本，不收 L4 缓存）；同格多条取最新、字不一致记 `ruling_conflict` 不放行；只收 high（fold 遍也是）；窗口改为前后 2 字至少一侧相同（证据 `win_sides`）。缺省关、关时不进参数 dump；`load_ver_equiv` 返回多 `void`。宽松档下 fold 按裁定给的字被影子（shadow_veto）降审时另记 `fold_ruling_vetoed`，进 `_LANE_HARD`，待审通道不按整理本字放回（20 册回放 vol49:179:9:4）。

- **PATCH**（11-23，GUJI-776 SJ 验收）：`core/corpus_pin._check_pin_once` 的「语料库 vN 清单与当前文件不符」同一工作区、同一版本、同一批文件只警告一次（原先按册去重，一次 db sync 摸 42 册就打 42 遍）。只改提示，不进指纹（L0）。

- PATCH（缺省关，产物逐字节不变，code_equiv 登记）：seed_admit 书级开关 `ref_lib_5b_veto`／`ref_lib_5b_veto_lead`——「整理本＝库首位」放行（`ref_lib`）的 5-b 否决：5-b 首位是别的汉字、分 ≥ 门槛、领先 ≥ 门槛 → 退回人审（doubt `ref_lib_5b_veto`）。起因殿本字书 靃 被整理本规范成 霍、库首位也落到 霍（A23 11-23）。

- PATCH（纯搬家，产物逐字节不变、Step 指纹不变）：seed_admit 的参数类 `SeedAdmitParams` 与退役／恒开参数表、去键表搬到 `steps/seed_admit_params.py`（CV4 整理），`seed_admit` 照旧 re-export；新模块进 code_deps，经 `code_equiv.SPLITS` 合回原指纹。

- PATCH（产物逐字节不变，code_equiv 登记）：seed_admit 参数指纹去键规则由 `_drop_off_rare` 里一百多段 if 改成声明表 `_DUMP_DROP`（CV4 整理 PR3，规则逐条不变；397 册＋两两翻转 11,730 组 params_hash 不变）。

- PATCH（产物逐字节不变，code_equiv 登记）：seed_admit 36 个缺省开、397 册没有一册关过的护栏／通道改恒开、不再是参数（CV4 整理 PR2）：iron_*_guard、ref_lib_*_guard、variant_indirect_guard、edge_pair、rare_ref_coord／nf、occluded_variant_first、lane_seal_* 三个、vis_rulings、codepoint_semantic、evict_review、human_unbound_review 等，清单见 `_ALWAYS_ON`。册配置写 true 照读、写 false 报错；原进参数指纹的照原值补回，各册 params_hash 不变。`use_context`、`occluded_gate`（manager 读）与测试隔离用的 `context_page_end_review`、`context_garble_guard` 暂留。

- PATCH（产物逐字节不变，code_equiv 登记）：seed_admit 删 38 个无书用的死开关（CV4 整理 PR1，Sheldon 11-23「清除多余开关」）：context_verdicts、witness3_no_diff、textlayer_ref_gap 一族、p_ref_coord 一族、off_channels、match_tie_guard、solo_5b_borrow_db／char_ok、approx_gate、seal_lib_agree、lane_witnesses、follow_ref_variants_gap 等，清单见 `_RETIRED`。册配置写缺省值照读、写别的值报错；原进参数指纹的 6 个照旧补进 dump，397 册 params_hash 不变。

- PATCH：字对关系表（#1781）两处修正（GM2，QTW 11-22 全唐文 016/036/052 前后对比反馈）：①关系图套 V 对时把原来源盖掉了——原文件多只存一个方向，往空的反方向写 `[local:pairkind]` 后建图两向互写，74 对 V 只剩 `local:pairkind` 一家、n_bridge 掉到 1（如 㑹／會 原 hydzd＋twedu），`edge_pair` 等要 ≥2 家来源的口径不再认；现在两向来源并起来再补标记，`local:pairkind` 在已有别的异体来源时不多算一家，74 对的 tier／n_bridge 与套表前逐对相同。②C 对删了关系图的边，规则 A（`rare_ref` 各支）与 `lead_5b` 靠「库首位与整理本字有边就拦（形取谁说不准，留给人）」的护栏跟着松了：052:11:8:11 刻 冲、库 冲 0.982／沖 0.9816，#1781 后被 `rare_ref` 放成 沖。新增 `variants.look_alike`（有边，或在字对关系表里，V／C 都算），这两处改用它。052 的另两格（冡→冢、會 被 shadow_veto 送审）是 V 并后 `replace_form: lib` 取库首位、而库首位本身认错（冢 0.9656／冡 0.9505、㑹 0.9755／會 0.9669），同一机制在 052 放对 祇×3、雟，不在本 PR 改，见 PR 说明。

- 文档（11-23，GM2）：`doc/design/待审原因PendingReason.md` 正文搬到 guji-manager `doc/参考/待审原因/规范-PendingReason.md`（代码 11-04 已在 manager），这里只留指向。不动代码。
- PATCH（只动评测与训练脚本，不动产物）：识字 benchmark 第 2 期 c——`eval_advset.py`／`eval_match_pool.py` 按册号奇偶另报 dev／test（调门槛只看 dev）；`train_glyph_sim_cnn.py` 的 `--exclude` 认 items.jsonl／rare.jsonl／每行一格的 .txt，新增 `--exclude-chars`（对抗集留出字整类不进训练），配 dataset `glyph-match/train_exclude/`。
- PATCH（只加评测脚本，不动产物）：`scripts/eval_advset.py`——3a 子基准 A2「库外拒识」，在 dataset `glyph-match/advset-<书>/`（库外形近字对抗集，自带归一图）上用生产逐对判官量库外字被判 same 的题数，分形近层／异体层，`--against` 出翻转清单。登记在 guji-manager（`advset`／`advset_shiji`／`advset_qtw`）。测试 `test_eval_advset.py`。
- PATCH（只加评测脚本，不动产物）：`scripts/eval_match_pool.py`——固定候选池分片的通用评测（首位命中、放行、误放，按类别分报），先用于 3a 子基准 A5 退化（dataset `glyph-match/damaged-*`，真实残损集）。登记 `match_pool`／`match_pool_shiji`。测试 `test_eval_match_pool.py`。
- PATCH：四大步：整理本对位 `align_ref` 从 3 识字移到 4 定字（Sheldon 2026-11-22 定：第三步只管从字块图取证；align_ref 不读字块图，是文本证据与合证据）。4 定字小步改称 4a 整理本对位、4b 上下文、4c 放行。只改骨架 `stages:` 分组与文档，步骤 id、顺序、产物、指纹都不变（A23）。` 下加一行、写明档位。（下面到 `## [未发版]` 之前的几行是早先误写在文件头的 v0.7.x／v0.8.0 条目，原样保留。）

- PATCH：新开关 `border_detect.head_raise_notch`（A22，ZM 报殿本 vol24 27:7:-1 等小抬头格、27:8:1 缺口假格；缺省关）：抬头列占多数的页，主上版框被认在抬头框内框线上、没抬头的列成了「缺口」，整页抬头认不出（抬头格 20 多 px、缺口里切出假字格、抬头列末字没格）。开了以后，本页没认出抬头框、又没写 `hline_hints.top` 时，找「主上框不横穿、下面先白后有框条」的缺口列，主上框挪到缺口列框条内沿重探抬头，缺口以外的列全认成抬头才接受。殿本 vol05/24/28/60/95 共 796 页只动 vol24 p27、vol28 p4–24 共 16 页，看图全对。缺省不进参数 dump；border_detect、impl/keben/border 登记 code_equiv（vol24 16 页、vol28 13 页逐字节同）。
- 新书级开关 `seed_admit.lane_shape_first`（归属表路径，缺省空＝关、关时不进参数 dump；OCR 研究方向 2，设计稿「第 7 步 witness3 与整理本通道按刻形」）：witness3／coord_fallback 对表里 `attr: shape` 且 `variant: true` 的同字异形对，库首位与整理本字是这一对、库首位覆盖度够（≥`lane_lib_veto`）、且第 5 步 5a.3 对这一对有终判档（tier≥3）证据倾向库形时，改放库形（刻本原字，`evidence.lane.lib_form`），不再一律送审（lib_variant）或否决（lib_veto）；库否决的异体名单也由表生成（与手写 `lane_lib_veto_pairs` 取并集）；放库形时跳过 `lane_variant_guard`。只有库首位覆盖度不够用：020 册第一版（只看 cov）奥奧 6 格错 2，所以必须有分类器终判证据。020 册整册回放（d2 包，归属表 v2）：开 `pair_form`＋本开关比关着放行字只变 1 格（寇→𡨥，对），新增错 0（关 983 对 6 错、开 984 对 5 错），见 ai-team／项目文件夹 `020整册回放-1119/`。**`seed_admit.py` 改了，各书第 7 步代码哈希变、产物判过期**；没有书打开本开关，关着时输出不变。
- PATCH：`row_segment.roster_grid_slots` 跟进（A22，回 ZM／A20）：开着时人裁整列格的 `n_body_slots` 也取格数与最大号的大者、超格数打 `roster_slot_overflow`；雙行段内两行同号都空的号收掉（读序 `order_keys` 在两行同空处断段，vol01 87:9 整理本是一段）；Step3 分成两段的密雙行，第二段起号按段字距从上一段末顺延（88:2）。vol01 87–130 与 #1726 对照表比只 87:9 一列变（13a 起各号减 1）。缺省关不变，登记 code_equiv。
- PATCH：新册级开关 `row_segment.roster_grid_slots`（A22，Sheldon 11-19 经 ZM：殿本 vol01 职名页格号空格要占号，88:1:8a 按格数对位投错；缺省关）：职名分支切出的字按格网位置编号（`roster_segment.grid_slots`）——大字按版框内 `chars_per_line` 等分格，雙行一格一字的按格网、比格密的（vol01 p88）按本段字距逐字累加，左行比右行低一字从下一号起；号同侧严格递增、超出格数从尾往回收空号，收不回（字比格多）的列打 `roster_slot_overflow`。切法不变只改号；vol01 87–130 开后 397 列 392 列改号，人裁整列格（manual_cells）的号照人裁记录不动。只套书职名实现有 `grid_slots` 的书生效（史記写本没有）。缺省不进参数 dump；row_segment、roster_segment 登记 code_equiv（vol01 8 页逐字节同）。
- PATCH：`seed_admit.alt_note_region` 加反方向（MJ，GUJI-774）：主切法把左右结构大字劈成 a/b 小注、两半照样放行（脉经 01 41:1「脉」→「永」「月」，待审数看不出的错），备选同处是一个大字格且放行、其余格不更差，就换。01 只多换 41:1，送审数不变。seed_admit 登记 code_equiv。
- PATCH：新书级开关 `seed_admit.alt_note_region`（MJ，GUJI-774，缺省关）：`align_ref.alt_select: admit` 换列多一条路——备选这一列有雙行小注格、主切法同一范围是大字格（把小注并成了大字），主切法在那里放行的字备选也都放行，小注范围外待审不多、冲突不多，就换。参照本没有小注，劈对了格多、待审反而多，按原规矩永远换不过来（脉经 01 40:3「即穴也太淵」、59:7「一本」）。`scripts/yolo_alt_cells.py` 小注起点加一道：框高超过正文一格 1.4 倍的不算（YOLO 把两个扁大字并成高框时分类器摇摆，01 16:6「定息」被认成小注）。seed_admit 登记 code_equiv。
- PATCH：备选格表带整列写定的格（`row_segment.alt_cuts` 的行带 `cells`）＋两个配套开关（MJ，GUJI-774，都缺省关）。脉经正文夹着雙行小注的列，`yolo_alt_cuts.py` 的格线表不写；新脚本 `scripts/yolo_alt_cells.py` 用 yolo_tool 框字、一个小 CNN（32×32，脉经 02–05 放行格训，01 上召回 0.995、9,848 大字格误判 5）判哪些框是小注行，小注段按两行白缝劈开、左右各自框字，整列写成 manual-cells 格式的格（大字满宽、小注 a/b 逐字）；row_segment 读到带 `cells` 的行就按它出一份备选（旗 `alt_cells`，裁图走职名列的逐格裁法）。`row_segment.alt_cells_first`：这份顶掉本列的 `alt_nojz` 备选；`align_ref.alt_text_count_slack`：不分行参照页备选候选另认「库匹配高分格个数不比主切法少 slack 个以上」（小注拆对后格多、占比反降，01 30:7 主 12/23、备选 12/29 原先进不了候选）。配书级 `cell_shrink.manual_ink_fit`（先收到格内墨迹再裁、框外抹白，不带进上下邻字；不开时 01 7:7 认成「景多臺呼」）。脉经第 1 册送审 413→350，34 列变好、2 列各多 1 格（7:7「說」、28:2「吐」认字差）。row_segment、align_ref 登记 code_equiv。
- PATCH：备选格线表 `row_segment.alt_cuts`＋备选列上下文裁决 `context_decide.alt_columns`（MJ，GUJI-774，都缺省关）。脉经正文、序页字有高有低，等距 20 格累积错位（01 7:7「景之書并」4 字切成 5 格），自由行距无效。新脚本 `scripts/yolo_alt_cuts.py` 用 yolo_tool 单字模型在列图上框字（去重框、碎框、版框线，并高字被劈的两框，补低格起头与短列的空格），格线放在相邻字框之间，写成逐列格线表；row_segment 按表另切一份进 `alt_columns`。直接替换主切法时高字常被劈（聾→龍耳），所以只作备选按列挑。原先备选列不做 Step6，没有参照文字的页备选那遍少了 context 通道永远比不过主切法；`context_decide.alt_columns` 开着时备选列也裁决（不并 5-b 与 AI 证据），`PageDecision.alt_columns` 空不落盘，`alt_view` 有备选裁决就换、没有照旧丢。脉经第 1 册送审 447→413，16 列变好、0 列变坏（7:7、25:8「不言者」、56:10「此胃氣」、61:7「葶藶子茱萸丸」等）。row_segment、context_decide 登记 code_equiv。
- PATCH：新书级开关 `seed_admit.alt_backed_gain`（MJ，GUJI-774，缺省 0 关）：`alt_select: admit` 换列时，备选那遍这一列待审只少 1 格、但有字形背书的放行格多出 ≥ 这么多（冲突不多）也换。脉经 01 10:2 序页「則可」主切法劈成「貝丁口」，开 1 后换对；第 1 册只多换这一列（送审 448→447），第 2 册不变。seed_admit 登记 code_equiv。
- PATCH：新书级开关 `row_segment.alt_nojz`（MJ，GUJI-774，缺省关）：认出雙行小注的列另按同样格网、不认小注再切一份放进 `alt_columns`，下游按列挑。脉经左右结构的大字（則何肺脉眩瞤臥）中间有白缝，被认成雙行小注劈成 a/b，墨高、缝宽、连通体都和真小注重叠分不开。配套：不分行参照页（`ref_kind="text"`）也能按列挑备选——align_ref 在 `alt_select: admit` 时逐列换成备选重做 8-gram 对位（库匹配高分格占比比主切法低 5 个点以上的列不进候选），草稿对位字记 `AltDraft.chars`（空不落盘）；seed_admit 不分行参照页要求备选那份放行率不降，与参照文字 equal 的字多 ≥2、待审不多也换（半字照样放行，只比待审挑不出）。脉经第 1 册送审 463→448（17:5、24:1、40:6 换对），第 2 册 846→830（6 列换对，看图无误换）。row_segment、align_ref、seed_admit 登记 code_equiv。
- PATCH：页型表加按列的 `roster_cols`（MJ，GUJI-774 脉经第 1 册卷端「朝散大夫……臣林億等類次」25 字挤在 20 格的列里，Sheldon 11-19「职名页一定要特殊处理，每行字数不固定，高度也不固定」）：册 yaml `page_kinds: {roster_cols: {11: [2]}}` → `row_segment.roster_cols`，点名的列走职名页分支（不定字数、不定字高、格号从 1 数），同页其余列照正文切；整页职名仍用 `roster`。同一页不许既整页 roster／table／cover 又按列 roster_cols，同一列不许既 table_cols 又 roster_cols。只切一两列量不出全页「臣」行时，`roster_glyph_refine` 改把整列当官衔区按字形库重切（`segment_roster_page(chen_fallback=True)`，脉经 01 p11 c2「臣」贴着邻字）。缺省空、不进参数 dump；row_segment、roster_segment 登记 code_equiv。脉经 01 p11 c2 16→25 字、p37 c2 25 字，两页其余列与不开时相同。
- PATCH：书级钩子 `jiazhu_step.row_split`（A22，GUJI-774 脉经第 1 册小字比大字矮）：雙行小注段每行可切多于大字格数的格；整数格号，段内照本行第几字、段占 max(a,b) 个号、段后顺延，`boundaries`／`pos` 换逻辑编号，`n_body_slots` 写逻辑格数，列旗 `jiazhu_row_split+N`，闸3 按物理格数比格数、段内逻辑格线不量。缺省 None 不调；row_segment、row_boundaries、jiazhu_step、闸3 登 code_equiv `_ROW_SPLIT_1119`（史記 02、脉经 02 逐字节同），各书指纹不变。
- 页型表加 `no_ref`（无参校本页，Sheldon 11-19 定：参校本里本来就没有的文字，如脉经 01 林億序、06 牒文）：册 yaml `page_kinds: {no_ref: ["5-7"]}` → `seed_admit.no_ref_pages`；书级 `seed_admit.no_ref_params`（如 `{solo_5b_cov: 0.95, solo_5b_min_n: 1}`）只在这些页叠在第 7 步参数上，别的页不变。两个字段缺省空、不进参数 dump；`seed_admit` 已登记 `code_equiv`（脉经 01 3 页与 origin/dev 逐字节相同），没配的书不过期。脉经 5 页 322 格待审试跑放出 149 格，看图错 1 格。`kinds_from_params` 遇到形状错的 `params`（某步不是 dict）不再先崩，交给后面的校验报。
- PATCH：PUA 码表共享层读取侧（ZM 11-19，A23）：书配置（`book_defaults.yaml`／册 yaml）加 `pua_table_pin: N`（或 `vN`），seed_admit 的 `pua_code_table`／`pua_code_admit` 读中心库只读共享层 `pua-wyg` 的 `v<N>`（`guji db pull` 拉的副本，`core/pua_table_pin.py`；副本缺或 sha 不符报错，不读空表）；码表内容指纹 `pua_table_digest` 进 seed_admit 参数，**没钉的书参数 dump 不变、仍读本书 `config/pua/pua_table.jsonl`**。改了 `seed_admit`／`utils.pua_v2_codes` 模块代码，未跑 `scripts/code_equiv.py check`（云端没有产物），登记前各书 seed_admit 会判过期，需有产物的机器补跑并登记 `code_equiv`。写入侧在 guji-manager（`guji pua-table publish`）。
- 形近字对按刻形改字两件（OCR 研究方向 2，Sheldon 11-18「同意，按这个继续做」；都缺省关、关着时输出不变）：①`glyph_match.stages.pair.unsure: true`——5a 判 unsure 的格也逐候选对问一遍分类器，证据落 `stage.pair`（`on: unsure`，不改判决；写了才进 `stages_sha`，带 `.u`）；②`seed_admit.pair_form`（归属表路径，`-`＝所有对按刻形，试验用）——放行字与证据里过门槛的 `char` 不同时改成刻形字，通道、admit、provenance 不动，人裁不动，册码位表归走的字不改；归属表 `config/groups/pair_attribution.yaml`（`groups/pair_attr.py` 只读）里 `attr` 非 shape 的对不改，没标 `variant: true` 的异字对只记 `evidence.pair_form_review` 进复审。全唐文 020 册 34 页真跑：unsure 格出证据 781 格；`pair_form` 开后第 7 步只变 26 格（清→淸 22、寇→𡨥 3、著→蓍 1，对应全唐文回库后仍照整理本的 13 格等）。**`glyph_stages.py`、`seed_admit.py` 改了，开着 `stages`／跑第 7 步的书代码哈希变、产物判过期**。
- `guji seg check` 加页级检查 `gutter_ink`（A22 各书切分统一优化 U6，Sheldon 11-18 定）：网格模式（书级 `column_grid` 或 `column_grid_pages` 点名页）的正文页（闸收了过半的列），内竖线穿字分（`border_detect.gutter_ink_score`）> 0.5 报出，一页一行、col 记 `-`。只报不改切分；新书首跑就能看见「插值线整片穿字」（脉经 02 册旧包报 p15 0.89，书衣、空白页不报）。
- 新书级开关 `row_segment.cut_repair`（缺省关、开关本身不进参数哈希；A22 各书切分统一优化 U2，Sheldon 11-18 定）：一行开史記 k24–k26、脉经照抄的切点修整串（`cut_gap_guard` 0.08、`cut_free_seam` 0.35、`cut_gap_keep_glyph`、`cut_white_row` 0.35、`cut_glyph_line` 0.35），单写的项照单写的；展开后与逐项写参数 dump 相同、指纹一致。劈字判据 `_split_glyphs` 与两个换线护栏抽进 `seg/seam.split_blobs`／`blobs_keep_sides`（常数原值，行为不变）。
- 新书级参数 `row_segment.jiazhu_cc_min`（px，缺省 500＝原值、不进参数哈希；A22 各书切分统一优化 U3，Sheldon 11-18 定）：雙行小注段噪点否决门槛（`jiazhu_split.link_runs` 的 `cc_min`）按书调。脉经小字单字最大连通体 200–600px，书仓 k1 为改这一个数整段抄了 `link_runs`；开了本参数后书仓钩子只需留段端收编。
- 5-b 新增库字档（OCR 研究 Project，Sheldon 11-18 定）：册配置 `font.charset.lib_chars`，**缺省关，没有书打开**。开着时本书字形库里人裁过、而 5-b 基集里没有或会被简体否决挡掉的字（扩 B 以后的异体、内 无 遥 这类刻形）另开一档，每格都查、按余弦分与基集候选归并，刻例原型在这一档总是开着且只作用在这一档，这些字不受白名单否决（`rare_panel.lib_tier`、`cnn_candidates.real_chars`）。来由：四书人裁刻例里 445 例（112 字）5-b 结构上给不出来，升级档门槛在 r5 下一例都不触发；只开 `font.real_proto` 对这些字无效。全唐文 010 册对照（库去掉本册刻例）：给不出来的人裁 29 格首位／前三／前十 0／0／0 → 10／25／26，基集内人裁格不变，全册首位变 62 格（60 格变成现行放行字），第 7 步逐格零差异。开着的册 `rare_candidates` 指纹多一个键 `lib_chars`（库内容指纹）。**关着时产物逐字节不变**：`rare_panel`、`cnn_candidates` 两个模块已登记 `core/code_equiv.py`（全唐文 010 全册 182 页与 origin/dev 5c276aa 逐字节相同），各书 5-b 不过期。设计与证据 `doc/design/5b-库字档.md`。
- PATCH：5-b 笔画证据（#1684，缺省关）修输入归一：管线的 `char_patch` 是贴格裁的长方块，检测前先过 `to_canonical` 转成入库那种 256 方画布（`stroke_evidence.canonical_input`），原先直接压成方图。全唐文 020 册整册 A/B（29,687 格，rrf 4）：修之前 5-b 首位改错 1,927 格，修之后改对 136、改错 494，第 7 步放行 29,653、待审 34 都不变，**结论是全唐文不该开**（`doc/design/5b-笔画证据.md` 第五节）。`stroke_evidence.py` 在 5-b 的 `code_deps` 里，与 #1684 同版过期；没有书打开，关着时输出不变。
- 5-b 新增笔画证据（OCR 研究 Project 方向 4，Sheldon 11-18 定先改）：`clustering/stroke_evidence.py` 用不认字的笔段检测网络（合成数据训）检出字块里的六类笔段，和候选字的 GlyphWiki KAGE 标准骨架逐候选对齐、一对一匹配打分，只给 5-b 已有候选排先后，不带新候选。册配置 `font.stroke_evidence: {enabled, mode, weight}`，**缺省关，没有书打开**；`mode: rrf`（缺省，权重 4）当名次融合里多出来的一路，`mode: emb`（权重 0.1）只重排 embedding 那一路。三书人裁 5b 冻结集走产线路径（`scripts/eval_stroke_evidence.py`）首位命中：全唐文 76.2→81.1（rrf 4，改对 75 改错 12）、史記 47.6→52.1（emb 0.1，改对 74 改错 11）、殿本 60.0→61.4（rrf 4，改对 93 改错 51，不建议开）；前 5、前 10 基本不动。资源 `models/stroke_evidence_v1/`（检测权重＋97,681 字骨架索引）登记进模型表（种类 `stroke_evidence`），已传 R2，缺了告警一次原样返回。**`clustering/rare_panel.py`、`steps/rare_candidates.py` 改了且 `code_deps` 加了新模块，各书 5-b（`rare_candidates`）产物判过期**；关着时不走新分支。设计与证据 `doc/design/5b-笔画证据.md`。
- PATCH：`seed_admit` 的 `code_deps` 加 `feedback.lookup`、`feedback.bindings`（A31 11-18，#1676 审查意见）：人裁取字、撤下标记、绑定重挂这两处代码一改，有作废记录或重绑的格第 7 步输出就变，以前不进指纹、`guji status` 不报过期（#1673 靠改了 seed_admit.py 才过期，#1676 只改 lookup.py 不会）。`seed_admit` 指纹变，与 #1673 同版。以后改这两个文件也会让第 7 步过期，纯整理用 `code_equiv` 登记。
- PATCH：库内审阅撤库／改标（`glyph_audit evict／relabel`）留的撤下标记不再连该格现行人裁一起作废（ZM 殿本 vol01 11-18：库里刻例标的是旧字「曰」，现行人裁「淵」也被作废，21 格掉回机器字；#1673 同类，那条修库这条路，这条修事件这条路）。`feedback/lookup.stale_human_rules` 逐条读作废表：`relabel` 行只作废字形不是改标新字的人裁（新字从事件日志里那条 `glyph_audit` 取），`evict` 行只作废字形是被撤刻例原字的人裁（原字按字形库撤例审计 `evictions.char`，撤下时刻前两分钟内）；取不到的、别的来路的标记照旧全部作废。`stale_human_marks` 返回值不变。按中心库现状算：殿本 66 条、全唐文 236 条库内审阅标记里，会恢复人裁的殿本 14 格（其中改标 6 格 #1673 已能从库这条路恢复）、全唐文 5 格；史記没有这类标记。`feedback/lookup.py` 不在 `seed_admit` 的 `code_deps` 里（裁决侧不进指纹），本身不让产物过期；与 #1673 同版发出时随 `seed_admit` 一起过期，第 7 步重跑后生效。
- PATCH：库内审阅改标（`glyph_audit relabel`）改的人裁字进文本（OCR 研究 Project，字形库自检线 11-18）。改标时旧人裁事件被作废（`stale_verdicts.tsv`），而改标本身不是 confirm 事件，`bindings.rebind_library_shapes` 见「作废之后没有再裁」把库里新改的字也丢了，第 7 步照旧由机器放行旧字（全唐文 b3 整轮重算后仍有 10 格：侯 放成 𠋫、𡽪 放成 徽、廏 放成 廄）。现在作废当时或之后以 `glyph_audit` 改标重进的人裁刻例照常采信，落哪一格仍照绑定表，绑不上的进人裁绑丢闸回待审。`seed_admit` 代码指纹变，各册第 7 步产物过期；输出只在改过标的人裁格上变。
- PATCH：5a 新增一段 5a.3，形近字对的按书分类器（OCR 研究 Project 方向 2，Sheldon 11-17／11-18 定）：`groups/pair_clf.py`（本书刻例上按对训的逻辑回归，吃相似度 CNN 嵌入；每对分 借／起步／可用／终判／归文意 五档，刻例够了仍分不开的对自动归文意）、`scripts/build_pair_clf.py`（建书级文件 `config/groups/pair_clf.json`）、`glyph_match.stages.pair: {model, final}`（不写不跑；`final` 缺省 false 只出证据，判决一格不变）。全唐文 001–045 册 81 对按册留出：现库刻例最近邻 93.0%，本书刻例逻辑回归 99.4%；第一版 66 对够终判，嵌套验证给字 21,535 格错 2 格。**`steps/glyph_stages.py` 改了，开着 `stages` 的书（全唐文）`stages_sha` 变、第 5 步判过期**；没开 `stages` 的书不受影响。没有书打开 `pair`。设计 `doc/design/形近字组-按对分类器.md`。
- `eval/seg_screen` 加两条墨账（`guji seg check` 用；全唐文切分线 11-18，R033／R038 复盘）：`erased_strokes`，对比 column_raw 和 column_image，被抹掉的墨离列图两边都远、又不是贯穿多格的竖线，就报（清界行把「十」的竖、「恪」的忄当界行抹了）；`bbox_drop`，字所在那几行里落在所有字框外的成块墨（单字成列「制」丢刂、整字判成半格「使」丢亻）。全唐文 001/009/014 册 11 页（b2）10 处全报、误报 0。只读产物与缓存，不进任何 Step 的指纹。
- 新书级参数 `row_segment.jiazhu_span_t`（缺省 0.75＝原 `jiazhu_split.SPAN_T`、不进参数哈希；《脉经》MJ 11-19，GUJI-774）：雙行小注单格判据「墨跨度/列距」的下限按书调。0.75 是殿本标定（正文字跨度中位 0.59）；脉经字宽，第 1 册放行正文格跨度中位 0.786、73% 过 0.75，左右结构的字（肺、脉、謂、師）中缝一宽就被劈成 a/b；夹注对中位 0.88。脉经取 0.82：第 1 册整册送审 512→496，没有页变差。只影响切分（`segment_column`），交接闸的 `column_frac` 不变。缺省时逐字节同（脉经第 1 册 3 页），登 code_equiv。
- 新书级参数 `border_detect.edge_strip`（布尔，缺省关、不进参数哈希；《脉经》MJ 11-19，用户指出 03 p42 右边明显的框线没吸上、03 p46 右边 5 条线偏，A22 定位到册 `ink` 二值化）：探竖线之前先把页边书口条抹白（`strip_page_edge`，只给 `detect_borders` 用）。书口条是叠着的书页边缘，从天头一直通到页底，二值化后成一束竖黑条，比细内框线更像框，网格模式把外框定在书口边上、内插线整片偏；真版框线天头没有。判据：天头 6% 行里逐列墨比例 > 0.5，从页边往里走（先放过 40px 页边留白），连续 12px 不是就停，最多走页宽 7%。书口紧贴版框的页抹的时候会连框线一起抹掉（02 p24），所以抹与不抹两版都跑，出带列少的胜、一样多比穿字分，抹的那版胜出才用（页上记 `edge_strip` 旗标）。不改用灰度（灰度 A/B 105 页净放行 +231，但 02 p58 等 14 页左框太淡认不出、整张网格错半列）。
- `border_detect.grid_outer_fix` 加强：按版式列数强拟列宽均匀（《脉经》MJ 11-19，用户指出「为什么没有强制列宽一致」）。开着时，只重定外框（窄条／收边）之后页上仍有列宽出带的，另试一版：按版式线数（列数＋1）跑 `pitch_rescue`、不查「旧线贴着在带列又挨着细线就不许挪」护栏（`rescue(n_lines=, keep_guard=False)`，缺省参数行为不变），再重定外框；两版按与列宽检查同一口径（竖线 x 取版框中高处）数出带列，强拟版出带更少才采用。脉经全书 418 页：出带页 13→12，修好 04 p37（中间一列 378 被拆成两列、外列 110／157）、06 p24（少两条线、9 列）；03 p46 换了一种出带、02 p2／03 p2（书衣、非正文）回到不救援。`pitch_rescue.py`、`border_detect.py` 改了，开关关着时逐字节同（脉经第 2 册 4 页），登 code_equiv；开着的书（脉经）border_detect 起重跑。
- 新书级参数 `border_detect.grid_outer_fix`（布尔，缺省关、不进参数哈希；《脉经》MJ 11-18，用户指出 02 p15／p24 换线后外框仍错）：书级网格模式下，`grid_free_fallback` 换线之后（换没换都做）重定外框线：①一侧外列是空白窄条（< 0.5 倍内列中位、靠里半段逐列墨中位 < 0.5 倍版心平均），去掉窄条外侧那条线（粗框条／双边框外线），在另一侧外框线外 0.6–1.45 倍列距里找最实的竖线当版框补一列（那边得确有字）；②网格模式下也跑列宽均匀拟合（`pitch_rescue`，原先只在自由模式跑），放在③之前；③`grid_outer_trim` 挪到这一步做，找不到细线时只在落点是字缝（靠版心半边逐列墨中位 < 0.5 倍满列字身墨）的情况下按列距平移。脉经全书 418 页：列宽出带页 40→13（余下多是书衣、首页），改 65 页。起因：02 p15 左边线落在粗框条与首列字之间的白边、右边整列「少陰」落在网外；02 p24 换线后右线落在书口上（列宽 255）；列宽均匀拟合在网格模式下不跑，换到自由模式后又被「贴版框外列不许甩出网」护栏挡回。关时逐字节同（脉经第 2 册 4 页），登 code_equiv。
- 新书级参数 `border_detect.grid_free_fallback`（穿字分门槛，缺省 0＝关、不进参数哈希；《脉经》MJ 11-18，GUJI-774）：书级网格模式下，内竖线「穿字分」（`gutter_ink_score`：贴线字缝带墨比例 ÷ 版心平均墨比例）高过门槛，就再用自由模式＋列距救援探一遍，线数相同且穿字分不到网格模式一半才换，换了的列打 `grid_free_fallback` 旗标。起因：脉经界行大多没印，网格靠插值补线，个别页列距不匀、补出的线整片错位斜穿字（02 p15 列图全跨两列，整页对不上参校本）。脉经 1–3 册 205 页按 0.15 换 17 页。关时逐字节同（脉经第 2 册 4 页），登 code_equiv。
- 新书级参数 `border_detect.grid_outer_trim`（倍数，缺省 0＝关、不进参数哈希；《脉经》MJ 11-18，GUJI-774 A22 定修在 Step1）：网格模式下首／末列宽于内列中位这么多倍（≤1.6 倍、列数等于版式列数的页），外框线收到「内邻线往外一个中位列距」：先在附近（±半个 slot_tol）找细界行、离原外框线够远才认，找不到按列距平移、记 `vline_filled`；线形取内邻线平移。`pad_outer_columns`（外列偏窄往外推）的镜像。起因：脉经半叶图书口紧贴版框，网格模式选版框对时无界行页各对支持数打平、按投影和挑中鱼尾那条，书口（鱼尾、「脉经卷X」）整条圈进首／末列，这些列送审率 25%（正常 8%）。脉经第 2 册 78 页改 7 条外框线（5 条吸到界行）。关时逐字节同（脉经第 2 册 4 页），登 code_equiv。
- 新书级参数 `row_segment.adopt_rel`（倍数，缺省 0＝关、不进参数哈希；《脉经》MJ 11-18）：L3 扩池后绝对门槛（`ADOPT_DIS` 30／`ADOPT_INK` 20）没有可改选的候选、现选与 U-Net 分歧 ≥1500px 时，取分歧 ≤ min(250, adopt_rel×现选分歧) 的扩池候选（干净格线仍只换不穿墨的）。起因：脉经字大（≈156px）、笔画粗，正确的 U-Net 引导缝穿墨 20–55px、分歧几十到两百，绝对门槛全挡，格线切进下字头（善、黄、痛、胃）。2–6 册 ≥1500 且有候选的 31 条看图约 26 对 2 坏 3 平；1000–1500 那档坏 4 条，所以门槛 1500。只在最终那遍切用；关时逐字节同（脉经第 2 册 4 页），登 code_equiv。
- 两个书级开关修切分丢笔（全唐文切分线 11-18，字形自检撤库 12 例，台账 R033／R038；缺省都关、不进参数哈希，关时全唐文 001/009/014 册 11 页 column_warp、cell_shrink 与 origin/dev 逐字节同，登 code_equiv）：`column_warp.inner_bar_span`——贴边界行内侧的孤立窄条离边超过 0.13 列宽、本横条里有墨的行不到一半，就是字贴着界行的竖笔，不当第二道线连界行抹白（「十」剩「亠」、「恪」丢忄、「四」丢右竖）；`cell_shrink.long_rule_outer_only`——`strip_long_rule` 只认贴图块外沿 0.18 宽以内的竖线（单字成列的「制」，字缘就是自己，刂 被当拐角框线抹）。11 页开关前后字块只变 9 格，全是救回笔画，格位不变。
- 新书级参数 `row_segment.cut_judge_scale`（缺省 1.0＝关、不进参数哈希；《脉经》MJ 11-18）：U-Net 切点判官窗口缩到不超过这么多倍才进网络，seg check 的 cut_through 同用。判官训练集字高≈110px，脉经字高≈156px，判官对大字失灵（第 2 册 12 页 1040 个切点 789 个 escalate，所选切线 dis_unet 中位 310）；窗口白底二值（册配置 ink，#1650）＋0.7：中位 8、escalate 124，放行 1896→2033，「其口唇口唇」「曰善」「故脣」「表裏」等格线落进字内白缝的改对。关时逐字节同（脉经第 2 册 12 页），登 code_equiv。建议值：字高 ≈ 110/scale。
- 新册配置字段 `ink`（册级墨层＋二值化，用户 11-17 定，起因脉经彩图；`utils/ink.py`）：`color` auto／luma／max／red（auto：彩图取三通道最大值压掉朱印朱批等有色记号，灰度图照旧）、`binarize` otsu（缺省）／sauvola／none（＝灰度）、`window`（可 auto 按页高放大）、`k`、`speck_area`（缺省按页高缩放去小斑）。写了 `ink` 的册 Step1 起读「墨层＋二值」页，`ink` 规范化取值进所有步的指纹（键 `ink`），`seal_detect`、`invert_detect` 读原样亮度；**没写的册行为与指纹逐位不变**（老开关 `binarized_input` 照旧）。缺省用 Otsu 不用 Sauvola 31/0.10：MJ 脉经第 1 册 8 页实测 Sauvola 放行 956→849、Otsu＋去小斑 932 且格数不变。`guji binarize` 对写了 `ink` 的册按墨层出二值副本，并顺带写体检 `binarized/<书>/<页>.qc.json`（`utils/binqc.py`：color_mark／bin_diff／speckle 区域与 halftone 页旗，原图左上原点坐标；不进指纹、不进 R2／中心库），给控制台决定哪些字块缺省看彩图。设计 `doc/design/彩图墨层与二值体检.md`。
- PATCH：`proof_cycle plan --allow-empty`、`auto_cycle` 零票判 go 的册自动带上（ZM 11-18：殿本 21–99 册旧单没人投，swap run 整批被 `cellvotes draft`「读到 0 票」守卫拦下）。交给 `guji cellvotes draft --allow-empty`（要 guji-manager ≥0.4.59、设 CELLREVIEW_TOKEN），当场读网站按单版和按条目都是 0 条才出空计划，守卫不关；plan.json 记 `empty_confirmed`。只动 scripts，不进指纹。
- PATCH：`scripts/zhengli/proof_cycle.py apply` 出单带 `--allow-empty`：落完票新单 0 格也换成空单、升 book-text，旧单不再挂在线上（殿本 vol08 008-r10）。`auto_cycle` 失败原因取最后一条 ✗ 行（以前取末尾 300 字，常抄成前面的提示）。只动 scripts，不进指纹。
- PATCH：字形库体检的清边不变式顺带核对派生归一图是不是现装 cv 算的（OCR 研究 Project，自检线 11-17 实遇）：`glyph_selfcheck.clean_invariant` 抽至多 400 例，把 `derived` 里存的归一图和现算的比，结果多 `derived_checked`、`derived_stale` 两个键；有不一致时 `guji glyph-db selfcheck` 打印一行，提示先 `guji glyph-db rebuild`。`glyph.db` 的派生是建库那一刻装着的 cv 算的，升级 cv 不会自动重算，拿旧归一图跑体检等于清边没修。只读库，不动任何 Step。
- PATCH：`scripts/zhengli/republish.py` 的 push、add-alt、add-cell、edit-cell、add-sprites 写回后**缺省就** `guji db sync` 并触发网站发布（原来要加 `--sync`，殿本 019-r10 忘了加漏发；ZM 11-17 框架建议 1）；只写本机加 `--no-sync`，旧的 `--sync` 照收。不碰 Step，指纹不变。
- 新书级参数 `row_segment.cut_glyph_line`（缺省 0＝关、不进参数哈希；史記 r79 ①类上下字交错，SJ 切分线 11-17）：`cut_white_row` 之后选中切线仍劈开单字大小连通块时，被劈的块按离哪边别的墨近整块归那边（一样近时按墨多的那边，少的一边 ≤35%），逐列取上格墨之下、下格墨之上离原线最近的 y（±这么多格内，不限坡度），kind `glyph_line`、`chosen_by="glyph"`；拿不准、块高过 1.15 格、某列上下墨重叠都不动。史記 32 册 103 页（与 v0.7.59 三开关同开）：改线 31 处，切坏线 105→77、新劈 0，抽 20 处看图全对。关时逐字节同，登 code_equiv `_GLYPH_LINE_1117`。建议值 0.35。
- PATCH：清边不再删贴在字身外缘的真笔画（忄／帝／常 的侧点、而／百 的顶横；OCR 研究 Project，Sheldon 11-17「残墨彻底修好」）：`clustering/normalize.py` 加 `STROKE_KEEP`，规则 3（padding 带碎屑）和 `_drop_stray_components` 要删的连通体，粗细 ≥0.7×本图块笔宽、面积 ≥2×笔宽²、长宽比 ≥2、离其余墨 ≤3 笔宽的留下。管线真实字块实测（按该格定字的字体模板量）：全唐文 009 抽 9407 格变 173、更像 9、更不像 0；史記 08 抽 5467 格变 45、更像 22、更不像 0；殿本 vol05＋vol40 抽 1.76 万格变 83、更像 11、更不像 7。`normalize` 在 `glyph_match` 的 `code_deps` 里，各书 5a 判过期（与 #1617 同一波）。原理见 guji-manager `doc/参考/字形图清边与归一.md`。

- 史記 r78 三个书级切点开关（A22 11-17，缺省都关、不进参数哈希，关时殿本 vol30、全唐文 020 逐字节同，登 code_equiv `_R78_1117`）：`row_segment.cut_gap_keep_glyph`（cut_gap_guard 换线不许劈新字、不许把上字一段跨 ≥0.35 格的墨划给下格；修 r77 代/黃、實、彬、為等 gap 换错的线）、`cut_white_row`（仍劈字时挪到 ±这么多格内最近的整行白，护字内白缝）、`straight_seam_ink`（直线候选 seam_ink 记真墨，只是记录）。史記 32 册 105 页：改选 16 处看图全对，格号 0 变化。

- `scripts/seg_pins_check.py` 加第 1c 节整列丢字预检（SJ r75 请求，A22 11-17）：①钉后格数要等于原列格数（旧切分有字格，没有就比旧钉子），不等要在钉子 `expected.count_why` 写理由；②列图上格外成段的墨（剥长直线、细高界行残段后每行墨 ≥4px、连续 ≥max(25px, 0.4 格高)、不在任一格里）算问题，版框线附近不算、印章压到的只提示。史記 r75 丢字 4 列两项都拦住；史記 6 册 188、殿本 14、全唐文 19 个钉子列 ② 无误报。只是预检脚本，不进任何 Step 的 `code_deps`，产物指纹不变。

- 新书级参数 `row_segment.cut_free_seam`（缺省 0＝关、不进参数哈希；史記 r77 切分清零，A22 11-17）：选中切线仍劈开单字大小连通块、且墨大半在上格时，在 ±这么多格内找零墨（或穿墨减半）折线改选，上字戈钩／长捺／竖尾整块归上字。史記 42 册 82 页与 cut_gap_guard 0.08 同开：实际切坏线 72→54、新劈 0、格号不变。关时殿本 vol30、全唐文 020、史記 42 逐字节同，登 code_equiv `_FREE_SEAM_1117`。建议值 0.35。

## [未发版]

- PATCH（CV3 2026-11-28，Sheldon 11-27 定形近字组方案）：形近字组登记表 `config/near_groups/v2.json` 类型只分 `variant`（异体，同义异码）与 `near`（形近异义）两类，原另记一类的 6 组（guan、hou、kgc、tsh、xz、zh）归 near，组内异体归并照旧在 `fold` 字段；旧版书级表的 `fold` 类型读成 near。每组加处理方式 `handling`（`methods` 允许的 3b 看图方法、`context` 文意、`aspect` 4d 宽高比、`action` admit／evidence、`threshold`），人定值在新输入文件 `config/near_groups/handling.json`，其余按现役行为的缺省规则生成；日曰（ry）、己已巳（jys）`methods: []`（不做字形区分，去掉 stroke_veto 对 jys）、context=true；aspect 日曰 true（按现役）、己已巳 false。读口 `near_registry.handling_of(组, over=书级覆盖)`（书配置优先、handling 缺省；methods 不许书级放宽）、`resolve(groups, book)`。3b `glyph_near` 守 `handling.methods`：书配置挂了以外的方法过渡期警告、跳过并计数（产物新字段 `PageNear.skipped_methods`，空的不落盘；`near_registry.STRICT_METHODS` 改 True 后载入即报错）。现役读口（NEVER_MATCH_FAMILIES、partners、_PARTNER、NEAR_FORM_CHARS、manager N01、glyph_near_spec、groups_of）取值逐项不变。**指纹变更：glyph_near 起过期**（glyph_near.py、near_registry.py 改了；登记表数据不进指纹，其余 Step 的 code_hash 不变）。

- PATCH（产物逐字节不变，code_equiv 登记；CV0 2026-11-28，脉经第 2 册缺文小注）：`reference_profile` 的 `kind: none` 段可写 `cols`（列级无参照，可与页段重叠）；align_ref 在这些列不出对位字、坐标对位与提示，产物写 `none_cols`；`page_token` 只在声明页加 `|nc:…`。manager 待审原因据此按格认「参照缺是设计」。
## [0.9.15] - 2026-11-28

PATCH（L0）＝v0.9.14＋#2018（reference_profile 列级无参照 cols；dev 条目见上文）。对 v0.9.14 全部 32 步 code_hash 全同；底库 b35 不变。

## [0.9.14] - 2026-11-28

PATCH（L0）＝v0.9.13＋#2008（收尾步 char_decide 兼容读口；dev 条目见上文）。对 v0.9.13 全部 32 步 code_hash 全同；底库 b35 不变；各书不过期。

## [0.9.13] - 2026-11-28

- 新表／读口（不进任何 Step 指纹，现役代码不改读，L0；CV3 W1 第一期 2026-11-28，Sheldon 定方向）：形近字组登记表 `config/near_groups/v2.json`（格式 `near_groups/2`），由 `scripts/build_near_groups_v2.py` 从六处来源确定性合成（注册字组表 185 组＋手工 20／人裁 42／字体 78／`near_groups.json` 572 对，去重后 619 组，类型 near／variant／fold，记 `src`；书级 pair_clf 与 3b 组用 `--pair-clf`／`--glyph-near` 出书级版本）；读口 `groups/near_registry.py`（按字查组、按类型过滤、转 3b 书配置、展开 `ref`，没写 `ref` 原样返回）。守卫 `tests/test_near_registry.py`。来源清单与第二期要改的读口见 `doc/3-识字/形近字组登记表.md`。
- PATCH（缺省关，产物逐字节不变，code_equiv 登记；CV0 2026-11-27，Sheldon「四维＋准确度分档」）：册配置 `references[]` 新键 `form`／`punct`／`script`／`accuracy`／`accuracy_evidence`（写错值就报，`form` 与 `line_is_column` 矛盾也报），`reference_profile` 段可写 `accuracy`（只许压低）；`seed_admit` 新开关 `trust_from_accuracy`：开时按本页参照的 accuracy 推信任档（very_high/high → `reference_trust`，mid → `ref_lib_coord`，只往上推），`script: trad|simp` 的页关照录异体、`edge_pair_to: ref` 退回 freq；本册摘要进 `ref_accuracy` 指纹。门槛与实测见 `doc/design/参校本四维与准确度分档.md`。
- PATCH（各书产物不过期，第四步逐字节不变；CV2 2026-11-27，Sheldon 定「折线只存拐点」，已通知 CV0/CV3/CV4/A30）：`products/kinds/cells.py` 折线落盘改游程——格的 `seam_top`／`seam_bottom`、切点候选的 `y` 在产物 JSON 里存 `{"n": 长度, "runs": [[x, y], …]}`（无损，只存变化点），载入时展开回逐 x 表，旧产物照读；直接读 JSON 的脚本用 `cells.seam_ys()`。史記 42 册 40 页 row_segment 产物 13.9MB→6.1MB。本模块不在 code_deps 里，指纹不变；新跑的 row_segment 字节会变，跨此改动做 `code_equiv check` 比 row_segment 要以本版为基线。
- PATCH（缺省关，产物逐字节不变，code_equiv 登记；CV2 2026-11-27）：cell_shrink 新开关 `end_dash_row`，列首／列尾格端区里成排的虚线短划整排抹白（`extractor.strip_dash_row`）。写本内框细线印成短划、整页拟不出内线的页，紧框不再横着拉宽去圈短划（cut-frame 史記 42:43:5「宗」、42:27:5「事」）。
- PATCH（11-27，CV0，参校本 bug）：`seed_admit.no_ref_params` 也叠在册配置 `reference_profile` 声明 `kind: none` 的页上（原先只认 `no_ref_pages`／`page_kinds.no_ref`），两种写法同一口径。现行各书没有同时配 no_ref_params 与 none 页的，产物不变，登 code_equiv。
- PATCH（指纹变更：seed_admit 起过期，`feedback.bindings` 在其 code_deps；CV0 2026-11-27）：绑定给无框旧人裁补锚时，字形库里同格号人裁实例的图只有在「裁决当时那版切分被换掉」之前写进库才当旁证（看切分步 manifest 历史）；之后才写进去的（回库、补放、重切刷新）是按原格号从新切分切的，与现格比等于自己比自己——史記 03 册 #17918／#17967 因此把 16／360 格旧人裁照原格号采信。另：manifest 查不到这一页时现行切分起始时间不再当 0（当作刚切）。`_VERSION` 9。code_equiv：殿本 vol28 13 页、全唐文 020 16 页逐字节相同；史記 02 25 页中 10 页不同（15 格 human→机器字，均为上述情形）。
- PATCH（L0：`glyph_analyzer` 缺省关、尚无册跑过）：`glyph_analyzer` 的 `code_deps` 补 `clustering.sim_cnn`（`match_algo` 用它解析 `sim_model` 拼证据里的算法名），过 manager 指纹覆盖守卫 `test_code_deps_coverage`（CV0 2026-11-27，GM3 报）。
- PATCH（`context_rank` 缺省关、尚无册跑过；指纹变更：context_rank 起过期，不随重跑；CV3 2026-11-28）：`context_rank` 抽出 `page_seq`、`neighbor_texts(match, dec)`（本页每格的左右文，读序和邻格取字规则与本步同一份），供 manager 给已发册的待审卡现算候选（`guji audit cands`）；`manager_api` 登记 `glyph_candidate_mod`、`context_rank_mod`、`ctx_fill_mod` 三个名字；本步产物不变。
- PATCH（新步骤缺省关，现役各步 code_hash 不变；指纹变更：context_rank（新步）起过期——缺省关、尚无册跑过，不随重跑；CV3 2026-11-27，候选字线）：4 定字加 `context_rank`（候选字线所说的 4b，按上下文排序）：给 3a 未判 same 的格，把候选池（收尾 `glyph_analyzer` 的 cands，缺则 3a 候选）按「图像分＋0.005·填空语义分」重排，记进产物 `context_rank`（每格 [字, 融合分, 图像分, 填空 logp]）。填空模型 SikuRoBERTa（钉 revision，不微调），前后文取本页读序左右各 24 字、邻格字用 `context_decide` 定字或其第一候选。**只排序、不放行、不改别的步骤的产物**，`context_decide`、`seed_admit` 都不读它。依据测试集 `char-candidates`（@cands）：甲层首位 56.3%（原序）→ 76.5%、前 3 82.4%→89.0%；乙层卡片前 3 命中 80.4%（旧按钮）→ 90.7%，难格 22.7%→78.7%；伤害率（原首位已对被换掉）3.3%，难格 10.9%；邻字错 20% 增益只掉约 2 点。书配置 `context_rank.enabled`（缺省 false）。评测脚本加 `--ctx-noise`。
- PATCH（新步骤缺省关，现役各步 code_hash 不变；指纹变更：glyph_candidate（新步）、glyph_analyzer 起过期——两者缺省关、尚无册跑过，不随重跑；CV3 2026-11-27，Sheldon 11-27 定「候选字线」由 CV3 做）：3 识字加 3c `glyph_candidate`（按图候选：字块图过 r5 向量网络，对全字表〔EmbPack 约 10.2 万字，含扩 B 以后〕取余弦前 50，**不用分类头与 RRF 融合**；再把图像前 5 名的异体族成员按自己的图像分插在前 10 之后）。书配置 `glyph_candidate.enabled`（缺省 false＝不跑）。收尾 `glyph_analyzer` 可选并入它的前 10 个，证据记 `evidence.c = {sim, fam_of?}`。依据测试集 `open-guji-dataset/char-candidates`（`guji eval run @cands`）：甲层难格首位 54.7%（3b 产线）→77.0%、前 10 87.8%→95.7%；扩 B 以后的字首位 1.5%→16.2%、前 30 80.1%→93.7%（异体族展开）。负结果：CSLS 去枢纽性校正全线更差。
- PATCH（新步骤缺省关，现役各步 code_hash 不变；CV3 2026-11-27，Sheldon 11-26 定的第三步重构第一块）：3 识字加 3b `glyph_near`（形近字组分析：书配置 `glyph_near.groups` 里登记的字组被 3a 触发时，按组登记的方法给组内各字新分＋证据，不定字）与收尾 `glyph_analyzer`（汇总成每格 `cands`〔字＋校准后 p＋各小步证据〕与 `p_map`，第三步不判放行）。第一个方法 `cnn_small`：殿本 宫／宮／官 小 CNN（ZM 训，按册号 % 5 取留出折，`models/glyph_near_gong`，已登记模型表、传 R2；calib.json 用 7447 格留出概率保序标定）。框架：`StepSpec.enabled_by`（参数为假就跳过的可选步骤）、骨架 `finals:`（大步收尾，必须是本大步最后一步，`Pipeline.final_of`）。殿本 vol02 49 格经步骤复核与训练留出概率最大差 0.0195、0.5 两侧一致 49/49。

## [0.9.12] - 2026-11-28

补发（PATCH，L0）＝v0.9.11＋#1993（朱楓林集 MBJ：藏书印、墨点判非字，骑线字合一格进右列；CV2）。三个开关缺省关，对 v0.9.11 各步 code_hash 全同（row_segment、cell_shrink、seed_admit、seed_admit_params、seed_admit_lanes 按本线 v0.9.11 哈希重登 code_equiv `_MBJ_MARKS_1128`）；底库不变；配 manager 同 0.9.11；没开开关的书不过期。

- `row_segment.straddle_merge`：界行断开处骑在线上的字合成一格放进右列，左列那格记空（格旗 straddle／straddle_into）；开了的册从 row_segment 起过期。
- `cell_shrink.ink_marks`（`char_w`＝本书中位字宽）：按原图墨打格旗 ink_seal／ink_speck；见骑线旗在原图上裁整字。
- `seed_admit.ink_marks`：印（旗或已 occluded）、墨点对位无字判非字放行；对位有字或贴字的墨点送审。

## [0.9.11] - 2026-11-28

补发（PATCH，L0）＝v0.9.10＋册号位数统一五件（#1970 #1976 #1977 #1980 #1987），给改名迁移中的各书（脉经、朱楓林集、北行、幼學、殿本）正式钉。对 v0.9.10 各步 code_hash 全同（row_segment 登 code_equiv `_LAYOUT_ALIAS_1128`）；底库不变；配 manager ≥0.7.0（`ops.rename_volume`／`ops.renumber`），待审路径按数值认要 ≥0.7.1；没写 `aliases` 的册行为逐位不变。

- 事件读口（#1970）：`core/volume_id` 按全书册数定位数；`core/volume_alias` 按册 yaml `aliases` 读事件时把旧册名换新名，旧记录不改写。
- 实例 id 不换（#1976）：`v1:`／`v2:` 前缀键与 `payload.instance_id` 保持原样，glyph_audit 撤库事件对得上库。
- `status` 认改名过期（#1977）：`<产物根>/<册>/_renamed.json` 对照表把上游 sha 换回改写前，指纹对得上就算新鲜，记 `rename_only`；`run` 照旧。
- 格位表／备选格表认旧册名（#1980）：`row_segment.load_layout` 表行 `vol` 是本册 `aliases` 里的旧名也归本册（脉经第 1 册继续用原 alt_cells 表）。
- 新命令 `guji-cv rename-seal <册> [--keys …]`（#1987）：改名后封存只因改名改写了来源文件而变的参数指纹（如 `exclusions_fingerprint`），`status` 的 rename_only 据此认作改名；封存后再变照常过期。

## [0.9.10] - 2026-11-27

补发（PATCH，L0）＝v0.9.9＋#1961（汉书 WYG #18261，vline_track 淡线兜底封上界；dev 条目见上文）。对 v0.9.9 各步 code_hash 全同（border 登 code_equiv `_TRK_CLIP_1127`，dev 与本线同一条）；底库 b35 不变；各书不过期。

## [0.9.9] - 2026-11-27

补发（PATCH，L0）＝v0.9.8＋#1922（cherry-pick cc426f1，四周單邊版框，MBJ 要用；dev 上 #1922 条目见上文）。对 v0.9.8 各步 code_hash 全同（border、seg.lines 按本线哈希登 code_equiv `_SINGLE_SIDES_1127`）；底库 b35 不变；不需 manager 配套。
`frame_layers` 在 border_detect 的 book_deps 里：写了左右=1 的册从 border_detect 起过期，没写的不变。

## [0.9.8] - 2026-11-27

补发（PATCH，L0）＝v0.9.7＋#1956（cherry-pick b42592c，朱楓林集 MBJ 要用；dev 上 #1956 条目见上文）。对 v0.9.7 各步 code_hash 全同（seed_admit 三模块按本线哈希登 code_equiv `_SEG_BOX_1127`）；底库 b35 不变；不需 manager 配套。
重跑起点：册 yaml 写了 `chars_per_line_pages` 的从 border_detect 起过期；`seed_admit.seg_box_check` 开了的从 seed_admit 起过期；都没写的册不过期。

## [0.9.7] - 2026-11-27

从 dev 切（脉经 01 按用户 11-27 定用最新改动重跑）：v0.9.6 之外带上 dev 已合的 #1899、#1900（2b side_cut 缺省开）、#1911、#1914、#1918（boundary_net、layout_off_tol 缺省关）、#1919、#1920（solo_5b_scope）、#1921、#1923、#1930、#1932、#1933。
指纹变更：对 v0.9.6，column_band、cut_gate（#1900 side_cut 缺省开）、seed_admit 起过期；不要的书写 params.column_band.side_cut: false 可免 column_band 过期。底库 b35 不变。

- PATCH（产物逐字节不变，code_equiv 登记，L0；CV0 2026-11-26，GM2 分工）：页绑定盘上缓存（`cache/<册>/bindings`）键加算法哈希 `algo`（`bindings.py`、`anchor.py`、`anchor_backfill.py` 三文件 sha256 前 16 位）：换了这三处代码的 cv，旧绑定缓存不再命中、现算。防同一工作区换 cv 版本后沿用旧版算的绑定。
- PATCH（产物逐字节不变，code_equiv 登记，L0；CV0 2026-11-26，GM4 方案第九节定 A）：删钉垫片 `pin_removed`：`feedback.bindings.removed_pin_events` 读 `<feedback>/pins/*.state.jsonl`（manager 钉状态流 `pin_state`，每个 `pin_id` 后到覆盖先到），最后为 `removed` 的钉，其 `payload.events` 列的答案事件不进 `human_chars`、不进绑定表（`expired`／`reactivated` 不删）。没有钉状态文件时行为不变。钉状态是数据、不进指纹：写了 removed 要从 `seed_admit` 起 force 重放。cv 改读编好的钉表后去掉。

## [0.9.6] - 2026-11-26

补发（PATCH，L0）＝v0.9.5＋#1924（钉子护栏，CV0 11-26 批；dev 上已有 MINOR 改动，故走补发线）。指纹不变（code_equiv 登记）。配 manager ≥ v0.6.35（写钉子时记几何底 geom）。

- PATCH（产物逐字节不变，code_equiv 登记，L0；CV1 2026-11-26）：`row_segment` 套整列钉子（manual-cells）前比钉子写入时记的列图几何底（manager v0.6.35 `column_basis.geom`）：一致照套；不一致经旧／新 `ColumnMapper` 把格框经原图换到新列图，角点最大位移 >3px 的列打 `manual_cells_remapped`，出口闸（row_segment_gate）记旗「待人核」。没记 geom 的老钉子照原坐标套、只在日志提示。开关登记表 outer_bar 记「直线页可能被记成三段，人钉切格的书慎开」。缘由：全唐文 031–060 outer_bar 让列图挪 10–32px，钉子照旧坐标套切偏。

## [0.9.5] - 2026-11-26

补发（PATCH，用户 11-26 定「发 patch 随时用」）＝v0.9.4＋#1899（字块按页取回接口，配 manager ≥ 含 #1013 的版本）。产物与各步 code_hash 逐位不变，各书不过期。

- PATCH（11-25，CV0「字块随包存 R2」第一步，产物与 23 步 code_hash 逐位不变，L0）：`RunContext.chain_fingerprint(步, 页)`＝该步及全部上游这一页 manifest 指纹的合哈希（跨机共享派生图的键）；`RunContext.materialize` 缓存不在时先问 `core.derived.PAGE_FETCHER`（只管 `char_patch`，由 manager 注册；产出它的那一步自己在跑时不问；同页只问一次；`GUJI_PATCH_FETCH=0` 关），取不到照旧现算；`ImageCache.put_bytes` 放取回的已编码图。`core/step.py`、`core/derived.py`、`products/cache.py` 不在任何 code_deps。

## [0.7.115] - 2026-11-27

史記线 PATCH（SJ 请，GUJI-777）＝v0.7.112＋dev #1953 移植：seed_admit 书级 `symbol_ref_blank_from`（圈号 ○ 被误判成 口囗□日四、整理本此位空、库前三含 ○ 且 cov 与首位差 ≤ 0.03 时放行为 ○；缺省空＝关，关时不进参数 dump）。**不含** v0.7.113／v0.7.114 的 #1921、#1923、boundary_net（那两版的整书重算已取消，本版直接接 v0.7.112）。
指纹变更：只 seed_admit 代码变，钉 v0.7.112／v0.7.103 的册改钉本版后从 seed_admit 起过期；SJ 只对 17/40/41 册相关页做页级 seed_admit 回放，不整册重跑。本线 2 条老红（test_default_group_flow_has_no_codepoint_groups、test_p_ref_coord_takes_coord_ref_only_when_no_text_label）v0.7.112 上同样红，非本版。

## [0.7.114] - 2026-11-26

史記线 PATCH＝v0.7.113＋#1918 移植（boundary_net、layout_off_tol）。dev 已有，本节只记账。

## [0.7.113] - 2026-11-26

史記线 PATCH＝v0.7.112＋#1921＋#1923 移植（codepoint_no_exempt）。dev 已有这两项，本节只记账。

## [0.9.4] - 2026-11-26

W1 补发（PATCH，用户 11-26 定）＝v0.9.3＋三件：
- #1903 `border._fit_head_raise` 死循环修复（head_raise_fit；值真变才再来一轮＋迭代上限），code_equiv 登记，产物不变。
- #1896 殿本列末第三道线再收紧（vol04 207:6、vol05 149:6 回成「二」），`FRAME_LAYER_REV=2`：只有殿本（frame_layers 下端 2）从 column_end 起过期。
- #1902 `core/parallel.py` row_segment 并行登记峰值 1.0→4.0 GB（全唐文 001 执行机 OOM），不进指纹。

指纹：只有殿本从 column_end 起过期，其余书不变。底库 b35。

## [0.9.3] - 2026-11-25

W1 补发（殿本）：v0.9.2 ＋ #1891 列端剥层第二版（下端第三道线只认边距证据，末字下横不再被当框剥掉；含 b0f76ea `column.py` 登 code_equiv）。**只有殿本（册配 frame_layers 下端 2）经 column_end 指纹里的 frame_layer_rev 从 column_end 起过期，其余书指纹与产物不变**（check_fp_change 对 v0.9.2：0 步变），钉 0.9.2 的书不用改钉。未修好：vol04 207:6、vol05 149:6 两格（已交 CV1）；vol17 14:9 空列底多留 1px 细线（可忽略）。全量测试 4386 过，1 条 dev 老红（test_seg_move）。底库仍 b35。

## [0.9.2] - 2026-11-25

**CV 里程碑 W1**（Sheldon 11-25 定：发 PATCH＋新底库 **b35**；计划 ai-team `domain/CV/里程碑/W1-计划.md`）。收 v0.9.0 之后 dev 上 CV1–CV4 的全部改动（含 v0.9.1 移植的 ruling_by_u）：切字五小步 #1869／#1872／#1881（原标 MINOR，用户定按 PATCH 发）、版面开关改缺省开 #1892、seed_admit 缺省与书级放行通道 #1889／#1867、裁定键三方案与 ruling_by_u、冷缓存护栏 #1864 等，条目见本节与文件开头散列的未发版条目。**指纹变更：border_detect 起过期（W1 各书统一重跑；版面开关缺省开＋切字五小步拆步）**。配套 guji-manager v0.6.22（读五小步产物 #1001、seg_pin 拼回列窗口 #1007）。测试：全量 4371 过，唯一失败 `test_seg_move::test_split_parts_listed_together_in_every_step` 在 dev 上本就挂；护栏 `guji eval guard` 归各书 W1 验收时跑（本机无各书 glyph.db，记未验证）。底库：`check_base_corpus` 过（b35，65 文件）。

- PATCH（seed_admit 指纹变：groups/flow.py；现行三书 main 包输出不变）：字组复核 `review_fix_agree`（一二 yr）加例外——整理本（或坐标对位字）＝已放行字时，两路图像解法给了别的字也不改字、照常降审。起因殿本 replay-1125 二→一 37 格：框型配置改了冷缓存再生的列图、旧格坐标裁偏，ids 与 yr_bars 同错。殿本 99 册、史記 42 册、全唐文 28 册 main 包里该规则改字 0 格。CV4。
- PATCH（新开关缺省关，产物不变；border_detect／impl.keben.border 指纹经 code_equiv 登记不变，CV1 11-25）：`border_detect.vline_track` 竖线逐条先直线、贴不住再自由折点三段折线（`impl/keben/border.refit_vlines_by_track`），不看页级 w80 门槛与书级 `vline_polyline`。79 页版面基准 >5px 线 88→19，与 `outer_bar` 合开 88→16、>20px 9→1。
- PATCH（新开关缺省关，产物不变；border_detect／impl.keben.border 指纹经 code_equiv 登记不变，CV1 11-24）：`border_detect.outer_bar` 左右外框线先找粗外框条、再找内框细线（`impl/keben/border.refit_outer_by_bar`）。79 页版面基准 p95 合计 985→873、>20px 线 9→5。
- PATCH（产物逐字节不变，code_equiv 登记）：写裁定前校验（GM4／CV4 11-24，裁定键长期方案①）。`rulings.validate`（＝`validate_payload`）查版本 seed_admit 认不认：group=O 认 vis-o1／src-1／ctx-m1／src-2，其他字组认本组 `prompt.md` 的 `ver`，任何组认看图 L4 `vis1:<哈希>`，再加 `ver_equiv.yaml` 登记的版本；`#模型` 后缀去掉再比。`RulingLog.append` 对 `ctx_ruling` 事件调用，不认就整批拒写（`BadRequest`）；vis-o1／src-1 写了 admit_ok 却不是收的子类只提醒。管线自己写缓存（`RulingStore.put`／`put_cell_code`）不校验。看图判子类表挪到 `rulings.VIS_RULING_SPECS`，seed_admit 引用同一份。三书现有 59,255 条裁定试跑只拦 460 条本来就查不到的（串组版本、ctx-wenyi-1）。
- PATCH（库里没有带 cells_sha 的裁定时产物逐字节不变，code_equiv 登记）：裁定格锚点后备键（GM4／CV4 11-24，裁定键长期方案③）。窗口键（含版本等价）都没中时，`RulingStore.get_anchor` 按「格号＋写裁定时本页 `cells_sha`（`rulings.page_cells_sha`＝`bindings.page_state` 两份 sha 用 + 连）＋整理本对位字 `ref`」三样全对取裁定，另要求裁定字在库候选或＝ref、裁定当时的窗口与现窗口编辑距离 ≤3（`window_diff` 记进证据），其余护栏照旧；`_vis_ruling_pass` 与 fold 遍用它，证据记 `ruling_key=anchor`。只认 payload 自带 `cells_sha` 的裁定（新裁定写入方当场写，存量由 manager 回填、只回填能证明是写裁定那一刻产物的）；库里一条都没有时不算 cells_sha。
- PATCH（脚本，不进指纹）：`scripts/zhengli/auto_cycle.py` 判 fresh 也认 manager 收尾落定记录 `reports/<册>/_land/landed.json`（`{digest, pack}`，pack＝现 ★main 即不用重出）。待审没变时收尾不换 rev、不出 `rev-<rev>` 包，原判法会永远判过期（GM4 换包按条目对账）。

- PATCH（新入口，不进任何 Step 指纹）：`feedback/pending_cells`——产物→待审格的纯函数（格号、图块指纹 fp、按内容寻址的单格字块图、digest），给 guji-manager `guji pipeline` 收尾对账待审条目用（GM4 换包按条目对账，sheldon 11-23 定 cv 只出产物）；只读产物与字块图缓存，不碰中心库／R2／网站／book-text，不要 rev。`manager_api` 登记 `pending_cells`、`machine_pending`；`scripts/zhengli/pending_list.py` 的取格口径改调它（输出不变）。

- PATCH（缺省无表时产物逐字节不变，code_equiv 登记）：裁定版本等价登记表（GM4／CV4 11-24，裁定键长期方案②）。数据目录 `<feedback>/rulings/ver_equiv.yaml`（随中心库同步，缺文件＝空表）登记「旧提示词版本→新版本」，可开 `model_suffix`（只差 `#模型` 后缀即等价，各后缀须同字、conf 取最低）。`RulingStore.get_equiv` 精确键没中再按表查；`_vis_ruling_pass` 放行与 fold 遍用它，护栏照旧，白名单按目标版本判；非精确命中的 `evidence.vis_ruling`／`evidence.fold` 多带 `ruling_key=ver_equiv`、`ruling_ver`。在线问前查缓存仍按精确键（二审小组按「版本#模型:effort」分键）。
- PATCH（语料表，Step 代码指纹不变）：异体人工表补 鿄→梁，字对关系表记 梁鿄 为 V（GM3 全唐文金标，CV4）。

- PATCH（语料表，Step 代码指纹不变；底库语料变，下次出底库时进）：异体人工表补 䕶→護、蹖→踳；字对关系表 `variants.pairkind.tsv` 记 䕶護、蹖踳 为 V，巿市 为 C（形近不同义）。起因 GM3 复核全唐文异体闸 18 格（CV4）。

- PATCH（只改分组，步骤 id、产物、指纹都不变）：单列拉直（`column_warp`／`column_crop`／`column_trace`、`line_ocr`，骨架槽位 `columns`）从大步 1 版面移到 2 切字（Sheldon 2026-11-22 定：1 版面只认位置、判类型；射影、缩放、字与框线分离整个归切字）。`--from cut` 现在从拉直起跑；小步编号改为 2a 单列拉直、2b 逐字切分、2c 字框收缩，doc／Wiki 同步。

## [0.7.112] - 2026-11-25

史記 patch 线：v0.7.107 ＋ `scripts/zhengli/proof_cycle.py`、`scripts/zhengli/zl.py` 的 char 导出也改走 guji-manager 导出器（v0.7.107 只改了 republish；auto_cycle／proof_cycle 出的导出不带 u，book-text local_check 报「旧版已有 u，新版把 u 全丢了」，`guji swap book-text` 用同一份导出推标点也报 u 对不上——殿本 vol04，11-25）。只改脚本，23 步指纹与 v0.7.107 全同，钉旧版的册不用改钉。要 guji-manager ≥ 0.6.21。（CV0 u T1）

## [0.7.111] - 2026-11-25

全唐文 patch 线：v0.7.109 ＋ `scripts/zhengli/proof_cycle.py`、`scripts/zhengli/zl.py` 的 char 导出也改走 guji-manager 导出器（v0.7.109 只改了 republish；auto_cycle／proof_cycle 出的导出不带 u，book-text local_check 报「旧版已有 u，新版把 u 全丢了」，`guji swap book-text` 用同一份导出推标点也报 u 对不上——殿本 vol04，11-25）。只改脚本，23 步指纹与 v0.7.109 全同，钉旧版的册不用改钉。要 guji-manager ≥ 0.6.21。（CV0 u T1）

## [0.7.110] - 2026-11-25

殿本 patch 线：v0.7.108 ＋ `scripts/zhengli/proof_cycle.py`、`scripts/zhengli/zl.py` 的 char 导出也改走 guji-manager 导出器（v0.7.108 只改了 republish；auto_cycle／proof_cycle 出的导出不带 u，book-text local_check 报「旧版已有 u，新版把 u 全丢了」，`guji swap book-text` 用同一份导出推标点也报 u 对不上——殿本 vol04，11-25）。只改脚本，23 步指纹与 v0.7.108 全同，钉旧版的册不用改钉。要 guji-manager ≥ 0.6.21。（CV0 u T1）

## [0.7.109] - 2026-11-25

全唐文 patch 线：v0.7.104 ＋ 只改 `scripts/zhengli/republish.py`（同史記线 v0.7.107；不进任何 Step 的 code_hash，23 步指纹与 v0.7.104 全同，不用登 code_equiv，册 yaml 钉 v0.7.104 的不用改钉）。① 出单导出改走 guji-manager 的 `guji_manager.output.guji_format_export`（同 dev），册有字格身份账时 char 每格带 `u`（v0.6），推 book-text 时 local_check 不再报标点／专名 u 对不上；没装 manager 才退回本线 `scripts/export_guji_format.py`。要 guji-manager ≥ 0.6.20。② 移植 dev 067f2229：出单后 `db sync` 缺省不推字形库（GUJI_DB_NO_GLYPH）。（CV0 u T1，11-25）

## [0.7.108] - 2026-11-25

殿本 patch 线：v0.7.106 ＋ 只改 `scripts/zhengli/republish.py`（同史記线 v0.7.107；不进任何 Step 的 code_hash，23 步指纹与 v0.7.106 全同，不用登 code_equiv，册 yaml 钉 v0.7.106 的不用改钉）。① 出单导出改走 guji-manager 的 `guji_manager.output.guji_format_export`（同 dev），册有字格身份账时 char 每格带 `u`（v0.6），推 book-text 时 local_check 不再报标点／专名 u 对不上；没装 manager 才退回本线 `scripts/export_guji_format.py`。要 guji-manager ≥ 0.6.20。② 移植 dev 067f2229：出单后 `db sync` 缺省不推字形库（GUJI_DB_NO_GLYPH）。（CV0 u T1，11-25）

## [0.7.107] - 2026-11-25

史記 patch 线：v0.7.103 ＋ 只改 `scripts/zhengli/republish.py`（不进任何 Step 的 code_hash，23 步指纹与 v0.7.103 全同，不用登 code_equiv）。① 出单导出改走 guji-manager 的 `guji_manager.output.guji_format_export`（同 dev），册有字格身份账时 char 每格带 `u`（v0.6），推 book-text 时 local_check 不再报标点／专名 u 对不上；没装 manager 才退回本线 `scripts/export_guji_format.py`。要 guji-manager ≥ 0.6.20（导出器配老 cv 不崩、带 u 的 char 保持 v0.6）。② 移植 dev 067f2229：出单后 `db sync` 缺省不推字形库（GUJI_DB_NO_GLYPH）。史記 012 实跑：012-r1 1 格 → 012-r2 3 格，book-text 0.1.1→0.1.2。（CV0 u T1，11-25）

## [0.7.106] - 2026-11-25

殿本 patch 线：v0.7.105 ＋ dev #1868（CV1，border_detect 书级开关 `head_raise_fit`：抬头列认下后校内框高度、量上外框跳过抬头列；缺省关、关时不进参数 dump）。只带 border_detect／impl.keben.border 的改动，eval/ 与文档不带。**对 v0.7.105 实测（check_fp_change）23 步指纹全不变**：本线哈希已登 code_equiv（vol28 12 页 border_detect＋gate 逐字节同）。不开 `head_raise_fit` 的册不过期；开了的册按参数指纹从 border_detect 起过期。（CV0，ZM 11-25 定）

## [0.9.1] - 2026-11-25

0.9 patch 线（跟 v0.9.0 的书：脈經、北行）：v0.9.0 ＋ 移植 dev #1848＋#1856（书级开关 `seed_admit.ruling_by_u`：窗口键没中时按字格永久编号 u 查裁定，读身份账 `<feedback>/uid/<册>.jsonl`，只收 high、前后 2 字至少一侧相同、裁定字在库候选或＝整理本字；字组在线问前查缓存也按 u 后备，版本须完全相同）。缺省关、关时不进参数 dump。做法同 v0.7.103／v0.7.104：本线无格锚点接入，seed_admit 只加 u 档；`feedback/rulings.py` 取 v0.7.102 全文，`RulingLog.append` 写前校验缺省不开。**不含** v0.9.0 之后 dev 的其他改动（dev 上未登记的 seed_admit 指纹变更与底库 b35 都不带）。对 v0.9.0 实测（check_fp_change）23 步只有 seed_admit 变：指纹变更：seed_admit 起过期（开 ruling_by_u 的书从 seed_admit 重放）。底库不变。（CV0，u 项目 T3；Sheldon 11-25「彻底收尾」）

## [0.7.105] - 2026-11-25

殿本 patch 线：v0.7.102 ＋ dev #1864（冷缓存再生列图护栏：column_warp.render 再生尺寸≠产物 warped_size 报错、cell_shrink 内框线记忆带产物戳、core/step 册配置漂移拒绝现算；只动 render 路径，按本线哈希登记 code_equiv）＋ dev #1863（group_flow：一二复核整理本＝放行字时不按两路图像改字）。含 #1848＋#1856（ruling_by_u，v0.7.102 已带）；#1813／#1820／#1838 在 v0.7.97–0.7.99 已有，#1862 已关（#1864 的子集）。**对 v0.7.99 实测（check_fp_change）23 步只有 seed_admit 指纹变**：border_detect 到 read 不变，指纹变更：seed_admit 起过期（殿本开 ruling_by_u 后统一重跑）。`ruling_anchor_loose` 参数名与去键规则同 v0.7.99，已开它的册参数 dump 不变。（CV0，ZM／CV1 11-25 定）

## [0.7.104] - 2026-11-25

全唐文 patch 线：v0.7.101 ＋ 移植 dev #1848＋#1856（书级开关 `seed_admit.ruling_by_u`：窗口键没中时按字格永久编号 u 查裁定，读身份账 `<feedback>/uid/<册>.jsonl`，只收 high、前后 2 字至少一侧相同、裁定字在库候选或＝整理本字；字组在线问前查缓存也按 u 后备，版本须完全相同）。缺省关、关时不进参数 dump。本线没有格锚点／版本等价接入（seed_admit 只加 u 档）；`feedback/rulings.py` 取殿本线 v0.7.102 全文，`RulingLog.append` 写前校验在本线缺省不开。**23 步 code_hash 只有 seed_admit 变**，未登记 code_equiv：u 项目 11-25 起各书开 `ruling_by_u`，seed_admit 起重放。底库不变。（CV0，u 项目 T3；Sheldon 11-25「尽快完成转换」）

## [0.7.103] - 2026-11-25

史記 patch 线：v0.7.98 ＋ 移植 dev #1848＋#1856（书级开关 `seed_admit.ruling_by_u`：窗口键没中时按字格永久编号 u 查裁定，读身份账 `<feedback>/uid/<册>.jsonl`，只收 high、前后 2 字至少一侧相同、裁定字在库候选或＝整理本字；字组在线问前查缓存也按 u 后备，版本须完全相同）。缺省关、关时不进参数 dump。本线没有格锚点／版本等价接入（seed_admit 只加 u 档）；`feedback/rulings.py` 取殿本线 v0.7.102 全文，`RulingLog.append` 写前校验在本线缺省不开。**23 步 code_hash 只有 seed_admit 变**，未登记 code_equiv：u 项目 11-25 起各书开 `ruling_by_u`，seed_admit 起重放。底库不变。（CV0，u 项目 T3；Sheldon 11-25「尽快完成转换」）

## [0.7.102] - 2026-11-25

殿本 patch 线：v0.7.99 ＋ dev #1848（书级开关 `seed_admit.ruling_by_u`：窗口键、锚点都没中时按字格永久编号 u 查裁定，读身份账 `<feedback>/uid/<册>.jsonl`，护栏同宽松档；缺省关、关时不进参数 dump）＋ dev #1856（字组在线问前查缓存也按 u 后备，版本须完全相同）。本线没有 `seed_admit_params.py`，开关写在 `steps/seed_admit.py`。**23 步 code_hash 只有 seed_admit 变**，未登记 code_equiv：u 项目 11-25 起各书开 `ruling_by_u`，参数 dump 本来就变，seed_admit 起重放。（CV0，u 项目 T3；Sheldon 11-25「尽快完成转换」）

## [0.7.101] - 2026-11-25

全唐文 patch 线：v0.7.100 ＋ #1852（pair_clf 核对 sim_model），内容已在 dev，本条仅记发版（CV0）。23 步 code_hash 不变；全唐文（开 stages）glyph_match 起过期。换 glyph_sim_qtw_v2 要等 pair_clf 在 v2 嵌入上重训后一起换。

## [0.7.100] - 2026-11-25

全唐文 patch 线：v0.7.93 ＋ #1849（模型表 `glyph_sim_qtw_v2`），内容已在 dev，本条仅记发版（CV0）。23 步 code_hash 与 v0.7.93 全同；全唐文书配置改 `sim_model.path: models/glyph_sim_qtw_v2/model.pt` 后 glyph_match 起过期。

## [0.7.99] - 2026-11-24

殿本 patch 线：v0.7.97 ＋ 裁定键三件＋#1838，内容已在 dev，本条仅记发版（ZM）。

## [0.7.97] - 2026-11-24

殿本 patch 线：v0.7.95 ＋ #1813 ＋ #1820（框型规则、inner_pull），内容已在 dev，本条仅记发版（ZM）。

## [0.7.96] - 2026-11-24

史記 patch 线：v0.7.88 ＋ 5a 相似度模型（供史記切 `glyph_sim_shiji`，Sheldon 11-23 定直接切）。本线基于 v0.7.62，原本没有 `sim_model` 代码，光加模型表行用不上，所以一并移植：
- dev #1394／#1466：`glyph_match.sim_model` 开关（缺省关）与 `clustering/sim_cnn.py`（照 v0.7.90／dev 原样，含 calib.json 与 `fuse: mean`）。glyph_match 代码哈希登 code_equiv（与 dev 同一条，本线旧哈希规范值也是 fe823292），**23 步 code_hash 与 v0.7.88 全同**；不开 `sim_model` 的册产物不变。
- 模型表：#1823 `glyph_sim_shiji` 两行，并补 `glyph_sim_base_v1` 两行（#1631）与 `glyph_sim`（全唐文）两行，`model_pack.KINDS` 与 provenance 同步。
- **不含** #1771（never_group 8 对）与新底库 b34：底库升版要用户点头，本版底库仍 b31。
- 用法：史記册 yaml `params: {glyph_match: {sim_model: {path: models/glyph_sim_shiji/model.pt, fuse: mean}}}`，开了的册 glyph_match 起过期。

## [0.7.95] - 2026-11-23

殿本 patch 线：v0.7.94 ＋ dev #1814（seed_admit 书级开关 `ref_lib_5b_veto`／`ref_lib_5b_veto_lead`，缺省关）。「整理本＝库首位」放行（`ref_lib`）的格，5-b 首位是别的汉字、分 ≥ 门槛、领先 ≥ 门槛（缺省 0.02）→ 退回人审（doubt `ref_lib_5b_veto`），只降级。供殿本带它重跑 5a A/B（CV3 11-23）。本线 seed_admit 还没拆出 `seed_admit_params`，按本线结构手工移植（去键照 `_drop_off_rare` 原写法）。**开关关着时产物不变**：seed_admit 代码哈希 d2026a75→340e78ad 已登 code_equiv，其余各步 code_hash 与 v0.7.94 相同，底库 b29 不变。

## [0.7.94] - 2026-11-23

- 发版说明（殿本 patch 线，ZM 11-23，PATCH）：v0.7.90 ＋ 模型表补回 `glyph_sim_base_v1`（model_pack KINDS、model-registry 两行、provenance，照 v0.7.89），供殿本 5a 新相似度 A/B 的 C 臂从 R2 取模型。各步 code_hash 与 v0.7.90 相同，底库 b29。

## [0.9.0] - 2026-11-23

- **MINOR**（Sheldon 11-22 定，11-23 说「可以发新版」）：九步并成四大步、cv 自己的入口 `guji-cv`、原 Step8／Step9 移到 guji-manager。23 步 `code_hash` 与 v0.8.0 相同，各书产物不过期。影响见 RELEASES.md v0.9.0。
- 九步并成四大步（用户 11-22 定）：1 版面 `layout`（原 Step0–2）、2 切字 `cut`（Step3–4）、3 识字 `read`（Step5）、4 定字 `decide`（Step6–7）；Step8 入库、Step9 排版输出移到 guji-manager。骨架 `_skeleton.yaml` 加 `stages:`，`Pipeline.stages`／`stage_of`，`guji-cv pipeline --from/--to` 可写大步名。删 `guji fp-migrate`（连 `products/fp_migrate.py`）、`guji import-pdf`（manager `source commons` 已收 PDF）。cv 自己的命令行入口 `guji-cv`（＝`python -m open_guji_cv`）只有 cv 的命令、不并 manager 的，大步工具可带前缀（`guji-cv layout preclean`、`guji-cv read rare`、`guji-cv decide variants`）；`guji` 留作 manager 的总入口。doc 按四大步重整（`doc/README.md` 入口，各大步 `步骤与产物.md` 由 `scripts/gen_stage_docs.py` 生成），Wiki 按四大步重排。23 步 `code_hash` 不变。
- 原 Step9 排版输出的代码整个搬进 guji-manager `guji_manager/output/`（用户 11-22 定，manager #791）：删 `report/` 的 collate、collation_grade、same_char、absent、tiers、strips（留 `slots.py`、`witness.py`），删脚本 render_guji_markdown、export_guji_format、export_guji_page、convert_pages_to_char_cord、reflow_md、export_wikisource、build_collation_report 及 7 个测试，删 `guji export`（登记进 `MOVED_TO_MANAGER`，现为 `guji output export md|format|wikisource|reflow`；对勘报告 `guji output collation-report`）；`manager_api` 删 13 个只给这些模块用的名字。`scripts/zhengli/` 的 zl、republish、proof_cycle 改跑 `python -m guji_manager.output.guji_format_export`，collect_exit／ledger 写 `guji output export format`，upload_wikisource 从 manager 取 `BOOKS`。23 步 `code_hash` 不变。

## [0.8.0] - 2026-11-21

- **MINOR**（Sheldon 11-21 定升 0.8）：v0.7.0 以来的累积（书级开关与钩子、5a/5b 形近字对与库字档、字组与 never_group 登记、切分与出单门修复、网站票读中心库 D1 等）；本版起新任务用 v0.8。各档 PATCH 明细见下面 [0.7.x] 各节，影响见 RELEASES.md v0.8.0。

## [0.7.93] - 2026-11-21

- 发版说明（全唐文 patch 线，形近字线 11-21，PATCH）：v0.7.92 ＋ #1778（seed_admit 书级 `group_flow_hou_shape_late`，5c vis_ruling 后补跑 hou_shape，缺省关）；dev 已含 #1778。

## [0.7.92] - 2026-11-21

- 发版说明（dev 线，A31 11-21，PATCH；全唐文切分线用）：dev eb000256（含 #1771／#1774 never_group 新登记 15 对、#1775 印框格记空）。Step 指纹对 v0.7.89（全唐文 patch 线）只 seed_admit 变（实算 23 步）。**配底库 b32**（＝b31 的 never_group.json、variants.tsv 换 dev 版，新增 config/groups/wu/rules.yaml），钉老底库的册要 `guji corpus pin` 改钉。
- PATCH：seed_admit 加书级 `occluded_manual_seal_blank`／`occluded_seal_align_yield`／`occluded_seal_keep_cov`（缺省关、关时不进参数 dump；#1775，QTW 切分线 11-21）：人定印框（`seal_detect.overrides`）压着、没有坐标对位字的遮挡格记 coord_blank 由 R5 判非字；past_leaf／行为空判整列时不算印纹上硬配的现役对位字；库判 same 或 unsure 首位 ≥ 0.93 的格不判空（印压真字）。全唐文 046–060 清单 47 格全判空（含 8 格印纹被放成 一／二／和），057 p90 待审 5→1。登记 code_equiv（057 12 页逐字节同）。
- PATCH：`seed_admit` 5c `_vis_ruling_pass` 给本遍窗口里的待审格记 `evidence.vis_ctx`（`left`／`right`／`ref`，即终审裁定键的窗口与整理本对位字）。产物是整遍跑完的状态，后面 consensus_lib 等遍放行、stroke_veto 等遍降审的邻格让从产物重算的窗口与 5c 不同，裁定键对不上（A33 11-20，全唐文 001–030 26 格 6 格失效，例 027:59:4:7）；manager 写键、`rulings-hits` 补键直接用这个（guji-manager #761，旧产物 manager 按 5c 时状态推断）。放行判定不变，只多一个 evidence 键。**`seed_admit.py` 改了，第 7 步代码哈希变、各书 seed_admit 起产物判过期**（产物多了键，不能登 code_equiv）。
- 册 yaml 新字段 `gaps:` 记缺页（Sheldon 11-18 定：只按图片页号记，不另立书上页号）：每条 `after_page`／`what`／`kind`（原书缺／未拍）／`est_chars`／`evidence`，`load_gaps` 校验，只许写在册 yaml。`guji export format` 有缺页的章另写 `NNN.gaps.json`（`guji-gaps/0.1`，lines.md、char.json 不动），`guji export md` 在缺处单起一行〔原书此处缺…〕。没有 Step 读它、不进任何 Step 的 `code_deps`，各书指纹不变。格式 `doc/formats/缺页.md`。
- PATCH：`column_warp.det_warp` 缺省改开、`row_segment.cut_judge` 缺省改 `unet_f64`（A22 切分开关收敛 11-13 定，A20 11-18 转）。殿本、史記、全唐文早已显式写，`params_hash` 不变（code_equiv 已登）；没写的脉经 6 册、北行 column_warp 起过期。要旧行为写 `det_warp: false`／`cut_judge: unet`。`scripts/seg_harness.py` 认 `unet_f64`。
- PATCH：字形库体检加「清边不变式」（OCR 研究 Project，Sheldon 11-17 要求防再犯）：`glyph_selfcheck.clean_invariant(库)` 逐例看库图（已清过边的 canonical）在匹配前再清一遍还删不删墨，删 ≥3% 记违例，占比 ≥0.2% 报警；`run_selfcheck` 开头先跑并打印，结果进 summary 的 `clean_invariant`。只读库，两三分钟。#1617 修复前全唐文 1.16% 违例、殿本史記 0，修复后三套书都是 0。不进任何 Step 的 `code_deps`，产物指纹不变。`doc/经验/管线手册-踩坑与负结果.md` 第 4 节记这条坑和三条规矩。

- 模型库登记 5a 相似度 CNN 的跨书通用底座 `models/glyph_sim_base_v1/`（殿本、史記、全唐文三书合训 59,116 例；OCR 研究 Project 11-17，Sheldon：模型应该放到模型库里）：`core/model_pack.KINDS` 加种类 `glyph_sim_base`（global），模型表与出处表同步，权重与校准表已传 R2。校准表是通用保守包络（`scripts/fit_glyph_sim_calib.py` 的 `--work`／`--cnn` 可给多次，逐点取 cov 最小）。不动任何 Step 与 `sim_cnn.py`，各书产物指纹不变；还没有书的配置指向它。用法见 guji-manager `doc/参考/5a相似度模型.md`。

- 绑定（`feedback/bindings.py`）加迁移补锚闸（A31 11-17，ZM 第一册线报）：补锚档 `source=backfill:migrated` 的行（cellvotes rebase 迁移事件无框，取 r9c 包同编号格的框）与上一版锚（`target.anchor.migrated_from.id`）落到的现格不同 → `review`（`why=migrated_prev_differs`）。原来 IoU 1.0 判 valid，人裁静默落进邻格。不进任何 Step 的 `code_deps`，产物指纹不变；只有带这类补锚行的页（现只殿本）绑定缓存重算。

## [0.7.90] - 2026-11-21

- 发版说明（殿本 patch 线，ZM 11-21，PATCH）：v0.7.86 ＋ #1763 seed_admit 5c 记 `evidence.vis_ctx`。只 seed_admit 指纹变（d14c7e84→61687d88），底库 b29 不变，不登 code_equiv。**不含** v0.7.87／0.7.88／0.7.89 与 dev 其他改动。

## [0.7.89] - 2026-11-21

- 发版说明（全唐文·形近字线 11-21，PATCH）：v0.7.87 ＋ #1768 `groups.hou_shape` 支持 `hou_shape/2`（小卷积网判 候／𠋫，046–053 刻工第二竖偏长、几何阈值分不开；按册 5 折留出 Sheldon 标签 t=0.98 覆盖 193/222 错 1，疑点选错）。hou_shape/1 分支不变（本线 groups.hou_shape 不在 seed_admit code_deps，不用登 code_equiv），**各步代码指纹与 v0.7.87 相同**；全唐文中心库换 `config/groups/hou_shape.json`（schema hou_shape/2）后 seed_admit 按参数指纹过期。底库不变。**不含** v0.7.86／v0.7.88 与 dev 其他改动。

## [0.7.87] - 2026-11-20

- 发版说明（全唐文·形近字线 11-20，PATCH）：v0.7.85 ＋ #1763 seed_admit 5c 给待审格记 `evidence.vis_ctx`（终审裁定键窗口 left/right/ref），manager ≥0.4.79 的 `rulings-hits --rekey` 直接用它补键（全唐文码位归一在 seed_admit 末尾改放行字，产物终态推不回 5c 窗口）。**seed_admit 代码哈希变、产物多一个键，不登 code_equiv**：钉本版后 seed_admit 起判过期（有意）。底库不变。**不含** v0.7.86（殿本 patch 线）与 dev 其他改动。

## [0.7.85] - 2026-11-20

- 发版说明（全唐文·形近字线 11-20，PATCH）：v0.7.82 ＋ #1755 seed_admit 书级整理本字别名 `group_flow_ref_alias`（Sheldon 11-20 定「整理本 間 不挡本书刻的 閒，照刻形记閒」；全唐文书配置写 `{間: 閒}`）。字组流程开头把整理本字与坐标对位字按别名表换成本书刻的字，避免 ids 判閒、整理本 間 时的 ref_dissent。缺省空、不进参数 dump；seed_admit、groups.flow 已登 code_equiv（本线哈希，链 a834dd3e→d84d3546、d17a46a7→e83a839b）。**对 v0.7.82 各 Step 产物不判过期**；全唐文推书配置后 seed_admit 按参数指纹过期（有意）。底库不变。**不含** v0.7.83/v0.7.84（殿本、史記 patch 线）与 v0.7.82 之后 dev 其他改动。

## [0.7.84] - 2026-11-20

史記 patch 线：v0.7.80 + #1746（A24，ry 入口 `ref_top_extra`）。SJ v0.2 整书重跑用；配底库 b31 不变。**不含** dev 线及殿本 patch 线（v0.7.81–0.7.83）其他改动。

- PATCH：字组 ry（日曰）补放入口加 `FlowSpec.ref_top_extra`（只 ry 设 回囘）：库首位与整理本／坐标对位字同在日曰、分差 0.03 内的组外字都落在 回囘 里才进组，其余组外字照拦（目 仍留给 joint）。起因：史記 g27 补库把「回」刻例 2→20，44 格曰因「回」进分差窗口、组流程入口不进全落待审。SJ 15 册沙盒回放：救回 36/44、同页无掉回、新增放行抽 10 格全对；A22 回测殿本 0 变、全唐文 1 格（字同）。
- **Step 指纹对 v0.7.80**（实算）：只 `seed_admit` 变（be5aa272→c289e2ab），其余 22 步不变。语料文件未动，底库仍 b31。不登 code_equiv（注册表改动，行为变）。重跑起点：已在 v0.7.80 上跑到底的册从 seed_admit 起。

## [0.7.82] - 2026-11-20

- 发版说明（全唐文·形近字线 11-20，**dev 快照 patch**，PATCH；全唐文 d2/d3 实际跑的是 dev 42e5d7d6，v0.7.81 基于 v0.7.74 缺 #1727 lane_lib_veto_pairs 等，作废勿用）：直接取 dev a90cc10f，即 dev 42e5d7d6 + #1734 witness3 `lane_shape_first`（缺省关）＋ #1729 seed_admit 候𠋫 书级刻形判法 `group_flow_hou_shape`（没配 json 不跑），两项都已登 code_equiv（#1735/#1736、#1737，链式 3e10a081→182de6ff→d84d3546）。**对 dev 42e5d7d6 各 Step 产物不判过期**；全唐文推 `config/groups/hou_shape.json` 后 seed_admit 按参数指纹整体过期（有意）。底库不变。

## [0.7.81] - 2026-11-20

- **作废，勿用**（底子错：全唐文实跑 dev 42e5d7d6，本版缺 #1727 等；改用 v0.7.82）。
- 发版说明（全唐文·形近字线 11-20，**全唐文 patch 线**，PATCH；用户 11-20 定各书自发 patch 版）：v0.7.74 + #1729（seed_admit 候𠋫 书级刻形判法 `group_flow_hou_shape`，`groups/hou_shape.py`；cherry-pick f249d335，path_params 冲突手解：本线只加 `group_flow_hou_shape`），不含 v0.7.74 之后 dev 上的其他改动。#1737 的 code_equiv 登记是 dev 线哈希，本线不适用、未带。**Step 指纹对 v0.7.74 只有 `seed_admit` 变**（91ee5d84→06b1760b，未登 code_equiv：没跑产物比对；全唐文随后推 `config/groups/hou_shape.json`，seed_admit 本来就要整体重落），下游随之过期。底库不变（b30）。

## [0.7.80] - 2026-11-20

史記 patch 线：v0.7.62 + #1586 + #1627 + #1673 + #1676 + #1677（前置 #1502、#1505），配**底库 b31**（＝b28＋两份异体文件）。SJ v0.2 整书重跑用（A31 11-20）。**不含** dev 线及殿本 patch 线其他改动（#1506／#1508 读不到人工指定改报错、#1678 variants.tsv、#1679 等都不带）。

- PATCH：异体边补 16 对兄弟异体（#1586，`config/variants/local_edges.json`、`variants.json`，与 dev 逐字节同）。底库文件变：钉 b28 的册须改钉 **b31**，否则起跑被语料校验拒绝。
- PATCH：人裁作废与重绑（与 dev 上 `feedback/bindings.py` 逐字节同；`lookup.py` 只差 #1506／#1508 的读失败报错）：
  - #1502 `stale_human_marks` 字形库读不到时仍读 `stale_verdicts.tsv`；#1505 `rebind_library_shapes` 尊重作废标记（误锚人裁重绑后不再落到别的格）。
  - #1627 迁移补锚闸：`backfill:migrated` 补锚与上一版锚落格不同 → `review`（旧格号人裁不再静默挂到邻格；史記没有这类补锚行）。
  - #1673 库内审阅改标重进的人裁刻例照常采信；#1676 撤库／改标的撤下标记只作废被撤刻例原字的人裁（史記没有库内审阅标记）。
  - #1677 `seed_admit` 的 `code_deps` 加 `feedback.lookup`、`feedback.bindings`。
- **Step 指纹对 v0.7.62**（实算）：只 `seed_admit` 变（ec92cec7→be5aa272），其余 22 步不变；另因底库换号，读语料的步随钉子过期。不登 code_equiv。

## [0.7.79] - 2026-11-20

- 发版说明（A31 11-20，**殿本 patch 线**，PATCH；ZM 第一册线要，vol01 87–130 重跑前）：v0.7.78 + #1731（`roster_grid_slots` 跟进：人裁整列格 `n_body_slots` 取 max(格数, 最大号)、超格数打 `roster_slot_overflow`；`grid_slots` 段内两行同空的号收掉、密雙行第二段起号顺延；新逻辑只在开关开着时走），**不含** dev 线其他改动。code_equiv：row_segment、roster_segment 按本线哈希重登（`_ROSTER_GRID_MANUAL_0779`，old 取 v0.7.77 本线哈希），**关着时 Step 指纹对 v0.7.78（＝v0.7.77）全不变**；开了 `roster_grid_slots` 的册 row_segment 按此过期。底库不变（b29）。tag 在 main 合并提交；dev 以 `-s ours` 合回、树不变（#1731 已在 dev）。

## [0.7.78] - 2026-11-20

- 发版说明（A31 11-20，**殿本 patch 线**，PATCH；ZM 第一册线要，vol01 职名页 87–130 格号空格占号）：v0.7.77 + #1726（row_segment 书级开关 `roster_grid_slots`：职名分支切出的字按格网位置编号，列首、字间空格占号；缺省关、不进参数 dump；`impl/keben/roster_segment.grid_slots`），只带这一项，**不含** dev 上 #1726 依赖的 `roster_cols`／`chen_fallback` 及 dev 线其他改动（含 #1678，故不触发 variants.tsv 的 CorpusDrift）。code_equiv：row_segment、roster_segment 按本线哈希重登（`_ROSTER_GRID_0778`；dev 上证据为殿本 vol01 8 页对 dev、87–130 关着对 main 包逐字节同，本线未另跑产物比对），**关着时 Step 指纹对 v0.7.77 全不变**；开了的册 row_segment 参数指纹变，从 row_segment 起重跑。底库不变（b29）。tag 在 main 合并提交；dev 以 `-s ours` 合回、树不变（#1726 已在 dev）。

## [0.7.77] - 2026-11-19

- 发版说明（A31 11-19，**殿本 patch 线**，PATCH；ZM vol20 116:6:15 有图形人裁仍留单）：v0.7.76 + #1722（`scripts/zhengli/pending_route.py` 出单扣格：图形票／认不出的字票落成的 `confirm v=figure` 人裁算已裁，类别 `figure`；`deciding` 不变；republish 票账同口径），**不含** dev 线其他改动。只改编排脚本，不进 code_deps，**Step 指纹对 v0.7.76（＝v0.7.70）全不变**；底库不变（b29）。tag 在 main 合并提交；dev 以 `-s ours` 合回、树不变（#1722 已在 dev）。

## [0.7.76] - 2026-11-19

- 发版说明（A31 11-19，**殿本 patch 线**，PATCH；ZM vol20 116:6:15 图形票台账记未落）：v0.7.75 + #1703（`scripts/zhengli/republish.py` 票账：网站图形票／认不出的字票落成的 `confirm v=figure` 人裁算已落；vision 来源不算；cherry-pick cd93723e，测试只带本条），**不含** dev 线其他改动。只改编排脚本，不进 code_deps，**Step 指纹对 v0.7.75（＝v0.7.70）全不变**；底库不变（b29）。tag 在 main 合并提交；dev 以 `-s ours` 合回、树不变（#1703 已在 dev）。

## [0.7.75] - 2026-11-19

- 发版说明（A31 11-19，**殿本 patch 线**，PATCH；ZM 报 vol20 换单 020-r13→r14 出单门拦 5 格 overturn_empty）：v0.7.70 + #1715（`scripts/zhengli/proof_cycle.py`：新导出里机器没认出的 □（`lacuna` 无 `guess_c`）与 〓／▣ 占位算「机器无字」，旧字是现行人裁就留人裁字、不复审；排除名单判残的 □、图片格、无法识别字、原刻残带推测字仍算推翻人裁，复审说明写「□（判残）」等，出单门不拦；退回成字时去掉阙文／组字标记），**不含** dev 线其他改动。只改编排脚本，不进 code_deps，**Step 指纹对 v0.7.70 全不变**；底库不变（b29）。tag 在 main 合并提交；dev 以 `-s ours` 合回、树不变（#1715 已在 dev）。

## [0.7.74] - 2026-11-19

- 发版说明（A31 11-19，**dev 线 patch**，PATCH；全唐文·总览请求，Sheldon 已批全唐文开）：v0.7.73 + #1701（5-b 库字档 `font.charset.lib_chars`：本书字形库人裁过、5-b 给不出来的字另开一档进候选；缺省关；cherry-pick eef4214），不含 v0.7.73 之后 dev 上的其他改动（#1684 stroke_evidence 等）。code_equiv：cnn_candidates 照 #1701 原登记；rare_panel 按本线哈希重登（本线未另跑产物比对，dev 上证据为全唐文 010 全册逐字节同）。**Step 指纹对 v0.7.73 全不变**；开了 `lib_chars` 的册 rare_candidates 指纹多带库内容指纹，按此过期。底库不变（b30）。

## [0.7.73] - 2026-11-19

- 发版说明（A31 11-19，**dev 线 patch**，PATCH；全唐文·形近字线请求）：v0.7.72 + #1707（seed_admit 书级开关 `lane_lib_veto`：witness3／coord_fallback 两条补放通道遇字形库首位 cov ≥ 阈值且不同字、非异体 → 送审；缺省 0＝关、不进参数 dump；cherry-pick 304d4b6，无冲突），不含 v0.7.72 之后 dev 上的其他改动。Step 指纹对 v0.7.72 只有 `seed_admit` 变（未登 code_equiv：没跑产物比对；开开关的书按参数指纹本来要重跑 seed_admit），下游随之过期。底库不变（b30）。

## [0.7.72] - 2026-11-19

- 发版说明（A20 11-19，**dev 线 patch**，PATCH；A23 请求，史記、殿本用三书合训底座跑 5a 新相似度 A/B）：v0.7.71 + #1631（模型表登记 `glyph_sim_base_v1`；cherry-pick 78c29c0b），**不含** v0.7.71 之后 dev 上的其他改动。不动任何 Step，各步 `code_hash` 不变；不配新底库。tag 在 main 合并提交（PR #1704）；dev 以 `-s ours` 合回、只加本节。

## [0.7.71] - 2026-11-18

- 发版说明（A31 11-18，**dev 线 patch**，PATCH；全唐文·形近字线请求）：v0.7.68（已含 #1655、#1658、#1665）+ #1586（16 对兄弟异体边）+ #1673／#1676（库内审阅改标／撤库不再连现行人裁一起作废）+ #1677（seed_admit code_deps 加 feedback.lookup、feedback.bindings）+ #1679（回库前核验 BackfillProbe，manager 用，不进指纹）+ #1678（variants.tsv 加 𦫵→升）＋语料表补登 variants.tsv（#1678 漏跑 guji corpus registry，新 sha 已传 R2）。不含 v0.7.68 之后 dev 上的其他改动（row_segment 1.53／1.54、#1664 adopt_rel、#1670／#1680 border_detect、#1671 5a.3 pair、#1650 等）。**Step 指纹对 v0.7.68**：`seed_admit` 变（#1673、#1677 加 code_deps；dev 线所有册 seed_admit 判过期），其余步不变。**配底库 b30**（＝b29 + variants.tsv；b29＝b27 + #1586 两份异体文件），钉 b27 的册要 `guji corpus pin` 改钉 b30，否则新版 cv 拒跑。

## [0.7.69] - 2026-11-18

- 发版说明（A31 11-18，殿本 patch 线，ZM 要）：v0.7.67 + #1586（关系图补 16 对兄弟异体边：`config/variants/local_edges.json` 加 16 条 `local:keben`、`variants.json` 同步加标签；三书人裁 5b 补边清单 A 档，Sheldon 11-16 人审定），PATCH，**不含** dev 线（v0.7.65／66／68）与史記线其他改动。只动数据不动代码；`seed_admit` 读关系层判「有无直接异体边」，含这 32 字的格（殿本约 40 格）结果可能变。语料表重登（两份异体文件＋补登 `sb/rules.yaml`，sha 与 b27 一致）。**配底库 b29**（＝b27 换这两份异体文件），钉 b27 的册在本版上报 CorpusDrift，要改钉后从 `seed_admit` 起重跑。

## [0.7.68] - 2026-11-18

- 发版说明（A31 11-18，**dev 线 patch**，PATCH）：v0.7.66 + #1665（`eval/seg_screen` 加两条墨账：清界行抹笔 `erased`、字框外丢墨 `bbox_drop`，全唐文 R033／R038 复盘；cherry-pick 613f201），不含 v0.7.66 之后 dev 上的其他改动（#1661 row_segment 1.53、#1664 adopt_rel 等）。只读产物与缓存，**不进任何 Step 指纹**，对 v0.7.66 产物全部仍新鲜。要配 guji-manager #667（seg check 处置「cv丢笔」）。底库不变（b27）。

## [0.7.70] - 2026-11-18

- 发版说明（ZM 11-18，殿本 patch 线）：v0.7.69 + #1655 + #1672（row_segment 1.54 列端表空格居格中粗横「一」不记空），PATCH，**不含** dev 线其他改动。tag 在 main 合并提交（PR #1674）；dev 以 `-s ours` 合回、树不变（#1655、#1672 已在 dev 上）。

## [0.7.67] - 2026-11-18

- 发版说明（ZM 11-18，殿本 patch 线）：v0.7.64 + #1661（row_segment 1.53 细横「一」不记空白），PATCH，**不含** dev 线（v0.7.65／66）与史記线其他改动。tag 在 main 合并提交（PR #1662）；dev 以 `-s ours` 合回、树不变（#1661 已在 dev 上）。

## [0.7.66] - 2026-11-18

- 发版说明（A31 11-18，**dev 线 patch**，PATCH）：v0.7.65 + #1658（全唐文切分丢笔两个书级开关 `column_warp.inner_bar_span`、`cell_shrink.long_rule_outer_only`，台账 R033／R038；缺省关、不进参数哈希；cherry-pick 33d1991），不含 v0.7.65 之后 dev 上的其他改动。code_equiv 照 #1658 登 5 条（column_warp、seg.profile、impl.keben.column、cell_shrink、clustering.extractor）：这 5 个模块改前在 v0.7.65 与 dev 30febf9 逐字节同，本线登记后经换算与 v0.7.65 相同，**Step 指纹对 v0.7.65 不变**，开关不开的册不过期；开了开关的册按参数指纹从 column_warp 起重跑。底库不变（b27）。

## [0.7.65] - 2026-11-18

- 发版说明（A31 11-18，**dev 线 patch**，PATCH）：v0.7.60 + #1655（seed_admit 书级开关 `vis_ruling_ctx_subclasses`：文意终审裁定 ctx-m1 在 Z／N 之外再收哪些子类，缺省空、空时不进参数 dump、行为不变；cherry-pick eef87fb），不含 v0.7.60 之后 dev 上的其他改动。给全唐文形近字线（子类 `A`）。Step 指纹对 v0.7.60 只有 `seed_admit` 变（未登等价：没跑产物比对；开开关的书按参数指纹本来也要重跑 seed_admit），下游随之过期；底库不变（b27）。全量测试与 v0.7.60 失败清单一致（57 条，多为缺 guji-manager；另 3 条 corpus registry／group_flow 缺省名单／p_ref 在 dev 合 #1655 前就败）。

## [0.7.64] - 2026-11-18

- 发版说明（ZM 11-18，殿本 patch 线）：v0.7.58 + #1652（row_segment 1.52 叠横画数字二三不当框线），PATCH，**不含** dev 线与史記线其他改动。tag 在 main 合并提交（PR #1653）；dev 以 `-s ours` 合回、树不变（#1652 已在 dev 上）。

## [0.7.62] - 2026-11-18

- 发版说明（A31 11-18，史記 patch 线，r80 用）：v0.7.61 + #1617 + #1635（清边），PATCH，不含 dev 线其他改动。normalize.py 与 dev 同；不登 code_equiv（史記 glyph_match 起过期）。tag 在 main 68ea912（#1644）。

## [0.7.61] - 2026-11-17

- 发版说明（A31 11-17，史記 patch 线，r79 用）：v0.7.59 + #1638（dev 10ebd48 cherry-pick），PATCH，**不含** dev 线其他改动。冲突手解：`segment_column` 只加 `cut_glyph_line`；code_equiv 按本线重算登 `_GLYPH_LINE_0761`（row_segment a57cd50d→cb32ff35、row_boundaries 8055bbc3→158f4327）。tag 在 main 7781c20（#1639）。

## [0.7.59] - 2026-11-17

- 发版说明（A31 11-17，史記 patch 线，r78 用）：v0.7.57 + #1632（dev c4415f9 cherry-pick），PATCH，**不含** dev 线其他改动。冲突手解：`segment_column` 只加三个开关（本线无 grid_adjust 等钩子）；开关登记表按本线补三行；code_equiv 按本线重算登 `_R78_0759`（row_segment 6ba5531b→a57cd50d、row_boundaries 02c5d8e0→8055bbc3）。tag 在 main ff2ff30（#1633）。

## [0.7.57] - 2026-11-17

- 发版说明（A31 11-17，SJ 史記 patch 线，r77 用）：v0.7.55 + #1624（dev 2e1b5b0 cherry-pick），PATCH，**不含** dev 线 v0.7.56 的其他改动（#1610、#1617 等）。冲突手解：`segment_column` 只加 `cut_free_seam`（本线无 grid_adjust 等钩子）；开关登记表按本线补一行；code_equiv 按本线重算登 `_FREE_SEAM_0757`（row_segment a931bd1d→6ba5531b、row_boundaries fbb1d8d6→02c5d8e0）。版本号不叫 0.7.56：那号已发 dev 线（全唐文用）。
- 新书级参数 `row_segment.cut_free_seam`（缺省 0＝关、不进参数哈希；史記 r77 切分清零，A22 11-17）：选中切线仍劈开单字大小连通块、且墨大半在上格时，在 ±这么多格内找零墨（或穿墨减半）折线改选，上字戈钩／长捺／竖尾整块归上字。史記 42 册 82 页与 cut_gap_guard 0.08 同开：实际切坏线 72→54、新劈 0、格号不变。关时与 v0.7.55 等价（登 code_equiv）。建议值 0.35。

## [0.7.56] - 2026-11-17

- 发版说明（A31 11-17，**dev 线**，PATCH）：dev 头 `46836b7`＝v0.7.53 + #1610（stages.route.table 按数据目录解析，书级形近字组表）＋#1618（daizhige 对 row_segment 等价登记）＋#1617（归一化清边细线护栏）。**Step 指纹对 v0.7.53**：`glyph_match` 变（#1617 改 `clustering/normalize`，未登等价，产物会变），下游随之过期；`row_segment` 也变——#1618 把 daizhige 换回 #1604 前的哈希，v0.7.42／v0.7.49／v0.7.51 出的 row_segment 因此不过期，但 **v0.7.53 出的 row_segment 反而判「代码或版本变了」**（产物逐字节同；status code_ok 下正式版当新鲜）。#1610 的 glyph_stages 不在 code_deps，开 stages 的册靠 stages_sha。**底库不变**：对 b27 逐文件一致。

- PATCH：归一化清边的细线规则不再删本字的细笔画（OCR 研究 Project，Sheldon 11-17 定修）：`clustering/normalize.remove_edge_specks` 规则 2 加相对笔宽护栏，候选线粗细不超过本图块笔宽（`stroke_width_px`）的 `LINE_STROKE_RATIO`＝0.6 倍才当界行／版框删。旧的绝对上限按图块短边 4.5% 算，全唐文 200px 的字块上涨到 8～9px（256 画布上 11.5px），把 6～9px 粗的忄竖、底横、顶横、亻都删了：入库存图删一遍（库图残，字形库自检查出 569 例），匹配前归一再删一遍（州 成 川、伽 成 加）。全唐文全库 3.9 万例现格重裁：归一图变 3.09%，字体模板首位＝库标 89.94%→91.66%，569 例名单里首位回到库标 157→561；殿本两册、史記一册真实字块 1 万格只 1 格变。规则 3 的面积上限抽成 `PAD_DEBRIS_AREA_RATIO`（值不变），另留实验旋钮 `PAD_DEBRIS_INNER_AREA_RATIO`（缺省不开）。**缺省输出变**：`normalize` 在 `glyph_match` 的 `code_deps` 里，各书 5a 及下游判过期；库的派生归一图要重算，库图本身残的要从现格重入。原理、数字、上线步骤见 guji-manager `doc/参考/字形图清边与归一.md`。
- PATCH：code_equiv 登记 utils/daizhige（#1604 〓→▣）对 row_segment 行为等价，史記 v0.7.51→v0.7.54 row_segment 不过期（A22）
- PATCH：`glyph_match.stages.route.table` 给相对路径时按数据目录、工作区、仓根的顺序找（书自己的形近字组表随中心库走），找不到报错而不是悄悄退回仓里的大表。只动 `steps/glyph_stages.py`（不在 `code_deps`），各 Step `code_hash` 不变；已开 `stages` 的全唐文 `stages_sha` 变一次（还没有带 `stages` 的产物）。背景：全唐文七册实测，仓里按 CNN 近度建的核心表拦 21.8% 的 same 格、只对上 198 个自信错里的 21 个；按实际出错字对建的书级表留一册验证拦 3.7%、对上 129 个（`doc/design/形近字组-5a分流与第7步对接.md` 第七节）。

## [0.7.53] - 2026-11-17

- 发版说明（A31 11-17，**dev 线**，PATCH）：dev 头 `4b90c3b`（含 `32a7764` #1589＋#1609 5a 分段 `glyph_match.stages`，全唐文要）。上一版 dev 线是 v0.7.42，本版并进其后 dev 上全部改动：#1573/#1576/#1580/#1583/#1590/#1594/#1601/#1606（缺省关或已登记等价）、#1587（row_segment 1.51，各书一律生效）、#1604（整理本占位符 〓／▣ 区分）、#1588/#1599/#1600/#1605（只动 manager 侧或脚本）及下面各条。**Step 指纹对 v0.7.42 变了的四步**（实算，经 code_equiv 换算后）：`column_gate`、`row_segment`（#1587 改 `impl/keben/row_boundaries`＋row_segment 升 1.51；#1604 改 `utils/daizhige`）、`align_ref`、`seed_admit`（#1604 改 `align_ref_coord`、新增依赖 `utils/gap`；#1601 改 `groups/flow`）——v0.7.42 及更早的产物这四步起过期，等于从 column_gate 起重跑；`glyph_match` 指纹不变（`_STAGES_1116` 已登记），开 `stages` 的册靠参数过期。**底库不变**：`check_base_corpus` 对 b27 一致（对最新 b28 多出 wu/rules.yaml，b28 是史記 patch 线的，dev 线书别钉 b28），钉 b27 的册不用改钉。

- PATCH：`glyph_match.stages` 的 5a.1 weak_knn 格：带进候选的对手不再排到首位字前面（对手分是纯 CNN 分，候选里是融合分，直接比会把对手顶成库首位；全唐文 020 整册对比发现 碑→裨、遽→蘧）。只动 `steps/glyph_stages.py`，没开 `stages` 的书不受影响。设计文档第六节补整册对比：29688 格，放行 29664→29662，放行字 0 变。

- PATCH：5a 分段接进第 5 步（Sheldon 11-16 定结构）：`glyph_match` 新参数 `stages`（缺省关，不进参数 dump），`steps/glyph_stages.py` 在判决层之后跑 5a.1 分流（same 降 unsure，落法并进匹配器现有护栏：落表 `never_match`＋对家进候选，近邻不一致 `conflict`＋对手进候选；来由记 `stage.route`，第 7 步与 manager 待审原因不用改）与 5a.2 形近字组字形方法（证据落 `MatchRec.stage`；书级 `final` 名单里的组才在这一步定字，缺省空＝全部待审）。相关模块不进 `code_deps`，开着的书靠 `stages_sha` 判过期；`glyph_match.py` 的改动登记等价（`_STAGES_1116`）。开关登记表、设计文档第三节已更新。

- PATCH：形近字组表与分流规则（OCR 研究 Project，Sheldon 11-16 定方向）：`config/near_groups.json`（全唐文、史記、殿本字形库挖的极近字对，并上手工、人裁、字体表与库内异体对，572 对／920 字，核心 369 对）、`clustering/near_route.py`（读表、近邻一致度、分流规则：首位字落表送审，近邻一致度不满送审）、`scripts/build_near_groups.py`（`mine`／`merge`）、`groups/shape_stage.py`（5a.2：按注册字组里只吃字块图的方法出字形判定）。表里每对标了所在的注册字组。**没接进匹配器**：新模块不在任何 Step 的 `code_deps` 里，各书指纹不变、缺省输出不变。
- PATCH：row_segment 书级参数 `cut_gap_guard`（缺省 0＝关，不进参数 dump）：切点选定后，选中那条不在白缝里、候选池里另有干净落在白缝里的，改用白走廊最宽的那条（`chosen_by="gap"`）。史記写本 U-Net 把上字底横、下字头判给扁字（畫/一、靈/七），Step4 照切线分墨 一→二；史記 25 页＋58 页改 11 个切点，看图 9 对 2 持平。关时殿本 vol30、全唐文 020、史記 09 row_segment 逐字节同，code_equiv `_GAP_GUARD_1117`。`scripts/code_equiv.py check` 基线检出链接本机 models/（A22，SJ r76，11-17）。

- PATCH：`scripts/seg_pins_check.py` 加第 1b 节钉子列几何：压墨（钉子格线劈字，判据同 seg check `cut_through`，过 U-Net 裁判，强／中档算问题）与一格跨两字（`eval/seg_screen.two_glyphs`：格高 ≥1.2 倍字高、格里墨分两段各 ≥0.3 倍，或墨跨 ≥1.1 倍且断开）；`--geo-hint-only` 降成提示。只改检查工具，不动 Step 指纹（A22，SJ r76 切分审计，11-17）。

- PATCH：seed_admit 书级减法参数 `group_flow_exclude`（如 `[shi]`）：从 `group_flow`（缺省全部 flow 组）减掉点名的组，免得书配置抄全名单；缺省空不进参数 dump。殿本 vol28 16 页 seed_admit 逐字节同，code_equiv `_GF_EXCLUDE_1116`（A22，史記 勢𫝑，A24 定方案①，11-16）。

- PATCH：`scripts/train_glyph_sim_cnn.py` 支持几本书合训 5a 相似度 CNN（`--db` 给多次，同码位跨书合一类；`--per-book-classes` 按书分类）、`--resume` 按轮存档续训、`--limit` 每书限例数、`--threads`；单书用法与结果不变。`scripts/eval_sim_bench.py` 加 `cnn` 子命令（`--model <权重> --name <分数名>`）给一份 CNN 权重出逐对分。只动 scripts，不改 Step 指纹。实验结论见 ai-team `跨书通用底座-2026-11-16.md`，用法见 guji-manager `doc/参考/5a相似度模型.md`（OCR 研究 Project，11-16）。

- PATCH：`table_cols` 正文只剩一列的页（史記 11:193）周期门槛下限改 1，不再整页拒（估不出走 period_prior 兜底）；文档写清列号是图上右起（产物 quad 右上原点）；A20 两处小毛病（常量位置、冲突报错打全 dict）。殿本、全唐文、北行 column_gate 逐字节同，code_equiv `_TABLE_COLS_ONE_1116`（A22，SJ 11-16 实测）。

- PATCH：半文半表页按列标表格 `page_kinds.table_cols: {页: [列号…]}`（GUJI-772，SJ 台账 R030，A20 定方案；A22）：翻成 `column_gate.table_cols`（缺省空不进 dump），点名列拒收（拒因 `table_column`，GateLevel L0t），不进列宽中位与页级周期、门槛扣表格列数，Step3 出 ok=False、闸3 拒因同名，不进待审单；其余列照正文切。殿本 vol28、全唐文 020 各 16 页、北行 8 页两道闸逐字节同，code_equiv `_TABLE_COLS_1116`。

- PATCH（数据）：`config/variants/local_edges.json` 补 16 条兄弟异体无向边（㕘／叅、𡚁／獘、𢑱／彛、𥪡／䜿、嵗／𡻕、𨽻／隷、𥗤／𡕎、滙／𣾀、𠫊／㕔、𨚫／却、𦊨／𦊕、𩛻／䬤、藳／藁、駵／𩤃、𫾻／敭、𣢾／款），`variants.json` 同步加这 16 对的 `local:keben` 标签（按 build_variants 3.5 的逻辑只补这 16 对，没有重拉上游）。来源：候选召回线三书人裁 5b 冻结集，清单在 ai-team `domain/CV/字形领域/大字符集候选召回-2026-11-15/关系库补边清单-2026-11-16/`，Sheldon 11-16 人审定补 A 档。**hanzi 核心包没有重建**（`config/hanzi/` 现版只含 1 条 local:keben，11-06 加的 14 条也不在里面），`HanziDB.family()` 要等重建后才看得到。共用异体表变了，各书用到关系图的步指纹是否变未测。

- PATCH：seed_admit 书级参数 `semantic_extra`（「异体=正字,…」，缺省空不进 dump；A22，史記 r71）：叠在 VariantMap 之上补语义对，只管语义层、放行字照旧是刻形。史記 圗 不在 `variants.auto.tsv` 里，异体护栏认不出 圗、`variant_rank` 调不到，8 格照整理本放成 圖；史記配 `semantic_extra: 圗=圖` 即可。没改共用异体表（那样各书 seed_admit 指纹都变、钉语料的册要改钉）。殿本 vol28、全唐文 020 各 16 页 seed_admit 逐字节同，code_equiv `_SEM_EXTRA_1116`。

- PATCH：seed_admit `follow_ref` 变体遍跳过书级钩子 `variant_rank` 按刻形放的格（史記 r71：来 14 格、圗 8 格被改回整理本 來／圖；SJ 11-16，A22）。钩子缺省 None 时没有这种格：殿本 vol28、全唐文 020 各 16 页 seed_admit 逐字节同，code_equiv `_FR_KEEP_VR_1116`。

- PATCH：seed_admit 异体护栏书级钩子 `follow_ref_hooks.variant_rank`（史記，Sheldon 11-15 定 圗兾凢来 不并码位归一、改流水线放行；SJ 请求，A22）：三通道本要以 `cand_variant` 拦、`variant_norm` 也不放时再问书仓一次，钩子拿到异体在现字（名次 0）与库前 topk 名的名次，返回与放行字语义同的字就放，证据记 `lane.variant_rank=hook`、`variant_from`、`variant_ranks`。缺省 None 不调：殿本 vol28 16 页、全唐文 020 16 页 seed_admit 逐字节同，code_equiv 已登记 `_VR_HOOK_1116`、指纹不变。史記书仓覆盖了 follow_ref_hooks，照常过期；史記走 patch 线的话要把本改动 cherry-pick 到 patch 线并按本线哈希补登。

## [0.7.49] - 2026-11-16

- 发版说明（ZM 11-16，殿本 patch 线）：v0.7.42 + #1587（row_segment 1.51 闭口方框字不当框线），PATCH。基于 v0.7.42，不含 v0.7.43–48 与 dev 上其他改动；tag 在 main 合并提交（PR #1597）；dev 以 `-s ours` 合回、树不变（#1587 已在 dev 上）。

## [0.7.46] - 2026-11-16

- 发版说明（A31 11-16，SJ 史記 patch 线）：v0.7.45 + #1583（status 过期原因分出「语料钉变了」），PATCH；不改 Step 指纹，无 code_equiv 登记。tag 在 main d73f7e4。dev 上 #1583 已在 `## [未发版]`。

## [0.7.45] - 2026-11-16

- 发版说明（A31 11-16，SJ 史記 patch 线）：v0.7.44 + #1580 移植（A22 分支 a22/semantic-extra-0744 9d9f43b），PATCH，不含 dev 线 v0.7.40／v0.7.42。tag 在 main 合并提交（PR #1581）；dev 以 `-s ours` 合回、树不变，只追加 code_equiv 本线哈希登记 `_SEM_EXTRA_0744`（seed_admit be2ed592→ffceeab9）。

## [0.7.44] - 2026-11-16

- 发版说明（A31 11-16，SJ 史記 patch 线）：v0.7.43 + #1576（A22 移植分支 f5f1a97），PATCH，不含 dev 线 v0.7.40／v0.7.42。tag 在 main 合并提交（PR #1577）；dev 以 `-s ours` 合回、树不变，只追加 code_equiv 本线哈希登记 `_FR_KEEP_VR_0743`（seed_admit 1f3cc925→be2ed592）。

## [0.7.43] - 2026-11-16

- 发版说明（A31 11-16，SJ 史記 patch 线）：v0.7.41 + #1573（`follow_ref_hooks.variant_rank` 钩子），PATCH，不含 dev 线 v0.7.40／v0.7.42。tag 在 main 合并提交（PR #1574）；dev 以 `-s ours` 合回、树不变，只追加 code_equiv 本线哈希登记 `_VR_HOOK_0743`（seed_admit 1f3cc925→ebd54cc7、follow_ref_hooks a73e9aaf→76f1e160）。

## [0.7.42] - 2026-11-15

- 发版说明（A31 11-15，dev 线）：dev 头 `0cb4065`＝v0.7.40 + #1565（`sb-否決-卜-史記` 补 4 条），PATCH。只改 `config/groups/sb/rules.yaml`，代码指纹与 v0.7.40 同。**钉 corpus 的册（殿本、全唐文）改钉前别升含 #1558 的版本（v0.7.40 起）**：先改钉底库 **b27**（Ops 出，rev 1011430；＝b24／b25 只改 sb/rules.yaml，含 #1558＋#1565；**不是 b26**，b26 是史記 patch 线的底库），`guji corpus pin --same-output-as <旧总号> --note '<证据>'`（配 manager ≥0.4.50），五步不过期；还钉 b24/b25 的册在本版上报 CorpusDrift。证据：A22/A24 回测 #1558 殿本五份整理本 0 变化、全唐文 kanripo 23530 处 0 变化；#1565 殿本、全唐文 0 变化。史記两次共 23 处卜判十→弃权。史記走 patch 线 v0.7.41。
## [未发版]

- PATCH：`guji status` 过期原因分出「语料钉变了」（SJ v0.1 预检 11-16，A31）：读语料的步（glyph_match、rare_candidates、align_ref、context_decide、seed_admit 等 `CORPUS_STEPS`）只因册的 `corpus:` 改钉而过期时，原来报「代码或版本变了」，现在报「语料钉变了：corpus 6→8（代码未变）」；代码也变了报「代码或版本变了；语料钉也变了：…」。新条目在 manifest 记 `corpus_pin`／`corpus`（不进指纹）；老条目没记就拿 `self_hash` 逐个旧总号试。只改原因文案，过期判定、`code_ok` 不变（语料变化不算「只是代码变了」）；不改任何 Step 指纹。

## [0.7.40] - 2026-11-15

- 发版说明（A31 11-15，dev 线）：dev 头 `ea45a81`，基于 v0.7.37，PATCH。带 #1561（语料等价登记 `same_output_as`，殿本／全唐文改钉 b25 要用）、#1558（sb 组 `sb-否決-卜-史記`）、#1553（part_shape，缺省关）、#1554（variant_norm，缺省 None，已登等价）、#1557、#1551／#1552（只动 eval）。代码指纹：seed_admit、follow_ref_hooks 经 code_equiv 与 v0.7.37 同；**但** `config/groups/sb/rules.yaml` 变了：钉了 corpus 的册（殿本、全唐文）起跑报 CorpusDrift 拒跑，须改钉底库 b25（Ops 已出，与 b24 只差这一个文件），各册 `guji corpus pin --same-output-as <旧总号> --note '<证据>'`（要 manager ≥0.4.50）则五步不过期；没钉 corpus 又用 sb 组的册 seed_admit 过期。史記走 patch 线（v0.7.38／v0.7.39 见下），本版不给史記。
- PATCH：sb 组手写否决 `sb-否決-卜-史記`（A24 11-15，史記 r68，#1558）：史記卜组 21 格人读为卜被 sb-十-r1/l1 误判十，加具体上下文否决、整格弃权。**下次 dev 线发版须知（A22 11-15 更正，取代原「指纹会变、被判过期」的说法）**：code_equiv 登记不了 `config/groups/sb/rules.yaml`（它走数据路进指纹）。殿本、全唐文都钉了 corpus，发版后起跑前 `require_pin_clean` 会因 rules.yaml 与所钉底库清单不符报 **CorpusDrift 拒跑**。处理顺序：①发 dev 线新版 cv（带 #1561）＋ manager（带 #584）；②出新底库，**只含 sb/rules.yaml 这一处差异**，不夹带别的；③各册（殿本十册、全唐文各册）单独 `guji corpus pin` 改钉，加 `--same-output-as <旧总号> --note '<回测证据>'`，读语料的五步（glyph_match、rare_candidates、context_decide、align_ref、seed_admit）就都不过期。证据：A22/A24 回测殿本五份整理本 0 变化、全唐文 kanripo 23530 处 0 变化，最好再补一册几页 seed_admit 逐字节对比。改钉前这两本书在新版上跑不了。没钉 corpus 又用 sb 组的册（若有）仍会因 group_flow_fingerprint 变而过期。史記不登等价、照常过期。史記 patch 线已单独发 v0.7.39（= v0.7.38 + #1558 + #1557）。
- PATCH：seed_admit 异体护栏书级钩子 `follow_ref_hooks.variant_norm`（史記 r68，SJ／A24 11-15，A22）：三通道 `cand_variant` 拦前最后问书仓一次，返回与放行字语义同的字就放（本书已归一的异体）。缺省 None 不调，殿本 vol28 16 页 seed_admit 逐字节同，code_equiv 已登记、指纹不变。
- PATCH：语料等价登记（A22 11-15，答 A31「sb/rules.yaml 这类规则文件改动能否登记等价」）：`corpus_pin.append_pin(..., same_output_as=M)`（manager `guji corpus pin --same-output-as M`）让册的新总号沿用总号 M 的语料指纹，读语料的五步不判过期；按册登记（钉子账是每册的），note 必须写证据，登记时记下两版清单差异条目、取指纹时再核，对不上报错。不登记的册行为不变，现有指纹逐位不变。
- PATCH：`scripts/check_code_equiv_monotonic.py` 改为执行 code_equiv.py 取 ENTRIES（原正则只认单引号写法，漏读 194 条，A31 11-15 报的 cut_select／seam 三条断链是误报）；补抄 v0.7.24／v0.7.28 两条 align_ref 中间哈希（A22 11-15）。不动指纹。
- PATCH：seg check 加字内落缝检查 `inner_gap`（史記 R002，A22 11-14）：格线挨着对不上参校字且没放行的格、落在字内窄白缝，旁边另有宽得多的字缝（宮的两口之间、主／言的点与身之间）。只动 eval（`seg_screen`、`seg_screen_run`），不进 code_deps，产物与指纹不变；manager 记 GAP 结构旗。
- PATCH：`inner_gap` 加同段窄缝线 `chain`、报页坐标（SJ 11-15）：从报出的线往上下连着落在窄缝（或正落在本线该挪去的缝）的线一并列出；seg check 挪线建议给页 y（列窗每轮可能变）。只动 eval，产物不变。

## [0.7.39] - 2026-11-15

- 发版说明（A31 11-15，SJ 史記 patch 线）：v0.7.38 + #1558（sb 组手写否决 `sb-否決-卜-史記`）+ #1557（code_equiv 只增检查修读登记，只动检查脚本与登记、不动产物），PATCH，**不含** #1432/#1437、#1467 及 dev 上其他改动（v0.7.34–v0.7.37 是 dev 线，本线不带）。#1558 原样 cherry-pick dev 8475e60，只改 `config/groups/sb/rules.yaml` 一行，进 `seed_admit.group_flow_fingerprint`，用 sb 组的册 seed_admit 指纹会变；**不登 code_equiv**（对史記是真实行为变化）。#1557 本线原无 `scripts/check_code_equiv_monotonic.py`，整份取 dev 版；登记只追加 A22 那两条 align_ref 中间哈希（本线 align_ref 哈希 a2bc661c 不在其中，不改本线任何指纹）。
- PATCH：sb 组手写否决 `sb-否決-卜-史記`（A24 11-15，史記 r68）：史記卜组 21 格人读为卜（以卜有求、卜有憂、周公卜三龜等）被 sb-十-r1/l1 误判十，加具体上下文否决、整格弃权。A22/A24 回测：殿本五份整理本 0 变化，全唐文 kanripo 23530 处 0 变化，史記 daizhige 仅 21 处卜由「判十」改「弃权」。
- PATCH：`scripts/check_code_equiv_monotonic.py` 改为执行 code_equiv.py 取 ENTRIES（原正则只认单引号写法漏读登记，cut_select／seam 三条断链是误报）；补抄 v0.7.24／v0.7.28 两条 align_ref 中间哈希（A22 11-15，#1557）。不动指纹。

## [0.7.38] - 2026-11-15

- 发版说明（A31 11-15，SJ 史記 patch 线）：v0.7.33 + #1554（seed_admit 异体护栏书级钩子 `follow_ref_hooks.variant_norm`），PATCH，**不含** #1432/#1437 及 dev 上其他改动（v0.7.34–v0.7.37 是 dev 线，本线不带）。原样 cherry-pick，code_equiv 登记 seed_admit、follow_ref_hooks 两行（哈希按本线重算，逐字节同证据是 dev 上殿本 vol28 16 页）。
- PATCH：seed_admit 异体护栏书级钩子 `follow_ref_hooks.variant_norm`（史記 r68，SJ／A24 11-15，A22）：三通道 `cand_variant` 拦前最后问书仓一次，返回与放行字语义同的字就放（本书已归一的异体）。缺省 None 不调，殿本 vol28 16 页 seed_admit 逐字节同，code_equiv 已登记、指纹不变。

## [0.7.37] - 2026-11-14

- 发版说明（A31 11-14，全唐文 QTW 要）：dev 头 `61fd9ed`，基于 v0.7.36，PATCH。主要为带上 #1548（wu_shape 收紧，替掉 v0.7.36 里 #1540 的库前 3 名补放）；另含 #1545（seg check 格高离群，只动 eval）、#1546＋#1547（互相抵消）、#1544／#1527（doc）。史記 patch 线不带这些。

- PATCH：seed_admit `group_flow_wu_shape`（嗚鳴书级刻形判法）只判本格字（库首位）是 嗚鳴 的格，去掉 #1540 的「字形库前 3 名有嗚鳴也补放」（全唐文 t1 实测这样放进的 21 格全是 鴨鵝鳩塢 等右边是鳥／烏的别字，3 格错成鳴）。开关缺省关，不开的书产物与指纹不变；全唐文 020 f5 包 20 页 code_equiv 逐字节相同已登记（#1548）。
- PATCH：seg check `cell_size`（格高离群）在格贴墨切的列（roster：职名、卷端题署）里，矮格离上下字一个字距、上下留白不窄、邻格高正常时当整字扁字不报（史記 r61 闸误报 35:15:8 等 5 列「史記卷一百N」的「一」，台账 R019）。只动 eval，产物与指纹不变。史記 r61 01/35/40/42 矮格 135→60（去掉的看图全是整字），人钉尺子没丢真错，殿本 99 册只少 vol01:87:6 一格误报。

## [0.7.36] - 2026-11-14

- 发版说明（A31 11-14，全唐文 QTW 要）：dev 头 `cbd4fa8`，基于 v0.7.35，PATCH。含 dev 上已合未发的 #1534（row_hooks `jiazhu_pair_ok`、`jiazhu_heads` 传 ruler）、#1535／#1536／#1537／#1538（seg check：align_drift 及收紧、CHECKS 补登记、劈字弱档）、#1539／#1540（wu_shape 嗚鳴书级刻形判法及护栏）、#1541（row_hooks `edge_frame_only`）。row_hooks 两钩缺省不调，殿本 fixture 产物与指纹不变，code_equiv 已登记；seg check 只动 eval。全量测试 54 失败＋3 错，与 v0.7.35 基线逐条相同（缺 guji-manager）。史記 patch 线不带这些。

- PATCH：Step3 行切分书级钩子 `row_hooks` 加 `edge_frame_only(gray, spans, content_x, border_top, border_bottom, period, ink_threshold)`：补认「列端格里只有版框线」，与 P5 缺省判据（`seg/profile.frame_only_edge_cells`）取并集，照样记空、打 frame_line（全唐文台账 R018：none 页空列首格把上框粗条＋细线切成「一／幸／士」，粗条离 border_top 远过 0.2 格高，或这列没有 border_top）。缺省 None 不调，殿本、史記产物和指纹不变；row_segment、row_hooks 登 code_equiv。

- PATCH：seg check 劈字 `cut_through` 加弱档（A22 11-14，SJ 看图「劈字中多是笔画相触」）：中档里挪不到 `CUT_WEAK_MOVE`＝0.33 格高的记「弱」，manager 只当提示。史記 r59 20/37/41/42 整册：中档 67 条里 49 条变弱，有劈字旗（强／中）的列 71→30；r59 之后人钉的 77 列召回不变（41:76:2、41:87:7 只有中档，挪 0.35／0.39 格高，仍是中；弱档里的 37:152:3 另有对位串错）。只动 eval，不影响产物。
- PATCH：修 #1535 漏登记：`align_drift` 没进 `seg_screen_run.CHECKS`，有对位串错报出的册 `guji seg check` 直接 KeyError（A22 11-14）；加测试守卫 rows 用到的检查名都要登记。
- PATCH：seg check 新检查 align_drift「对位串错·疑整列错位」（史記台账 R017，A22 11-14）：一列里连续 ≥3 格对不上参校字（至少一格没放行）、劈（列中没配到参校字的格挨着没放行的对不上格）、或没放行且对不上的格 ≥3；只读 seed_admit／align_ref／glyph_match，不加步骤、不进产物指纹。史記 r59 切分线钉的 33 列报 23 列，全书非钉子列报 172 列；殿本 4 册报 3 列。
- PATCH：seg check 对位串错 `align_drift` 按 SJ 切分线抽看收紧（A22 11-14，史記 R017）：散在单格对不上不再报，要劈（n 挨 b）、连续两格没放行对不上且全列 ≥3、或连续 ≥5 格对不上；考證列（○／考證）不查；同页报出 ≥3 列的 value 加 `page`（整页的事，manager 降成提示）。r59 172→87 列（结构 75），切分线 23 列全留；殿本 4 册 3→1。只动 eval，不影响产物。

## [0.7.35] - 2026-11-13

- 发版说明（A31 11-13，全唐文 QTW 要）：dev 头 `c57b7968`，基于 v0.7.34，PATCH。只多 #1531（`group_flow_ruling_first` 在线模式 `GUJI_LLM_ONLINE=1` 时不先查，只给只读裁定库用；补复核按裁定改字的测试）。缺省关，code_equiv 已登记，没开名单的册产物不过期。

- PATCH：seg check 新增 `block_tall`（殿本 vol06 147:3:3「也」，ZM 11-13）：cell_shrink 字块高 ≥ 本格 row_segment 格高 1.35 倍（且多 24px 以上）的格单独报（列末格不查）。cell_size／page_pitch 只比格线高度，格线对而字块连上贯穿长竖线时都不报；原先只有 `Lv` 被归「公用清格」漏掉。殿本 vol06–10 现行包扫出 06:147:3:3（格高 128、字块 427）、07:133:7:3（印章压空列）、07:5:2:1（1.36）。只读工具，不进产物指纹。

- PATCH：新增 `scripts/orphan_rulings.py` 孤儿人裁普查（ZM 11-13）：human_chars 的「N 条页表 rev 不符不采信」把旧代迁移事件、有现行孪生的原始事件、**迁移时对不到新格的原始事件**混在一起；脚本只列最后一类（换源前的定字人裁、没有现行代孪生），按册出 TSV 交册线复核。仅维护脚本，不进产物指纹。

- PATCH：seg check 格高／夹注宽离群按参校字证实豁免（史記台账 R011／R013，A22 11-13）：`eval/seg_screen` 的 cell_size、page_pitch、half_width 离群格，参校字落在字形匹配前 3 名、邻格无反证的不报，记 `geo_ref_ok` 表；Step3 挪过格位表的列不豁免。只读工具，不进产物指纹。

- PATCH：换单落票核对两种票都读（ZM 11-13，第五册 005-r13 的 25 票漏落）：`republish.old_rev_votes` 原先只读按单版记的票（`?rev=`），且没令牌又没快照时静默当 0 票；现在同时读按单版票和按条目票（`?items=1`，换成现行格号），读不到来源就停。换单门 `votes_gate`、`proof_cycle`、`text_release` 都经它。脚本改动，不进产物指纹。

- PATCH：wu 嗚鳴 规则修正（QTW 回测 130 格，A31 11-13）：ming-禽獸聲、ming-器聲 加 `(?![呼乎咽哉])`，「蕭瑟鳴呼」「之鶴鳴呼」不再与 wu-嗚呼 冲突，判嗚。只改 `config/groups/wu/rules.yaml`（底库文件，要出新底库）。

- PATCH：字组 wu 嗚鳴（全唐文 QTW 经 Ops 转，A31 11-13）：本书嗚的刻形与库里鳴的刻例看图分不出，按文意定（L1 规则→L2 表→L3 裁定库，未决的问进 llm_queue），补放＋复核，文意 strong 才改字。**放进 `registry.OPT_IN_GROUPS`，需点名才开**（册配置 `group_flow` 写缺省名单＋`wu`），没点名的册产物逐字节不变，code_equiv 已登记 `groups.registry`。新增底库登记文件 `config/groups/wu/rules.yaml`（corpus-registry），钉了语料总号的册要配新底库后再钉。顺带修 `test_codepoint_groups_flow_only` 漏算 OPT_IN_GROUPS（zw 起就红）。
- PATCH：恢复 #1488 误删的 code_equiv 登记（align_ref f235b50d、align_ref_coord 9de0c6ed、row_segment 6dde638e、row_segment_pagemap a71017d1 四条），补入 v0.7.17 线的 row_segment fb60a8eb；新增 `scripts/check_code_equiv_monotonic.py`（登记链只增不减检查），版本号规矩加一条。只动登记表与脚本，不改任何 Step，产物指纹不变（A31 11-13）。


- strokes 加 `ink_gap`（沿两点连线量落墨比例与最长断口，「笔画接不接」）、`ClassStats.max_z`／`llr_decide(max_z=)`（离哪一类都远就弃权）；L1 纯算法，不被 Step 引用，不动指纹。全唐文已放行 日曰／己已巳／千干 6,450 格按册留出，见 ai-team 笔画识别-研究 扩组2（A23 11-13）。
- PATCH：重跑后覆盖逻辑清查（ZM 11-13，只动 scripts/zhengli，不进任何 Step 指纹）：①`proof_cycle.human_chars_of` 改调 `feedback.lookup.human_chars`（过绑定表，对沙箱产物算），换图源后失效的老人裁不再被当成「被机器推翻」（殿本 vol03／05／08／09／18／20 线上单有 14 条这类假复审）；机器推翻人裁的复审行第 4 列带上旧人裁的字（出单门归一比对、网站「已有判断」靠它）。②`republish.py` 加 `sheet_gate`：push 前跑 guji-manager `review.sheet_audit`，机器无字当推翻人裁、失效旧人裁当被推翻、码位归一后同字、锚点格混进判字单、重复格都拦（`--ack-sheet-audit "<原因>"` 放行）；prep 把体检写进差异单。③锚点类待审格（A01/A02）随 manager 改放待审单旁表 `anchor_cells[]`，不进判字用的 `cells[]`。需 guji-manager ≥ 0.4.46。

- PATCH：align_ref `coord_dp` 加书级参数 `coord_dp_skip_cost`（缺省 0 不进 dump）：每次跳过扣分＋整理本字在前几名候选里记 0.5 分，不再为一处载体字吻合把整列整理本字错开一格（史記 r53 33:101:5、35:84:2、37:194:3 错放）。align_ref、align_ref_coord 的 code_hash 变，已登记 code_equiv（关着时指纹值不变）（A22 11-13）。
- PATCH：row_segment 的 pins 档格位表指纹与夹注参照指纹只算本册钉位点名的 daizhige 源文件（史記 0244.jsonl 入库不让 01–17 册过期；#1463）。row_segment、row_segment_pagemap 的 code_hash 变，已登记 code_equiv（指纹值不变）。
- 切分筛查加 page_pitch（正文格高对本页中位：整列偏 >10%、单格 ≥1.5／≤0.6 倍）、half_width（夹注半格宽对本册中位 0.7–1.4、同号 a/b 宽差 >30%），只读产物、不进指纹（A22 11-12）。
- scripts/seg_fork_drift.py 加 `--ws <书仓>`：比书仓 code/ 覆盖模块与 cv 缺省实现（分叉点取书仓文件首次提交时刻），整份同缺省时提示可去掉覆盖。` 下加一行；切 rc 时改成 `## [X.Y.Z] - 测试中`，发版时改成日期（见版本号规矩第三节）。

## [未发版]

- PATCH：Step3 行切分书级钩子 `row_hooks` 加 `jiazhu_pair_ok(patch, ink_threshold, forced)`（判一格是不是真并排两字；人指认小注格与段内格各查一次，判否就不拆），`jiazhu_heads` 多传 `ruler`（全唐文 k8 撤掉 row_boundaries／jiazhu_split 整文件 fork 用）。缺省 None 不调，殿本、史記产物和指纹不变；row_segment、row_boundaries、row_hooks 登 code_equiv，全唐文另登两项 SPLITS，各册 row_segment 指纹不变。
- PATCH：删没书开、关时不进参数 dump 的切分开关（A22 开关收敛 L0 批，A20 11-14 定）：`border_detect.merge_narrow_pair`、`border_detect_gate.pagetype_model`（含 path、fingerprint）、`column_gate.period_edge_fallback`、`row_segment.colgold_prior`／`colgold_fingerprint`、`row_segment.yolo_merge`（含 `yolo_*` 六个）及只在开着时走的代码。四个模块登 code_equiv（殿本 vol01 13 页逐字节同），各书产物不过期。册配置里还写着这些键的会被静默忽略（没有书写）。`pagetype_model` 包、`impl/keben/column_pair_merge`、`yolo_tool_infer` 模块留着（闸认旗、研究脚本还用，且在 code_deps 里）。关时也进 dump 的另一批（page_survey_block、hint_ignore_dash、narrow_reject、dash_blank 等）随统一重跑轮删。

## [0.7.34] - 2026-11-13

- 发版说明（A31 11-13，全唐文 QTW 要）：dev 头 `e1b1505d` 的正式版（dev 线，接 v0.7.31；v0.7.32／33 是史記 patch 线不在这条链上），PATCH。含 #1526（seed_admit 书级 `group_flow_ruling_first`：名单里的字组文意先查对话裁定库，缺省空＝关，不进参数 dump；全唐文 book_defaults 加 `group_flow_ruling_first: [jys]` 才开）、#1517（follow_ref 钩子 rival_skip，缺省不调）、#1523（align_ref `coord_legacy_line_guard`，缺省关）及 seg check／脚本类改动。缺省关的新开关都已登记 code_equiv，没点名的册产物不过期。底库文件没变（相对 v0.7.31），不用配新底库。

- PATCH：align_ref 书级开关 `coord_legacy_line_guard`（缺省关，A22 11-13，史記 r60 37:2:6）：参校本一列缺字时现役 difflib 按整页字流把图上多出的字配到别行同字、下一列整段错配，坐标对位被冲突闸整列退回。开了以后列↔行已定的列里，现役 equal 字不在本列整理本行里的格不当现役证据，坐标给了字的改坐标字。关时殿本 vol60、史記 37 全册逐字节同（code_equiv 已登记）。

- PATCH：seed_admit `follow_ref` 加书级钩子 `impl/keben/follow_ref_hooks.rival_skip`（缺省 None 不调）：书仓覆盖后，算领先差时指定的字不当对手（史記同族第三形 吴呉吳、嵗歳歲，SJ 请求、A24 定规则，实现进史記书仓 code/）；钩子经 `facts(a, b)` 拿关系层事实；被排除的字记 `lane.rival_skip`。cv 不加开关。code_equiv 已登记，殿本 vol28 16 页逐字节同，seed_admit code_hash 不变（A22 11-13）。
- PATCH：重生成 `doc/4-定字/字组/字组总表.md`（wu 嗚鳴 那行我手写过，和注册表生成的对不上，manager 的比对测试红了）。只改文档（A31 11-13）。

## [0.7.31] - 2026-11-13

- 发版说明（A31 11-13，全唐文 QTW 要）：基于 v0.7.30，只多 #1512（wu 规则修正，只改底库文件 `config/groups/wu/rules.yaml`）。PATCH。**要配新底库（b24）后再 `guji corpus pin`。**

## [0.7.30] - 2026-11-13

- 发版说明（A31 11-13，全唐文 QTW 要）：dev 头 `018f9d57` 的正式版（基于 v0.7.29，只多 #1508 lookup 分片不存在不报错、#1509 字组 wu 嗚鳴），PATCH。**wu 需点名才开**（册配置 `group_flow` 写缺省名单＋`wu`），没点名的册产物逐字节不变，code_equiv 已登记 `groups.registry`。**新增底库登记文件 `config/groups/wu/rules.yaml`，钉了语料总号的册在 v0.7.30 上起跑前要配新底库后再 `guji corpus pin`。**

- PATCH：`lookup._shard_items` 分片文件还不存在（FileNotFoundError）按「没有人工指定」返回空表，不报错；只有真读坏了才报（接 #1506，manager CI `test_resolved_cuts_empty_when_store_unavailable` 暴露）。（ZM，11-13）

## [0.7.29] - 2026-11-13

- 发版说明（A31 11-13，覆盖逻辑线／各书要）：dev 头 `f509b605` 的正式版，PATCH，**含 #1467**（row_segment 1.50 大印印边墨，row_segment 起判过期）、#1505（字形库重绑尊重作废标记，改产物、不登等价）、#1503／#1504／#1506（republish 出单前查原图、bind_check 用正式 book_bindings、lookup 读不到分片／绑定表时报错，`GUJI_LOOKUP_LENIENT=1` 可回退），以及 snap_cut／cut_through／stroke_veto 等 dev 上已合的其余改动（均缺省关）。不是史記 patch 线（史記钉 v0.7.18），钉不钉由各书自己定。

- PATCH（改产物）：`feedback/lookup.py` 读人工指定分片（抬头/列数/夹注单列/粘连列切线）和 `human_chars` 的绑定表时，读不到不再悄悄退回空表／按格号，改为报错（`GUJI_LOOKUP_LENIENT=1` 可退回旧行为并打警告）。此前这些静默回退会让人的指定在重跑里悄悄失效、之后又冒出来。（ZM，11-13）

- PATCH（改产物）：`rebind_library_shapes`（字形库人裁重绑）尊重作废标记：字形库 `human_stale_*`／`stale_verdicts.tsv` 撤下之后没有再裁的格，库里那份不再顶上。此前重绑只看该格号最新事件的锚，误锚的人裁（vol01 182:9:15a「宅」）撤下后仍会在重绑时落回去。（ZM，11-13）
- PATCH：republish `bind_check`（出单时“人裁绑定：N 条 {…}”那行，也是 id_mismatch／unbound 的来源）改用正式的 `book_bindings`（带字块图缓存／现切、字形库、补锚档），不再用几何口径的 `compute_page(cache=_NoCache)`——后者没图可比，没有框的老人裁一律判 unanchored（vol04 报 631 绑不上，实际 570 valid；补上 109 条 cellvotes rebase 迁移事件的框后 679 valid）。（ZM，11-13）

- PATCH：republish from-pack/issue 出单前查原图在不在（`need_source_images`）：人裁绑定要现切字块图比像不像，原图没拉时 vol04 682 条只绑上 51（拉了原图后 570），老人裁被静默判成 unanchored。现在没原图直接停并提示 `guji source pull`。读者侧冒烟的 HEAD 请求带 Referer（data.openguji.com 图防盗链，无 Referer 一律 403，云端容器里必误报）。（ZM，11-13）

- PATCH：seg check `cut_through` 的「挪得开」从降到原位 1/10 放到 1/4（`CUT_KEEP` 0.1→0.25，A22 11-13）。史記人裁格框尺子（37 册 116 列，去掉人裁重切 1,855 条格线；人挪过且原线劈字 58 条）：报出 23→33 条，报出的里头人也挪过的 86%→81%。顺带量了 U-Net 裁判：58 条里认人线 46（门槛 0）→54（0.05），#1496 的护栏门槛有独立佐证。只读产物，不进指纹。
- PATCH：snap_cut 整字护栏门槛 `seg.cut_select.MOVE_TOL` 0→0.05（A22 11-13）：史記 42 册 9 页 snap_cut 原拦下 15 条，Sheldon 看图修钩尖笔尾的 9 条该放（一致率只掉 0.002–0.043：武丁、殷本、屬爵、以争、釐、善、義、江夏…），挪进字内白缝的 6 条该拦（掉 0.055–0.18：之×2、帝辛、忠、魯、之士）。放到 0.05 后多放行 8 条、之士照拦。snap_cut 关（殿本、全唐文）逐字节不变，cut_select code_hash 变，已登记 code_equiv。
- PATCH：seg check `cut_through` 的 U-Net 裁判门槛从「挪后一致率比原位高 0.02」改成「掉不超过 0.09」（Sheldon 11-13 看史記 42 册 16 条：挪坏 5 条一致率都掉 ≥0.105，挪好 11 条多数只掉 0.01–0.08）：史記 9 页 3→9 条全对、挪坏的全拦；殿本 vol30 1→5 条。只读产物，不进指纹。
- PATCH：`guji seg check` 加 F6 `cut_through`（格线劈字，A22 11-13，Sheldon 同意并进；量法出自 SJ 史記 r54）：相邻两格分界按连通块量切割量（Step3 选了折线按折线量），≥0.025 格高² 且 ±0.4 格内能挪到原位 1/10 以下，再过 U-Net 归属裁判（挪后一致率比原位高 0.02）才报，一条线一行、value 强｜中；没 torch／权重不跑、summary 注明。殿本 vol30 全册不过裁判 33 条看图几乎全是两字相粘处格线本来对（最省墨处在字内白缝），过裁判剩 1 条；史記 42 册 9 页 16→3 条都真劈字；长钩尖伸进下格裁判也判归下格，查不出。只读产物，不进指纹。
- PATCH：snap_cut 整字护栏（防横点字劈开，A22 11-13）：snap_cut 开着时格线的每个去处先过 U-Net 归属裁判（新原语 `seg/cut_select.move_keeps_glyphs`：看上下两格整个窗口，挪后一致率不低于原位才许挪），不再挪进「一二三」「辛」「思」「魯」「爵」这类字的上下部件之间的白缝。史記 42 册 9 页 snap_cut=0.4：原挪 67 条里 15 条挪进字内白缝，护栏拦下 14 条（剩 1 条是相邻格线后挪造成的次序差），放行的都落在字缝。snap_cut 关（殿本、全唐文）逐字节不变，row_boundaries、cut_select 的 code_hash 变，已登记 code_equiv。
- PATCH：seed_admit 加笔画反向护栏 `stroke_veto`（书级模型路径，缺省空＝关、不进参数 dump、行为不变；新模块 `groups/stroke_veto`，用 #1474 的笔画识别）：已放行非人裁格，放行字在 己／已巳、千／干 组里而笔画判出另一类 → 降审，doubt `stroke_veto`（全唐文形近字线 11-13：扩组2 001–030 放行错 24 格笔画全判对）。
- PATCH：row_segment 书级参数 `snap_cut`（格高倍数，缺省 0＝关、不进参数哈希；GUJI-771，史記 r54 格线劈字，A22 11-13）：格线定下后，仍劈着字的内部格线按墨块切割量（`seg/seam.cut_cost_profile`／`cut_cost_sides`，新原语）在 ±snap_cut 格内挪到切割量最小处，只往被劈小截那边挪；去处护栏 `snap_gap_ok` 留给字内白缝判据。史記 42 册 14 页 snap_cut=0.4：强档劈字 49→0、中档 247→122；37 册 12 页 45→8；格号不变。row_segment、row_boundaries、seg.seam 的 code_hash 变，已登记 code_equiv（关时逐字节同）。
- PATCH：row_segment 1.50 表说整列空的列记空认大印印边墨（`_in_seal(stain_ink=True)`）：格与大印框重叠不到一半、但格里 ≥70% 的墨（按连通块）落在印框里也记空；有字的列、丢字、挑格网仍按框重叠。史記 r53 印边压相邻空列碎格（SJ 11-13）。row_segment code_hash 变（不能登记等价）：史記 42 册 78 个大印页 6 页变（5 页假字格改空、1 页空列格线挪）；殿本 15 册 23 个大印页逐字节同；全唐文 005–011 无大印。

## [0.7.27] - 2026-11-13

- 发版说明（A31 11-13）：v0.7.26 + #1496，PATCH，不含 #1432/#1437、也不含 #1495（依赖 #1494 的 cut_through）。dev 已含 #1496，本条仅补记发版。

## [0.7.26] - 2026-11-13

- 发版说明（A31 11-13）：v0.7.25 + #1492，PATCH，不含 #1432/#1437（史記 patch 线用）。dev 已含该改动，本条仅补记发版。

## [0.7.25] - 2026-11-13

- 发版说明（A31 11-13）：v0.7.18 + #1467 + #1490，PATCH，不含 #1432/#1437（史記 patch 线用）。dev 已含这些改动，本条仅补记发版。

## [0.7.24] - 2026-11-13

- 发版说明（A31 11-13）：v0.7.23 + #1474 + #1487 + seed_admit code_equiv 登记，PATCH，不含 #1463/#1465–#1468。dev 已含 #1474/#1487，本条补记发版；code_equiv 登记（stroke_veto 缺省关，seed_admit 代码指纹 ≡ v0.7.23）同步进 dev。

## [0.7.28] - 2026-11-13

- 发版说明（A31 11-13，ZM 殿本线）：v0.7.23 + #1497，PATCH，**不含** v0.7.24–27（史記线，含 #1467）与 dev 上的 #1432/#1437。
- `coord_conflict_drop_bad` 丢掉的冲突格，现役对位记录里的字改成坐标字（op 记 replace）：待审单的参校字显示坐标字，不再显示现役配错的字（殿本 vol05 1:4:1 周／撰）；现役字与库首选不再互证。开关关着行为不变。

## [0.7.23] - 2026-11-13

- 发版说明（A31 11-13，ZM 殿本 vol05 p1 列 4）：v0.7.22 + 下面一条，PATCH。
- `coord_conflict_drop_bad` 加稀疏列例外：同列现役 equal 只有冲突这一格、没有全同格、现役字不是邻格坐标字时，也只丢该格（原口径要全同格 ≥3）。开关关着行为不变。

## [0.7.22] - 2026-11-13

- PATCH：重跑后覆盖逻辑清查（ZM 11-13，只动 scripts/zhengli，不进任何 Step 指纹）：①`proof_cycle.human_chars_of` 改调 `feedback.lookup.human_chars`（过绑定表，对沙箱产物算），换图源后失效的老人裁不再被当成「被机器推翻」（殿本 vol03／05／08／09／18／20 线上单有 14 条这类假复审）；机器推翻人裁的复审行第 4 列带上旧人裁的字（出单门归一比对、网站「已有判断」靠它）。②`republish.py` 加 `sheet_gate`：push 前跑 guji-manager `review.sheet_audit`，机器无字当推翻人裁、失效旧人裁当被推翻、码位归一后同字、锚点格混进判字单、重复格都拦（`--ack-sheet-audit "<原因>"` 放行）；prep 把体检写进差异单。③锚点类待审格（A01/A02）随 manager 改放待审单旁表 `anchor_cells[]`，不进判字用的 `cells[]`。需 guji-manager ≥ 0.4.46。

## [0.7.21] - 2026-11-13

- 发版说明（A31 11-13，ZM 殿本 vol05 对位冲突整列退回）：v0.7.20 + #1478，PATCH，不含 dev 上的 #1463/#1465–#1468 及 dp_skip_cost。
- align_ref 加缺省关的书级开关 `coord_conflict_drop_bad`：「与现役对位冲突」的列，同列现役 equal 与坐标全同格 ≥3 且不少于冲突格数、冲突格没有整列错位迹象时，只丢冲突格、列照用（比 `coord_conflict_pair_only` 宽，不限 2 格、可相邻）。开关关着行为不变。

## [0.7.20] - 2026-11-13

- 发版说明（A31 11-13，ZM 殿本 vol01 001-r18）：v0.7.19 + 下面一条，PATCH，不含 dev 上的 #1463/#1465–#1468。dev 上同一修复为 #1476。
- `republish.py from-pack` 的 `bind_check` 和 `pending_route` 的「扣已裁」先剔除被后来人裁 `payload.overrides` 推翻的旧人裁：旧裁绑到别格（iou 低）或 unanchored 时，不再把新裁已生效的格误判成 id_mismatch 塞进 keep.txt、留在单上。只动 scripts/zhengli，不改 Step，code_hash 不变。

## [0.7.19] - 2026-11-13

- 发版说明（A31 11-13）：v0.7.16 + #1470，PATCH，不含 #1463/#1465/#1466/#1467/#1468。dev 已含该修复，本条仅补记发版。

## [0.7.18] - 2026-11-13

- 发版说明（A31 11-13）：v0.7.17 + #1468，PATCH，不含 #1432/#1437（史記 patch 线用）。dev 已含该修复，本条仅补记发版。

## [0.7.17] - 2026-11-12

- 发版说明（A31 11-12）：v0.7.15 + #1463，PATCH，不含 #1432/#1437（史記钉 v0.7.15 线用）。dev 已含该修复，本条仅补记发版。

## [0.7.16] - 2026-11-12

- 发版说明（A31 11-12）：v0.7.14 的后继，PATCH。v0.7.14 漏登 seed_admit code_equiv（#1452 改了 seed_admit 代码），已补（v0.7.14 与本版两条登记，A22 在史記 01 册 23 页验）；另含 #1456 `solo_coord_dissent`（缺省关）。含 #1432（alt_cut 备选格全同不出），钉本版的书若开着 alt_cut，row_segment 会过期。史記整书线钉 v0.7.15（v0.7.13 + #1452 + #1456，不含 #1432）。
## [0.7.14] - 2026-11-12

- 发版说明（A31 11-12）：dev 上 v0.7.13 之后的全部改动，PATCH；含 seed_admit `vis_ruling_half`（缺省关）。
## [0.7.15] - 2026-11-12

- 发版说明（A31 11-12，SJ 史記整书线要）：基于 v0.7.13，只多 #1452 `vis_ruling_half` 与 #1456 `solo_coord_dissent`（均缺省关、不进 dump），**不含 #1432／#1437**（史記开着 alt_cut，#1432 会让 row_segment 过期）。PATCH。seed_admit 的 code_hash 变化，缺省关的书已登记 code_equiv（史記 9 页逐字节相同），缺省关的书 seed_admit 不过期。
- seed_admit `vis_ruling_half`（书级，缺省关、不进 dump；A31 11-12，SJ 史記）：`group_flow_llm_skip_half` 开着时，有放行型看图裁定的夹注半格也能放行（裁定 cell＝当前格号、字＝整理本字、无 clipped／frame_residue／jiazhu_*／split_* 疑点；evidence.half=True）。金标 3 格 0 错。PATCH。
- 切分筛查新判据 `eval/seg_screen.odd_cell_heights`（表 `cell_size`）：一列里格高 ≥1.7 倍中位（多半两字并一格）或 ≤0.5 倍（一字拆两格）。在殿本 vol01 旧包（11-09）上量召回时发现：ZM 11-12 钉的职名页并格四列格高都是中位的 1.8–1.9 倍，原有判据只靠成串 FOR 抓到；整册 1724 列只有 6 列命中。不进指纹。
- `eval/seg_screen_run`：钉子列按产物的 `manual_cells` 旗认（产物早于钉子的列照普通列查），新表 `pin_stale` 列出「有 active 钉子、本页产物没用上」的列（要从 row_segment 重跑）。不进指纹。
- 切分筛查并进史記快筛的格级判据（`guji seg check` 用，《切分三方向》第 2 步）：`eval/seg_screen` 加 `ink_ledger`／`ledger_flags`（FOR、Lh、Lv）、`end_frame_hits`（Fend）、`patch_edge_lines`（Fpatch）、`jiazhu_wide`（JZW）、`pin_slots_diff`（钉子列只比格号）、`layout_slots_diff`（版式对格号，同数判过）；跑法搬进 `eval/seg_screen_run.py`（`scripts/seg_screen.py` 变薄壳，多出 cell_flags／pin_slots／layout_slots 三张表，缓存缺图现算）。原语 `seg/rules` 加 `vertical_rule_mask`／`horizontal_rule_mask`。殿本 vol01 6 页非钉子列格级 flags 与 SJ `tools/seg_check/seg_detect.py` 逐格相同。不进指纹，产物不变。
- 新原语 `seg/rules.py`：`long_rule_mask`／`strip_long_rules` 剥长直线（界行竖 200px、版框横线 0.85 列宽且至少 40px，参数在签名上）。史記 patch_clean、史記快筛、`eval/seg_screen` 原先各抄一份；`eval/seg_screen.strip_long_lines` 改调它（逐像素同，有单测）。不进任何 Step 指纹，产物不变。
- 切分人定覆盖统一读取入口 `feedback/seg_overrides.SegOverrides`（列级 manual-cells／抬头／column-slots／cuts／pins／solo／forced 一处读，`blocks_layout` 定哪些屏蔽格位表），row_segment 改用；row_segment 新书级钩子 `impl/keben/row_hooks`（`grid_adjust`／`jiazhu_heads`／`half_a_left`，缺省 None），全唐文可不再复制整份 row_boundaries。code_equiv 已登记（殿本 vol01 11 页、vol28 10 页逐字节同），**各书产物不过期**。
- row_segment `alt_cut` 备选与主切法有字格（框、种类、半边）全同、只差空格框或格号的不再出（SJ r43 09:194:5 闸判抬头一格、表是 0，备选格号 -1..14 被 seed_admit 选中、整列格号减一）。开了 `alt_cut` 的书参数 dump 加 `alt_cut_rev`，**只有史記 row_segment 起过期**；关着的书 code_equiv 已登记（殿本 vol28 15 页、全唐文 001 13 页逐字节同），殿本、全唐文不过期。
- strokes `ClassStats` 加各类自己的标准差（`sds`）与似然比判 `llr_decide`：两类散布差很多（木 紧、本 散）时合并方差会判错；全唐文已放行 15,477 格按册留出（别册放行格学类分布），木本 不一致 23→5、人入 29→6、未末 25→0。不被 Step 引用，产物不变。
- 5a 精验可选度量学习 CNN（`glyph_match.sim_model`，缺省关；A23，Sheldon 11-10 同意接进 pipeline 按书测）：新模块 `clustering/sim_cnn.py`（`SimNet`、`CnnVerifier`，整库嵌入算一次，逐对分＝余弦），训练脚本 `scripts/train_glyph_sim_cnn.py`。全唐文端到端（同一 kNN 粗排与护栏）首位命中 99.41→99.74%、精度 99.9% 下 same 放行 74.3→78.7%、每格 28→14 ms。关着时 `sim_model`／`sim_model_sha` 不进参数 dump，glyph_match 代码等价已登记（keben 3 页逐字节相同），**各书产物不过期**；开着时权重 sha256＋sim_cnn 代码哈希进参数指纹。开了要按书重标 `consensus_cov`／`consensus_margin`、`font_tier.cov`。
- 模型表登记全唐文 5a 相似度 CNN `models/glyph_sim_qtw/model.pt`（新种类 `glyph_sim`，owner 全唐文 995ejelvk0，消费者 glyph_match；已传 R2，sha 289fdf56…；Sheldon 11-12 同意）。出处进 `config/model-provenance.json`。只是登记，不开开关、不改 Step，各书产物不过期。
- 5a 相似度 CNN 分数校准与平均分（`glyph_match.sim_model` 仍缺省关）：权重旁 `calib.json`（`sim-calib/1`，`scripts/fit_glyph_sim_calib.py` 按同等误配率拟合）把 CNN 分映射到 cov 尺度，seed_admit／align_ref 约 30 个 cov 门槛不用逐个重标；`fuse: mean` 再与覆盖分取平均。全唐文 006 册 A/B：只用 CNN 送审 31→28 但库外字被认成形近字（廬→盧、樹→榭）约 4 格；fuse mean 送审 31→22、新放行 9 格看图无明确错。训练脚本加 `--init`／`--lr`（库小的书拿别书权重起步微调）。模型表登记 `models/glyph_sim_qtw/calib.json`。sim_cnn 不进 code_deps，**各书产物不过期**。

## [0.7.13] - 2026-11-12

- 发版说明（A31 11-12，SJ 整书线要）：基于 v0.7.12，只多 `scripts/code_equiv.py` 的 PYTHONPATH 追加（#1442）。PATCH。只动脚本，不碰 Step，`code_hash` 不变，各书产物不过期。
- PATCH（A31 11-12）：`scripts/code_equiv.py` 起子进程时 PYTHONPATH 改为「被比检出放最前、原有 PYTHONPATH 追加在后」，不再整个覆盖（原先 guji_manager 靠 PYTHONPATH 指向源码检出装的找不到）。只动脚本、不碰 Step，code_hash 不变。

## [0.7.12] - 2026-11-12

- 发版说明（A24 11-12，SJ 要）：基于 v0.7.11，只多 #1438（`follow_ref` 表项不再接管 `follow_ref_variants` 路径）。PATCH。史記 r45 给 follow_ref 追加 嵗=歳 后，嵗 的格 ids 判 歲，原来靠 variants 改回整理本 嵗，表里有了 嵗 这一项后表路接管、只认 歳，歲 就留下来了。修：整理本形在表里、本格字不是表里那一形时，只要开了 `follow_ref_variants` 且同义异体，仍按参校本取异体改回整理本形。**受影响面：开了 `follow_ref_variants` 且 `follow_ref` 表非空的书（目前只有史記），seed_admit 起过期，要从 seed_admit 重跑（影响不止 嵗：表里每个整理本形此后都会走 variants，带出此前不改的同义异体改字，史記 r47 实测 吳→呉 6 格，看图与整理本均是呉）；其它书 dump 不变，`code_equiv` 已登记 seed_admit（按代码论证，未做逐页比对），不过期。** `seed_admit` 参数 dump 对这类书加 `follow_ref_variants_rev: 1`。不含 dev 上的 #1394、#1429–#1437。无底库变更。

## [0.7.11] - 2026-11-12

- 发版说明（A31 11-12，SJ 要）：基于 v0.7.10，只多 #1413（字组 zw 丈文：文意规则＋参校本同字才放行），**但 zw 改成需点名才开**：放进新表 `registry.OPT_IN_GROUPS`，不进 `GROUPS`（否则会改 `glyph_match` 弱命中等全书行为）、不进缺省 `group_flow`（`generic_flow_names` 不含）。没点名 zw 的册产物逐字节不变，`code_equiv` 已登记 `groups.registry`（SJ 11-12 在史記 03/09/02 各 7 页上证 seed_admit 在 zw 未点名时逐字节相同），殿本、全唐文不会因此过期。要用 zw 的书（史記）在册配置 `group_flow` 里显式写缺省名单＋zw。不含 dev 上的 #1394、#1429–#1431。**注意：#1413 新增底库登记文件 `config/groups/zw/rules.yaml`（corpus-registry），钉了语料总号的册在 v0.7.11 上起跑前要配新底库 b<M+1>（`guji corpus build-base`，需写令牌）后再 `guji corpus pin`。底库 b22 已由 Ops 出（比 b21 只多 config/groups/zw/rules.yaml）。**

## [0.7.10] - 2026-11-12

- 发版说明（A31 11-12，SJ 要）：基于 v0.7.9，只多 coord_ref_hint（GUJI-767 第二步，#1426，不含 dev 上的 #1413 字组 zw 规则与 #1394）。PATCH。缺省关，各书产物不过期、不用重跑。
- PATCH（A31 11-12，GUJI-767 第二步）：align_ref 加通用开关 `coord_ref_hint`（缺省关、不进参数 dump；要 `coord_dp` 开着）：`coord_dp`／`coord_dp_flat` 对位得出但无字形证据所以不进 `coord` 的整理本字，记进 `PageAlignRef.ref_hint`（{格 id→整理本字}，空不落盘），只供点校当候选，不是放行证据，`coord`／`chars`／放行结果都不变。史記 r42 圈号邻字 A9 45 格（整理本有字而字形库误读）用。align_ref、align_ref_coord 的 code_hash 变，code_equiv 已登记（SJ 11-12 在史記 03/09/02 各 7 页上证关着时逐字节相同）。

## [0.7.9] - 2026-11-12

- 发版说明（A31 11-12，SJ 要）：基于 v0.7.8，只多 #1421（不含 dev 上的 #1413 字组 zw 规则）。PATCH。缺省关，各书产物不过期、不用重跑；史記 r4x 要开才用 `coord_relaxed`＋`coord_circle_ext`。
- PATCH（A31 11-12，GUJI-767）：align_ref 加通用开关 `coord_circle_ext`（缺省关、关时逻辑不变、不进参数 dump，要 `coord_relaxed` 开着）：圈号「○」认定放宽到字形库前 3 名、夹注 a/b 全圈号的整格算圈号格、`coord_dp`／`coord_dp_flat` 跳过圈号格并补记空格位、有圈号而几何拟不上时按格号配。史記 r41 因 ○ 对位错开的 56 列用。align_ref、align_ref_coord 的 code_hash 变，两条 code_equiv 已登记（SJ 11-12 在史記 03/09/02 各 7 页上证关着时逐字节相同）。小圆环形状判据待 A22 出原语。

## [0.7.8] - 2026-11-11

- 发版说明（A31 11-11，QTW 要）：基于 v0.7.7，只多 #1418（不含 dev 上的 #1413 字组 zw 规则，它会改识别结果，留下一版）。PATCH。缺省关，各书产物不过期、不用重跑；全唐文 016–030 要开才钉。
- seed_admit 书级开关 `consensus_lib_cov`，缺省关、关时逐字节不变、不进参数 dump，code_equiv 已登记：5a 共识升档判 same、库字就是库首位、cov ≥ 本值、无护栏／硬疑问、不是 己已巳 的仍待审格，放库字（通道 `consensus_lib`，不入字形库）。`consensus_fallback` 把库字≠整理本字的共识 same 退回 unsure 后，这批格常卡在准入。全唐文 f4 016–030 这类 88 格，cov≥0.97 的 78 格看图 0 错；同门槛普通 unsure 错率 35%，所以只认共识升档。排在各补放通道与 near_knn_gap 之后，形近字组判留审的格不碰。本机开 0.97 实跑 016–030 放 81 格：55 格整理本是别字（剌/刺、寖/寢 等）、23 格无整理本字，看图 79 对、1 存疑；唯一错格（028:29:7:12 百→白）和一/二 组的黑条格已由这两条闸挡掉。字形线 11-11。
## [0.7.7] - 2026-11-11

- 发版说明（A31 11-11，A22 要）：基于 v0.7.6，只多 #1414（不含 dev 上的 #1413 字组 zw 规则）。PATCH。code_hash 不变、各书产物不过期、不用重跑。只影响缓存再生，史記本机旧缓存要清。
- 不经 Engine 直接建的 RunContext（`guji cache get／warm`、控制台、审阅卡）补上书仓 `code/defaults.yaml` 套书缺省参数层，再生的列图、字块与跑步时一致（#1414，A22；SJ r39 03:177:8:21b「約」丢糸旁）。PATCH，23 步 code_hash 不变，各书产物不过期。

## [0.7.6] - 2026-11-11

- 发版说明（A31 11-11，SJ 要）：基于 v0.7.5，只多 #1410。PATCH。
- cell_shrink：`manual_ink_fit` 不抹本格跨框笔画（#1410，SJ）。只有开了 manual_ink_fit 的书（史記）cell_shrink 起过期；殿本、全唐文已登 code_equiv `_MF_1111`，不过期。

## [0.7.5] - 2026-11-10

- 发版说明（A31 11-10，史記 GUJI-750 要）：基于 v0.7.4 + #1403–#1406、#1408。PATCH。
- seg_pins_check（#1403–#1406，SJ）：沙箱失败判不通过、补锚按旧绑定位置取框、缺切点裁判权重或字形库拒跑；沙箱模式也认 `--base-items` 当基线；老失锚不计入结论；补锚草稿已有锚行的事件原地替换（出 `anchors_merged.jsonl`），第四节补锚档 (event,key) 重复判不通过。只动 scripts/ 与 feedback/pins_check.py。
- cell_shrink 加书级钩子「发前清格」（#1408，impl/keben/patch_clean，缺省不清；SJ 要，史記书仓 k4 需 cv ≥0.7.5）。
- cell_shrink 人工定框列加书级开关 `manual_ink_fit`（#1405，A22，缺省关、关时逐字节不变，不进 dump；code_equiv 已登记）。

## [0.7.4] - 2026-11-10

- 出单门：复审格旧人裁与现行字套码位归一后相同就不上单（#1397，ZM；pending_route --codepoints，republish 传本册表）。只动 scripts/，不改 Step code_hash。PATCH。

- auto_cycle 加 `--ack-unlanded-votes <原因>`，透传给 proof_cycle apply → republish issue（ZM 提，ai-team 字的等价与归一审视陷阱 4；`guji swap run` 同名参数透传到这里）。只动 `scripts/zhengli/`，PATCH。

- republish.py 三处文案「文本线升 minor」改 patch（纯文案，用户 11-10 定小改动一律 patch；ZM 提）。L0。

- 格号变动单一路径收尾（ZM 11-10）：republish 遇「格号没变但有增删字」也走格级对照表（`swap.booktext`），不再退出叫人推 a32 分支等 A33；auto_cycle 的 book-text 失败结论改叫 `guard-stop`，提示切坏交切分线、锚点交 A33、修好后 `guji swap book-text --sheet`。只动 `scripts/zhengli/`，PATCH。
- rerun_prep.sh 切到 cv 版本后先从 R2 取回 models/、fonts/、底库语料大文件（PATCH，A30 11-10；SJ r32 的 #1833/#1835/#1839 三单 prep 在「模板索引」段失败）：v0.7 起 cv 仓不带这些文件，从 v0.6.x 切过来时检出把它们删了，`pull-rare-index` 算出的 checkpoint 指纹是 `nockpt`，对不上已发布的向量包（`d2ce8bab0fd0`）。调 `ensure_repo_models()` 取回后指纹为 d2ce8bab0fd0，对得上。只改准备脚本，不动产物、指纹（L0）。
- strokes 差一笔「学门槛」：`verify_learned`（多出那一笔的独占率、落墨率按本书两字刻例类中心判）、`extra_feats`、`bad_fit`。多出那一笔与别的笔交叉的组（木本、目自、十士）固定门槛弃权太多，殿本库留一 木本 弃权 99→2。不被 Step 引用，产物不变。

## [0.7.3] - 2026-11-10

- 发版说明（A31 11-10，QTW 要）：基于 v0.7.2，只多 #1388。PATCH。

- seed_admit 两个书级开关，缺省关、关时逐字节不变、不进参数 dump，code_equiv 已登记：`group_flow_pair_shape_nm_5b`（匹配器护栏 never_match 的待审格，5-b 首位落在两字对里也交 `group_flow_pair_shapes` 刻形判；全唐文 001–003 目录页 王 50 格看图全对，5-b 首位是土的那格挡掉）、`solo_cal_5b_canon`（solo_cal 5-b 档按本书码位表归一后比，5-b 给 慎、库给 愼 算一致；愼 5、吕 2 格）。形近字线 11-10。

## [0.7.2] - 2026-11-10

- 发版说明（A31 11-10）：从 dev 9b5aa9f（#1381）切，只含 #1381，不含之后的 #1383。PATCH；只动 `scripts/zhengli/`，无 code_hash 变化、无需登记 code_equiv。需配套 guji-manager ≥ 0.4.37（`swap.booktext`）。

- republish：book-text 遇增删格／改号改调 guji-manager `swap.booktext`（按新旧 cord 框的格级对照表判字、挪标点专名、守卫），swap run 不再因增删格报 need-A33；proof_cycle 格号变了时不按格号退回「推翻人裁」；换文文本线升 patch（ZM 11-10）。

## [0.7.1] - 2026-11-10

- 发版说明（A20 11-10，SJ 要）：从 dev f666f3d 切，只多 #1378（书级代码第 4 步代码等价，row_segment 指纹回到 v0.6.39，v0.7.0 判的 row_segment 过期撤销）。
- PATCH 登记书级代码第 4 步（#1375）的代码等价：`row_segment`、`impl/keben/row_boundaries`、`impl/keben/jiazhu_step` 进 ENTRIES，新 code_dep `seal_ink` 进 SPLITS（缺省实现合回 jiazhu_step；史記书仓 k2 的 jiazhu_step＋seal_ink 合回 k1 那一项）。殿本／北行／幼學／全唐文与史記（配书仓 k2）的 row_segment `code_hash` 与 v0.6.39 逐位相同，**v0.7.0 起判的 row_segment 过期撤销**。证据：SJ 11-10 史記 02、05 册 10 页产物逐字节相同；缺省钩子分支是删开关后的原路径。

## [0.7.0] - 2026-11-10

- **MINOR**（用户 11-04、11-09 定）书级代码系列收尾＋模型文件搬出 git，见 RELEASES.md v0.7.0。从 dev 1bb3d44 切。
- 书级代码第 4 步（cv #1375，Sheldon 11-10 选「先搬自成一块的，其余留着」）：`row_segment` 删开关 `seal_inkcut`／`seal_gap_slots_empty`／`jiazhu_free_split`／`jiazhu_step_split`，改成书级钩子 `impl/keben/seal_ink`（新）、`impl/keben/jiazhu_step.free_split`（缺省什么都不做），实现搬进史記书仓 `code/`（k2，书仓 PR #1）。书配置写 true 而工作区 `code/` 没覆盖对应钩子就拒跑（`row_segment._RETIRED`）。`row_segment`（及 `row_boundaries`、`jiazhu_step`、`seal_ink`）`code_hash` 变：**各书 row_segment 起过期**（殿本等切法逐字不变）。其余单书开关冻结留 cv（`doc/design/书级代码.md`）。
- 模型文件搬出 git（用户 11-04 定，`doc/design/模型系统.md` 4.2 第 1 条）：`models/` 下 11 个文件 `git rm --cached`、`.gitignore` 忽略 `models/**`（留 README）。真源 R2，按 `config/model-registry.json` 取回：`guji model fetch`、`guji pipeline` 起跑前、测试开跑前、`install_release.py` 装完都自动取（**执行方要有 `GUJI_DATA_TOKEN` 或 `_READ`**，首跑约下 50 MB）。删前核过：表里 87 项 R2 全有，取回与原文件逐字节相同。模型内容不变，不影响指纹。

## [0.6.39] - 2026-11-10

- PATCH（A31 11-10，sheldon 定）`republish.py push／edit-cell／add-alt／add-sprites --sync` 触发网站 proofing-sync 时带 `only=<书>/<章>`（原先 push 等没设 publish_only，整站发布，整站冒烟要好几分钟）。L0（只改发布触发）。

- `human_chars`：人裁因现格字块图拿不到没法认格时，每册 ≤ 20 条默认放行（记 warning，事件不删），超过 20 条才报错拦下；`GUJI_ALLOW_LOST_HUMAN=1` 仍可无上限放行（PATCH，ZM-殿本二册 11-10，sheldon 定）。只改报错路径，产物不变；`lookup.py` 若在某步 `code_deps` 里，该步指纹会变，需要时用 `scripts/code_equiv.py` 登记。

## [0.6.38] - 2026-11-10

- 发版说明（A31 11-10）：从 dev 83bd46b 切，含 #1366（row_segment 1.49：卷端题列起格把框线记空格照旧算上，修 #1357 带来的格号后移，史記 01 p119 c2）。各书从 row_segment 起过期。

## [0.6.37] - 2026-11-10

- 发版说明（A31 11-10）：从 dev 1520d9b 切，含 #1361、#1363（待审条目化：换单逐格对条目、add-cell）、#1362＋#1364（border 越界修复，登等价，不过期）。待审条目要 guji-manager ≥ v0.4.35（旧 manager 照旧整张换单）。

- PATCH（A22 #1362，A31 登等价）`impl/keben/border` 外框采样列越过图宽时去掉（史記09 年表页 border_detect IndexError）；只影响原先崩的页，登 `core/code_equiv`（keben 3 页逐字节相同＋代码论证），各书 border_detect 不过期。

- PATCH（A31 11-10，待审条目化第 2 步）`republish.py add-cell`：单上加一格不换 rev——开待审条目，现行字块图单独出一张 webp（文件名按内容 sha256，传 R2），条目带它、导出时并进 `sprites[]`，网站照旧发布。L0。

- PATCH（A31 11-10，sheldon 定待审条目化）`republish.py push` 换单改为逐格对待审条目（guji-manager `review/pending_items`，`guji pending`）：没变的格条目不动、变了只改字段、新格开条目、不再待审的关掉、人工撤下的不放回；格号与图块指纹（字块图 sha1）都记；导出的整张单每格带 `id`／`ver`（网站按条目记票）。`edit-cell` 有条目时改条目。manager 没有条目模块时照旧整张换。L0。

## [0.6.36] - 2026-11-10

- 发版说明（A31 11-10）：从 dev 7917fa4 切，含 #1354、#1355（edit-cell 单格原地改）、#1356、#1357、#1358（row_segment 1.48 列端框线格记空，各书从 Step3 起重算）。配 guji-manager ≥ v0.4.34。

- 改切分（A22 P5 11-10，#1357）`row_segment` 1.48：列端物理首／末格只有版框线的记空（各书一律），列上打 `edge_frame_only`，格上打 `frame_line`（「不是字」标记，A31 定名，manager resolve 的 `new_not_char` 认它）；软参数 `manual_cells_fingerprint`。**各书从 row_segment 起过期**。同一列别的格 slot、格号、锚不变；book-text 导出时这一格不再出字。
- PATCH（QTW/A22 11-10，#1356、SJ #1354）`seg_screen` 加三项筛查；`seg_pins_retire` 取建钉理由、`keep_for` 的钉子判留。L0。
- PATCH（A31 11-10，sheldon 定「先单格原地改」）`republish.py edit-cell`：线上单单格原地撤下（挪进 `withdrawn[]`）、放回、改说明，不换 rev、不动别的格，已投的票照旧有效；每次操作记 `edits[]`。换单（push）时上一版撤下的格照旧撤下。L0。

## [0.6.35] - 2026-11-10

- 发版说明（A31 11-10）：从 dev d0de2985 切，含 #1333（撤库重审闸）、#1349、#1350（待审格现行有字则 book-text 不动，撤库重审格也保持）。配 guji-manager ≥ v0.4.34。

- PATCH 撤库重审格自动上单（A23，Sheldon 11-09「不论什么版本，撤库就给这格出待审卡，人裁定了再改 book-text」）：`scripts/zhengli/republish.py` prep 读带 `review` 的撤库事件，撤库后没人再裁的格并进复审清单（卡片头显示「撤库重审」），book-text 不因此改字。L0（脚本，不进指纹）。
- PATCH 撤库重审闸 `seed_admit.evict_review`（缺省开，A23，Sheldon 11-09）：库内刻例审阅卡上「撤库」的格（带 `review` 的 `glyph_audit evict` 事件，guji-manager 审阅页出）机器放行一律退回待审（doubt `evict_review`，待审原因 seg_defect）；`feedback/lookup.evict_review_cells`。seed_admit 指纹变；没有这类事件的书产物不变。
- PATCH（A31 11-10，A23 要）`hold_pending_current` 把撤库重审格（`feedback.lookup.evict_review_cells`，cv#1333）也算作待审：现行有字则文本不动，现行是 □ 且无候选也保持 □，人裁定了才改。cv#1333 没并入时自动跳过。L0。

- PATCH（A31 11-10，用户定）`republish.py` 入库前加 `hold_pending_current`：待审格现行 book-text 已有字、首选字不同时文本不动（等人裁定了再改，少改 book-text 提交）；现行是 □／缺格才写首选字。需 guji-manager 含 `apply_pending(current=)` 的版本，旧版跳过并提示。L0。

## [0.6.34] - 2026-11-10

- PATCH（A31 11-10，用户定删 book-text 各书 CHANGES.md）`scripts/zhengli/republish.py` 的 `bump_book_text` 不再传 `--pr TBD`，改收 bump_original 打印的「版本记录」行写进 book-text 提交信息。与 manager、book-text 同名 PR 配套。L0。

- PATCH（A31 11-09，SJ 反映史記 r20 manifest 的 manager_version 为空）`core/contract.manager_version()` 在没设 `GUJI_MANAGER_VERSION` 时取已装 guji-manager 的版本（`m<版本>`，与 manager 子进程口径一致），没装仍为 None。只供审计，不进指纹，L0。

## [0.6.33] - 2026-11-09

- 发版说明（A31 11-09）：从 dev 93e03bc 切，含 #1338、#1339（rerun_prep 修复）、#1340（删 decision_build，book-text 只录首选字）。

- PATCH（A31 11-09，用户定 book-text 只录首选字）删 `scripts/zhengli/decision_build.py` 与其测试；`text_release.py run` 的 G1 改为「线上单待审清零」（不再生成 decision.json、不再算「看不出」占比）；`export_guji_format.py --pending` 提示改为写首选字、不写 pending_reason；runbook E3 注明废弃。待审信息、候选、人裁事件都在 KV。L0（不影响切分／识别产物）。

## [0.6.32] - 2026-11-09

- 发版说明（A31 11-09，A24 要）：从 dev 56f6227 切，含 #1332（seed_admit `textlayer_ref_gap`，缺省关）、#1334（rerun_prep 工作区完整检出）、#1335（#1332 的 code_equiv 登记，殿本 vol04 38 页逐字节相同，seed_admit 指纹不变）。
- 文档（书级代码第 5 步）：`doc/参考/切分代码结构.md` 改成三层（seg／impl 缺省实现／书仓 code/）、各书怎么改自己的切分与出 k<N>；`doc/版本号规矩.md` 加「四库版本号与书级代码」一节；`doc/开关登记表.md`、Wiki「各书一览」换新路径。
- PATCH 书级代码：起跑前比对书仓 `code/` 与 `k<N>` 清单时不算 `*.md`（改 README 不再让钉了 `code: N` 的册拒跑）；设计文档补打 tag 走中转站的用法。L0。
- PATCH 登记 #1332（seed_admit `textlayer_ref_gap`，缺省关）的代码等价：殿本 vol04 新图 38 页与改前逐字节相同，seed_admit 指纹不变（L0）。

## [0.6.31] - 2026-11-09

- 发版说明（A31 11-09，SJ 要）：从 dev 43af102 切，含 #1326–#1328（书级代码 v0.7.0 系列第 1–3 步，L0，各书 code_hash 不变）。史記 r20 切分层钉本版。

- PATCH（v0.7.0 系列第 3 步）史記、全唐文的书级代码搬出 cv：`books/shiji_wyg`（roster_segment、roster_glyph、jiazhu_step、defaults.yaml、samples.yaml）→ 书仓 988g3f0wsu `code/`，`books/quantangwen`（row_boundaries、jiazhu_split、samples.yaml）→ 书仓 995ejelvk0 `code/`，各出 `k1`；相关 6 个测试文件随走（书仓 `code/tests/`）。`seg_set.OVERRIDES` 清空、`SEG_SETS` 去掉 shiji_wyg／quantangwen：**跑这两部书的工作区必须是带 `code/` 的书仓**，没有就报错（不会悄悄走殿本）。等价登记在书仓 `code/equiv.yaml`（moved＋只改 import 的 entries），两部书各步 `code_hash` 与搬前逐位相同（L0）。`scripts/seg_samples.py` 认工作区书仓的样页单。
- PATCH（v0.7.0 系列第 2 步）刻本/现代/自由三条版式的缺省实现改名：`books/siku_zongmu` → `impl/keben`、`books/beixing` → `impl/modern`、`books/zengguang_youxue` → `impl/free`（样页单、defaults.yaml 随走；seg_set 名不变，`seg_set.IMPL_OF`/`set_dir` 对照）。搬家登 `code_equiv.MOVED`、只改 import 的登 ENTRIES（`_MV_IMPL`）：5 套书 × 23 步 `code_hash` 逐位相同（L0）。外部 `from open_guji_cv.books.siku_zongmu…` 要改成 `impl.keben`。
- PATCH（v0.7.0 系列第 1 步）书级代码：各书工作区仓 `code/` 挂成 `guji_book.<name>`（`core/book_code.py`），`seg_set.resolve` 先查书仓覆盖；册配置新键 `code: N`（`k3`）钉书级代码、简写 `pin: c31-g19-m2-k3`（`core/lib_pins.py`）；起跑前钉了 `code:` 的册校验 `code/releases/k<N>.json`；`book_api` 公开面；`guji code` 搬在 guji-manager ≥0.4.30。没有 `code/` 的工作区行为不变：5 套书 × 23 步 `code_hash` 逐位相同（L0）。设计 `doc/design/书级代码.md`。

## [0.6.30] - 2026-11-09

- 发版说明（A31 11-09，QTW 要）：从 dev 11ec58c 切，多 #1322（row_segment `grid_end_fit`）、#1323（seed_admit `solo_cal_allow`／`lead_5b`），都缺省关、关时逐字节不变（code_equiv 已登记），版本号不升。全唐文 001–003 front10 钉本版。

- seed_admit 书级开关 `solo_cal_allow`（字组／形近白名单，库首位＝5-b 首位、cov≥`solo_cal_5b_cov` 才放）和 `lead_5b`（无参照格库与 5-b 不一致、5-b 首位领先明显时放 5-b 首位，通道 `match_lead_5b`）（PATCH，形近字线 11-09，全唐文 001–003 front9 逐格看图定门槛），都缺省关、关时逐字节不变（code_equiv 已登记）。

- row_segment 书级开关 `grid_end_fit`（PATCH，A22 11-09，ZM 派单 vol28 列尾下溢）：等距格网末线顺末字墨推到白段或下版框线上沿（`books/siku_zongmu/row_boundaries.fit_grid_end`），缺省关、关时逐字节不变（code_equiv 已登记）；vol28/89 列尾下溢 8.4%/4.3% → 0.2%。

## [0.6.29] - 2026-11-09

- 发版说明（ZM 11-09）：从 dev 3b1e330 之后切。含 #1317（border_detect 页级覆盖 hline_hints）；0.6.28 的 rc 切在 #1317 之前，不含它，本版补上。0.6.27 误打在 dev 上、0.6.28 缺 #1317，殿本第 9 轮钉 0.6.29。

- border_detect 页级人给上／下版框位置 `hline_hints`（PATCH，A22 11-09，GUJI-758）：册 yaml 写 `params.border_detect.hline_hints: {页: {top: y}}`，线放在人给的 y、倾角按附近粗框条量；殿本第 9 轮上版框认错 10 页（抬头框贴图顶）用。缺省空不进 dump，code_equiv 已登记，没写的页产物不变。

## [0.6.28] - 2026-11-09

- 发版说明（ZM 11-09）：从 dev 449bbbc 切。多 #1315（`ss_count` 一横之下竖画两侧磨残碎墨当士，two_frag，殿本 r8 Z04 十士 12 格；`groups/bars.py` 变，ss_bars 产物过期）、#1311（待审单上排除名单无人看过的格）、#1318（`edge_pair_to`）。**v0.6.27 tag 误打在 dev 提交 3d179a8 上（没走 rc→main，不含 #1311、#1318），不用，本版取代它**；tag 不改不删，按规矩发新 PATCH。

- seed_admit `edge_pair_to`（缺省 `freq`＝旧行为、不进 dump，版本号不升，code_equiv 登记；A24 V01 定案 11-09，sheldon 经 ZM GUJI-756）：`edge_pair` 放哪一形按书定。`lib` 放库首位（刻形，殿本按刻形转写，「同字」只表示这格可以不人审、不写暂归一，evidence `decision: keben`）；`ref` 放整理本字（史記、全唐文按整理本录，`decision: ref`）；`freq` 照旧放字频高的一形（`provisional`）。

## [0.6.26] - 2026-11-08

- 发版：从 dev 6f58b53 切，多 #1309（eval_sim_bench）、#1310、#1312；产物、指纹都不变（L0）。殿本第9轮用（ZM GUJI-758）。
- `republish.py push` 文本推进 book-text dev 后现算锚点类待审原因 A01–A03（PATCH，A31 11-09，方案 8.9，#1312）：写线上单之前调 `guji closeout derive`，以推前的 dev 为 A03 漂移基准，先清后算、幂等，盖掉出单时算的 A01/A02；本章没有标点／专名或没推文本就不跑，失败只警告、不拦推单。`issue`（换单）经 push 一并生效。不动产物、指纹（L0）。
- `republish.py` 出单时现算锚点类待审原因（PATCH，A32 11-09，方案「标 main 后自动收尾」8.9）：新增 `add_anchor_reasons`，给了 `--book-text` 就调 guji-manager `closeout.plan.stamp_pending`，把标点／专名锚点对不上的格写成待审原因 A01 `anchor_miss`／A02 `add_del`（deferred，不出字卡、不算人审率；一格多因主因不变、其余进 `pending_reason_also`）；manager 没有该模块或没给 book-text 就跳过。不动产物、指纹（L0）。

## [0.6.25] - 2026-11-08

- 发版：从 dev f24811b 切，多 #1303（auto_cycle 失败还原工作区）、#1306（solo_cal）；seed_admit 仍 1.82、row_segment 1.47。全唐文 front9 用。
- seed_admit `solo_cal`（＋`solo_cal_tiers`、`solo_cal_skip`、`solo_cal_5b_cov`，缺省关、关时逐字节不变、不进 dump，code_equiv 登记）：无参照格 5a 校准直放，通道 `match_solo_cal`。cov≥.98＋gap≥.03 或 cov≥.95＋gap≥.05；另一档库首位＝5-b 首位且 cov≥0.95。形近表首位、字组、己已巳于干曰日代伐遣遺真、near_form／occluded 等疑问不放。全唐文 front8（中心库 914128）本机实跑放 1,442 格（去 真 后 1,426），抽 80 格看图未见错（形近字线 11-08，Sheldon 定）。

## [0.6.24] - 2026-11-08

- 发版：从 dev 6abb2b8 切，多 #1296、#1297、#1298、#1299（row_segment 1.47）、#1300、#1301、#1302；seed_admit 仍 1.82（新开关都缺省关、code_equiv 登记）。全唐文 front9、殿本第9轮 vol01 职名页用。
- row_segment 1.47：殿本职名页大字雙行整段分栏＋「臣」上限 0.9em，**一律生效、不是开关**（取代刚合的 #1298 里缺省关的 `roster_lr_run`／`roster_side_max`，那两个参数删掉，没有册写过）。整段分栏有护栏：整段分栏的扁块（高 <0.6 宽）比逐带处理多过 2 个就整段不认（全唐文 001 p35 c6 左行 28 字被谷点劈成 46 格，QTW 11-08 报）。雙行段开头右行单独一个窄字（p88 c5/c6/c1 的「太」「太」「經」，Sheldon 11-08 指出）也认 jiazhu_a（`_lead_in_jiazhu`）。殿本只有 vol01 有职名页，87–130 页只有 87、88 两页有雙行列（7 列）；396 列变 12 列、看图全对。row_segment code_hash 变，殿本各册 Step3 下次重跑过期（史記职名页走自己的实现，不变）（A22 11-08）。
- seed_admit 自适应门槛二期（缺省关、关时逐字节不变、不进 dump，code_equiv 登记）：`solo_adapt_near_slack`（＋`solo_adapt_near_gap` 0.03）差本字自比分位不到 slack 的格须领先 ≥near_gap；`solo_adapt_nf_ok` 首位不在形近表／字组时 near_form 疑问不拦（窗口内形近表对手照拦）。全唐文 front8 001–003 在中心库 914091 上本机从 seed_admit 起实跑：solo_adapt 多放 967 格（与离线看图清单一一对上，存疑 1）（形近字线 11-08）。
- seed_admit front7 三档（缺省关、关时逐字节不变、不进 dump，code_equiv 登记）：`num_run_cov_5b`（＋`num_run_gap_5b` 0.02）：5-b 首位作证、原门槛之下的数字格 cov 降档；`solo_adapt_risk_gap`：高危对手落后够多就不拦；`solo_adapt_abstain_ok`（＋`solo_adapt_abstain_skip`）：首位不在字组、只被 group_flow_abstain 挡的格照自适应门槛判。全唐文 front7 001–003 本机从 seed_admit 起实跑：num_run 多放 598、solo_adapt 多放 235（形近字线 11-08）。
- seed_admit `solo_5b_same_cov` 修：书级开 `consensus_fallback` 时无参照格的共识 same 全被退回 unsure，same_cov 一格都认不到；改看退档前的 glyph_match verdict。全唐文 front5 002/003 本机实跑 match_solo_5b 2,035→3,362、1,185→1,825（形近字线 11-08）。
- seed_admit `solo_adapt_pct`（"p10"／"p25"，缺省 None＝关，`solo_adapt_*` 不进 dump，关时逐字节不变，版本号不升、code_equiv 登记）：无参照格按字自适应门槛，通道 `match_solo_adapt`、不入字形库。cov 门槛取该字库内刻例自比分布的百分位（下限 0.94），5-b 首位须就是库首位（不认异体），领先 ≥0.01，窗口内对手是高危字对（库内互比自动算出）或形近表就不放，并比互比上限。字表由新脚本 `scripts/char_cov_profile.py` 出，放中心库 `config/groups/char_cov_profile.json`。全唐文 001–003 待审离线：p10 档放 2,221 格、按字排图全看未见确定错放（存疑 6），p25 档 1,250 格（存疑 2）（形近字线 11-08）。

## [0.6.23] - 2026-11-08

- 发版：从 dev 7a3b278 切，第8轮用。多 #1248、#1290、#1291（seed_admit 1.82）、#1292、#1293。
- groups yr 数横（#1248）：两横时上横连续度 <0.5 弃权（`upper_broken`）；殿本 r7 Z04 yr 36 格里 18 格改弃权；846 个已放行一／二格中真「二」被弃权 2.7%（弃权不放错）。`groups/bars.py` 改了，各书 yr_bars 下游过期（A24 11-08）。
- seed_admit `num_run_juan_cov`（缺省 None＝关，不进 dump）：num_run 开着时，紧挨数字串前面的「卷」（后一格是数字）cov ≥ 这个值也放；`solo_5b_same_cov`（同上）：solo_5b 开着时，库已判 same 的格 cov 门槛降到这个值。全唐文 002／003 front4 看图：「卷」409 格全对；0.95 档 same 格 1,961 格未见错放（1 格 費 存疑）。版本号不升、code_equiv 登记（形近字线 11-08）。
- seed_admit `num_run_cov`／`num_run_gap`（缺省 None＝关，不进 dump，关时产物逐字节不变，版本号不升、code_equiv 登记）：无参照格「数字串里的数字」放行，通道 `match_num_run`、不入字形库。库首位是数字、cov 够、领先够、同列同半格前后至少一格也是数字，护栏只认 never_match／无护栏，疑问只认 near_form、库 unsure／same 被拦、上下文 margin、字组弃权。全唐文 001–003 front3 姓氏韻編卷数小注逐格看图 0.995／0.01 档放 1,730 格、0 错（形近字线 11-08）。
- seed_admit 1.82：规则 A（rare_ref／rare_ref_sparse）不在折叠组待文意的格（`evidence.fold_pending`）里拿整理本字定组内字；折叠组 `fold_ref_char: false` 本来就是不信整理本（殿本 vol41:55:4:19「六日僧道」被放成日，应为曰；r7 殿本 vol20–99 只影响 2 格，另一格 vol64:51:2:10 回待审）（A24 11-08）。
- seed_admit `solo_5b_char_ok`／`solo_5b_human_min`（缺省 None＝关，不进 dump，关时产物逐字节不变）：solo_5b 的字级白名单，库首位字须在名单里或本书人裁刻例 ≥ human_min 才放。全唐文留出检验错放 牟→年（库里 3 条刻例全自动进库）后，改成人看过刻例的字级名单；通用「人裁≥1」闸砍 56% 放行格且挑不出错，不做。

## [0.6.22] - 2026-11-08

- 发版：从 dev 6e8127b 切，只多 #1279（参校本属性 B 块：align_ref／row_segment 按 reference_profile 分支，未声明的册不变；殿本、史記逐字节相同）。全唐文 001–003 钉本版从 align_ref 起重跑。

## [0.6.21] - 2026-11-08

- 发版：从 dev 76fd114 切，只多 #1282（border_detect `top_edge_reslope`，缺省关、逐字节相同）。殿本 vol14 换新图钉这一版开它（p45 上框贴图顶）；其余 vol01–19 仍钉 v0.6.20（两版关开关时产物相同）。

- border_detect `top_edge_reslope` 上框贴图顶时连倾角重找（书级，缺省关、关时不进参数 dump；A22，vol01–19 换新图 11-08）：新图按版框裁、上方只留几十行，抬头框顶、纸边暗条会贴着图顶，联合搜索在图顶截断处拿到窄峰高分、倾角也是假的（vol14 p45 上框落在 y=0、倾角 0.035，真框在 128–146 行），整页抬头列格网偏一格。开关开时上框贴图顶就在 ±0.05 各档倾角里找离开图顶的最好峰。vol14 p45 c1/c3 修后与旧 ★main 对齐。殿本建议与 `bottom_lock_reslope` 一起写进 book_defaults，从 border_detect 起重跑。

## [0.6.20] - 2026-11-08

- 发版：从 dev c074583 切，只含 #1283（seed_admit 撤回 1.81，#1277 改登记 code_equiv）。在 1.81 下算的册钉本版不过期；第8轮门槛写 cv ≥ v0.6.20。

- seed_admit 版本号 1.82 撤回 1.81：#1277 `group_flow_llm_half_groups` 缺省空时逐字节不变，改用 code_equiv 登记（史記 vol02 18 页对 1cefd43a 逐字节相同）。各书在 1.81 下算的 seed_admit 不再因 #1277 过期；已在 v0.6.19（1.82）下重算的册换到本版会再判过期一次（A31 请求，A24 11-08）。

## [0.6.19] - 2026-11-08

- 发版：从 dev 1a9d029 切（seed_admit 1.82），含 #1266–#1278（A22 #1271 colgeom 认 ruled_warp、#1272 下框越界不崩＋bottom_lock_reslope；A20 #1273 参校本属性 A 块；A24 #1268/#1278 solo_5b、#1274 rare_charset、#1277 group_flow_llm_half_groups；#1275/#1276 刻例按来源分列）。殿本 vol01–19 换新图钉这一版。

- solo_5b 接可信刻例与借库（参校本属性 C1/C4，A24，A23 同意的收窄版）：`solo_5b_min_n` 改读 `trusted_keben_counts`（人裁＋有参照互证，借库／solo／来源不明不算）；`match_solo_5b` 放行格带 `evidence.no_glyph_lib`（不自喂，不进字形库）；新书级参数 `solo_5b_borrow_db`（同族书的库，加它的可信刻例，本书自己至少 1 条可信才借，缺省不借），借库放行的格标 `solo_5b.borrowed` 供分层抽检；证据键 `n_lib` 改名 `n_trusted`。seed_admit 不升版本号：solo_5b_cov 缺省关，殿本 vol62 11 页与 dev 逐字节相同，code_equiv 已登记。
- seed_admit 1.82 `group_flow_llm_half_groups`（书级，缺省空、不进参数 dump；A24 11-08）：这几组的夹注半格不受 `group_flow_llm_skip_half` 限制，照样查答案表／裁定库、记 `llm_pending` 问，可经 `feedback/llm_queue` 导出给对话判读。SJ 史記 H01 里 89 格半格（己已巳 45、日曰 44）因 skip_half 没有 L3 问、写不了裁定键；史記建议 `[ry, jys]`。

- seed_admit（版本号不变）新通道 `match_solo_5b`（书级 `solo_5b_cov`／`solo_5b_gap`／`solo_5b_min_n`，缺省关、关时不进 dump、逐字节不变）：无任何整理本对位的格，库首位 cov、领先异语义候选、刻例数都够且 5-b 首位作证才放；形近表、字组、己已巳、硬疑问不放，5-b 为空弃权（全唐文 001/002 总目、韵编，形近字线 11-08，A24 定口径）。
- Step5-b 生僻字候选读书级 `rare_charset`（参校本属性 C 块，A24，A31 11-08 核）：册配置写了 `rare_charset: <语料文件名>` 就用它做候选字表，与参校本脱钩（`kind: none` 的书也有字表；002 此前因没写 references、字表退回四库语料而 rare_candidates 整册为空）；文件不存在记日志退回老路。没写＝照旧 `book_corpus`，行为与指纹逐位不变；写了的册指纹多一个 `rare_charset` 键（只在 `_self_payload` 里按册加，不进 `book_deps`）。
- 参校本属性 B 块：align_ref、row_segment 按册配置 `reference_profile` 逐页分支（A22，A31 11-08 核；设计 ai-team `domain/CV/设计/参校本属性/B-cv对位与切分-A22.md`）。align_ref：`kind: none` 的页不读语料、不锚定、不做坐标对位，note 记「本页无参照（配置）」，产物新字段 `PageAlignRef.ref_kind`（`none`／`text`，column 与未声明为空、不落盘），下游请认字段不认 note；`text` 页照常 8-gram 对位、不做坐标对位（`coord_note`「参照不分列（配置），不做坐标对位」）、也不当别页借位的邻页；有参照的页第一版只支持 `references[0]`，指向别的参校本报错。按页进指纹：`StepSpec.ref_profile_aware`＋`Engine.fingerprint` 只在声明了非 column 的页加 `ref_profile` 键，未声明的册指纹逐位不变。row_segment：写了 `reference_profile` 的册 `layout_prior` 表里缺本册不再整册拦（缺表的页纯几何切，全唐文 003 首跑整册 0 页即此；没写的册照旧拦）；离线格位表有行照用（表是几何先验，与有无参校本无关）；自动配页 `page_map` 不配 none／text 页、strict 正文页计数不算它们，整册没有逐列页就不配页；页表并进 `page_map_fingerprint` 与缓存键（空时不变）；与钉位表钉了半叶的页冲突报错。code_equiv：row_segment 在殿本 vol60（自动配页 strict）与全唐文 001／002／003／006 共 43 页、align_ref 在 vol60 与全唐文 006 共 24 页上与 origin/dev 逐字节相同。全唐文 001–003 的 align_ref 无参照页会过期重跑（产物变了：note＋ref_kind）。
- 册配置加参校本属性 `reference_profile` 与书级 5b 字表 `rare_charset`（参校本属性 A 块，A20，A31 11-08 核）：`core/ref_profile.py` 按页段写 `kind: column|text|none`、段用 `ref:` 指 `references[]`（质量仍只写在 `references[].quality`），写错在读配置时报；基础配置只许写 `default`；`guji book show` 加一节；B 块翻译函数 `ref_none_pages`／`ref_text_pages`、按页指纹钩子 `page_token`；manager_api 导出 `RefProfile` 等。未声明＝每页 column，不进任何步的 `book_deps`、没有步读它，L0、产物不变。设计见 ai-team `domain/CV/设计/参校本属性/A-册配置.md`。
- border_detect 下框越出图底不再整页崩、`bottom_lock_reslope` 下框贴边重找倾角（书级，缺省关、关时不进参数 dump；A22，vol01–19 换新图 11-08）：①`_rule_offset`（界行贴证据）与 column_gate `trim_content_span` 的下框行号夹在图／列图内——新图版框贴图底（加上册 yaml 的 `bottom_gap` 跨页救援把下框挪出图外）时原先 IndexError，那一页 border_detect 或 column_gate 失败，产物目录里留着换图前的旧图残档，下游照读（vol09 p112/202/204/254、vol13 p131、vol15 p116、vol18 p64、vol19 p95 整页切成半宽窄列）；不崩的页逐字节不变。②下框联合搜索锁在搜索带上沿时，原逻辑沿伪影的倾角找非边界峰；伪影倾角可以很斜（vol12 p27 新图 0.047），真框沿斜线采样被拉散，下框停在末三四个字中间。开关开时在 ±0.05 粗扫各档倾角里找非边界峰，分数超过原倾角最好峰 2 倍才换。殿本 99 册新图 16,516 页贴边 37 页、开关只动 18 页，抽看都是下框从斜线／外沿回到内框线。殿本建议 book_defaults 写 `params.border_detect.bottom_lock_reslope: true`，从 border_detect 起重跑。
- 修：`eval/colgeom.ColumnGeom` 认 column_warp `ruled_warp`（A22 11-08）：人拖过的切线（`feedback.lookup.resolved_pins`）与切线金标的页面坐标↔列图行号换算按列窗 `ruled` 走同一算式，签名 `geom_sig` 在 ruled 时多一个键（关时签名不变）。不改这处，开 ruled_warp 的书人钉的格线会按射影落错行（列端最多差约 9% 列高）。不在任何步的指纹里，产物不过期。
- cell_shrink 列尾内框线两个书级开关（都缺省关、关时不进参数 dump；A22，殿本第 7 轮带框重字块，Sheldon 11-08 定修）：`inner_frame_fit2`——下框整宽法也拟不出内线的页再试一次，线厚上限放到 0.11 格高（殿本新图有的内线印到 8–12 行）、线位以上几乎整段是墨的像素列（界行）先剔掉再量半高宽（点线峰只有 0.1–0.2，界行垫的底子就有 0.1），加空段验线；vol95 下框拟不出的 38/220 页补回 16 页。`inner_frame_snap`——抹内线时沿线的形状往字那边再找线的残边行（在线有墨的像素列上 ≥0.6 也有墨），最多 0.035 格高，连着的墨超过上限（压线的字底一横）一行不补；整页拟的线到单列差几行时上半截线贴着字脚留下（vol95 p108「前」、p202「著」）。vol95、vol88 全册开关对比变 296 块：去线渣 272、补回被切的字（vol88 p121「逃」「進」）若干，变差约 5 块（字脚多一小截虚线、一个小点）。殿本 vol20–99 建议两个都写 true，从 cell_shrink 起重跑。
- row_segment `layout_title_fit` 书名列候选格网（书级，缺省关、关时不进参数 dump；A22，殿本第 7 轮复查书名列 11-08）：格位表认出「书名＋段尾双行小注」的列（格连成一段、小注在段尾、书名 ≥2 格、不抬头），按本列墨的起止量字距（页级格高的 0.78–1.12 倍），段里的格线由 DP 落在字缝正中（`_title_gap_cuts`：格高贴近字距、缝越宽越好），段外照页级格高；跟表、表挪一格两张候选各配一张，照常打分（等距格网优先，坏格严格更少才换）。起因：书名列刻得比正文紧，等分格网把书名字劈开、小注错一格（vol88 p129 c9）。vol88、vol32 全册开关对比只动 vol88 p129 c9 一列，改对。殿本 vol20–99 建议写 true（book_defaults），从 row_segment 起重跑。
- seed_admit 1.81 `fold_aspect_ctx_veto` 的组内文意一支（1.78 加的）不认 L1 规则，带概率的（L2 `p`）要到阈值（SJ 史記 06:46:1:9b、06:46:1:13a「李奇曰」被 `ry-ext-r1-日` 误否决；殿本 H01 L1 37 格错 15，A24 11-08）。名单页「日講官」墨迹宽高比 1.16／1.09，在墨迹口径 hi 1.2 下本来就不判，不靠这一支。

## [0.6.18] - 2026-11-08

- 第 8 轮发版：从 dev e9369d3b 切（seed_admit 1.80），含 #1237–#1263（A24 R01/H01/Z01–Z03/V01/N01/P01/D01、A23 笔画法 strokes 与 lane_group_img_veto、SJ #1258/#1262、A20 #1259 书级 bend_w80_med、A22 #1256 bottom_weak_ratio、#1255 rebase 原点换算、#1261 column_warp.ruled_warp 书级开关缺省关）。殿本第 8 轮 book_defaults 写 `params.border_detect.bend_w80_med: 0`（整页三段折线）。

- column_warp `ruled_warp` 列图矫正改「竖向线性、横向逐行按左右线插值」（书级，缺省关、关时不进参数 dump；`ColumnWindowRec.ruled` 关时不写；A22，殿本第 7 轮列首列尾切半根治 11-08）：整列单应把左右界行不平行（版面真实弯曲，列宽上下差 5–10%）当成透视，列图竖向被拉伸 ±9%，row_segment 等距格网偏半格，列首字头、列尾字脚切到格外。开了以后列图第 y 行就是原图线性对应那一行，Step3/Step4 回写用同一套逆映射（`ColumnMapper.of`）。殿本 r7 册 vol49／vol89／vol28：列尾下溢＞0.15 格 4.3%→0.1%／11.1%→4.5%／13.2%→8.3%，列首上溢 2.8%→0／5.6%→0.4%／5.9%→1.2%，穿字或格高不匀列 32→13／76→39／97→57；关时 column_warp、row_segment、cell_shrink 逐字节相同（code_equiv 11-08）。从 column_warp 起重跑。
- seed_admit 1.80 `fold_aspect_ink`（书级，缺省关、不进参数 dump；A24 11-08）：折叠宽高改量墨迹主体（字组字形路 `ry_shape` 的 ratio），不量切分框；没进字组的格不按宽高判。SJ 史記看图：框量 1.1–1.4 的「日」墨迹只有 0.68–0.93。史記 r18 10 册已放行格 0 错阈值：墨迹口径正文 1.2（曰收 80%）、夹注 0.95（收 99%），框口径要 1.42（收 22%）、1.19（收 50%）。

- seed_admit 1.79：`alt_select="admit"` 开 `p_ref_admit` 时，选列另跑两遍**不带 p_ref** 的准入来比（`_NO_P_REF`），产物仍取带 p_ref 的两遍；撤掉 1.77 的「p_ref 放的格按待审算」。r19 包回放（06:26、06:29、03:88，开 p_ref 四键）：1.77 在 06:26 换了 1、4、6、8 列、03:88 换了 1、3 列，而不开 p_ref 只换 06:26:1——p_ref 在后面几条跟整理本的通道之前取字，这些格不开 p_ref 时本由那些通道放，按待审算就多换了列。没开 p_ref 的书不受影响。
- seed_admit 1.78 `fold_aspect_ctx_veto` 开着时也认字组文意解法（`evidence.group` 里 ctx agree）给的另一个字（证据记 `fold_pending.ctx_veto.group_ctx`；SJ 史記 01:45 名单页「日講官」宽高比 1.15／1.08 没有 context_decide 排名，原先只靠 shadow_veto 挡回，A24 11-08）。史記 r18 10 册正文 hi 1.05 时判错的日由 7 格（只用排名否决）降到 4 格；夹注误伤曰不增加。

- seed_admit 1.77：`alt_select="admit"` 换列比较（`_col_stats`）时 `p_ref` 放的格按待审算（`_ALT_AS_REVIEW`）。p_ref 是待审格取整理本字、两遍都放，算放行会把主切法错位列的待审压下去而不换备选格网，切坏的格被整理本字盖住（史記 r19 离线开 p_ref：06:26:1「陳索」一格两字、03:88:4 列尾残块，备选格网切对；SJ 11-08）。没开 p_ref 的书没有这个通道，产物不变。
- seed_admit 1.76 `p_ref_min_cov`（缺省 0.8 开，缺省值不进参数 dump，`None` 关；SJ 史記 r19／A24 11-08）：`p_ref_admit` 不取库判 diff（「库里没有这个字」）或机器字 cov<0.8 的格，挡住切分坏格（一格两字、残块）被整理本字盖住；P01 本身的格（unsure 档 cov≥0.85）不受影响，开着 p_ref 的书（史記）会少放这类格。
- border_detect `bottom_weak_ratio` 下版框弱线护栏（书级，缺省 0 关、关时不进参数 dump；A22，殿本第 7 轮复查 11-08）：`seg/lines._weak_bottom_guard`，`_weak_top_guard` 的镜像——选中的下框线横向墨量不到带里最强横线的该比例、下方 ≥0.021 页高处另有够强的横线，改取最靠页心的那条（只往下挪）。殿本 vol20–99 新图源 13,320 页扫图只动 17 页、看图全是真框（vol22 p147 下框落在倒数第二行字身里、整页每列只切 20 格；vol24 p64、vol34 p37、vol44 p180、vol68 p218、vol79 p196 差 130–340 px）；vol22 全册实跑只动 p41、p147。殿本 vol20–99 建议写 0.3（book_defaults），从 border_detect 起重跑。
- border_detect `bend_w80_med`（书级，缺省 None 取代码常数 `seg/polyline.BEND_W80_MED`＝7、不进参数 dump；A20 11-08，A31 第 8 轮用）：页级界行 w80 中位不到它的页按直线页走，写 0＝整页一律三段折线（书级 `vline_polyline: false` 仍优先）。殿本第 7 轮换 Commons 图源后界行清楚，约一半的页判成直线页，Step2 整列一个单应把列宽上下差变成字距上疏下密，row_segment 等距格网切半列首列尾的字（R02 碰裁边 17%→30%）；vol28 p100–192 强制折线后列尾下溢 13.0%→9.0%、列首上溢 7.8%→1.0%，vol89 列尾 9.7%→2.9%（ai-team `domain/CV/质检/待审原因深挖/R02-第7轮列端切半-A20`）。殿本写法 `params: {border_detect: {bend_w80_med: 0}}`；缺省下 vol28、vol89 全册产物逐字节不变，code_equiv 已登记。
- seed_admit 1.75 `follow_ref_seen_conflict`（书级，缺省关、关时不进参数 dump；A24 N01 第 7 轮复查 11-08）：`follow_ref_seen` 也接「护栏 conflict」格——候选前两名恰是整理本形与 seen 对里的另一形、两字都被判 same（字形相同，只有整理本文意能定），放整理本形。殿本 七／𠤎（《易·震》「不喪匕鬯」文淵閣本作 U+2090E，库里 𠤎 两例图就是七）28 格；用法 `follow_ref_seen: "七=𠤎,𠤎=七"`＋本开关。
- seed_admit 1.74 `lane_group_img_veto`（书级，缺省 None 关、关时不进参数 dump；A23 Z02 第 7 轮复查 11-08）：补放三通道要放的字与字组图像判官（`rr_img`）反对的字不同、判官概率 ≥ 该值 → 不放（doubt `lane_group_img`）。殿本 r7 vol68:160:3:16、vol67:149:9:15 图是「入」、整理本「人」被 witness3 放成人；80 册回放只命中这 2 格。
- seed_admit 1.73 `group_flow_ref_pair`／`group_flow_ref_pair_coord` 不再把共字组搭档的码位解法（`组:codepoint`）当反对票（它只回报码位归一目标，无图像证据；本组自己的 codepoint 仍拦；只对开了这两项的书生效；A24 Z02 r7，殿本 sy 山由出 4 格看图全是山，r7 全册扫描无误放）。
- `seed_admit` 1.72：折叠组 `fold_occluded_lib_max_cov`（书级，缺省关、关时不进参数 dump）：遮挡格库首位在组外但 cov 小于此值（印泥下没有把握的别字）仍按整理本字归组，字待文意（A24 D01 深挖 11-08，殿本 r7 己已巳遮挡 19 格；建议 0.9，需同开 `fold_occluded`、`fold_ref_char: false`）。
- seed_admit 1.71 `p_ref_irregular_gap`（书级，缺省关、关时不进参数 dump；A24 P01 第 8 轮 11-08）：`p_ref_admit` 下，整理本字是异体写法（twedu／local:keben 指认，槪寳囘竒厯…）、机器字与它无直接异体边、库候选里整理本字及其正字的最高 cov 与机器字相差 ≤ 该值 → 取整理本字，不受 `p_ref_max_cov` 约束（相邻／夹注旋钮照旧），整理本字在字组里也放。殿本 r7 P01 275 格放 113，史記 r6 放 23（看图全对），全唐文 0。
- 修：字组 yr（一二）的陪衬字加 `子`（`groups/registry._YR_FLOW.tolerate`；A24 N01 第 7 轮复查 11-08）：一 的字块库里排成「二 1.000、一 1.000、子 0.97–0.98」，子 落在 delta 内又不是组员，格进不了字组、停在待审（护栏 conflict，N01）。殿本 vol48/52 本地重放：目标 12 格全放成「一」（目视全对），同册其余格无变化；入口放宽，给字仍凭数横／文意。产物指纹变，下一轮重跑生效。
- seed_admit 1.70 暂归一兜底放宽 `group_flow_pv_ref_gap`（缺省 0.01 开、`group_flow_pv_ref_cov` 0.95，缺省值不进参数 dump；A24 V01 第 7 轮 11-08）：整理本字（只认现役对位）与库首位都是某组暂归一的写法、首位 cov≥0.95、领先最好的组外候选≥0.01 时，分差内有组外形近字也进组（`flow.entry`）并允许兜底（`_provisional_base`）。第 7 轮殿本 𨽻→𨽾 还剩 20 格被 諫 據 綠 裁 等陪衬紧咬拦在组外（看图都是士示刻法）；三书 V01 现算命中 39 格（li 23、yi_560 7、shan 2、cp_ming2 2、mn 2 等），都是整理本与库首位同字异写。
- seed_admit 1.68 `fold_ctx_vias`／`fold_ctx_strong`（书级，缺省空／关、不进参数 dump；A24 H01 第 7 轮复盘 11-08）：折叠组认字组流程里文意路已给的字（`fold.via=ctx`），次序在文意裁定库之后、整理本字之前。殿本第 7 轮 H01 L3 答案表 strong 68 格与干净会话盲读 high 全同，现 fold_pending 里 106 格可放；L1 规则错得多（37 格错 15），不要进名单。见 `doc/4-定字/字组/折叠组.md`。
- 新增 `open_guji_cv/strokes`（L1）：笔画模板逐笔配准、差一笔／量几何两种判据的纯算法；不被任何 Step 引用，产物不变（研究，接线归 groups，A24）。
- strokes 差一笔收紧（全唐文 4,536 格留出：异判 2→0）：`verify_extra` 缺省 `hi` 0.5→0.75；钉住的笔先填小孔再量（空心点，`pin_fill_holes`）；新增 `pin_search_far`（近处没残墨才放宽找，缺省关，全唐文开 0.2）。不被 Step 引用，产物不变。
- 修：seed_admit `group_flow_pair_shapes` 补放时整理本（或坐标对位）是两字以外的第三个字就不判（全唐文 r16 库首位王、整理本三的格被王玉模型放成王；seed_admit 1.65）。

## [0.6.17] - 2026-11-07

- 第 7 轮冻结版：从 dev 4dc4448 切（seed_admit 1.64），重新带回 #1186（variants 补 14 对异体边，配底库 b21）、#1192、#1196。殿本换 Commons 景印文淵閣本页表（r003/r004）。**史記**书 yaml 要在 `params.seed_admit` 写 `alt_require_matched: true`（#1234）。

- seed_admit 1.64 `alt_require_matched`（书级，缺省关、关时不进参数 dump；A24 史記 r18 02:106:7 深挖 11-07）：`align_ref.alt_select="admit"` 换列时，备选格网这一列里没有坐标对位字的格比主切法多就不换。r18 里 #1191 让主切法那遍的字形背书变少，02:106 第 7 列备选（多一个 `-1` 格、整列后移一格）凭「待审少 2」被换，夹注逐格错位、约 20 格 coord_fallback 错放；r17 同列不换。真换对的列（02:100:5、02:108:6／8）备选没坐标字的格都更少。开关放史記书级配置。
- seed_admit 1.63 `group_flow_lift_shape_ratio`／`group_flow_lift_shape_ratio_jiazhu` 与 `reference_trust_skip`（书级，缺省空、不进参数 dump；SJ 史記 r18，A24 11-07）：`lift_shape_ref` 补放要字形路 ratio 落在书级区间内（日曰：`{ry: {曰: [1.15, 9]}}` 只放明显扁宽的曰，居中格按文意）；`reference_trust` 自动并入的 `lift_shape_ref` 等各项可单独关。史記 r18 lift_shape_ref 71 格曰按 1.15 留 56 格；标定见 `doc/4-定字/字组/ry.md`。

- seed_admit 1.60 `group_flow_ctx_agree`（书级，缺省关、关时不进参数 dump；A24 Z02 11-07 sheldon 定）：`group_flow_dissent_keep`／`group_flow_ref_pair` 里再列入这个名单的组（入人八 rr），放行字还要本组文意（ctx）同意才不降审／才取整理本字。入人八整理本 24 对 3 错、文意 10 对 10 错，「整理本＝文意」9 格 8 对 0 错。

- seed_admit 1.57 `group_flow_dissent_l1`（书级，缺省关、关时不进参数 dump；A24 Z02 按新码重做 11-07）：`group_flow_dissent_keep` 的组里，复核时已放行字＝整理本字、唯一反对的是文意 L1 规则（`ctx:ctx_l1`）而本组 ids 等非文意解法同意放行字 → 不降审，留痕 `dissent_keep`。新 Z02（73 格）里 B2／B2x 9 格放行字全对。

- seed_admit 1.58 字组入口认暂归一的另一写法作整理本字（`groups/flow.entry`；A24 V01 按新码重统计 11-07）：整理本字是本组暂归一 `forms`／`ref_forms` 里的写法（li 的 𨽻、sui 的 𡻕）时不再当组外字挡在门外，照样进组由解法定形、与整理本不一时暂归一兜底。第 6 轮 align_ref 把这些位对上了整理本字（第 5 轮缺位，按坐标对位进组暂归一放成 𨽾／嵗），入口反倒因「整理本字不是组员」不接，殿本 ★main V01 多出 219 格（𨽻 211、𡻕 8）。下一轮重跑生效；

- seed_admit 1.57 `group_flow_pair_shapes`／`group_flow_pair_shape_veto`（书级，缺省空／关、关时不进参数 dump；全唐文 大太／王玉／還遺，sheldon 11-07）：`pair_shape/2` 两字刻形模型＝主笔画紧框 32×32 墨量图＋逻辑回归，另带「本组 vs 组外形近字」判别作护栏；一本书可挂多对，补放规则同 `group_flow_pair_shape`（只补放待审格，给字须＝库首位或整理本字）。`veto` 开时，已放行（非人裁）格刻形以 |分值|≥`veto_thr` 判成另一字 → 降审 `pair_shape_veto`。HOG（`/1`）抓不住太、玉那一点：全唐文按册留出 HOG 错 278／183，墨量图 大太 2,605 给字错 1、王玉 1,904 错 0、還遺 357 错 0；r15 字组打架 10 格全对；查出已放行「王」实为「玉」3 格。训练 `research/char_groups/pair_shape/train_pix.py`。`group_flow_pair_shapes` 的相对路径先在数据目录找（模型随中心库走），再按工作区。`pair_shape/2` 另支持多类护栏（`multi`：两字＋每个组外形近字各一类，最像组外字或领先不足 `thr` 弃权），全唐文按册留出弃权 54→21、错 1→2（2 格都是字框切坏／带界行，且与库首位、整理本都不一，管线里不会放）。

- seed_admit 1.55 书级旋钮 `group_flow_ref_pair_coord`（**缺省关**，关时不进参数 dump、逻辑与改前相同；A24 Z07 差一路确认深挖 11-07）：`group_flow_ref_pair` 里的组联合判卡在「共字组搭档没表态」（`joint`）、现役对位缺这一格时，坐标对位字＝本组解法给的字、**没有任何解法（含搭档、图像路）给别字** → 取它（留痕 `ref_pair_coord`）；夹注半格、〓 不认。殿本 ★main Z07 124 格里命中 41 格（zy 于干子、wm 未、men、yz、zh），看图全对、0 错放；其余 83 格一个不中。要开须在书 yaml 同时开 `group_flow_ref_pair`（含这几组）。

- seed_admit 1.54 卿𨜊（`qing`）暂归一兜底认整理本〓（`registry.PROVISIONAL` 的 `gap` 加 qing，同 yi_560；A24 Z 类梳理 11-07，Sheldon 同意）：殿本整理本把这一刻形录成〓，字频给卿，却被坐标对位闸当「组外字」拦下（★main 现算 235 格，原因码 Z04）。库首位 cov ≥ `provisional_gap_cov`（0.95）、分差内都是卿𨜊时放成卿、记 `provisional`。殿本 10 册抽 30 格看图 30 格都是卿（大理寺卿、荀卿、少卿…），0 错放。下一轮重跑生效。

- 共识升档 same 退回原档（A23，全唐文 r15 待审 125→208）：`context_decide.consensus_as_unsure`、`seed_admit.consensus_fallback`（1.53）、`align_ref.coord_consensus_not_same`（史記 r18 对位丢字），书级、缺省关、不进参数 dump；context_decide／align_ref 代码等价登记。

## [0.6.16] - 2026-11-07

- 第 6 轮冻结版：从 dev d215e7b 切，回退 #1186（variants 补 14 对异体边，要配底库 b20，随第 7 轮再进）。

- seed_admit 1.51 `group_flow_form_open`（缺省开，缺省值不进参数 dump；A24 Z06 深挖 11-06，sheldon 11-07 定）：字组流程不再把 `form_open`（写法待定，原因码 Z06）当硬护栏，由组的刻形解法（li 隸𨽾、sui 歲嵗、yi_560 彝彛彞）定形；解法给字且与整理本字互证才补放，弃权或与整理本不一的仍留 `form_open`。殿本 ★main 99 册现算 Z06 共 5 格，离线试判 5 格全给字、4 格会放行、目视可判 3 格全对；史記、全唐文 0 格。报告 ai-team `domain/CV/质检/待审原因深挖/Z06-写法待定.md`。

- seed_admit 1.50 `p_ref_coord_max_cov`／`p_ref_coord_adjacent`（书级，缺省 `None`／关、关时不进参数 dump；A24 P02）：`p_ref_coord` 放的坐标对位格有自己的 cov 上限（`None`＝沿用 `p_ref_max_cov`）和相邻开关（只看 `p_ref_coord_adjacent`，不随 `p_ref_adjacent`）。原因：殿本 P01 要 `p_ref_adjacent`＋cov 0.95，P02 的切分错位格（vol29 p31 6:17–19，cov<0.95、相邻成片）一开相邻就会被放进去；史記 P01 要 0.97，P02 机器字对的格 cov 低到 0.9458，要 0.94。文本对位格的行为不变。

- seed_admit 1.49 `p_ref_skip_variant`（书级，缺省关、关时不进参数 dump；A24 P01 深挖 11-06）：`p_ref_admit` 不取与机器字有直接异体边的整理本字，留给异体对按刻形定。殿本放开相邻／夹注、cov<0.95 后 p_ref 会碰 L01 格，抽 30 格 14 格是异体对（羨羡、諫諌、緣縁…），其余 16 格整理本对 15。

- seed_admit 1.48 `p_ref_coord`（书级，缺省关、关时不进参数 dump；A24 P02 深挖 11-06）：`p_ref_admit` 对 P02（`ref_final_diff`）也生效——这类格在文本对位 `align_ref.chars` 里没标签（所在段被长度闸／不等长段丢掉），整理本字只在坐标对位里；开后退到坐标对位字（去掉冲突格、〓、空格位），cov 上限／相邻／夹注三个旋钮同样管。殿本线上 P02 看图 61 格：整理本对 53、机器字对 1（cov 0.96）、切分错位 3（相邻成片，被相邻规则拦）、看不清 4。

- seed_admit 1.47 字组复核／补放两个书级旋钮（**缺省全关**，关时不进参数 dump、逻辑与改前相同；A24 Z02 判法打架深挖 11-06，框架见 `doc/4-定字/字组/判法打架.md`）：`group_flow_dissent_keep`（＋`group_flow_dissent_margin`）——复核时已放行字＝整理本字、只有弱图像票（ids margin<1.0、yr_bars）反对不降审；`group_flow_ref_pair`（＋`group_flow_ref_pair_margin`）——补放／联合判卡在字形×文意冲突或共字组搭档没裁定时，整理本字＝本组解法给的字、反对只有图像路则取它。同批收窄 7 条 L1 规则（全册 39.5 万个字组格审计，与整理本冲突 1187→1119，好命中只少 7 个）：`zh-曾經`（前接 附理誤以體統融意 不算）、`yh-遺文`（前接 往旋返召放赦送賜贖 不算）、`yh-還朝`（前接 無補拾所不 不算、往往◎不算）、`yt-圓`（去 形）、`yt-圖`（后接 篇卽即地、前接崔 不算）、`rm-日`（去 每）、`js-申-l1`（后接 月聲子帳午 不算）；`config/corpus-registry.json` 重写。规则文件哈希变了，用到这几组的册 seed_admit 过期一次（第 7 轮重跑时生效）。

- seed_admit 1.46 `p_ref_max_cov`／`p_ref_adjacent`／`p_ref_jiazhu`（书级，缺省全关、关时不进参数 dump；A24 P01 深挖 11-06）：P 类取整理本字（`p_ref_admit`）加三个旋钮——机器字库覆盖率须低于上限、放开同列相邻成片、放开夹注半格。殿本线上 P01 单开 `p_ref_admit` 放 126 格、看图 13 格机器字本来对（cov 都 ≥0.94）；加 cov<0.93 放 31 格零错，再放开相邻＋夹注放 52 格。

- seed_admit 1.45 `rare_ref_coord_group_top`（书级，缺省关、关时不进参数 dump；A24 L05 深挖 11-06）：rare_ref 坐标对位那支，库首位是字组成员、坐标对位字不在任何字组时也放（坐标对位字在组里仍不放）。L05 格里糊墨的库首位多是 刪／冊／衛／王 这类字组成员（吸引子），整理本字与 5-b 首位一致、不在组里。殿本、史記 ★main 离线回放：配 `rare_ref_coord_min_cov` 0.85，L05 238 格放 91（缺省只调 min_cov 放 79），看图全是整理本字；缺省关，行为不变。

- seed_admit 1.44 `follow_ref_variants_gap`／`follow_ref_variants_cov`（书级，缺省 None 行为不变、不进 dump；A24 V01 深挖 11-06）：按参校本取异体（`follow_ref_variants`）的待审格单独放宽领先下限，只对关系层同词异体（`variant_edge(...).is_variant`）、库首位 cov ≥0.93 生效。史記 V01 夹注半格 10 格领先 0.002–0.004，看图字都对；开不开、设多少由书项目定（建议史記 0.002）。

- seed_admit 1.43 `edge_pair_group_seam`（缺省开，A24 V01 深挖 11-06，第 7 轮）：edge_pair 补字组缝——纯异体强边但有一字是字组成员、这一格字组没接的待审格也按 edge_pair 判（形近组领先 ≥0.03，`replace_form: review` 不越过）。三书 ★main 包约 9 格，看图字都对。
- `variants.variant_edge()`／`VariantEdge`（PATCH，A24；V01 深挖 11-06，算进第 7 轮）：放行与归因共用的异体口径（tier、来源、异体来源数、只有通假形近），`edge_pairs.is_auto_pair` 改用它，行为不变（全图 94,392 条边新旧逐条一致）；护栏类仍用 `are_variants`（宁多拦），`edge_pair` 要 ≥2 个异体来源是有意比归因严。manager `reasons.py` 之后改调它。
- 注释（A24 N01 流程梳理，sheldon 11-06）：`seed_admit` 模块头的通道说明重写（旧版只写 match_solo 两条）、`near_form` 疑问在 seed_admit／seeding／confusable 三处写清口径（手工表 20 对；与匹配层护栏 `_PARTNER` 三表并集、待审原因 N01 是三个口径），指向 guji-manager `near_form_guard/流程.md`。只改注释和 docstring，**不改逻辑**；`code_hash` 只认代码，各步指纹不变。
- `seed_admit` 1.41：折叠组（日曰、己已巳）书级参数化（A24 H01 深挖，sheldon 11-06「框架参数化，每本书自己试参数」；**全部缺省关**，关时不进参数 dump、逻辑与改前相同）。`fold_aspect_pairs`（哪组按宽高判、哪个字窄哪个字宽，缺省 `{ry: [日, 曰]}`）；`fold_jiazhu`（夹注 a/b 半格也折叠，半格只按宽高或文意裁定落字、绝不取整理本字；史記 H01 117 格里 94 格是夹注「某某曰」，原先半格一律跳过）；`fold_aspect_jiazhu`（半格单独阈值）；`fold_aspect_ctx_veto`（context_decide 给组内另一个字的概率 ≥ 阈值时宽高结论作废，记进 `fold_pending.ctx_veto`；防切分框不准，如史記 03:43:2:19b「孔安國曰」宽高比 0.68）。`scripts/fold_aspect_dist.py` 改为多册合并、正文／夹注分开、真值取已放行且机器字＝整理本字、按精度推荐阈值、一侧不可分就明说。新文档 `doc/4-定字/字组/折叠组.md`：流程、参数表、每本书怎么标定、三书现状（殿本不开宽高；史記只判曰；全唐文只判日）。seed_admit 版本变，各册 seed_admit 过期，随下一轮统一重跑。
- 补登记漏列的 `code_deps`：`align_ref` 加 `utils.han_ranges`（2.8 起 import）、`seed_admit` 加 `utils.pua_v2_codes`（1.37 起 import），以后改这两个模块对应步会判过期。代码早已在跑，补登记不改行为；`core/code_equiv.SPLITS` 登记合回原来一项，**两步 `code_hash` 不变、不过期**（全部 23 步改前改后实算逐位相同）。缘起 manager CI `test_code_deps_coverage` 在 dev 上红（A23 报）。
- `seed_admit` 1.40：规则 A（rare_ref）加少刻例支 `rare_ref_sparse`（书级，**缺省关**，关时 `rare_ref_sparse*` 不进参数 dump）。参校字（现役对位，缺了用坐标对位字）在本书库里刻例 ≤ `rare_ref_sparse_max_n`（2）、5-b 首位是参校字（参校字是扩展区码位时也认它的异体，`rare_ref_sparse_variant`）、领先同来源组外最好候选 ≥ `rare_ref_sparse_lead`（0.02）时放行，通道 `rare_ref`，evidence `rare_ref.via=sparse／sparse_coord`、`lead`、`n_lib`。硬护栏、字组、group_flow／shadow_veto 疑问、库明确认成别的字一律不放。补的是原 rare_ref 两支漏掉的格（替换段要求、整页没锚、cov<0.90）。缘起 A23 L02 深挖（ai-team `domain/CV/质检/待审原因深挖/L02-刻例太少不一致.md`）：殿本线上单 L02 286 格里 274 格图就是参校字；★main 回放 cv 自己的 5-b 能放约 46 格（领先 0.02）。sheldon 11-06 同意，开不开按书定，随下一轮统一重跑。seed_admit 版本变，各册 seed_admit 过期。
- `align_ref` 2.8：对位字流（`_corpus_text`）、坐标对位行偏移、金标清洗 `align_label.is_han`、`witness-align-stream` 统一按 `utils/han_ranges.py` 认汉字，**收扩展 A、B–J**（原先对位字流只留 U+4E00–9FFF，`is_han` 只到扩展 B）。整理本里的 㣲 𮅕 𮪍 这类扩展区字以前被删掉，整理本少一个字，difflib 在那里断段（A23 诊断 ai-team `domain/CV/质检/待审原因深挖/Z01-对位缺位诊断.md`：殿本 Z01 现役对位缺位 394 格里 109 格因此而起；殿本语料扩展区字约 1.26 万个）。97 册抽 4068 页现役对位 +3653 格，既有标签变 4 格，看图都不是退步（见 PR）。所有书 align_ref 及下游过期，**不进 v0.6.16，排第 7 轮随换图源全套重跑**（A31 11-06 定）。
- `seed_admit` 1.39：书级新开关 `match_ref_diff_guard`（**缺省关**，关时不进参数 dump、产物不过期）。打开后 match_ref（整理本 equal 段与库首选同字）在库判 diff 时不放行，记 doubt `match_ref_diff` 退回人审（并入 `_LANE_HARD`，待审补放不放回）。缘起殿本 vol05 66:9:15：图是「不」，对位滑格给「字」，库首选也是「字」但判 diff，原先 match_ref 没有 cov／verdict 下限照放。70 册 ★main 包里这类放行 177 格（殿本 155、史記 19、全唐文 3）。殿本开不开等 sheldon 点头（A24 11-06）。
- `seed_admit` 1.38：字组入口新开关 `group_flow_coord_outside_skip`（缺省开）。现役对位缺这一格、坐标对位字既不是组员也不是陪衬字（〓、空格位、暂归一写法除外）时不拉进组：组只会在组员里挑字，这类格进组必弃权（Z01）。A24 Z01 深挖（11-06）：殿本第5轮 Z01 527 格里 394 格现役对位缺位；按 ★main 包回放 Z01 −106（多为門辶囗族少见字，原因落回 L01／P02），已放行格不受影响（70 册包里命中 7 格，都是 𭶑，已按暂归一写法排除）。只改原因、不放行。seed_admit 指纹变，随第 6 轮重跑。
- `seed_admit` 1.37 `pua_code_table`（缺省关，殿本开；A24，A31 X01 派单）：按私用码表改放字——格→码对应离线算好存裁定库 `src-2`（按格号取，带整理本对位字核对，`RulingStore.cell_codes`／`put_cell_code`），非人裁放行字≠码表字 → 改放码表字（通道 `code_table`），一码多字（F1001／F1055）标族豁免、族外降审，人裁不动；每页统计 `PageAdmit.n_code_fix`／`n_code_mismatch`（0 不落盘）。新增 `utils/pua_v2_codes`、`config/pua/siku_qiefen_v2_codes.json`、`research/a24/pua_src/build_cell_codes.py`。开关关着时产物逐位不变（参数不进 dump）。

## [0.6.15] - 2026-11-06

- `seed_admit` 折叠组 `fold_occluded`（书级，缺省关）：遮挡格只在整理本字与库首位同在折叠组内时归组；须同写 `fold_ref_char: false`（#1178，A24，D01 深挖）。
- `ref_lib_coord` 疑问白名单加 `context_page_end`（#1179，A23 L04 深挖；殿本 0 命中、史記 3 格）。开了 ref_lib_coord 的书 seed_admit 过期一次。
- `glyph_match` 共识升档口径、形近护栏、same 门槛做成参数（#1174，缺省关、关时逐字节不变）。
- 待审原因 P01/P02 跟 guji-manager #239 改名 `ref_ocr_diff`／`ref_final_diff`（#1175，文档与补标脚本）。
- `seed_admit` 1.36：R5 题列套语容错 `lane_seal_title_tolerance`（书级，缺省 0＝关，关时不进参数 dump；殿本开 1）与 `lane_seal_title_prefix`。整列坐标字前 8 字与「欽定四庫全書總目」至多差 N 字、尾部（卷＋数字）完全符合时仍按套语放，不一致的字位记 `lane_skip.why=title_mismatch` 留人审。殿本 D01 深挖（A32 11-06，A31 定第 6 轮做）：vol77 p119 c1 整理本「錠」误字，其余 10 格可放，錠格留审。seed_admit 代码指纹变，各册 seed_admit 起判过期，随第 6 轮重跑。
- `row_segment` 切点判官（U-Net）结果落盘复用（`seg/cut_select`）：按窗口灰度内容＋墨阈＋判官指纹存执行机本地 `cache/_judge/`（每页约 4 MB），同机重跑同一页不再前向。史記（`cut_judge: unet_f64`）8 页首跑 108 秒、重跑 7 秒；产物逐字节不变、登记 code_equiv，不判过期。`GUJI_JUDGE_CACHE=0` 关。

## [0.6.14] - 2026-11-06

- 史記夹注逐步切 v1.5（`books/shiji_wyg/jiazhu_step`）：逐步切过的夹注行，格线（`boundaries`）跟着贴新切的 a/b 两半（`_step_boundaries`）。此前只换格不动格线，cell_shrink 合成满宽格取旧格线，v1.4 切满到列尾的段第 21 行格线落在字下白里、被列端渣格闸判空，两半的字悄悄丢掉（第 16 轮 6 列 12 字，另有旧有 8 格同因）。全书 738 页重跑到 cell_shrink：丢的 20 格回来，其余格框持平或变好。史記职名页单段列（`roster_segment.refit_column`）几何块只比整理本差 1 字时另按块凑一版，切线压块腰的条数比整列等分少 2 条以上才用（07:2:5 题署列修好；10:2:6、07:2:7 不变；职名页 100 页另有 5 列密排官衔变好）。新增验收脚本 `scripts/check_layout_drop.py`：格位表说有字、Step4 没了或判空的格逐格列出。
- `row_segment` 卷端大印列（`roster_seal_despeckle` 开着、`header_cols` 认得的列）去印点后抹列顶印边残块（`_clear_seal_top_residue`：印上边带里、矮且与下段隔 ≥0.3 列宽，或墨挤在 0.25 列宽竖带里的界行残线），起格跳过整格在首字之上的印泥格。史記 02 p2 c4–c6、04 p2 c4 题署列不再整列错一格；殿本不走，vol12 152 页逐字节相同、登记 code_equiv `_SEAL_TOP`。

## [0.6.13] - 2026-11-06

- `cell_shrink.ink_blob_empty`（书级，缺省关，关时逐字节不变、登记 code_equiv）：墨团闸，格里主体是一块实心圆团（闭运算后最大连通块占墨 ≥90%、长边 ≤0.6 格高、长宽比 ≤2、内切圆半径 ≥0.25 长边）就记空（旗 `ink_blob`）。全唐文 S6：011:68:1:14 墨点被认成字。005/006/007/009/010/011/012 七册全开只命中 2 格（另一格 009:156:9:22 本来就被渣格闸记空），0 误伤；18,469 张真字块半径比最大 0.198，墨团 0.30。
- `row_segment` 自动配页加参照类型 `page_map_ref`（Sheldon 11-06 定按文本类型做）：缺省 `column_slots`（daizhige，行为不变，登记 code_equiv）；`column_text` 接「逐列无格位」的参照（`#@ 半叶头`＋一行一列的逐列文本，如全唐文 Kanripo）——Step3 开跑前按列窗口与原图量各格墨，配页比各列字数、格位按图定，边跑边出格位表，不用先跑 Step1–4 再离线出表（`steps/row_segment_coltext.py`）。`utils/page_align` 抽出 `align_scores` 供各类型共用配页 DP。
- 史記夹注逐步 `jiazhu_step` v1.4：`_better` 在毛病格一样多、格高偏离小 0.15 以上时也换成新切法（第 14 轮 02:104:7「云密」、02:12:6「上洛」、05:48:8「集解」两字并一格，v1.3 只认毛病格变少没换）。只影响史記（seg_set shiji_wyg），row_segment 起判过期。

## [0.6.12] - 2026-11-06

- 史記套书缺省 `books/shiji_wyg/defaults.yaml`：01–10 册逐册同值的 23 个切分开关收到套书一层，`seg_set: shiji_wyg` 的册自动带上（01–10 册生效参数逐项核过不变，指纹不变）。

- `cell_shrink` 1.26：`inner_frame_cut`、`inner_frame_profile` 缺省开（殿本新图源 vol20–99、史記、全唐文全都开着，Sheldon 11-06 定）。没写这两个开关的册 cell_shrink 起结果会变（殿本 vol01–19 钉旧版、换新版前要写 false；北行现代本套书缺省写了 false）；写 false 的册参数 dump 与以前相同。cell_shrink 代码指纹变，各书 cell_shrink 起判过期。

- 切分共用（三套书盘点 11-06）：`scripts/seg_fork_drift.py` 查套书分叉副本是否漏跟原模块的修改；基础配置 `row_segment.layout_prior` 可写 `{book}` 占位、按册展开（展开后与逐册写死相同，指纹不变）。
- `inner_frame_keep_cross` 收窄（A22，SJ 第 13 轮）：压线段宽过列宽 0.12（字底一横）不留，还要往上连 10 行墨才算笔画（线的毛边不算）；新参数 `cell_shrink.inner_frame_cross_max_w`（缺省 0.12，只在 keep_cross 开时进 dump，0＝旧判据）。修列尾字块往下伸到内框线（史記 03:215:8:21「曰」读成「里」）。keep_cross 关的书逐字节不变（code_equiv 已登记）。

## [0.6.11] - 2026-11-05

- 精校换单 `proof_cycle`：机器改字默认按最新结果进文本，不再进复审（sheldon 11-05 定，取代 10-20「未冻结册变字一律进待审」；殿本 r5 换单因此多出 8,019 格复审，六成是 □→字）。只有机器推翻最新人裁的格留人裁的字、进复审。只动脚本，不改指纹。

- `row_segment` 格位表人定格线 `cuts`（＋`col_h`，表里没写这个键的列逐字节不变、登记 code_equiv）：表行给了整列格线（列图 y、格数＋1 条）就照线切，不跑 DP、不比候选格网，列端记空照旧；列图高与 `col_h` 差过 4px、线乱序或装不下表的格号就不套（旗 `layout_cuts_stale`）。全唐文 S1 用它钉住 slots／pitch 钉不住的 6 列（010:35:1「導」寸、011:85:9「一甲」、013:151:9「于」与闕三字小注、014:82:6 列首「大」、006:61:2「高」、010:99:1「卷二十九」）。
- `cell_shrink` `tail_one_abs`（书级，缺省关，关时逐字节不变、登记 code_equiv）：列端渣格闸加孤「一」绝对量逃生口（高 ≥14px、宽 0.45–0.8 墙距、实心、横着、居中 ≤0.1 墙距、不贴图块端，且往里一格是字），按格高算的两道逃生口够不着的列端「一」不再记空。全唐文 005–015 全书捞回 22 格，看图全是真「一」，0 误捞（006:135:5:22、009:103:9:22、012:31:3:1…）。

- `cell_shrink.inner_frame_local` 补（全唐文 S5，只在开关开时生效，关时逐字节不变、登记 code_equiv）：贴线搜索放宽到 ±0.5 格高、整页内线拟不出时种子线兜底（`fit_inner_frame_line(seed_fallback=)`）、列端剥框线只认贴着整页内线的线行（`extractor.INNER_REACH`）。修 009:107 業 腿被截、006:118:9:22 人 尾被剥、010:74 底线漏抹。
- `cell_shrink.inner_frame_local`（书级，缺省关，关时逐字节不变、登记 code_equiv）：整页拟出的内框细线逐小段贴到真线上，内线厚上限随格高放大（`seg.frame_line.localize_inner_line`、`inner_thick_limit`）。全唐文 S4：外框在页边拐弯、内线 5–12 行厚时整页拟合跟不上，列首列尾字块挂线（006:29:2:22、006:121:1:22、010:23:1:22、010:166:9:22、012:58:1:1，与 `inner_frame_profile` 同开全修）；006/010 各 60 页改 69 张字块，全是去掉线头。
- `column_warp.det_warp`、`row_segment.cut_judge: unet_f64`（书级，缺省关，关时逐字节不变、登记 code_equiv）：列射影与切点判官改 numpy／torch 双精度，跨 CPU 指令集逐位一致（S9：执行机与本机 012:99:1 切点不一致，根因是 OpenCV 5 warpPerspective 浮点 SIMD 与 fp32 判官）。全唐文 006/010 各 20 页四种 CPU 设置下产物逐字节相同；与不开比格框变 3 列、看图都切在字缝；整段慢约 35%。
- 史記夹注逐步 v1.3（books/shiji_wyg/jiazhu_step，SJ）：修 v1.2 在格数对的列上误挪的回归（01:60:8、02:37:1、02:56:4/5）。格数对时只按逐行空格判是否重切，不挪段首；新切法须格数更好且匀度不差过 0.05。只影响史記 row_segment 及下游。

## [0.6.10] - 2026-11-05

- cell_shrink 书级开关 `inner_frame_keep_cross`（缺省关，A22）：抹内框细线时，穿过线的笔画留着（写本字脚压线，史記 05 册「義」「軍」「何」「將」）。殿本试开竖画下多挂线头，不开。关着时逐字节不变（code_equiv 已登记）。
- 史記夹注逐步 v1.2（books/shiji_wyg/jiazhu_step，SJ）：分法不均的段图上能证明分法就不送审（旗 `jiazhu_uneven_img`）；段下沿、后段段首、列首抬头格、格数对但位置错、末段到列尾各补判据。只影响史記 row_segment 及下游。

## [0.6.9] - 2026-11-05

- `seed_admit` vis_ruling：裁定字须是汉字（#1135，A24，缺省开，只影响非汉字；汉字区含 Unicode 17 Ext J）；`build_events` 文本层取字只取已分配汉字（#1134）。
- `seed_admit`：参校字非汉字一律不取；`lane_coord_few_stroke` 少笔画名单（#1132，SJ 史記 r12，缺省关）。
- `ids_online` `IdsSpec.refine` 二次细判（#1128，缺省关）。
- `row_segment` `jiazhu_half_a`（全唐文套书，书级，缺省关，关时逐字节不变、登记 code_equiv）：格位表 `half`（只有右半有字）的夹注格一律发 `jiazhu_a`，左缘与缝放宽到压着右半的连通块最左；段尾奇数字居中跨缝时不再被缝劈开或发成左半（012:186:9:11「篇」、013:147:8:21「二」、013:147:9:2a「一」、8a「二」）。全唐文 005–015 有 half 的 34 页 138 格开前后只变这 6 格，无变坏。

## [0.6.8] - 2026-11-05

- `seed_admit` 折叠组改按文意（#1124，A24，缺省关）：新书级键 `fold_ref_char`（false＝不取整理本字，只用本组裁定 via=ruling）、`fold_aspect: [lo, hi]`（日曰按字块宽高比落字，via=aspect）；两样都没有的格留审，记 `evidence.fold_pending`。ref_free 组（己已巳）忽略 `group_flow_abstain_ref_ok`。`scripts/fold_aspect_dist.py` 标定阈值（#1127）。
- republish 出单报告单列待收字（含窗口回查判成的格数，写「最多 N 格」），读不到登记表时提示（#1121、#1122、#1123）；待收字登记表修重复前缀并加格式守卫（#1120）。
- `manager_api` 登记 `PuaIndex`、`resolve_pua_code`（#1126）。
- #1115 的 row_segment code_equiv 由 A22 复核成立（殿本 vol58 34 页、史記 05 32 页逐字节相同）。

## [0.6.7] - 2026-11-05

- `seed_admit` `iron_ex_from_store` 改缺省开（#1114，用户 11-05 定）。
- 待收字（#1115，A24）：`utils/daizhige` 把僻字码原码位带到 `columns.jsonl`（`daizhige:U+XXXX`，文本照旧 〓，row_segment 产物逐字节不变、已登记 code_equiv）；新增 `utils/pua_lookup.resolve_pua_code`（按整理本前后 20 字窗口回查码位，窗口唯一才认）；文档补 R03 `glyph_pending`。
- 私用码点选结果入码表、待收字登记表、F→E 码对照（#1116、#1117，研究数据）。

## [0.6.6] - 2026-11-05

- `seed_admit` `fold_groups`（#1104，A24，缺省关，书级）：折叠组（己已巳 jys、日曰 ry）内待审格整理本字在组里就放整理本字，`channel=fold`，`evidence.fold={group,ref}`。护栏 `fold_ruling_first`、`fold_lib_top_in_group`（#1107，缺省关）。
- `seed_admit` `p_ref_admit`（#1105，A24，缺省关）：P 类机器字≠整理本时取整理本字（孤立格、非半格、非字组），`channel=p_ref`。
- yh 字组 L1：贖還 定為還（#1106，A24）。
- 大太 dt、王玉 wyu、十卜 sb 加 IDS 字形解法声明（#1108，整字 HOG，模板由各书重训；没模板弃权）。
- `seed_admit` `ruling_ref_lead_min_unseen`／`ruling_ref_lead_min_oov`（#1110，缺省关，只进 params_hash）：5b 验证整理本字证人的书级阈值，由 manager final-review（v0.4.6）读。
- `seed_admit` 终审裁定证据（A31，配 manager #184）：ctx-m1 裁定放行的格，`evidence.vis_ruling` 带上裁定的 `via`（`ref_lead`）与 `ref_lead`（层、领先量）；裁定 `gate=ref_lead_fail` 的格留审，证据记 `ref_lead_fail`，供按包统计分放行来源。只动证据，放行结果不变。
- `seed_admit` `fold_coord_ref`（缺省关，只在 `fold_groups` 非空且开时进 dump；关时逐字节不变，登记 code_equiv）：折叠组扩展，现役对位缺时用坐标对位字，没进字组流程的格（如 曰 旁有组外字 田 挡了入口）库首位与整理本字同在某折叠组就按该组折，`evidence.fold.coord`。配 #1107 两道护栏用；全唐文 r13b 估多放日曰 14 格（形近字线 11-05）。

## [0.6.5] - 2026-11-05

- 抬头漏认收尾（2026-11-05，A22）：row_segment 1.46 `layout_raise_box` 改缺省开、重编候选同分优先；border_detect 1.20 上版框弱线护栏（选中线墨量不到最强横线 0.3、上方 ≥0.021 页高另有强线就改取，殿本 16516 页只动 12 页）；column_warp 1.6 `refine_top_by_frame` 否决加例外（上面另有满宽段、中间先白后字墨就照常上提，SJ 史記 02:5）。三步指纹都变，各书 Step1 起过期。border_detect 新参数 `top_weak_ratio`（缺省 0.3）、`top_weak_floor`（缺省不用）：写本（史記）册配置写 0.45／0.25，框条下细虚线、首行字顶齐平的页（SJ 02:5 等 7 页）上框改落到细虚线。
- 依赖：`opencv-python-headless` 由 `>=4.8` 钉到 `>=5.0,<5.1`（cv#1098：4.10 与 5.0 的 row_segment 产物不同，执行机与 uv.lock 已是 5.0.0.93；不改代码与指纹，执行机产物不变；本机装着 4.x 或 `opencv-contrib-python` 4.x 的要重装）（全唐文切分线）。
- `scripts/eval_font_family.py`：字体族实测，三书人裁刻例互为查询与库，量借库能借多少（只动 `scripts/`，不改指纹，A23）。
### Added
- cell_shrink `inner_frame_only`（缺省关）补列端切笔：Step2 当框条削掉的字顶字脚从 column_raw 补回，挨线的首末格条带开到内框线、地盘外伸 0.35 格（只认像笔画的墨块），贴线碎块只剥薄片（没拟出内线的一端也只剥薄片）；关着时逐字节不变（code_equiv 已登记）。
- `seed_admit` 三个缺省关开关（关时逐字节不变，登记 code_equiv）：`group_flow_provisional_to`（书级暂归一字形，组 id→字，须在该组 forms 内；全唐文彝组 yi_560 兜底落 𢑱 → 彝）、`ref_lib_coord_dissent`（坐标对位给实字且与现役对位语义不同时不走 `ref_lib`，硬疑问落审；全唐文 r11 麒→麟、褚→諸、俘→俾）、`replace_form_edge_exclude`（`replace_form: lib` 不换成假边表 `edge_pair_exclude.tsv` 里的另一半，往→住）（形近字线 11-05）。
- `scripts/zhengli/pending_list.py --seg-flags`：读 guji-manager `review/seg_defect --gate` 出的同字对照自检旗表，已放行的切笔格（clipped）改送人审（why `seg_defect`、`src: seg_selfcheck`），已在单上的只加 `seg_kind` 证据；`.meta.json` 指纹对不上现行产物就停。`republish prep` 在跑 pending_list 前按书级表现算旗表（`--no-seg-selfcheck` 关；书没开、manager 太旧都不跑）。只动 `scripts/`，不改指纹，缺省输出不变（两部书都登记为关）（A22 B1③）。
- `scripts/eval_ref_verify.py`：5b「验证整理本字」评测，在三书人裁 5b 冻结集上量 emb 首位且领先 ≥ m 作为证据的放行率与错放率（只动 `scripts/`，不改指纹，A23）。
### Changed（原误记在 0.6.3 下，实为 0.6.3 发版后合入）
- cell_shrink 再生字块提速（2026-11-05，A20）：执行机缓存是空的时下游逐格再生字块，本页 cells 产物与列图改按页记一次（原先每格重读 JSON、重解整列 PNG）。样页每格 7.5 → 3.8 ms，逐像素不变，已登记代码等价。
- seed_admit 加 `iron_ex_from_store`（2026-11-05，A20，缺省关）：铁证判别器的人裁刻例图从字形库取，不读缓存，产物不再随执行机缓存变；开不开待用户看 A/B（`doc/开关登记表.md`）。缺省关时已登记代码等价。
- 图形评测折叠己已巳、日曰（2026-11-05，Sheldon：这两组图上分不开，匹配到组内任一个都算对，不单独统计正确率）：新增 `scripts/eval_fold.py`；`eval_db_match.py`／`eval_match_pairs.py`（缺省折叠，`--no-fold` 回旧口径）／`eval_oov.py`（同）／`calibrate_lib_witness.py` 按组折叠金标与候选。只动 scripts/，各步指纹不变。

## [0.6.4] - 2026-11-05

### Fixed
- 文意留痕 `methods._ctx_out` 只留白名单键，把 #1071 记的待裁问题 `extra.ask` 丢了，`llm_queue export` 恒为 0 问：保留 `ask`（#1080，SJ）。seed_admit 指纹随之变，第5轮殿本从 seed_admit 起重放。

## [0.6.3] - 2026-11-05

### Changed
- 页型老写法改报错（A20 11-13）：册 yaml／基础配置里的 `border_detect_gate.body_pages`／`table_pages`／`row_segment.roster_pages` 读配置时抛 `BookConfigError`（11-04 起警告）；运行覆盖不管；`GUJI_ALLOW_OLD_PAGE_SYNTAX=1` 放行。中心库 391 册已扫过没有在用的；迁移脚本（guji-manager #548）核指纹时自动放行。只改配置读取，不动 Step、`code_hash` 不变。
- seed_admit `iron_ex_from_store` 改缺省开（2026-11-05，用户定）：铁证刻例图一律从字形库取，产物不再随执行机缓存变。**各书 seed_admit 判过期、要重跑**；史記 01 上 3 格待审转放行（都合坐标对位字）。
- 管线缺省不调 Anthropic API（2026-11-05，用户定；#1071、#1072）：文意 L3／二审小组／看图判只读裁定库，没命中弃权 `abstain:llm_pending` 并在产物留下问题；`python -m open_guji_cv.feedback.llm_queue export/import` 导出待裁清单、把对话统一审的答案写回裁定库。`GUJI_LLM_ONLINE=1` 才在线问。
- seed_admit 页头计数：src_code_conflict 降审计入 n_auto/n_review（#1046）。

### Added
- row_segment 书级开关 `layout_raise_box`（2026-11-05，A22，缺省关）：闸认出抬头框而逐列格位表记不抬头（首字顶格）时，加一张表按闸级数重编格号的候选格网，坏格严格更少才选；抬头框要比本页不抬头列高半格。殿本 164 列沙箱 84 列改对。关着时逐字节不变（code_equiv 已登记）。
- 三书人裁金标与 L2 证人标定脚本（2026-11-05，A23 字形领域中期第二项）：`scripts/build_book_human_shards.py` 从中心库人裁冻结 char-clustering 5a 分片＋5b `rare.jsonl`；`scripts/calibrate_lib_witness.py` 按生产口径重放 Step5-a、标定「库前五 ≥ t」证人；`eval_oov.py` 加 `--bench/--items/--no-flagged` 与分层报数。`build_match_pairs_dataset.py` 随机对循环加尝试上限（小书同字对不足时死循环）。只动 scripts/，各步指纹不变。

### Changed
- cell_shrink 书级开关 `inner_frame_profile`（缺省关，要 `inner_frame_cut` 一起开；A22-2，2026-11-05）：小段投票拟不出内框细线的页（殿本新图约两成页，内线磨成点线），按外框拉直的整宽行墨再找（`seg.frame_line._profile_inner`）。列端评测集 frame-end-crop 带框 17→8、切笔不变；开关关着各步指纹不变（code_equiv 登记）。
- 弹性对齐提速（2026-11-05，A20 性能子任务）：`clustering/verify._elastic_align` 的 query 侧取数表按条记忆（库匹配一个 query 连打约 10 个候选），块内位移最优从花式取数改成滑窗最大值。结果逐位不变，已登记代码等价，各书产物不过期。同机微测单次对齐快 10–18%；任务库史記 01 册两单（不同执行机）对齐 2.1 → 1.0 ms／次。
- 拆分 P4 中层（2026-11-04，用户「继续 都做完」）：`guji pipeline`／`status`／启动时的 manager 行为改成钩子（`core/hooks.py`，入口点组 `guji.hooks`，由 guji-manager ≥0.3.3 登记）：开跑前备钉版字形库／模型／语料与 Step5-b 模板索引（prepare）、整册跑完自动存包与没存包提醒（finished）、status 的收尾闸／裁放不一致／看图待审（status）、派生缓存取件器与耗时记录（startup）。没装 manager 时照跑；只有册钉了字形库、模型或语料时 `guji pipeline` 拒跑（退出码 2，`--no-prep` 放行）。`guji rerun`／`pagekinds`／`cache`／`product`／`products`／`perf` 搬去 guji-manager（老版本 manager 给装法、退出码 2）。`ops` 剩下的（除 model_blobs，测试开跑取模型要用）、`render`、`review`、`exp`、`feedback.vision`、`jobs.perf_push`、`cli_products`、`cli_perf` 删除；`ops/preflight.py` 改放 `open_guji_cv/preflight.py`（归 pipeline）。cv 里已不再有 manager 一侧的命令模块（`MANAGER_CLI_MODULES` 为空）。各步指纹不变。

### Fixed
- 插件命令在同一进程第二次建 parser 时（测试、控制台）被当成 cv 自带而漏登：`load_plugin_commands` 记下哪些是插件登记的（`_PLUGIN_ADDED`）。拆分 P2 第三批前置。

### Added
- S 类待审成因归因（A22-3，11-04）：`python -m open_guji_cv.review.seg_causes <册…> --products <产物根> [--pending …] [--known …] [--out 目录]`，只读产物包，把 S01–S04 待审格按包里的事实（钉页、页型、整理本∅、格位对得上、假大印／印章、反色带、页／列未过闸、列网、格少于整理本、错位、格数／格高离群、对位冲突）拆开，出汇总.md／逐页.tsv／逐格.tsv，各书自跑。统计口径仍是 `pending_reason`，不写单、不新增原因；不在任何 Step 的 `code_deps` 里。

### Changed
- 拆分 P3 jobs（2026-11-04）：任务库的执行方与命令（`jobs/` 的 runner、cli、board、notify、exit_trace）搬去 guji-manager（≥0.3.2），cv 留 spec、store、jobsdb。`guji job` 登记 `MOVED_TO_MANAGER`；`scripts/guji_jobs.sh` 改跑 `python -m guji_manager.jobs`，`python -m open_guji_cv.jobs` 留作转发（老执行方空闲换代码时沿用老命令行）。15 个测试文件随之搬走。19 步 `code_hash` 不变。
- 拆分 P2 第四批（2026-11-04，用户「继续 都做完」）：cv 里已没有别的模块依赖的 manager 一侧代码（118 个模块，约 3 万行）搬去 guji-manager（≥0.3.1，同路径 `guji_manager.<原路径>`），cv 删除：`review`（留 verdict_view）、`feedback` 生产侧、`eval`（留 rulers／colgeom／round_check）、`exp`（留 compare／labels／stats）、`formats`、`render`（留 overlay）、`snap`、`ops` 大部分、`report.html／run／progress`、`gold.transfer`、`datastore` 的 backup／spreads／verify／source_xform，及命令 close-check、exit-check、audit、char-diff、db、store、recheck、glyphlib、rekey-cells、promote、corpus、glyph-db、model、font（`MOVED_TO_MANAGER` 给装法）。相应 101 个测试文件搬去 guji-manager `tests/from_cv/`。`console_api` 里指向已搬模块的名字改取 `guji_manager.*`（控制台要装 manager）；`manager_api` 删去已搬的、加 270 个搬走代码仍要用的名字。`scripts/` 里 54 个脚本改从 `guji_manager` import，`scripts/zhengli/` 用到的没装 manager 时先调 `ensure_manager`；测试里 `ensure_manager` 不动本机的包（conftest 设 `GUJI_NO_ENSURE_MANAGER=1`）。`python -m open_guji_cv.review.seg_causes` 等改为 `python -m guji_manager.…`。19 步 `code_hash` 不变。
- 页型表加 `cover`（书衣／封面）页型（A20 11-04，SJ 建议，PATCH）：册 yaml `page_kinds: {cover: [页号]}` → 新参数 `border_detect_gate.cover_pages`，点名页记页型 `cover`、整页跳过（reject `page_type_skip`，flag `page_type_cover`），与自动判出的封面产物同形（网站占位按页型 `cover`）；同页不许同时写 cover 和 body／table；`guji pagekinds` 认「点名封面」。`cover_pages` 缺省空、空时不进参数 dump；border_detect_gate 代码变了，已在 `core/code_equiv.py` 登记（不点名封面的册产物逐字节不变，各册不过期）。
- 拆分 P2 第三批：15 条命令的命令层搬去 guji-manager（≥0.3.0），cv 删除 `cli_exp.py`、`cli_ops.py`、`cli_feedback.py`、`cli_eval.py` 与它们的命令层测试（9 条，含 `guji snap` 4 条），登记 `MOVED_TO_MANAGER`、`MIN_MANAGER_VERSION`。搬走的命令：exp、snap、archive、release、deploy、events、gold、batch、label-batch、eval、check、groups、cards、progress、collate。底下逻辑仍在 cv，`manager_api` 加 73 个名字。命令和参数不变；不碰任何 Step，`code_hash` 不变。
- IDS 模板库挪进模型系统（A24 11-04，Sheldon 同意；PATCH）：`config/groups/*/ids_bank.json`（73 个）和 `can/whole_bank.json` 是从殿本人裁挖出来的，按「从哪里来」归殿本 book 层——`model_pack.KINDS` 加 `ids_bank`、`ids_whole_bank`（含出处），`corpus_pin._not_corpus` 不再把它们算语料（老清单登记过的核对时跳过，钉着语料的册不受影响），`core/model_override` 的运行时换路径加上 `bank_path`、`whole_bank_path`（册钉旧模型号时模板库也走缓存根）。cv 自带的模型表 13→87 项、语料表 136→62 项（重写 `guji model registry`／`corpus registry`，87 个文件早已在 R2）。文件内容不动，`ids_online.fingerprint` 按内容哈希，**seed_admit 指纹不变**；`ids_override.tsv`、`ids_fine.tsv` 是手写规则，仍算语料。**注意**：已钉 `model: 2` 的殿本、史記在 `guji model build` 出 m3 之前，模板库改了不会被起跑校验发现（原先由语料钉号盖着），出新号时一起钉。不碰任何 Step 的 `code_deps`，`code_hash` 不变。
- `seed_admit.group_flow` 缺省改成通用字组，不含码位组 `cp_*`（A24 11-04，多书设计 A3，Sheldon 同意；**不要在下一轮统一重跑之前合**）：`cp_*` 是殿本逐对看图定的码位结论，新书缺省不该带上。新增 `groups.registry.generic_flow_names()`。殿本基础配置显式写了全集（含 `cp_*`），不受影响；但**史記 988g3f0wsu（42 册）、全唐文 995ejelvk0（248 册）的册配置和基础配置都没写 `group_flow`**，一直吃缺省全集——合之前要先把旧缺省全集显式写进它们的 `book_defaults.yaml`（`params.seed_admit.group_flow`，名单见 /mnt/project-files/a24/设计/group_flow-旧缺省全集-2026-11-04.txt），参数 dump 才与旧缺省逐字相同。改了 `steps/seed_admit.py`、`groups/registry.py`，两者都在 seed_admit 的 `code_deps` 里，**所有书 seed_admit 的 code_hash 变**，所以放在一次本来就从 seed_admit 起重跑的轮次里合；其他书（幼學、qtw-draft、北行、增廣等）有没有显式 `group_flow` 还没逐一核。
- 拆分 P2 准备：`scripts/zhengli/zl.py` 开工也先调 `ensure_manager.py`（下一批 `snap`、`events`、`collate` 等命令要搬去 guji-manager）。
- 页型表 `page_kinds`（A20 11-04，管线重组方案 B 第四期，PATCH）：册 yaml 顶层 `page_kinds: {body|table|roster: […]}` 取代散在 `border_detect_gate.body_pages`／`table_pages`、`row_segment.roster_pages` 里的页号，读配置时逐层翻回这三个参数，**值不变、Step 参数指纹不动**（`core/page_kinds.py`；不改任何 Step、不动 `code_hash`，契约只增可选字段）。`page_kinds` 属实测版式，不许写进基础配置；`guji book show --effective` 来源标「（page_kinds）」。新增只读命令 `guji pagekinds <册>`（点名／页型规则判／最后处理三栏对账，疑似误判的跳过页单列）与迁移脚本 `scripts/migrate_page_kinds.py`（干跑，每册核逐步 params_hash 不变，不推库）。老写法读配置时发 `FutureWarning`，**0.7.0 起报错**。
- 分段计时第二轮（A20 11-04）：`cli_perf.PERF_HOOKS` 加匹配器里面（`verify._elastic_align`／`_prepare`／`_elastic_miss`、`HogFeature.extract`）、seed_admit 铁证闸 `_iron_decide`、字组流程 `groups.flow` 各段与影子闸 `ShadowGate.judge`。只改名单，不改 Step 源码，`code_hash` 与产物不变。
- seed_admit 每页读人裁提速（A20 11-04，耗时统计查出 `rebind_library_shapes`＋`human_chars` 每页约 0.6 s）：殿本 vol04 每页 0.95 s → 0.2 s。大头是 `bindings.page_state` 逐页调 `cells_step()`、每次 `load_book` 重读册 yaml，`book_bindings` 一次对全书有人裁的页各调一遍，现在算一次传进去；事件读口记住过闸结果（`EventLog._gate_cached`：问过的各册 `source_rev` 都没变才复用，换图源切 yaml 立刻重判），`book_bindings` 两种分组共用一遍排序。绑定缓存键照旧含备选切法列（`page_state`），没加新的缓存层。改的模块都不在任何 Step 的 `code_deps` 里，`code_hash` 不变；vol04 全册 218 页新旧代码 seed_admit 产物逐字节相同（4 进程，整步墙钟 200 s → 157 s）。

## [0.6.2] - 2026-11-04

第4轮统一重跑用的版本（A31，用户 11-04 定「重跑尽量发新 cv 版本」）。比 v0.6.1 `code_hash` 变了的 Step：**border_detect**（#1010）、**seed_admit**（#999、#1007、#1009 动了它或它的 code_deps）。

### Fixed
- border_detect 1.19：列宽重拟合拟不出时减本页底色重拟，修 vol43 p1 满页霉点漏两条界行、整页未过 L1（A22，#1010）。
- db push/sync：本地字形账本被清空时拒推，防本机空壳清中心库（#1013，11-04 殿本账本被清事故后）。
- feedback：knn_infer 来源（字形近邻推断事件）不当人裁（#1006）。

### Added
- datastore/source_xform：换图源后旧页坐标→新页坐标（#1008）。

### Changed
- 第4轮字组（A24，#999）：于千子干笔画下限放宽、kgc 冦宼㓂按整理本定寇、can/ba 影子闸挑中整理本字时改放、终审上下文抽成 utils/final_ctx.py。
- 文意裁定事件带 `pending_reason`（缺省 unknown；字组问大模型缺省 group_abstain，PUA/GB/降审脚本显式传）（#1007、#1009）。`feedback.rulings` 在 seed_admit 的 code_deps 里。
- 待审原因：史記夹注分法不均 `jiazhu_uneven` 归 seg_defect，细分 jiazhu_uneven（#1012，review 层，不动指纹）。
- 步内分段计时（A20 11-04，Sheldon 选「大头两步加分段计时」）：`cli_perf.PERF_HOOKS` 点名 glyph_match、seed_admit 的各道关与匹配器 `GlyphMatcher._match` 等，`guji step`／`pipeline` 起跑时换成计时薄壳，分段记进 perf 记录并推任务库。不改 Step 源码，`code_hash` 与产物逐字节不变（`tests/test_perf_hooks.py` 拿真匹配器核开壳与不开壳产物相同）。`GUJI_PERF=0` 关。
- `invert_detect`（Step0 反色带）审过登记进 `core/parallel.AUDITED`，`--jobs N` 按页并行（A20 11-04，耗时统计查出串行、并行效率 0.25）。`core/parallel.py` 不进指纹，产物不变：殿本、全唐文、史記、北行共 130 页（含 4 页反色带）串行与 4 进程产物 sha 逐页相同。

## [0.6.1] - 2026-11-03

### Added
- 任务库：一批单全部跑完，自动通知提交人（11-04，sheldon 定）。某人名下没有排队／在跑的单、且有终态单没通知过时，执行方收尾（或空闲时）给 `submitted_by` 发一条汇总（成功／失败／被拦，附单号与简短原因），走中转站 send-to-roster；`jobs.job` 加列 `notified_at`（加列时历史单补成已通知），发送失败不影响单、退回下次再发。新 `jobs/notify.py`。不碰 Step，指纹不变。
- 待审原因规范文档 `doc/design/待审原因PendingReason.md`（A31，11-04）：是什么、真源与取法、29 个取值表、各处数据怎么写（单、卡、事件、裁定、看图、网站、看板、manager、book-text char v0.4）、各仓副本、加改弃用流程、迁移记录。只加文档。
- 语料：cv 自带底库语料表 `config/corpus-registry.json`（`core/corpus_files.py`）＋`guji corpus registry`，`corpus upload|fetch` 不给 `-w` 时按表进出 R2；`guji pipeline` 起跑前、`install_release.py`、测试开跑前缺了自动从 R2 取回原位（为 rc 时语料表搬出 git 做准备，L0）。
- 模型系统：一个环境里两本书钉同一模型的不同版本（`core/model_override.py`，设计 `doc/design/模型系统.md` 4.2 第 4 条）。钉了 `model:` 且 cv 仓里的模型与清单内容不同时，按 sha 摆进 `$GUJI_DATA_HOME/model-cache/…`，运行时把读模型模块的缺省路径改指那里；模块源码不动、`code_hash` 不变，仓里一致的册逐位同前（L0）。
- 历史事件补待审原因（A31，sheldon 11-03 定「回写，推不出写 unknown」）：`scripts/zhengli/backfill_event_reason.py` 给 `feedback/{events,rulings,vision}` 里的 `confirm`、`ctx_ruling`、`vision_check` 加 `pending_reason`（按 group／route／subclass／via／来源推，推不出 `unknown`），按原行写法重写、别的字段不动；缺省试跑，`--write` 在人裁写入锁内写。殿本试跑 65,617 条。不碰任何 Step。
- book-text 的 char 写待审原因（A31，sheldon 11-03 定；guji-format char v0.4 §4.8）：`guji_char_cord.apply_pending` 给待审单上的格写 `pending_reason`、去掉待审格的 `lacuna`／`guess_c`（`lacuna` 只给审过定阙的格），用到就把 `$schema` 升 v0.4；`_tok` 把待审 □ 与阙文同写 `[[]]`，分行稿逐字节不变。`republish.py` 升 book-text 时按同版公众单＋团队单写；`export_guji_format.py --pending` 可在导出时写。不改 Step9，指纹不变。
- 字形第三步：字体档进 R2（A20，11-04）。cv 带字体表 `config/font-registry.json`（11 个文件约 145 MB，已传 R2），新命令 `guji font registry|upload|fetch`，`guji pipeline` 起跑前与 `install_release.py` 装完自动补齐 `fonts/`；商业字体 `fonts/kangxi/` 不进表、不上公开的 R2。文件放回原位，代码与指纹不变。
- 语料底库文件搬出 cv 的准备（A20，11-04；`doc/design/语料库分层版本.md` 末节）：`guji corpus upload --all` 改传钉的清单里引擎仓的全部文件，不论大小，仓里改过的按底库 `repo_commit` 从 git 取当时那一版；`guji corpus fetch` 连引擎仓小文件一起取回原位；`guji pipeline` 起跑前对钉了语料的册自动补取缺的文件。不删文件、不碰 Step，指纹不变。已传殿本、史記钉的两版底库（131 个文件）。
- 模型系统收尾（A20，11-04）：模型卡加出处 `source`（`config/model-provenance.json`：训练脚本、训练数据、联动门槛，不进清单哈希）；字组 IDS U-Net（`config/groups/*/unet.npz`）挪进模型系统（种类 `ids_unet`），`corpus_pin._not_corpus` 不再算它语料，老清单里的条目核对时跳过；影子闸按训练数据改归殿本；cv 模型表扩到 13 个文件；`guji model upload` 不给 -w 传模型表。史記、殿本出 m2 并改钉 `model: 2`。
- 控制台待审卡带待审原因（A31，sheldon 11-03）：`review/cards.py` 出的每张卡加 `pending_reason`／`pending_reason_detail`，与出单同一套判法（`review/reasons.py::stamp_cards`，整页／整列对不上按这批卡自己数，刻例数取工作区 `glyph_db_path()`）；卡片缓存版本升 4、字形库进缓存键。不碰任何 Step。
- 模型系统：cv 自带模型表 `config/model-registry.json`（A20，11-04，为下一版把 `models/` 搬出 git 做准备）。`guji model registry` 重写表、`guji model fetch`（不给 -w）按表从 R2 补齐 `models/`，`guji pipeline` 起跑前自动补，`install_release.py` 装完也补；文件放回原位，代码与指纹不变。
- 补现行待审单的 `pending_reason`（A31，sheldon 11-03：已有数据也改写，推不出写 unknown）：`scripts/zhengli/backfill_pending_reason.py`，每张单取出单那一版的产物包 `rev-<rev>`（没有退回 ★main）用 `review/reasons.py` 判，只加 `pending_reason`／`pending_reason_detail`，别的字段不动；缺省试跑出报告，`--write` 才写回数据目录。殿本 99 张单 18,429 格试跑：全部取到出单版包，unknown 0。不碰任何 Step。
- 出单写待审原因 `pending_reason`（A31，sheldon 11-03 定）：新模块 `review/reasons.py` 按 `pending_reasons.yaml` 的 `priority` 逐条判一格为什么待审（判法搬自 A31 统计分类 v2：复审／改判、切坏、遮挡、整页整列对不上、极难形近、字组五种、整理本缺字／没字、库里没有、乱码闸、异体、形近护栏、刻例太少、改字层、库不认、与整理本不一致），都不中写 `unknown`；`republish.py` 出单时给公开单与团队单每格写 `pending_reason`（必有）与 `pending_reason_detail`，`cause`／`cls` 过渡期照旧双写。读 seed_admit／align_ref／glyph_match 产物、待审单字段与工作区 `output/glyph.db`（刻例数，库不在就不判刻例太少）。殿本 vol20、vol56 实测与 v2 统计分类逐格一致（差异只在改判复审优先、乱码闸先于刻例太少）。yaml 的 priority 按判定顺序重排。不碰任何 Step，`code_hash` 不变。
- 模型系统二期第一步（A20，11-04；设计 `doc/design/模型系统.md` 4.1）：`guji model upload|fetch`，清单里的模型文件按 sha256 进出 R2（键同语料大文件），取回时放回登记位置，所以 Step 代码、`code_hash`、指纹都不变；`guji pipeline` 起跑前对钉了 `model:` 的册自动补取缺的文件（`ops/model_blobs.py`）。已传史記、殿本 m1。
- 待审原因 `PendingReason`（A31，sheldon 11-03 定）：新模块 `review/pending_reason.py`＋配置 `review/pending_reasons.yaml`，全项目唯一真源。一格「为什么还在待审」只写字段 `pending_reason`，值为 29 个英文 enum 名之一（码如 `Z01` 只作分类值）；不确定一律 `unknown`。每个原因配大类、去向（human／llm／algo／deferred）、负责人、网页短名与说明、卡片形态、判定说明、旧码对应。`parse()` 对空值、认不出的给 `UNKNOWN`，`legacy_candidates()` 供迁移旧 `cause`／`cls`，`python -m open_guji_cv.review.pending_reason --json` 导出给别的仓。这是待审原因，不是判定依据（依据仍是 `why[]`）。本 PR 只加定义与守卫，出单写字段在下一个 PR；不碰任何 Step，`code_hash` 不变。
- 模型系统第一期（A20，11-04，Sheldon 定三系统构想；设计 `doc/design/模型系统.md`）：新模块 `core/model_pack.py`＋`guji model ls|build|verify|list`。每个模型文件一张卡（`model/1`：种类、sha256、层、归谁按从哪里来），本书模型总号清单 `config/model-pack/m<N>/manifest.json`（数据目录，随 db push 进中心库）；册 yaml `model: N` 钉住后，读模型的步起跑前校验清单（`GUJI_MODEL_DRIFT=warn` 放行），同时钉了 `corpus:` 的册 `group_flow_fingerprint` 并上模型内容，补上「钉语料的册换 L2 小头／rr_clf／rr_shape／book_knn 不过期」的缺口。opt-in：不写 `model:` 的册指纹逐位不变。任务单 `book_overrides` 认 `model`。
- 提速两处（A20 11-03，耗时统计查出；产物逐字节不变、各册不过期）：①页型判定 `clustering.page_type.page_features` 的长线形核开运算（竖线核长 0.3 页高）换成 `boxFilter` 滑窗计数 `line_open`，与 cv2 原式逐位相同；页级并行的 worker 里 OpenCV 单线程，全唐文原图上这一处每页 3.5 s，`border_detect_gate` 每页约 4.2 s → 0.4 s（殿本小图约 2 倍）。登记 `core/code_equiv.py`。②`seal_detect` 审过登记进 `core/parallel.AUDITED`，`--jobs N` 按页并行（原先串行、并行效率 0.25）；`core/parallel.py` 不进指纹。证据：随机图 14,400 例＋全唐文、殿本、史記、北行 36 页真图 page_features 逐项相同；全唐文 12 页、殿本卷首卷末 24 页（含 5 方印）`border_detect_gate`／`seal_detect` 与 origin/dev、串行与 4 进程产物 sha 逐页相同。
- Wiki 调整（Sheldon 11-03：重点四库总目，捎带全唐文、史記）：加「殿本四庫總目」专页（页型图组、职名页放行、各册落审率），各书一览补全唐文（v006 本地跑 Step1–4 出图），幼學鰲頭压成一小段、删「自由版式」页。只动 `wiki/`。
- 跑批耗时统计（A20，11-03，Sheldon 定；方案 Claude Doc《CV 管线性能统计方案》）：新模块 `core/perf.py`（`span`／`timed`／`count`，不在跑批里时是空操作），引擎 `Engine.run()` 自动给每步每页记计算、算指纹、清缓存、落盘与整步准备的耗时，并行时子进程的分段随结果带回；每次运行写一份 `<产物根>/../perf/<册>/<run_id>.jsonl`（机器规格、cv 版本、任务库单号 `GUJI_JOB_ID`、每步汇总与最慢 20 页），放在产物根外、不进 manifest 与产物包。新增 `guji perf top|show|pages` 读本机记录。`GUJI_PERF=0` 关掉，`GUJI_PERF_DIR` 换目录。`core/engine.py` 不在任何 `code_deps`，`code_hash` 与产物逐位不变（`tests/test_perf.py` 核开关两种跑法产物与指纹相同）。推到美国服务器 jobs 库 `perf` 表等 jobs 客户端切过去再加。
- 跑批耗时推到美国机任务库（A20，11-03）：设了 `JOBSDB_TOKEN` 时每次运行写完自动推 run 一行＋每步一行（含最慢 20 页，约 15 KB）到 `jobs.perf_run`／`jobs.perf_step`（`jobs/perf_push.py`，表幂等自建）；**只推美国机，不推 Neon**。新增 `guji perf top --remote [--by host|cv_version|book]`、`guji perf job <单号>`、`guji perf push`；执行方给子进程带 `GUJI_JOB_ID`，`--isolate-steps` 的各步记录用 `GUJI_PERF_GROUP` 串起来。不碰任何 Step，`code_hash` 不变。
- GitHub Wiki（Sheldon 11-03）：源文件在 `wiki/`（17 页＋侧边栏，以 v0.6.0 为基线，配殿本、史記、北行古本、幼學的真页面截图），出图脚本 `wiki/tools/make_shots.py`＋清单 `shots.yaml`（从产物包画版框、列带、字格、夹注、印章、放行等叠图）；`.github/workflows/wiki-sync.yml` 合进 main 时同步到 Wiki。`doc/版本号规矩.md` 加第八节：每升 MINOR 整体重改 Wiki，算在发版清单里。只加文件，不碰任何 Step，`code_hash` 不变。

### Fixed
- 任务库通知：`notify_submitters` 在库层返回 None 时当「没有到期的」，不再抛 TypeError 让执行循环退出（`test_jobs_runner_refresh`、`test_jobs_worker_conn` 因此挂，rc 修复，A31）。
- seed_admit 指纹补漏：#951 新加的 `groups.pair_shape` 补进 `code_deps`（seed_admit `code_hash` 随之变，本版 seed_admit 本来就改了，不额外多一次重跑），`path_params` 登记表补 `group_flow_pair_shape`（rc 修复，A31）。
- 用字账按书选（A20 11-03，配置分层清理第 5 条）：`seed_admit.edition` 还是缺省（殿本的 `wuyingdian_zongmu`）时按书换键（`core/ledger_edition.py`、`core/step.py::_with_book_ledger`；书 ID 取生效 `book_id`，没写取中心库工作区名），别的书没有自己的账（`config/variants/books/<书 ID>.json`）就是空账；审字卡、组视图同样按书取。**影响**：殿本与认不出书的册参数逐字节不变；史記、全唐文等能认出书 ID 的非殿本册 `seed_admit` 判过期（参数 `edition` 变了），自动放行不再拿殿本的惯刻形、殿本人裁过的转换对当先验。L2：从 seed_admit 起重跑（可与 #911 iron_gate 的重跑并一次）。不碰任何 Step 模块与 `code_deps`，`code_hash` 不变。
- 配置分层清理第二批（A20 11-03，Sheldon「剩下几条都做完」）：①任务库准备（`rerun_prep.sh`）改值走运行覆盖 `GUJI_BOOK_OVERRIDE`，不再 sed 本机册 yaml（旧 tag 不认才退回），执行方把它与 `book_overrides` 合成 `--override` 带进 pipeline；`guji … --override` 叠在环境里已有的覆盖上，不再顶掉。②`guji book show --effective` 列出借来的字形库（`workspace.yaml` 的 `glyph_lib.borrow`）及本机副本 rev、钉版快照里的借库。③推中心库前拦下「生效 `corpus` 在那册钉子账里查不到」的册（多见于写在基础配置里），`resolve_pin` 的报错说清总号每册各编各的。④新增 `scripts/check_base_corpus.py`，`doc/版本号规矩.md` 第三节第 5 条加「底库文件变了要配新底库」。只动工具与推库检查，不碰任何 Step 模块与 `code_deps`，`code_hash` 与产物指纹不变。
- `iron_gate` 缺省值两处对齐（Sheldon 10-23 定缺省开，11-03 确认）：`load_book` 读册配置时没写 `iron_gate` 的按**开**算（原先按关，与 `BookSpec` 缺省 True 不一致）。**影响**：册 yaml 与基础配置都没写的册 `seed_admit` 判过期（`iron_gate` 在 `book_deps`）——11-03 中心库实查：史記 988g3f0wsu 42 册、全唐文 995ejelvk0 236 册（另 12 册已显式开）、qtw-draft 5 册、幼學 yxat 1 册；殿本（基础配置已写 true）、北行（册里已写 true）不受影响。L2：从 seed_admit 起重跑。`code_hash` 不变。
- Step 参数优先级与文档对齐（A20 11-03 配置分层清理）：册配置 `params:`（基础配置 ∪ 册 yaml ∪ `--override`）在 `Engine.__init__` 按字段叠在管线 yaml `params:` 之上、`--params` 之下；以前管线 yaml 写过的字段册配置盖不住（只涉及 `modern_body` 的 `column_gate`、`cell_shrink`、`glyph_match` 三项）。册配置 `params` 里写 `null` 也能去掉管线 yaml 的值。刻本链管线没有 `params:`，殿本、史記等参数指纹逐位不变；现代链只有册配置写了这几项的书会变。`guji book show --effective` 新增 Step 参数逐字段来源（含管线 yaml 层）；`--override` 不许改 `book_id`、`volume`、`volume_width`、`chapter_width`。不碰任何 Step 的 `code_deps`，`code_hash` 不变。
- `guji source pull` 等动作在 dev 上报 invalid choice：拆分 P1a（#880）给 `cli_source` 加的插件表 `COMMANDS` 盖掉了同名的动作表；动作表改名 `ACTIONS`。只影响 dev，未发版。

### Changed
- 拆分 P2 第二批：`guji source`、`guji cellvotes`、`guji freeze` 的命令层（`cli_source.py`、`cli_cellvotes.py`、`cli_freeze.py` 与它们的命令层测试）搬去 guji-manager（≥0.2.0，同日合），cv 删除并登记 `MOVED_TO_MANAGER`、`MIN_MANAGER_VERSION`；底下逻辑（`datastore.sources`、`feedback.web_votes`、`ops.freeze_register` 等）仍在 cv，`manager_api` 加 31 个名字。命令和参数不变。不碰任何 Step，`code_hash` 不变。
- 拆分 P2 准备：整理脚本 auto_cycle、proof_cycle、republish 开工先调 `scripts/zhengli/ensure_manager.py`（云端复用 `ensure_manager.sh` 装／更新 guji-manager main；别的机器没装只提示），为下一批搬走 `guji source`／`cellvotes`／`freeze` 铺路。
- 拆分 P2 第一批：`guji opinions`（`opinions/`、`cli_opinions.py`、`config/opinions/rules.json` 与 `tests/opinions/`）搬去 guji-manager（同日合 guji-manager 对应 PR），cv 删除；`cli_v2.MOVED_TO_MANAGER` 登记，没装 manager 时给装法；新增 `MIN_MANAGER_VERSION`（opinions 要 ≥0.1.0），旧版 manager 里早先复制的过期副本（云端快照种子带着 10-27 的 opinions）不再被认，提示更新。`manager_api` 加 `data_home`、`central_data_dir`、`CentralError`。不碰任何 Step，`code_hash` 不变。
- 拆分 P1b：`cli_v2` 里 24 条 manager 一侧命令原样拆到 5 个模块——`cli_ops`（snap、archive、release、deploy）、`cli_feedback`（events、gold、batch、label-batch）、`cli_eval`（eval、check、groups、cards、progress、collate）、`cli_glyph`（store、recheck、glyphlib、rekey-cells、promote、corpus）、`cli_close`（close-check、exit-check、audit、char-diff），经 `MANAGER_CLI_MODULES` 登记；`cli_v2` 从 3600 行减到约 2000 行。57 个子命令及参数与改前逐一相同。顺带修插件加载：一个模块几条命令共用一个 `add_parser` 时只调一次（原先第二条起 handler 登记不上）。不碰任何 Step，`code_hash` 不变。
- 拆分 P1a：cv 里 manager 一侧的 9 个命令模块（glyph-db、exp、db、products、source、opinions、cellvotes、freeze、job）各加 `COMMANDS` 表（同 guji-manager 插件接口），`cli_v2` 改按 `MANAGER_CLI_MODULES` 名单现 import 登记；57 个子命令及参数与改前逐一相同。以后搬走一个只删名单一项、登记 `MOVED_TO_MANAGER`。不碰任何 Step，`code_hash` 不变。
- 拆分 P0：`cli_v2.MOVED_TO_MANAGER` 登记搬去 guji-manager 的子命令（现为空），本机没装 manager 时 `guji <它>` 给出装法、退出码 2；新增 `scripts/ensure_manager.sh`，`rerun_prep.sh`、`guji_jobs.sh` 开工时把 guji-manager 装好并跟到 main（每 10 分钟最多拉一次，失败只警告），取代原先只提示的 `manager_hint`。不碰任何 Step，`code_hash` 不变。
- 拆分 P0：新增门面 `open_guji_cv/manager_api.py`（同 `console_api` 机制），guji-manager 过渡期用 cv 内部只经这里或 `api`；`test_facade_exports_resolve` 同时核两个门面的名字都取得到。只加文件，不碰任何 Step，`code_hash` 不变。
- 中心库省流量（A31 11-02，Neon 出流量 10-31 一天 48 GB）：`db pull`／`sync` 取整文件表（files：线上单每份约 1.1 MB、字形库清单 3.4 MB）一律按路径、按字节分批（≤8 MB／≤100 个），不再整表 2000 行一页读挂重试；`db pull --exclude <前缀>`／`GUJI_PULL_EXCLUDE`（`run` = `feedback/lists/proofing/`）按需拉取，部分副本记进状态、push／sync 拒绝；`rerun_prep.sh` 缺省 `GUJI_PULL_EXCLUDE=run`；任务看板只取要用的列。不碰任何 Step，`code_hash` 不变（PATCH）。
- 册配置点名表格页 `border_detect_gate.table_pages`（史記年表，Sheldon 11-02 定暂搁置）：点名的页页型记 `table`（新加进 `PAGE_TYPES`／`SKIP_TYPES`），整页 `page_type_skip` 跳过，不切分、不出待审、不进统计；优先于 `body_pages` 与 `grid_overrides_skip`。缺省空、不进参数 dump，各书产物不变。年表以后的做法见 ai-team `domain/CV/新书登记/史记文渊阁/年表方案.md`。
- 书级「大印只认这些页」`seal_detect.stain_pages`（A32，GUJI-637，史記 D 类）：缺省 None＝照旧每页都找、不进参数 dump；殿本 20 页回放产物逐字节不变，已登记 `core/code_equiv.py`，不让各书过期。史記各册真印只在首叶，没印页的纸面底纹被认成大印（01–03 册 115 格误判遮挡），书级配 `[2]` 去掉。
- R5 库否决只在库认得默认字时才算（A32，GUJI-637，vol20–99 r1 遮挡格）：`seed_admit` 1.31 `lane_seal_lib_veto_min_n`（缺省 2），`code_hash` 变（从 seed_admit 起重跑）。默认字在字形库里刻例不到 2 个时，库首位必然是别的近形字，「库反对」不算证据，不再否决。r1 包库否决 177 格里，刻例 ≤1 的 83 格看图 0 错（刻例 2 的 12 格有 1 错、≥10 的 44 格有 6 错，照旧否决）。113 页回放新放 88 格、0 格收回，逐格看图未见错。
- 字形库 edition 一律是书 ID（Sheldon 11-01 定，QTW 转 A23）：`GlyphDB.admit_instance` 在库没声明 `meta.book_edition`、调用方也没点名 `edition_tag` 时抛 `MissingBookEdition`（原先静默按实例 id 前缀 v2／volNN 当 edition）；`glyph-db stats` 加 `edition_problems`，`close-check` 加 8b「字形库 edition 是书 ID」。不改产物指纹。
- 待审成因表 `review/causes.py` 的「交给」标注：A1/A3/A4/A5/A6/A9 不再一律写「切分」，改为「对位（成片时查切分）」，A3 只差 1 格＝挤格才归切分（A22 11-1 反馈：第1轮 538 格里 489 格切分没问题）。只改文字，不改判定，不动产物指纹。
- 卷末印页的空栏不再人审（A32，GUJI-637，vol20–99 r1 遮挡格 443）：`align_ref` 2.5、`seed_admit` 1.29，`code_hash` 变（从 align_ref 起重跑）。卷末页整理本只到「…皆附存目」，后面几列是「乾隆御覽之寶」压着的空栏；邻页／页钉位定位时这些列已过了整理本这半叶的末行，原先记「列行对应不成立」、印里的格 `via=none` 只能人审。
  - `align_ref`：这种列的退回原因改记 `COORD_PAST_LEAF`（「整理本这半叶没有这一列」），其他不变。
  - `seed_admit.occluded_past_leaf_blank`（缺省开）：遮挡格所在列是 `COORD_PAST_LEAF`、且这一列没有现役对位字 → 默认字来源记 `coord_blank`，由 R5 判非字。r1 包 80 册只有 5 页命中（vol21 p225、vol30 p140、vol37 p71、vol39 p176、vol44 p65），回放放 55 格，逐页看图全是印文碎块；其余页逐格不变。
- 异体边表自动暂归一 `seed_admit.edge_pair`（缺省开；A24 10-31，r5 重放 V 类「组外异体对」单格长尾约 360 对，`seed_admit` 1.28，`code_hash` 变）：整理本字与库首位互为「自动对」（`groups/edge_pairs.is_auto_pair`：边表 `edge_tier`=T1 纯异体且 ≥2 个异体来源、不在字组、不在 `config/variants/edge_pair_exclude.tsv`）、库首位 cov≥0.92 领先≥0.005、无护栏的待审格，放两形里已放行字频较高的一形（`config/variants/form_freq.tsv`）。通道 `edge_pair`，证据 `edge_pair.decision=provisional`（暂归一，将来筛出再拆）。只升不降、不碰人裁。r5 包 vol07–99 回放约放 94 格，看图全对；其余单格对多数不是异体（无边或只有 link／通假边），不碰。新增 `groups/edge_pairs.py`、两张表、`tests/test_seed_admit_edge_pair.py`。
- 印章遮挡格再放宽两条（A32，GUJI-637，vol20–99 r3 遮挡 931 格）：`seed_admit` 1.27，`code_hash` 变。只在册开 `lane_seal` 时生效。
  - `lane_seal_lib_veto_second`（缺省开）：默认字正是字形库第二名时库否决不生效。r3 包里库否决 340 格，看图默认字错的约 10 格全在「默认字不在库前二」那一档。
  - `lane_seal_codepoint_variant`（缺省开）：异体护栏遇到本书 `codepoints:` 已归一的异体对（𩔖→類、巻→卷、别→別…）或同在暂归一组 `PROVISIONAL` 的两形，不再拦，放归一后的字。
- `rerun_prep.sh`：迁仓过渡期的退回旧总仓没生效（`t` 包装总返回 0，克隆新仓失败也当成功），改成直接判克隆是否成功。

- `seg_samples.py submit --base <带注释的 tag>` 把 tag 对象的 sha 当提交交单，执行方检出后对不上（「cv 没切对」），改成 `rev-parse <base>^{commit}`（v0.6.0 组合验收时发现）。
- 下版框误取末行字身（border_detect 1.13，A22 查 A31「无整理本对位」10-31）：`seg/lines.find_horizontal_border` 下框次选峰原在 ±60 行窗里量，窗边的峰被截断、半高宽量不全分数虚高，末行字身横排一串时压过真框，整页下框上移一格、每列末字丢掉（vol84 p89、vol85 p94）。改为曲线多采一个窗宽再量；上框不动（抬头页主框靠那个截断分数才选中，另有链路）。vol20–99 共 13,320 页筛：54 页下框下移约一格，逐页看图全改对，其余逐位不变。`border_detect` 及下游判过期。PATCH。

- 列首／列尾格剥框线漏剥写本框线（cell_shrink 1.22，A22 查 SJ 报的史記列首格顶线残留）：`extractor.strip_frame_line` 判「线与字之间隔着白行」原只看紧挨线行的 2 行，毛笔线两边拖着几行毛边，被当成字连着线、整条不剥；剥时也只剥到线行，毛边留在图块边上。改为越过 `FRAME_LINE_EDGE` 行毛边再找白行，碰到白行就连毛边一起剥（碰不到＝字脚压线，照旧只剥到线行）。史記 01／02 册 `patch_qc.has_edge_frame_line` 命中 170→145（列首 98→73）；殿本 vol06、vol30 各 48／52 格变，看图全是剥掉线残、字不受损。`cell_shrink` 及下游判过期。PATCH。

## [0.6.0] - 2026-10-31

MINOR（用户 10-31 定）。含切分模块化（共用原语库 `seg/`、各套书自管 `books/`，M2–M4）、控制台与 manager 拆出、任务库按书 ID 区分与殿本工作区独立成仓、keben_free 第八轮等（见下）。

- 架构：`describe`（纯净性一句话）从 `ops/pack_purity` 下沉到 `datastore/packs.describe_purity`（标 main 要用，`datastore → ops` 的向上依赖让 `test_no_new_upward_imports` 红），`ops.pack_purity.describe` 保留为别名。rc/v0.6.0 上修，同改动合回 dev。
- jobs：执行方连续 3 单环境类失败就暂停领单 30 分钟并在 `workers` 里写原因（10-30 worker-23 的数据令牌坏了，一小时内 23 次 db-pull 500，别的执行方都正常），免得一个坏会话把排队的单的重试次数耗光。
- jobs：任务库加列后老连接报 `cached plan must not change result type` 会让执行方领单崩掉（10-30 加 book_id 时 #1153／#1156），`DB` 遇到这个错误自动重连重试。
- 任务库按书 ID 区分、殿本工作区迁到自己的仓（Sheldon 10-30）：四库总目（96mid1ogzk）的工作区搬进 `guji-workspace/96mid1ogzk-si-ku-zong-mu`（仓根即工作区，3711 个文件与旧仓逐文件核对 0 差异），`spec.WS_REPOS` 登记「书 ID → 仓」，ws_glob 里的书 ID 查得到又没显式给 `ws_repo` 就走它，执行方自检也查这个仓。册号（vol01）每部书都有，`jobs.job` 加 `book_id`（旧行按 ws_glob 补），同册互斥锁改成（书 ID，册号）——不同书的 vol01 能并跑；`guji_jobs submit --book-id`、`ls --book-id`，`ls`／板子多一列书 ID；`ws_repo` 不进指纹。`rerun_prep.sh` 找册 yaml 改按工作区 `.central.json` 的 ws id（原先取数据目录里第一个，多书会话会取错）。迁仓过渡期：会话没挂新仓时，执行方自检放行旧总仓，`rerun_prep.sh` 克隆不了 `--ws-repo` 就退回旧总仓里同一本书的目录。
- 自由版式 `keben_free` 第八轮（Sheldon 10-28 盯 yxat 9、10 页）：`layout_hints` 块与版面树叶子可写格式 `fmt`（plain 每列一行字／mixed 大字夹小注），`block_detect` 1.10 落进产物并给块编号 `label`（版面树按层 1a、1b）；`cell_cut` 1.5 `fmt: plain` 走 `segment_plain`（整列按墨切、块内识别字高作先验），字框加字号 `cid`＝页-块-行-字。只有 keben_free 管线用（yxat 一册）。
## [0.5.32] - 2026-10-28

PATCH。含控制台拆成独立包 guji-console（C0–C3）、keben_free 第七轮、A24 码位组与字组送审若干（见下）。

- **控制台拆成独立包 `guji-console`**（Sheldon 10-28，设计 `doc/design/拆分-控制台独立成包与上网站.md`，C0–C3）：`open_guji_cv/console/` 连提交历史搬进 open-guji/guji-console，cv 里删掉；控制台只经门面 `open_guji_cv.console_api` 读 cv，消费事件、导金标、迁载体、漂移检查、跑评测改调命令行；写人裁事件的逻辑挪到 `review/event_write.py`（`guji cellvotes write` 也用它）；`guji gold drift` 加 `--json`。**要用控制台就另装**：`uv pip install -e ../guji-console`（同一个环境），装上后 `guji console` / `guji runs` 由它经入口点提供，参数不变；`.[console]` extra 留成空的。37 个控制台测试文件（253 条）随包搬走。不动任何 Step 的 `code_hash`（L0）。PATCH。
- 自由版式 `keben_free` 第七轮切字（Sheldon 10-28「先实现十几页」「考虑识别软件辅助」）：新可选步 `line_ocr`（逐列送 PaddleOCR 读文本行，产物 `free_ocr_lines`）；`cell_cut` 1.4 有识别行时按行定区（大字行／并排小注行）、按读出的字数切，漏掉的段落与没有识别行的列走规则；混排栏（认出了大字、但大字行不到一半）按字形认大字（`segment_mixed`）。`.[cpu]`／`.[gpu]` 的 paddleocr 下限提到 3.2。只有 keben_free 管线用（yxat 一册）。
- 倚𠋣 麓𪋤 邃𮟏 冥㝠𡨋 隱隠𨼆 码位组（A24 第 1 轮，sheldon 10-28 定 倚/麓/邃/㝠/隠）：新 cp_yi3 cp_lu4 cp_sui4 cp_yin3b，cp_ming2 成员加 𡨋 并改给 㝠；撤 yin 刻形组（隱𨼆 刻形差别暂不拆）。99 册回放补放 112 格看图 0 错。
- 按刻形拆判的异体对组（shang ba sang xian yin … 共 31 个）与 dian 开 `ref_top_enter`（A24 压低组外异体对送审第 1 轮，10-28）：库首位与整理本同在组里就进，分差内的组外字不再挡入口；给字仍由整字 HOG 判。vol01–99 回放新进 100 格，逐格看图 0 错。只动 `registry`。
- 字块图像＋文意 L4（A24 第 2 轮，2026-11-01，门辶于千子干）：新 `groups/vis_llm`、`FlowSpec.vis`（zy yz men wj guanm chuo yh xuan 开）、`seed_admit.group_flow_vis`（缺省开；用 group_flow_llm_model，没密钥不问）。字组流程没放成或要降审的格，把原图字块连同前后文问一次大模型；高置信、是组员且有证人（整理本／坐标对位、文意 L3／L1、字形 ids）同字才放或不降审，整理本在组里说了另一字时不越过。`group_flow_llm_groups` 缺省加 yz wj yh。殿本 vol20–99 的 276 格回放送审 276→173，逐格看图 0 明确错；留出 360 已放行格 high 307 格同放行字，不同的 4 格里 3 个是 間／閒。`seed_admit` 与 flow 代码变，开 `group_flow` 的册判过期。PATCH。
- 第 1 轮压低字组送审（A24，2026-10-28）：men／chuo 加文意第二路（`FlowSpec.lift_ref_missing_ctx`，整理本与坐标对位都缺时 ctx 给字可补放，有参照不越过）并新增 `config/groups/{men,chuo}/{prompt.md,rules.yaml}`；`seed_admit.group_flow_llm_groups` 缺省加 zy xz rr guan men chuo。vol07–99 离线回放九组送审 815→约 391。`seed_admit` 与 flow 代码变，开 `group_flow` 的册判过期。PATCH。
## [0.5.31] - 2026-10-28

PATCH。含遮挡卡 seed_admit 1.25/1.26（异体优先于印章、印框内背景干净格不算遮挡）、align_ref 2.3、row_segment 1.40/1.41、border_detect 1.12 弯列、字组暂归一与码位组、keben_free 第二至四轮等（见下）。

- 修 #731 的 `cp_shu4`（述𫐠）与 `chuo`（辶族）共用「述」却没互相声明 `overlaps`，`test_members_of_different_groups_do_not_overlap` 挂；补上互相声明、重生成字组总表。PATCH。
- 规则 A 坐标对位那支放宽 `near_form`（A24「复盘形近护栏 N 类」，10-28）：整理本字（坐标对位字）在库里刻例 ≤2、BMP 字、不在册 `codepoints` 里、5-b 首位逐字等于它、库候选里没有 cov ≥0.96 的对手（cov ≥0.80 的候选也不是它的异体）时，`near_form` 疑问不再拦 `rare_ref`（库前三名里的形近字只是最像的邻居，不是真对手）。`never_match`／`conflict` 护栏与其余硬疑问照拦。开关 `seed_admit.rare_ref_nf`（缺省开，`rare_ref_nf_max_n`／`rare_ref_nf_cov` 调门槛），放行格 `evidence.rare_ref.near_form_relaxed`。依据：5,980 条人裁金标上符合条件的坐标对位格 83 格 0 错；95 册 N 类 536 格所在页真回放（seed_admit 重跑）新放行 59 格，逐格看图无错放。`seed_admit` 的 `code_hash` 变，各册 `seed_admit` 及下游判过期。PATCH。
- 字组 `cek` 策䇿（码位组，暂归一到 䇿，登记 `PROVISIONAL`）：策→䇿 是 sheldon 10-26 定的暂归一，但库里 策／䇿 cov 并列（< same 档 0.996）、文意 margin≈0，整理本字归一成 䇿 又不在任何字组，全册 244 格送审（分类 V）。册配置 `group_flow` 加 `cek` 后库首位与整理本同在组里就放行，字落 䇿。只动 `groups/registry.py`，不动 Step。MINOR。
- 36 个 `cp_*` 码位组（A24 压低组外异体对送审第 1 轮，10-28）：sheldon 在 `config/codepoints.yaml` 早定了用哪个字（寄𭔃 急𢚩 耶𫆀 尋㝷 黎𥠖 寶寳 泰㤗 步歩 …）、但没建码位组的异体对，流水线见「库首位与整理本是异体对」一律送审。加 `CODEPOINT_GROUPS`／`PROVISIONAL` 各 36 行，各册 `group_flow` 加了才生效；vol01–99 main 包回放补放 268 格，逐格看图 0 错。只动 `registry`，不动 Step。
- 自由版式 `keben_free` 第六轮（Sheldon 审 yxat p13、p15「要保持均匀」）：`column_trace` 1.8 接断口的竖线图只用来认界栏、排网格用原图；认界栏量拟成的中线踩线（不量弯路），无界栏的密排正文不再被认成有界栏；劈墨罚 3→2。只有 keben_free 管线用（yxat 一册）。
- 自由版式 `keben_free` 第五轮（Sheldon 审 yxat 9–42 页）：`column_trace` 1.7 界栏逐条顺着竖线像素找（各条斜得不一样也跟得上），按界栏切只躲压线的字；劈开墨块的罚 1→3。`block_detect` 1.9 细框线不再往里找内框、版心线让 4→1px。只有 keben_free 管线用（yxat 一册）。
- 标 main 之后的插件钩子：`guji products pack promote`／`pack push --main` 标完 main，调入口点组 `guji.post_promote` 的函数 `(book, label, ws)`；manager 用它自动重出线上待审单（取代 2 小时轮询定时任务）。不动 Step。PATCH。
- 自由版式 `keben_free` 第四轮（Sheldon 审 yxat 9–40 页）：`block_detect` 1.8 双线框取细内框、框线改折线、人标分栏线一起拉成水平（分段 Coons）；`column_trace` 1.6 认虚线界栏、有界栏的块切线顺着界栏走，走缝离字留空（笔画旁 4px 有代价、小墨点便宜），变缝幅度 0.08→0.15 列距。只有 keben_free 管线用（yxat 一册）。
- 自由版式 `keben_free` 第三轮（Sheldon 审 yxat 17–36 页）：`block_detect` 1.7 按框线把页面拉正（框四边量内沿拟二次曲线、Coons 曲面片映成矩形，产物加 `warp`，三种产物坐标都在拉正后的图上），同一条线的重叠段也连起来；`column_trace` 1.5 列宽罚 1→4（空缝之间按均匀挑）；`cell_cut` 1.3 在拉正后的图上切。只有 keben_free 管线用（yxat 一册）。
- 自由版式 `keben_free` 往下自审 yxat 17–36 页：`block_detect` 1.6 框线吸到框线墨带内沿（粗框线、双线框不再吃掉贴框的标题列），块边离内沿 12→2px；首尾相接的断线段连成一条再找框（弯框线认不出时不再退到纸边）。只有 keben_free 管线用（yxat 一册）。
- `border_detect` 1.12：三段折线拟合加一道验收——拟出的折线沿线 ±12px 的墨密度比直线高出 0.08 以上就判折点被字的竖笔勾走，这条线退回直线（单边判：真弯页上是直线压字，不受影响）。新图源（siku-qiefen-v2）界行淡而断，整页 w80 中位 40+ 全进折线，A31 整列待审清单里 vol70 p77、vol59 p58、vol24 p67、vol40 p34 九条线中段齐刷刷平移 45–88px 压进字里，整列认字错。vol70／vol59 全册 Step1–3 对比：变 17 页，看图全是改好或持平（列格位不变、只是格框回到字上），vol59 p1 版心列底多一个空格。`border_detect` 的 `code_hash` 变，下游判过期。PATCH。
- 自由版式 `keben_free` 第二轮（Sheldon 审 yxat 9–16 页）：`block_detect` 1.5 上下两块在分隔线处相接（`split_pad` 0）；`cell_cut` 1.2 列上下两端的长横墨不当字；`column_trace` 1.4 正文网格切线先数劈开几个墨块、再取空白正中，列宽放宽到 0.6–1.5、罚 4→1，竖线贯穿块高 80% 才当界行（撤第一轮的 σ 抹平）。只有 keben_free 管线用（yxat 一册）。
- 拆分 M4（10-27）：`scripts/rerun_prep.sh`、`guji_jobs start` 开工时检测本会话有没有装 guji-manager，没装就提示装法（私有仓，快照里没有）；只提示不拦。不动 Step。PATCH。
- 自由版式 `keben_free` 找列（Sheldon 审 yxat 9–16 页）：`column_trace` 1.3 等宽网格两端贴块边（版框内沿、版心线，不留窄条）、切线代价按 0.12 列距抹平（切在列间空白正中，不落进小注两行间）；人标 `align`（`block_detect` 1.4 记进 `BlockRec.align`）同组的块共用一套列线。只有 keben_free 管线用（yxat 一册）。
- 同义字组暂归一兜底（sheldon 10-27，A24）：同义组方法拆不开写法、与整理本说法不一而本要留人审／降审的格，库形与整理本（复核时已放行字）都认是这个字，就放成这组最常见的字形，`evidence.group.decision` 记 `provisional`，可筛出来再拆（`groups.flow.is_provisional`、`registry.PROVISIONAL`；开关 `seed_admit.group_flow_provisional` 缺省开）。不同义组不兜底，组里意思不同的字（識）、陪衬不算同一个字。vol07–99 离线回放：同义组送审 676→212，兜底 464 格看图字都认对。`guji groups status` 加「暂归一兜底」列；建模板脚本剔除兜底格。`seed_admit` 参数与 `code_hash` 变，开 `group_flow` 的册判过期。PATCH。
- 拆分 M4 地基（10-27）：`guji` 支持插件命令——入口点组 `guji.commands`（装了 guji-manager 即并入它的子命令；本仓自带同名命令优先）。只改 `cli_v2`，不动 Step，19 步 `code_hash` 不变。PATCH。
- 拆分 M3b（10-27）：`clustering.seeding` 去掉对 `datastore.packs` 的 import（LM 缓存取法改走 `core.derived`，`guji` 入口注册）。`seed_admit` 的 `code_hash` 会变，已登记代码等价（`core/code_equiv.py`）：vol04 40 页逐字节相同，指纹仍与改前一致，产物不过期。pipeline→manager 反向依赖剩 5 条。PATCH。
- 拆分 M3a（10-27）：pipeline 一侧对 manager 一侧的反向依赖由 12 条清到 6 条。`discover_workspaces` 搬进 `core/workspace`；`parse_cells_spec` 搬进 `core/book`；`is_exp_branch` 搬进 `core/workspace`；`PULL_MARK` 归 `ProductStore`；派生缓存取法抽成 `core/derived`（本机 `GUJI_DERIVED_DIR` 优先，其次入口注册的取法），`font_pack.push_packs` 挪到 `ops/derived_push`。行为不变，19 步 `code_hash` 与 dev 逐一相同。PATCH。
- 自由版式 `keben_free` 加「有界栏但不规律的正文」（人标块 `ruled: true`，yxat 99–102 下栏；#712 起初叫 `kind: table`，已改名）：`column_trace` 1.2 这类块列数不给死、列宽放宽到 0.5–1.2 倍列距，每列按横界栏记 `breaks`；`cell_cut` 1.1 在横界栏处断开切字、界栏的墨不当字，`free_cells` 加 `rule_seg`。只有 keben_free 管线用（yxat 一册），其他块逐字节不变。
- `align_ref` 坐标对位不再因「孤立弱冲突」整列退回（A31 vol15 p50 列 7／9：整列 24 格成 □，正确的「有」「程」恰是坐标字）。同列现役 equal 与坐标字不合处只有一格、现役 equal 段长 ≤2、坐标字非空、不是邻格错位、同列至少 5 格 equal 全同时，列照用；冲突格仍记进 `coord_conflict_ids`，`seed_admit` 照旧不放它的 match_ref。vol03／14／15 全册回放：新保留 6 列（vol03 2、vol15 4），vol14 不变，原先退回的错位列仍退回。`align_ref.py` 的 `code_hash` 变，各册 `align_ref` 及下游判过期。PATCH。

## [0.5.30] - 2026-10-27

PATCH（GUJI-748 换图源后漏切的抬头字，#706）。**从 v0.5.29（main）加 #706 切出，不含 dev 上的 #701 align_ref、#702 cell_shrink 1.21**：51–99 册正在用 v0.5.28 整册重跑，本版 22 步 `code_hash` 与 v0.5.29 逐一相同（实算；#706 改的 `border_detect`、`row_segment` 已登记代码等价），不让它们过期；#701 #702 随下一版发。

- 人裁逐列抬头覆盖（#706）：中心库 `char-segmentation/head-raise-columns` 的 active 裁决 `{raised: yes|no, n_raised}` 现在有步骤读了。`border_detect` 给 Step1 漏认抬头框的列补框（同页有抬头框取同高，没有按一格高；判 no 的去掉认错的框），`row_segment` 该列抬头级数听裁决、表和闸不再改（line_index 列旗 `head_raise_verdict`）。裁决不进指纹，写裁决 → `guji db sync` → `--from border_detect --pages …` 重跑该页生效（runbook 整理一册书）。没有裁决的页逐字节不变（border_detect vol23 172 页、row_segment vol23 46 页），登记 `code_equiv`。PATCH。

## [0.5.29] - 2026-10-27

PATCH（GUJI-748 换图源后旧格号数据，#703）。**从 v0.5.28（main）加 #703 切出，不含 dev 上的 #701 align_ref、#702 cell_shrink 1.21**：51–99 册正在用 v0.5.28 整册重跑，本版 22 步 `code_hash` 与 v0.5.28 逐一相同（实算），不让它们过期；#701 #702 随下一版发。

- 换图源后旧格号数据的三处读口（GUJI-748，殿本 siku-qiefen-v2 页号重编）：① 换单门 `republish.votes_gate` 认出换源前出的旧单（单子的 `source_rev`／`--old-source-rev`，老单按 `routed_as_of` 早于 2026-10-26），旧格号的票经 ~q 迁移事件的 `migrated_from` 或格级对照表（push／issue 新参数 `--cells`）对到新格再看落没落，对不上的（表里没有／删／IoU 低）列为「无法对位」、写 `旧单票无法对位.tsv`、不拦；`pending_list.py` 出单起记 `source_rev`。② 看图结论：换源前的（锚里没有 rev）本来就不采信，补回归测试；`guji events import-vision` 加 `--source-rev`，换过源的册不给就整批报错（不再抛异常），不自动按产物盖 rev。③ `guji gold rebuild`：换源前事件照旧不重放、输出加 `dropped_by_source_rev`；新页表事件落到与 stale 旧条目同号的格时另立新条目，不拿旧条目的 expected／input／source_events 打底（金标 `Anchor` 加可选 `source_rev`）。都不在任何 `code_deps`，各步 `code_hash` 不变。PATCH。

## [0.5.28] - 2026-10-27

PATCH（GUJI-748 换图源：#693 Step1 push_bottom_to_bar 右界越界整页失败修复、#696 导出裁出图框；另含 keben_free 自由版式 #686 #692 #694，缺省关）。

- `scripts/export_guji_format.py` 导出时把略出图边的字框／格框裁到图内（殿本 vol59 p58 贴边一格外沿出图 47px，「字框出图」检查不过，republish 整册出单被拦）；整个在图外的不动、照旧报。不在任何 `code_deps`。PATCH。
- 换源新图两处修补（GUJI-748）：① Step1 `push_bottom_to_bar` 右界截到图内（vol23 p10、vol37 p74 右界线外推出图，`IndexError` 整页失败）；只在原先越界报错的页上生效，`border_geometry` 登记代码等价（vol20 新图 94 页逐字节相同），各步 `code_hash` 不变。② 引擎：上游某页最近一次跑失败时，盘上那份是更早一轮的旧产物，原先下游照样读它接着跑（vol23 p10 新图拿旧图版框切出 74 格），现在按缺失处理、下游判 blocked；`core/engine.py` 不进指纹。PATCH。

## [0.5.27] - 2026-10-26

PATCH（GUJI-748 换图源缺格页：#683 Step1 网格模式按界行反推版框 `grid_lattice_fallback`；另含 #682 印章页切分（Step1 列距救援、印章定位 1.3）、#686 自由版式管线 keben_free（新三步，独立管线、不影响 keben_body_v2）、#679 #684 #685 #687 字组规则、拆分 M0–M2 #677 #678 #680、#674 PDF 源件、#681 任务库连库断线重排）。相对 v0.5.26，`border_detect`、`row_segment`、`cell_shrink`、`seal_detect`、`seed_admit` 五步 `code_hash` 变（合前实算），新增 `block_detect`、`column_trace`、`cell_cut`；其余步不变。字组文件变了：换用本版重跑的册要按 CorpusDrift 出全局层新底库、改钉 `corpus`。rc 上全量测试：失败 32 条与 v0.5.26 上逐条相同（本机环境类，无新增）。

- Step1 网格模式按界行反推版框（GUJI-748，殿本换源 vol12 p139）：`border_detect` 加参数 `grid_lattice_fallback`（缺省关，不进参数 dump，只管 `column_grid_pages` 点名页）。版框那条线不在候选池里（右版框贴图边被边窗里的界行顶掉、左边带进邻叶版心）时，网格模式原先选不出版框对、退回截断，与自由模式逐条相同只出 8 列；开了改按已探到的细界行拟等距网格、在图内框出 `expected_cols` 列再逐槽验线（`peak_line_search.lattice_frame_pair`，窗口并列就不猜）。p139 开后 9 列各 21 格、159 字、三道闸都过。缺省产物逐字节不变，`steps.border_detect`、`border_geometry`、`peak_line_search` 登记代码等价。
- 拆分 M2（10-27）：`guji pipeline` 开跑前备输入（钉版字形库、Step5-b 模板索引）和整册跑完自动存包的代码从 `cli_v2` 挪进 `ops/prep.py`；`guji pipeline` 加 `--no-prep`，缺省行为不变。不在任何 `code_deps`，19 步 `code_hash` 不变。PATCH。
- 拆分 M1（10-27）：新 `open_guji_cv/api.py`（pipeline 公开面，只转发）、`core/contract.py`（`CONTRACT_VERSION=1`）、`doc/参考/契约.md`；`guji version [--json]`；manifest 条目加可选字段 `contract_version`、`manager_version`（不进指纹，老条目为 None）。19 步 `code_hash` 合前实算与 dev 逐一相同。PATCH。
- 拆分 M0（10-27）：`tests/test_architecture.py` 给每个包标 pipeline／manager 一侧，新增守卫「pipeline 不许 import manager」（存量 12 条登记）。只改测试与文档，PATCH。
- 设计文档 `doc/design/拆分-pipeline与manager.md`（10-27）：把 cv 拆成 pipeline 本体和 pipeline manager 的边界、契约与分步迁移方案。只加文档，不动代码，PATCH。
- 新开一部书（《增廣幼學須知鰲頭雜字大全》哈佛本，10-26）：`guji source commons` 收 PDF 源件（`pdfimages` 原样抽每页嵌入图，不重压）；`--splits auto` 与新子命令 `guji source spreads <源件>` 对开图按书脊折痕自动出拆页表（天头地脚里找折痕，附核对图）；新 `guji db init -w <工作区>`：中心库里还没有的工作区，把册 yaml 等挪进数据目录、记 rev 0，之后 `guji db push` 整批进库（原先新工作区没法进库）。不动 Step。

## [0.5.26] - 2026-10-26

PATCH（GUJI-748 换图源：#664 source pull 删页表外残留原图、#666 prep 删页表外旧页产物、#670 抬头框探测按图尺度缩放 `head_raise_scale`；另含 #661 印章遮挡格放行、#665 #667 #668 #669 字组规则）。`seed_admit`、`align_ref` 的 `code_hash` 变（#661）；Step1 等价登记，产物不因 #670 过期。

- Step1 抬头框探测按图尺度缩放（GUJI-748）：`border_detect` 加参数 `head_raise_scale`（缺省 1.0，不进参数 dump），把 `border_geometry` 里 HR_* 长度常数（旧图上量的绝对像素）按册缩放比换算。殿本换 siku-qiefen-v2（约 0.70 倍）后粗外框半高宽落进细线／粗条两档之间、内框离主上边框够不上 `HR_DIST_MIN`，抬头框整片认不出（vol07 新 p43 五列抬头全丢）。换源的册在 yaml 写 `params: {border_detect: {head_raise_scale: <缩放比>}}`（与 `bottom_gap` 同一个比）。缺省值产物逐字节不变，`border_geometry`、`steps.border_detect` 登记代码等价。
- `scripts/rerun_prep.sh`（GUJI-748）：钉了页表版的册，产物目录里页表外的旧页产物（`p<页号>*`）一并删掉。worker 上留着旧图源多出的页（vol53 旧 183 页、新 182 页）会被 Step3 配页当正文页读而停在 183.png。
- `guji source pull`（GUJI-748）：钉了页表版（`source_rev`）的册，原图目录里页表外的 `<页号>.png` 是旧图源残留，拉完删掉（vol04 新页表 218 页，worker 上残留旧 219–221.png 被当正文跑）。`scripts/rerun_prep.sh` 同步加这一步，旧 tag 跑单也生效。
### Changed
- 印章遮挡格放行（A32，sheldon 10-26 定规则 1–4）：`seed_admit` 1.24、`align_ref` 2.2，两步 `code_hash` 变。只在册开 `lane_seal` 时生效。
  - R5 `lane_seal_via` 缺省改 `coord,align`（align 定位的默认字也放）；题列拦截词只留「書總目／四庫全書」，正文里带「總目」的列不再误拦。
  - 新 `lane_seal_title_formula`：整列连起来正好是「欽定四庫全書總目卷N」的卷端题列按坐标字直接放，`巻` 一律录作 `卷`（`lane_seal_title_norm`，本项目新规矩，不跟整理本）。
  - 新护栏 `lane_seal_lib_veto`（0.95）：库首位 cov≥0.95 且与默认字不同、又不是异体对 → 送审；`lane_seal_shift_guard`：整页印章格默认字与库首位系统性错一格 → 整页 R5 不放。
  - `align_ref.coord_neighbor`（缺省开）：逐列本整页定不了位置时借后一页（再前一页）的位置推本页半叶头，供印章页出坐标字。
  - 108 页印章页回放见 PR 正文。

- `guji cellvotes migrate --bind <旧 main 绑定 JSON>`（GUJI-748）：按旧 main 的**绑定格**查格级表（rebound 的原始 key 偏一格，vol04 有 7 条落到邻格），旧 main 上没认上格的不迁、列「旧绑定失效」；改绑后与同格更晚人裁重合算被盖掉、不列冲突；数据目录里已迁过的 `~q` 事件不再迁。迁出的事件 `migrated_from` 另记 `bound`。
- 四庫 vol04 换 siku-qiefen-v2 图源（GUJI-748）：`split_table_siku.json` 去掉 vol04 旧图合扫拆页 4 行（新图一页一图），`meta_vol04.json` 快照说明改为新图源。
- `scripts/rerun_prep.sh` 人裁自检：换图源的册（yaml 钉了 `source_rev`）本机产物的页表 rev 不符时按「还没有切分产物」跳过绑定自检（GUJI-748；vol04 首跑 #255 在执行机旧图产物上认新页号人裁，报 26 条认不出而失败）。不动 Step。

## [0.5.25] - 2026-10-26

PATCH（#654 换图源后旧页号事件不采信；#652 qa_pick）。无 Step 的 `code_hash` 变。

### Added
- 换图源（GUJI-748，设计 `doc/design/殿本换图源-siku-qiefen-v2.md` §六）：册 yaml 写了 `source_rev` 的册（已换图源），指向页的人裁事件锚里 `anchor.source_rev` 相符才采信，旧页号事件一律不采信（不看 ts）；`glyph_audit` 与不指向页的事件豁免，没切的册行为不变。统一读口 `core/event_files.py`，`EventLog` 读缺省过判据、维护日志读原样；写入拒写、`guji db push` 拒收新的旧 rev 事件（提示走 `guji cellvotes migrate`）；`guji db status` 与落票脚本打印不采信条数；原先直接扫事件文件的 11 处改走统一读口，测试禁止别处再直接扫。

- `scripts/zhengli/qa_pick.py` 默认配额加 `follow_ref=10`（v0.5.24 新放行通道），免得质检样本漏掉它（没列的通道不挑）。PATCH，不动 Step。

## [0.5.24] - 2026-10-26

PATCH（#648 修 `--override` 起不来；字组 #647 等）。

### Fixed
- `--override` 运行覆盖的原文写进 manifest 时 `ManifestEntry` 没有 `config_overrides` 字段，带 `--override` 的任何一步都报 TypeError 起不来（v0.5.23 的 #634 漏了；没带 `--override` 的跑法不受影响）：补字段与测试。PATCH，无 Step 的 `code_hash` 变。

## [0.5.23] - 2026-10-26

PATCH（#634 #637 册配置分层与运行覆盖；字组与人裁 #623 #624 #625 #626 #627 #629 #630 #638 #640；换图源工具 #636 #639）。seed_admit 的 `code_hash` 变（字组）。**新版起支持册配置分层：A31 把册 yaml 迁成「基础配置＋瘦身册」后，更旧的版本读这些册会静默丢掉基础配置，须改钉本版或更新。**

- rc 修复：核心依赖补 `ruamel.yaml`（`guji book split` 要用，#634 漏声明，干净环境装完一跑就 ModuleNotFoundError）；重生成 `doc/4-定字/字组/字组总表.md`（#640 改 xz 后没重生成）。

### Added
- 字组 象彖𧰼（xz，全册任务 08）：𧰼 模板换成人裁表（象 129／𧰼 178，含 sheldon 10-26 标注页 173 格），门槛 1.0→0.3、λ=3；组里加 `lift_ref_agree`（字形与整理本同字才补放）。按册留出一致格 0 错。xz 本来就在各册 `group_flow` 里，重落即生效。30 册离线回放：送审 147 补放 93（全 𧰼），复核降审 63（多为 𧰼 被放成 象）。文意 L2 表补格在中心库（xz-l2-2），要另推。seed_admit 的 `code_hash` 变。
- 册配置分层与运行覆盖（PATCH，设计 `doc/design/册配置分层与运行覆盖.md`）：工作区基础配置 `config/book_defaults.yaml`（册 yaml 只写各自不同的，合并结果与拆前逐字段相同；没有基础配置时行为不变）；`guji pipeline/step/status --override JSON` 运行覆盖（内存里叠在册 yaml 上，不改文件、不推库，原文记进产物 manifest `config_overrides`）；`guji book show <册> --effective` 看生效配置与来源层；`guji book split --books vol51-vol99 [--apply]` 把一组册的共用部分抽成基础配置（逐册强校验）；任务库 `book_overrides` 放开到 BookSpec 字段（`guji_jobs submit --override`），执行方改传 `--override`；`rerun_prep.sh` 读生效值。**注意：旧版本不认基础配置，册 yaml 迁成瘦身形式前，所有跑这些册的会话都要先升到含本改动的版本。** 无 Step 的 `code_hash` 变（对 vol50、vol51 实测 `guji status` 与 dev 逐行相同）。
### Fixed
- `--params` 显式传默认值（如 `shadow_veto:false`）会被册 yaml `params:` 静默改回：`_with_book_params` 改按「调用方有没有显式传」判，不再比是否等于默认值。
- 字组（全册任务 04「码位已定仍送审」）：码位组新入口 `FlowSpec.ref_top_enter`（库首位与整理本／坐标对位字同组就进，分差内的组外字不拦；出岀 除外），码位法给字要库首位 cov ≥ 0.91（`FlowConfig.codepoint_min_cov`）；新码位组 lei 類𩔖、cuan 竄𥨥、lang 郎郞；新 SHAPE 组 xiang 鄉鄕｜卿、weim 微㣲｜徵徴徹、zhen 鎭鎮｜鍾愼…，bie 別别 由码位组改成整字 HOG（別｜刖則所冊），两码位并一类、形近字当陪衬进库，ref_enter＋lift_ref_agree，按册留出判成本组字 0 错。册 yaml `group_flow` 不点名 lei cuan lang xiang weim zhen 就不生效（bie 已点名，改判法即生效）。82 册离线回放：任务 04 送审 288 格补放 235，另补放 8，逐格看图 0 错。seed_admit 的 `code_hash` 变。

## [0.5.22] - 2026-10-26

PATCH（#612 #614 #616 #619 #621 字组与人裁，#606 #611 #613 #615 #617 工具）。seed_admit、glyphdb_admit 的 `code_hash` 变。

- yh 文意规则 還鄉 补 鄕：中心库码位 鄉→鄕（暂归一）后整理本／放行字作 鄕，原规则只认 鄉。

- proof_cycle apply 加 `--ack-unlanded-votes <原因>`：旧单有票没法落成人裁（如图形格）时，原样交给 republish issue 放行换单。
### Fixed
- 字形库人裁以最后一票为准（`glyphdb_admit`，sheldon 10-26 定）：按人裁时间 `ts`（`replay_key`）处理，库里这一格已是更晚的人裁时旧票不再覆盖（此前按消费顺序覆盖，补消费积压时旧票压掉新票：vol04:143:9:16 改判 由 后被 10-22 的 山 盖回，全库 7 格）；更晚的人裁判切坏／非字／破损（`seg_defect`、`not_a_char`、`damaged`，含 `kind=not_a_char`）时撤掉这一格更早的人裁刻例（此前一直留着，全库 16 格）。新刻例证据记 `ts`；路由表 `not_a_char` 加 `glyphdb_admit` 去处。结果多两个计数 `superseded`、`withdrawn`。
- seed_admit 放行字落册码位（`codepoint_semantic` 最后一遍）：这对字已有按刻形拆判的字组（`registry.SHAPE_GROUPS`，同族的不算）时，人裁的刻形、该组判出的刻形照录，不再按工作区 `codepoints` 改回。修 變𠮓：工作区 變→𠮓 把人裁 變（vol04:197:7:3，A32 10-25 报）和 bian 组判出的 變 全改回 𠮓，bian 组上线后线上一格 變 都没有（v0.5.17 产物 vol04–20 有 74 格组判 變 被改回）。判 𠮓、组弃权、组外的格照旧归一；宮→宫（guan 族内）等其余码位不变。seed_admit 的 `code_hash` 变（PATCH）。
- 任务库看板写不上时不再沉默：原因打到执行方日志并写进 `jobs.worker.note`（`guji job workers` 显示）。

### Added
- 字组：新 SHAPE 组 pai 派𣲖（右边 𠂢 有横／无横）、qi 奇竒（上部 大／立）、sui 歲嵗（上部 止／山）：模板＝vol51–99 已放行格，首轮按册留出错例看图改标；门槛 0.5／1.0／0.5 按册留出 0 错；ref_enter＋lift_ref_agree。册 yaml `group_flow` 不点名就不生效。vol51–99 离线回放补放 74、改码位 14，三组送审 89→16。seed_admit 的 `code_hash` 变。
- 字组：新 SHAPE 组 shi 勢𫝑（左上 坴／幸）、fa 發𤼵（右下 殳／矢），标签全是 sheldon 在标注页逐格过的；按册留出门槛 0.5 均 0 错。模板库在 `config/groups/{shi,fa}/ids_bank.json`，册 yaml `group_flow` 不点名就不生效。vol21–50 离线回放：补放 𤼵31 𫝑64 勢3、改码位 發→𤼵 77、勢→𫝑 15。seed_admit 的 `code_hash` 变。
- 字组 shi、fa 补 vol51–99 标注（勢𫝑 144 格、發𤼵 159 格）进模板库；fa 门槛 0.5→0.9（按册留出 660 格 0 错），shi 310 格门槛 0.5 仍 0 错。vol51–99 样本外回放：补放 79、改码位 81，逐格看图。seed_admit 的 `code_hash` 变。
- 任务库看板：`guji job board`（执行方领单、收尾、心跳时自动写）把在跑、排队、最近结束的任务整理成一张表，写进中心库 `progress.metric`（栏目 `jobs`），网站后台「文本整理 → 重跑任务」显示：配置、状态、阶段、开始时间、已跑多久、预计完成（同类已成功任务耗时中位数）、结果包。不动任何 Step，`code_hash` 不变。

- cellvotes：网站精校页新增 `damaged`（破损、阙字）档，映射成 `confirm v=damaged guess=<字>`（录阙字方框 □，票上带的字当「最像的字」）；页面单选组各项与档的对应写进 web_votes 模块说明。

## [0.5.21] - 2026-10-25

PATCH（#605 字组）。seed_admit 的 `code_hash` 变（`groups/` 注册表、流程、字形判法表）。

- 字组：新 SHAPE 组 yin 隱𨼆、suan 算𮅕、guanm 闗關（与 men 共用 關），模板库在 `config/groups/<组>/ids_bank.json`；新 `FlowSpec.ref_enter`（库首位是陪衬、整理本或坐标对位字在组里也进组补放，先于库首位字的组）；kui 陪衬补 𮑮襄𠮓變雙凌。册 yaml `group_flow` 不点名就不生效。vol21–50 离线回放补放 𮅕87 𨼆28 闗13、改码位 9（PATCH）。
- proof_cycle apply 加 `--reuse-products <目录>`：引擎换版本后产物已自己从头跑好，沙箱直接用它，不取出单版包、不重跑 seed_admit；发布用的 cv 版本取引擎的 tag。

## [0.5.20] - 2026-10-25

PATCH（#595 Step1 1.10 列距救援：出带列两边线吸到淡界行；#599 印章定位 1.2：窄密度区按小印取模板位置，不再套整页大印正方形）。Step1、印章定位的 `code_hash` 变。

- 印章定位 1.2：只有宽 ≥ 0.75×版框宽的密度区才按大印套版框正方形；窄的（卷末小印印得淡、碎墨成区）在区里找模板位置按小印记，分数 < 0.2 就不算印；小印覆盖门槛 0.6→0.5。修 v0.5.17 首跑卷末页小印被当整页大印、大半页正文判成遮挡（vol35 p173 42 格、vol31 p213、vol36 p110、vol46 p225、vol49 p196、vol50 p102），vol44 p237 漏测的卷末印测出；另有卷末页小印已认出、又多套了一个整页大印的 6 页（vol28 p102/p193、vol34 p153、vol38 p88、vol40 p174、vol48 p35）去掉假大印，vol46 p95、vol47 p7/p47/p63/p87 页角碎墨的假大印去掉。vol21–50 有印或疑印的 764 页前后对比只这 18 页变，卷首大印一页没动。印章定位的 `code_hash` 变（PATCH），输出格式不变。
- Step1 1.10 列距救援：前几路都不成时加第 4 路 `snap_lines`，把出带列两边的线吸到附近的淡界行细峰上、没有界行就吸到字间空白中点，列宽进带才收；网格模式线数比自由模式多（自由模式漏线）也照收。修 v0.5.17 首跑界行极淡的 5 页：vol24 p69、vol29 p28、vol37 p76、vol45 p54、vol48 p121（此前整列丢字或两列并一列）。vol11–50 的 100 页样本另有 4 页（vol30 p78、vol31 p159、vol35 p43、vol49 p128）线在列间空白里挪了 2–11px，看图都对；vol13 p46 不动。Step1 的 `code_hash` 变（PATCH）。

## [0.5.19] - 2026-10-25

PATCH（#593 Step3 自动配页，缺省关的新设置）。Step3（`row_segment`）的 `code_hash` 变：版本 1.39、`code_deps` 加 `steps/row_segment_pagemap`、`utils/page_align`、`utils/daizhige`；缺省 `page_map: off` 时参数与输出不变。

### Added
- Step3 自动配页 `row_segment.page_map: off|loose|strict`（Sheldon 10-25 定殿本 vol51 起不再离线补格位表）：开着时 Step3 开跑前读全册 Step2 列窗口与原图，每页 9×23 格墨量指纹与 daizhige 全书半叶对齐（带状粗找多候选 → 单调 DP → 局部重排 → 回填），得出页→半叶与格位表，存 Step3 产物目录 `_page_map.json` 复用，代替 `layout_prior` 的离线表；`strict` 整册配不上（正文页没配准超过 max(2, 3%) 或有字页平均得分 < 0.95）就拦。钉页 `corpus/daizhige/page_pins.jsonl`。新钩子 `Step.prepare`（引擎分发页前主进程调）、`Step.book_params`（按册填参数）。殿本 vol11/13/14/16/17/19/20/21 自动表与中心库人核表逐格一致，vol51 整册跑通（PATCH）。

## [0.5.18] - 2026-10-25

PATCH（#589 Step1 列距救援不甩出贴版框的真列，殿本 vol40 p14、vol46 p118、p148 丢整列正文；#587 新册首跑自动标 main；#586 出单版产物包记对 cv；#588 看板）。Step1 的 `code_hash` 变。

- Step1 1.9 列距救援：新加第 0 路「出带的窄外列、外侧半列宽内有版框残段 → 外框线吸到版框」（`snap_outer_to_frame`），并且任何一路都不许把贴版框的旧外列甩出新网（`drops_framed_col`）。修 v0.5.17 首跑 vol40 p14、vol46 p118/p148：版心条在版框外，fuse 外推进版心、整网平移一列，框里的真列整列丢掉、版心被当成一列（A31 报的「无整理本对位」成片页）。vol11–50 触发救援的 100 页样本只这 3 页变。Step1 的 `code_hash` 变（PATCH）。
- `guji products pack push`：这册还没有 main 指针（新册首跑）时存包后自动标 main，不用加 `--main`（sheldon 10-25 定：新册的第一个包只能是 main）。只在正式库、装的是正式版 cv 时自动；实验分支、dev／rc 版只提示不标。任务库 `push` 步走同一条命令，自动生效。只在 `cli_products.py`，不动任何 Step（PATCH）。

### Added
- 字组看板：`group_progress` 每个字组写一张卡（`group.<组>`，送审格＋出现、放行率、组判率），`guji groups status --progress <套书 id>` 出完报告顺手写网站后台 yiti／xingjin 两栏（Neon 正式库）。只是看板数据，`code_hash` 不变。

## [0.5.17] - 2026-10-25

PATCH（A24 字组成批上线第二批的代码部分：#552 suo 组与 719 库标研究；#555 變𠮓 改刻形组；#556 尙尚 恢复复核改字；#558 宮宫 暂归一登记；#570 字组状态写后台看板；另含 #563 #572 Step1 列距救援 fuse、任务库与进度上报若干）。新组要在册配置 `group_flow` 点名才生效；`groups/registry.py`、`groups/flow.py`、Step1 的 `code_hash` 变。

### Changed
- 出单版产物包记对 cv：`republish.py issue --engine <worktree>` 用重跑的那份 cv（`engine_run.py`＋PYTHONPATH）存 `rev-<rev>` 包，`proof_cycle apply` 自动传 `--engine`，`--cv-commit` 也改记引擎的提交。此前包里记的是本仓 dev（册006 rev-006-r5 记成 7b40f6e），下一轮 apply 核引擎对不上（A32，PATCH）。
- `proof_cycle plan --recheck-extra <tsv>`：把别处发现的疑点（如重标时看出的字错）并进本轮复审清单，同格以它为准，可带旧人裁 id 让网站写明「已有判断」（A32，PATCH）。
- 字组：新建取框组 suo 瑣𤨏（GUJI-719，#552）；bian 變𠮓 改成刻形组（下半 HOG，只给 變，#555）；尙尚 恢复复核改字（vol16 两格放大看是 尙，#540 的「只降不改」撤回，#556）；宮宫 登记为暂归一到 宫（#558）。

### Added
- `python -m open_guji_cv.eval.group_progress`：`guji groups status` 的 json 写网站后台「文本整理」的 yiti／xingjin 两栏（缺省只打印，`--write` 写库，#570）；`guji groups status --prev` 出送审分类与增减（#553）。

### Fixed
- 任务库：执行方同一会话接第二张单（准备带 `--reset`）时 `db pull --force --no-rebuild` 不建 glyph.db；上一次准备在拉库前就失败的会话里 glyph.db 从没建过，建钉版库报 `no such table: sources`（#3–#6）。`--reset` 改成照常重建。
- 任务库：准备脚本的「语料校验」也认 `GUJI_CORPUS_DRIFT=warn`（之前单上写了放行，准备阶段还是拦下，#1 vol07 因此失败）。常驻执行方两张单之间每 10 分钟看一次 dev 上 jobs 模块、准备脚本、启动器有没有更新，有就空闲时退出，线程重新 start 换上新代码。
- 任务库：`retry` 过的单再也领不到（领单序号按已清零的次数算，撞 `UNIQUE (job_id, n)`，又被当成「同册被抢」悄悄吞掉）；现在序号接着历来最大的排，只有同册互斥的冲突才换一条，别的冲突照常报错。
- 任务库：环境类失败（如会话没挂 guji-workspace 私仓）退回排队后冷却 5×次数 分钟（新列 `run_after`，schema v3，`GUJI_JOBS_BACKOFF_MIN` 可调），并优先让别的执行方领；之前同一个坏会话几秒内把 3 次机会用完。执行方领单前自检能否读 guji-workspace，读不了就只报到不领单（`workers` 列出原因），挂上后自动开始领。`workers` 的「跑完」改称「领过」。

### Added
- 任务库常驻执行方：新表 `jobs.worker`（执行方名字、会话、空闲／在跑哪条、最近报到），`guji job workers` 列在线执行方，`ls` 表头带在线数；执行方空闲每 30 秒报到、在跑每分钟心跳。`GUJI_JOBS_LEASE_MIN` 可调租约（测试用）。文档加常驻执行方线程的开法。

### Added
- 重跑任务库 `guji job`（云端 `guji_jobs`）：重跑、A/B、评测交到 Neon 中心库 `jobs` schema（job／attempt／event／result 四表），同配置按指纹只跑一次；执行方 `FOR UPDATE SKIP LOCKED` 领单、租约心跳，准备→铺底→人裁检查→跑→对比→存包一口气跑完，每步进展与结果（包标签、R2 位置）记库。见 `doc/design/重跑任务库.md`。`scripts/rerun_prep.sh` 加 `--reset`（同一会话接第二张单时先还原本机册配置）。
- `guji source commons-pack`：页表里修过的页（拆页、转正、换图）合进 Commons 根，出回传用的新版 DjVu，逐页解码核对；`guji source commons --reroot`：传完重登记，页序与页图字节不变（设计稿 §十三）。

## [0.5.16] - 2026-10-25

PATCH（A24 字组成批上线第一批的余下部分：#532 #537 #540 #545；#538 #544 起跑自检与人裁绑定；#539 意见池；#536 #542 #543 #546 #547 字组文档）。新组要在册配置 `group_flow` 点名才生效；`seed_admit`、`groups/flow.py`、`groups/registry.py` 的 `code_hash` 变。

### Fixed
- 只重跑 seed_admit（基线包没有 `cache/`）时老人裁静默丢：绑定要拿字形库存图比现格字块图，缓存没有就判 unanchored（殿本 vol10 78/146）。现在缺字块图就现切；切不出来报错（`GUJI_ALLOW_LOST_HUMAN=1` 放行）；`human_chars` 读工作区事件而目录不存在时报错（`GUJI_ALLOW_NO_EVENTS=1` 放行）。绑定缓存版本 7→8。`scripts/rerun_prep.sh` 末尾加人裁自检、写 `~/.guji_env`（GUJI_WORKSPACE）。
- 起跑自检：跑 seed_admit 时字形库有人裁、事件目录却不在（数据目录没指对）就拒跑。此前只在事件里的人裁会被机器通道悄悄放行顶掉（殿本 vol06／vol10 沙箱重跑实测 88／68 格）。

### Changed
- 字组残留送审清理（A24 10-25，铺开 #9）：sb ly mb wj em rr 的 L1 规则拿整部整理本逐处回测修订；rr 随机森林 `rr_img` 改为复核弱票（新 `FlowSpec.review_weak`）；徵徴 复核按刻形改字、门槛单独定（新 `FlowSpec.review_fix_margin`，zheng 0.70）；`seed_admit` 影子闸不再降「同义组已按刻形定的码位」和「形近组补放时整字 HOG 过门槛给的字」（vol16:42:4:3 傳 被降审后又被坐标兜底放成傅）。殿本 vol06–20 离线回放：这几组组内送审 182→133（zheng 35→13、rr 33→21、mb 61→53…），变了的格逐格看图 0 错。`groups/flow.py`、`seed_admit` 的 `code_hash` 变，缺省开。研究脚本在 `research/char_groups/residual_1025/`。
- 字组：码位组 huo 獲𫉬、kui 夔䕫、lie 獵𤢪（殿本每对只一种刻法，码位 sheldon 10-25 定，#532）；一二 yr 加数横第二路 `yr_bars`，整字 HOG 不许单独补放，新 `FlowSpec.lift_ref_veto`（#537）；尙尚 复核只降不改（vol16 两格刻 尚 被改成 尙，#540 #541）。
- 字组文档：码位归一分「真归一」「暂归一（可分待拆，只限同义）」两类并补标已有条目（#542 #543 #546 #547）；登记 寃𡨚（#536）。

## [0.5.15] - 2026-10-24
PATCH（#522 seed_admit 1.23 iron_coord_guard；#528 ref_lib_diff 不放行、ref_prefer 等缺省开；#527 #529 #530 #531 #520 字组；#515 重跑提速；#523 guji source commons；#521 #524 控制台插图块）。缺省输出只把少量放行挪到待审、不改字，不属「多数册值得重跑」的核心升级，按 PATCH。`shadow_veto` 从此缺省开，执行方要装 `.[shadow]`（用发版附件装时 `--extras shadow`），否则起跑前自检拒跑 seed_admit；#533 补了 8 条没装 sklearn 就红的老测试。

### Added
- seed_admit 1.23：铁证与坐标对位字互证 `iron_coord_guard`（缺省开，A31 cv v0.5.12 错放 vol07:30:4:8 水→木，cv#522）：现役对位字被库分歧过滤掉时，铁证字与坐标对位字语义不同、又无直接异体边 → 落审（`iron_vs_coord`）；殿本 17 册 main 包回放命中 14 格（宫/官 ×10 等），看图 13 错 1 难分。`ref_lib_diff`（#528）进 `_LANE_HARD`，待审补放通道不再按整理本字放回。版本号连同 #528 一起记 1.23。只会把放行挪到待审，不改字。
- `guji source commons`：以 Wikimedia Commons 上的 DjVu 为原图的根（10-24 用户定，设计稿第十二节）：核 Commons sha1、存 R2 镜像、`ddjvu` 原尺寸解页、发布页表；会话连不上 Commons 时 `--djvu` 配 `--commons-json` 用别处下好的文件。四庫總目 99 册全部登记（vol01–20 补记根，页图不变）。只在 `datastore/` 与 CLI，`code_hash` 不变（PATCH）。
- `groups.ctx_l2.add_verify`：逐格细读复核补进 L2 表（细读与表字不同 → `disagree:verify` 弃权；表里低把握而细读 high → 用细读的字；至少两遍都 high 同字才 strong）。L2 答案留痕加 `runs`（几遍给了这个字）。日曰／日目 vol11–20 细读 197 格与新表在 dataset `char-groups/variant/ry/`，随成批上线替换中心库表（A24）。

### Changed
- 字组补放与坐标对位互证（`group_flow_lift_ref_guard` 同一开关下）：没有现役对位时，坐标对位是**组内另一个字**而给字的只有单遍文意表（不 strong、不是 L1、不到两遍同字、别的方法也没同字）→ 不补放（`group_flow_coord_dissent`）；补放留审时文意（本组或共字组）给了与整理本不同的字另记 `group_flow_ctx_contra`，进 `_LANE_HARD`，witness3、坐标兜底等补放遍不按整理本字放回。殿本 vol11–20 回放：挡下单遍 haiku 读反的 3 格错放和 2 格被 witness3 放错的格；`ctx_contra` 对全部字组（vol04–20 现有产物）还挡下 witness3／rare_ref 按整理本放的 4 个错字（木族「與此本皆合」等应为本），多留审 1 格（間問）（A24）。`seed_admit` 与 `groups/flow.py` 的 `code_hash` 变，缺省开。
- `config/groups/ry/rules.yaml`、`rm/rules.yaml` 修订（vol11–20 全部日曰目格回测）：rm 规则去掉曰进得来的词组（子、名、題等，原 `rm-目` 334 次命中错 194 次）；ry 加否決「分子目」「◎註曰」「◎月／◎本」，`ry-日鈔書名` 放宽到所有日鈔／日抄，`ry-干支日` 除「乙卯自序」，`ry-ext-r1-日` 除「故曰干祿」（A24）。

## [0.5.14] - 2026-10-24

PATCH（#447 发版自动附带执行包，本版用来首次验证 release workflow；#512–#519 字组与 db sync 改进）。

### Added
- PATCH：发版自动附带 Python 执行包（#447；新增 `.github/workflows/release.yml`、`scripts/build_release_assets.py`、`scripts/install_release.py`）：推 tag 时 wheel ＋ 资源包（`models/`、`config/`、`formats/`、`precleaned/`，Sheldon 10-24 定过渡期随 CV 包；字体、语料不进）＋ `install_release.py` ＋ 校验和自动挂到 GitHub Release，执行方不必克隆整仓。wheel 补上控制台前端 dist 与 `ops/baseline_tests.json`。不改 `open_guji_cv/` 的 Python 代码，各步 `code_hash` 不变。
- `guji db sync` 顺带落库：拉完合完对还没落进字形库的人裁只跑 `glyphdb_admit`、`glyph_audit` 两个消费者，逐条记账（报错的留着下次再试），落了再推；`--no-admit` 或 `GUJI_AUTO_ADMIT=0` 关。起因是批量写进中心库的人裁事件没人落库（10-22 起积压 967 条）；字形库更新的分工（落库、出快照、改钉）见 `doc/参考/受控重跑.md` 第六节。只在 `feedback/`、CLI，不动任何 Step（PATCH）。

### Changed
- seed_admit 四个开关改缺省开（2026-10-24 sheldon 定「确定该做的 feature 一律缺省开，别逐册开、过一阵又忘了其他册」）：`context_guard_ref_prefer`、`rare_ref`、`symbol_review`、`shadow_veto`（`shadow_conf` 缺省 0.97→0.8，殿本册配置一律是 0.8）。殿本 vol06–10 漏开 ref_prefer，vol06 v0.5.12 重跑 111:3:16 商→而（整理本「應時商確」）就是这条该拦的；在新包上开它另拦下旧错 130:5:9 于→子（「興國于氏」），多送审 3 格「入」（整理本作人）。殿本其余册 yaml 本来都开着，行为不变；别的书（北行日錄、全唐文等）从此也开，`shadow_veto` 要装 `.[shadow]`（起跑前自检会点名）。`seed_admit` 的 `code_hash` 不变、`params_hash` 变。
- `guji db sync`：字形库（`output/glyph_store/`）本地和库里都改了、本地又有库里没有的新人裁事件时不再整次停下：取库里的字形库、重建 glyph.db，删掉这些事件在字形库消费者（`consumed/glyph*.jsonl`）里的记账，在库里的字形库上重新消费一遍再推。本地字形库改了却没有新事件的照旧报冲突。省掉册 005 精校 10-23 三次手工 `pull --force`＋重写票（A32 复盘改进 1；只在 `datastore/`、CLI，不动 Step，PATCH）。
- `guji freeze register` 加 `--repo <cv 检出>`：产物是旧版 cv 跑的就指那个版本的 worktree，登记的 cv 版本与提交取自那里；检出认不出版本号（没拉 tag，记成 `dev+g…`）时计划报问题、不许执行，提示 `git fetch --tags`（A32 复盘改进 2；只在 `ops/`、CLI，PATCH）。
- close-check 1a 分开报过期原因：manifest 新记参数逐字段短哈希 `param_parts`（不进指纹，产物与 `code_hash` 都不变），`status` 的「参数变了」点名字段；只因共享输入（语料、证人、格位表、字组与异体表、借来的字形库等，`close_check.SHARED_PARAMS`）被别处更新而过期的页，1a（含冻结册）单列一句、不算失败；本册自己的变动照旧失败，两类都列。改动前跑的老产物分不出字段，照旧判失败（A32 复盘改进 3，标准 I；PATCH）。

### Fixed
- seed_admit `ref_lib_diff_guard`（缺省开，A24）：`relax_ref_agree` 的 `ref_lib` 分支在库判 `diff` 时不放行，记 doubt `ref_lib_diff`、退回人审。vol06 v0.5.12 重跑 149:3:3 图是「也」（框带版框竖线），整理本对位与库 top1 都给「十」、库判 diff（cov 0.83），旧版照放成「十」。vol06 新包 ref_lib 放行 13 格里只拦这 1 格，vol04–10 旧包 0 格。`seed_admit` 的 `code_hash` 变，各册只需重落 seed_admit。

## [0.5.13] - 2026-10-24

PATCH（#452 seed_admit 删准入三闸：`code_hash` 变、缺省参数下产物不变；#509 `guji recheck --glyph-diff`；#507 精校出单走 book-text dev）。

### Added
- `guji recheck <册> --glyph-diff <旧号|旧库>`：换字形库版本后只点名判决可能变的格（kNN 邻域差分：新旧库的 HOG 前 k 邻居、命中条目、共识门槛、近形对刻例），`--list` 逐格列理由，`--params` 指沙箱库。殿本 vol08 实测点名 6.7%（按字点名 32%），点名格重算＋其余照搬与整册全算 10,681 格逐字节相同（`doc/参考/受控重跑.md` 第五节）。只在 `ops/`、CLI，不动任何 Step，`code_hash` 不变（PATCH）。

### Removed
- seed_admit 1.22：删准入三闸 `runt_cell_review`（矮格转人审，含 `runt_ratio`、`runt_min_ink`）、`oversplit_gate`（过切提示，含 `oversplit_*`）、`nonchar_gate`（非字过滤，含 `nonchar_flags`、`nonchar_strokes`、`nonchar_jiazhu_ignore_rule_bar`）。三闸缺省都关，A/B 在 vol05、vol09 上单开逐格不变，vol04、05、09 触发条件 0 命中（[报告](doc/exp/准入三闸-vol05-vol09-报告.md)，cv#450；Sheldon 10-23 定删）。`seed_admit` 的 `code_hash` 变，各书该步判过期；缺省参数下产物不变。vol04 册 yaml 原开着 `nonchar_gate`，删后该键被忽略（实测 0 格），该步重算一次即可，键要另在中心库删掉。

### Changed
- 精校出单的 book-text 改走 dev（book-text 10-24 新规矩，open-guji/book-text#235；#507）：`republish.py` 的 `bump_book_text` 先切到最新 dev，升版后跑 `local_check.py --dev`、不重建 `index/texts`，提交并推 dev（别人先推了就 rebase 再推），不再开分支和 PR；`proof_cycle apply` 导出前先切 dev，原第 6 步「推分支、开草稿 PR」去掉。CHANGES 的 PR 列写 `#TBD`，由 book-text 每日合并换号（A32，PATCH）。

## [0.5.12] - 2026-10-23

PATCH（殿本 vol11–20 统一重落要钉：并进 #504）。

### Fixed
- 异体组按刻形复核（#504，A24 异体线）：13 个异体组对已放行格只跑字形方法复核，判出另一形就降审、不改字（修 旨→㫖 24 格等错放）；`guji groups status` 标疑格号漂移。`seed_admit` 的 `code_deps`（`groups/registry.py`、`flow.py`）变，各册 seed_admit 判过期；vol11–20 回放送审约 +85 格，不新增放行。

### Added
- 字组规范化（#503）：`doc/4-定字/字组/`（规范、总表、68 张组卡）＋ `guji groups status`，删旧 M7 文档。

### Changed
- `republish issue`（#500）：等发布认准 run、冒烟多等，冒烟没过不挡文本 PR。发布脚本，不进任何 Step。

## [0.5.11] - 2026-10-23

PATCH（殿本 vol11–20 统一重落要钉：0.5.10 之后只差 #498）。

### Changed
- 码位归一可放工作区级 `config/codepoints.yaml`（#498，Sheldon 10-24 定「归一放字形库这一层」）：`load_book` 先读与 `books/` 同级的该文件，再叠册 yaml 的 `codepoints:`（册里写的逐条覆盖）；没有这个文件行为不变。合并后的值经 `seed_admit` 的 `book_deps` 进指纹，加文件的工作区 seed_admit 判过期。

## [0.5.10] - 2026-10-23

PATCH（A30 要钉正式 tag 跑殿本 vol11–19；Sheldon 10-24 定带上 #471 及之后合进 dev 的改动，仍按 PATCH 发）。

### Fixed
- `proof_cycle apply` 用钉住的旧引擎重跑时经 `scripts/zhengli/engine_run.py` 起，读中心库事件跳过旧引擎不认的新种类（如 #485 的 `inverted_band`），并禁止 compact；重跑加 `--stop-on-error`，有一页失败就停，不再带着失败的产物接着导出出单（A32，册006 实跑 seed_admit 150 页全败后仍往下走）。发布脚本，不进任何 Step（PATCH）。
- 5a 简体参考字兜底（#486，A23，PATCH）：`match_replace` 系通道的参考字落在人工审定的纯简体清单（`config/dicts/simplified_refs.txt`，104 字）里、库 top 是其正字时，取库里的正字，不再把整理本混入的简体（贯/牵 等）放进产物。`clustering.seeding` 在 `seed_admit` 的 `code_deps` 里，`seed_admit` 的 `code_hash` 变，各册只需重落 seed_admit；输出会变，不能登记 `code_equiv`。清单文件本身不进指纹，以后改清单不会让产物判过期。
- seed_admit／align_ref 坐标冲突守卫（常开，无开关，A23）：`align_ref` 产物新增 `coord_conflict_ids`（坐标字≠现役 equal 字的格，全记）；match_ref 不放这些格、落人审（doubt `coord_conflict`）。起因：殿本 vol14 cv0.5.9 的 60:1:5 拱→撰、103:2:7（双行小注两字被切一格）放成「中」。vol14 两版回放每版约多送审 8 格。`seed_admit`、`align_ref` 的 code_hash 变，各册缺省输出会变；冻结册只登记不重跑。
- 生僻字面板（`rare_panel` 单格／批量入口）找不到识别权重文件时报 `CnnCheckpointMissing`，不再悄悄返回少 CNN／embedding 两路的候选（A23；wheel 安装后引擎仓根错位的同款坑）。只管文件缺席，没装 torch 仍由起跑前自检报；`GUJI_ALLOW_MISSING_DEPS=1` 放行。不在任何 Step 的 `code_deps` 里，`code_hash` 不变。
- 字形库体检（`glyph_audit`）撤库（evict）或改字（relabel）一个人裁入库的刻例时，同时把该格此前的人裁事件记进 `lists/stale_verdicts.tsv` 作废；撤下之后新裁的照常生效，机器入库的刻例不动（A23，GUJI-719 第 4 项）。此前撤库不留标记，旧人裁事件会让该格被误放行。不在任何 Step 的 `code_deps` 里。
- seed_admit `rare_ref`（两遍）也认 `lane_keep_ref_review`（A24）：被 `ctx_guard_ref`／`group_flow_ref_dissent`／`group_flow_coord_dissent` 拦下的格不再由 rare_ref 按整理本字放回（vol18:115:6:3 刻「本」、整理本与 5-b 作「木」，旧版放成「木」）。开了 rare_ref 的册参数 dump 多出该键，`code_hash` 变，各册只需重落 seed_admit。
- seed_admit `lane_keep_ref_review`（缺省开，A24）：被 `ctx_guard_ref`（ref_prefer）、`group_flow_ref_dissent`／`group_flow_coord_dissent` 拦下的格，不再由待审补放通道（witness3／coord_fallback／seal）按整理本字放回。vol20 实跑放回的格里改错 5 格（諸→諧、其→萁、本→木 等）：证人与整理本同为文渊阁系，与殿本刻字不同时照样一致。`seed_admit` 的 `code_hash` 变，各册只需重落 seed_admit。

### Added
- 图片格与插图块（GUJI-740，设计 book-text `docs/design/2026-10-图片格与插图设计.md` §五，格式 guji-format spec 09）：人裁 `confirm v=figure`（`alt` 说明）＝「这格是图形，不是字」，进排除名单（理由 `figure`），Step7 照排除格处理（不进库、不出卡），字位流占位出 □；网站精校票 `choice=figure`（带 `alt`）经 `guji cellvotes` 落成这一条。新 kind `figure_region`（控制台页级插图框，key `figure:<册>:<页>`）不配消费者。Step9 char-cord 导出用到图的册写 char v0.3（格 `fig`、图列 `kind: figure`）、cord v0.2（`marks.figure`）、新文件 `NNN.fig.json`（fig v0.1）与 `fig/NNN/<图 id>.png|webp`（按框外扩 2px 从页图裁，工作区原图 sha 对得上用它，否则取 R2 页图）；`--prev-fig` 沿用旧图 id、保留重绘图。没用到图的册导出逐字节不变。只动 `feedback/`、`report/slots`、`formats/`、导出脚本，不在任何 Step 的 `code_deps` 里，`code_hash` 不变；有图片格人裁的册 seed_admit 照常因名单变化过期（L0）。
- `scripts/zhengli/text_release.py`（M10 复盘第 6、7 项，A32）：`pin` 在冲 1.0 开始时记下册 yaml、语料版本与语料包、参照本、逐列格位表、字组配置、glyph_pin、产物包与引擎提交的指纹（数据目录 `feedback/lists/release/<册>.pin.json`，随 db sync 进中心库）；`check-pin` 分「本册输入变」（退出码 1）与「共享输入被别处更新」（2，冻结时记一笔不算失败）；`run` 按 1.0 标准顺序一次跑完输入锁、G0 票账、G1 待审与看不出 ≤2%、G3 close-check（钉住的引擎）、读者侧冒烟、冻结前能核的出口项，全过停在「请用户点头」。只读脚本，不进任何 Step（PATCH）。
- `proof_cycle.py`（M10 复盘第 4 项，A32）：重跑缺省全册 seed_admit（只跑有票的页会漏早有人裁的格）；`plan --engine <worktree>` 让重跑用出单版 cv、工具用本仓，核引擎的 HEAD 而非本仓；`plan --pack` 给没存 rev 包的老单指定包；导出后与 book-text 现文逐格比，人裁改字进文本、机器改判（无票变字）退回旧字并进下一张单的复审清单；出单换成 `republish.py issue`（只发这一章、等发布、冒烟）；新增只读 `status`（线上单投完没有，退出码 0＝可以落票），给定时任务用。发布脚本，不进任何 Step（PATCH）。
- 精校复审出单与网站推翻旧人裁（M10 复盘第 1、3、5 项，A32）：`republish.py prep/from-pack --recheck <清单>` 把指定格（人裁过的、已放行的都行）放回待审单，每格带 `recheck`、`note`（网站卡片头上常显的一句说明）、`prior`（已有人裁的字和 id），pending_route 不扣它们，现行切分里没有的列进差异单；`guji audit alt --extra` 给这些格也算相似字。`guji cellvotes draft` 另出 `recheck.tsv`（推翻旧裁、意见不一致、说无字又给字、格位变了四类挂起，可直接交 `--recheck`）；复审单上写明了旧裁、投票人投了不同的字，按有意推翻照写（payload `overrides`），出单后又来新裁的照旧挂起。新增 `republish.py issue`：出单、两道门、传图、推库、只发这一章（kaiyuanguji-web#584 的 `only`，网站没有就退回全站）、等网站发布、读者侧冒烟一条命令做完。发布脚本与 CLI，不进任何 Step，`code_hash` 不变（PATCH）。
- `guji opinions auto revert|finish-revert`（GUJI-734）：撤销已发布的修订批。在 book-text 开 `auto/revert-…` 分支把原批的格退回（A／B 整格还原，B′ 删格并把 cord 框放回、标点实体锚点跟回），文本线再升 patch，CHANGES 写明撤销了哪批、哪些意见、理由；现文已被后来改过则拒绝。合并后意见记 `reverted`、原批标 `reverted`、格谱系补撤销行，网站状态回到「还要再看」。只在意见池与 CLI，不动任何 Step（PATCH）。
- `guji source pull|show|list|check|ia|register|replace`：原图（源件 → 页图 → 页表）存 R2 正式桶，云会话一条命令取原图（`doc/design/古籍图片全流程-源件页图管线与IIIF.md`）。殿本 vol01–20、北行日錄、全唐文 v006–v010 已登记，与现用原图逐字节相同；`register --src-file` 登记 PDF、DjVu 等非 IA 源件。只在 `datastore/` 与 CLI，不动任何 Step，`code_hash` 不变（PATCH）。

### Changed
- 未发布版本跑管线正规化（A20，2026-10-23 sheldon 提）：① 不在 tag 上时 `cv_version` 改记 `0.5.10.dev12+g<12 位 hash>`（原 `0.5.9+12`，不带 hash、会撞号），浅克隆取不到 tag 记 `dev+g<hash>`（原记空、钉版册因此一律被拦）；② 钉版／冻结册在中心库实验分支（`GUJI_DATA_BRANCH=exp/*`，产物隔离）上跑自动放行；正式目录上 `--allow-cv-mismatch` 须带 `--why "<理由>"`；放行理由记进 manifest 新字段 `cv_override`；③ 非正式版 cv 出的产物包不能在正式库标 main（`--why` 例外）。只动 `core/cv_version.py`、`cli_v2.py`、`cli_products.py`、`datastore/packs.py`、`products/manifest.py`，都不在任何 Step 的 `code_deps`，各步 `code_hash` 不变，老产物不过期（L0）。见 `doc/版本号规矩.md` 第五节。
- Step0 invert_detect 1.2（Sheldon 10-23 审 vol11–20 候选）：建议修法改成新规则 `inverted_poly`（多边形，按黑区实际形状圈：可台阶、可分段，修时不再现量），vol11 p40 范围太大、vol13 p85/86、vol14 p87 略偏、vol17 p126 台阶被抹平都贴合了；下边框按位置排（黑条下方是空白地脚就不报，与页顶外框对称），vol16 p80/p104、vol20 p168 不再送审。`utils/preclean` 加 `inverted_poly` 与通用 `rule_mask`。`invert_detect` 的 `code_hash` 变，各册只需重落 Step0 候选；已在 yaml 登记的反色页不受影响。
- 删 `glyph_match.near_shape.allow_guarded`（A20／用户 10-24 定）：匹配器已判护栏（never_match／conflict）的格近形决胜一律不升档；书 yaml 里的旧键读进来被忽略。`glyph_match` 的 `code_hash` 变，vol02（唯一开着它的册）的 glyph_match 需重算一次。
- 放行开关缺省开（2026-10-23 sheldon 定「没问题的 feature 一律缺省开，开关只为方便 A/B」）：`seed_admit.context_guard_diff`、`context_guard_ref_blank`、`lane_witness3`、`lane_coord` 改缺省开，`group_flow` 缺省＝注册表里全部声明了 flow 的字组（书 yaml 写 `[]` 才关），书级 `iron_gate` 缺省开。殿本 20 册 yaml 本来都开着，行为不变；`seed_admit` 参数 dump 变，各册放行判过期。
- Step1 border_detect 1.6：列距救援 `pitch_rescue`（缺省开，`utils/pitch_rescue`）。自由模式列网里有列 < 0.7×中位列宽时（多挑一条假竖线把一列劈成两窄列、外侧一整列落在网外、字悄悄丢掉），先网格模式重探，选不出版框对再去掉劈线、在有字的一侧补外框；新网干净才接受，没触发的页逐字节不变。殿本 vol11–20 九页里修好 8 页（vol13 p75、vol14 p103/186、vol16 p120、vol19 p29/86、vol20 p68/113），vol16 p8 密排夹注页留人工。`border_detect` 的 `code_hash` 变，全书 Step1 起判过期。
- Step1 列距救援收紧到实测列宽带（Sheldon 10-23：殿本列宽极一致，按分布严格限）：殿本 vol04–20 共 2,969 页，内列宽／页中位 99.9% 在 0.907–1.088，最外两列 0.84–1.26。触发改为「有列出带」（内列 ±10%、外列 0.85–1.3），新列网也须全在带内；另加「列宽合格的列两边的界行不许动」，防网格把印好的真界行挪进空白（vol13 p46）。vol11–20 触发 31 页、改 8 页（原 7 页列网错位＋vol11 p55 右框线更贴界行），vol04–10 不变。

### Fixed
- `ops/col_gate.py`（A20，A24 报）：读原图改走 `utils.image_io.imread`，不再直接调 `cv2.imread`（Windows 非 ASCII 路径会静默读空；`test_image_io_guard` 在 dev 上因此失败）。缺原图照旧跳过。不进任何 Step，`code_hash` 不变（L0）。
- `scripts/dzg_import.py`（A20，A24 报）：daizhige 源用缅甸字母（U+1001 起，登记在每条 `glyphs`）当缺字图占位码，原先只转 PUA，233 处原样进了 `siku_daizhige.txt`、成了坐标对位的整理本字。现在与映不上的 PUA 同记 `〓`；新增 `fix-glyph-codes` 就地修已有整理本（一字换一字）。已据此出殿本语料 v18（中心库 rev 94678）。脚本不进任何 Step，`code_hash` 不变（L0）；换钉 v18 的册语料指纹变。
- `scripts/zhengli/republish.py add-sprites`（A20，A31 报）：核坐标时把 `img.s` 文件名也一起比了。线上单已是哈希名（`p0001.<sha8>.webp`，册 006–010 先前补过主雪碧图、只缺相似字图），重建出来是 `p0001.webp`，于是 105 格坐标全对也整单被拒。现在比之前去掉内容哈希，页名不同照样拒。发布脚本，不进任何 Step，`code_hash` 不变（L0）。

### Fixed（rc 上修）
- `guji db sync`／`pull` 读的过程中有人往同一工作区推新行（如 `admissions.jsonl` 追加）时，不再报「库里有超出 n_lines 的行」退出，而是重读（原来只在读完后核 rev，读到一半的不一致直接抛）；没有新写入的不一致照旧报错。10-23 A30 sync 殿本撞上（与 dev／v0.5.9 无关，同一段代码，换时间重试就过）。只动 `datastore/workcopy.py`，各步 `code_hash` 不变。

### Added
- 指纹覆盖守卫 `tests/test_code_deps_coverage.py`（A20）：`code_hash` 只认 Step 模块与手列的 `code_deps`，不顺 import 走；普查出 11 个 Step 共 39 处「import 了算法模块却没进指纹」（seed_admit 15 处，含 `shadow.*`、`feedback.mojibake`、`clustering.confusable`、`steps.align_ref`/`context_decide`）。现登记为存量、约定搭车补（该步下次本来就改算法时顺手补进 `code_deps`），新增 import 不登记就测试失败。只加测试，不碰任何 Step，`code_hash` 不变（L0）。
- `guji opinions auto`（M11，GUJI-735 起步；MINOR 级新命令，不碰任何 Step，`code_hash` 不变）：修订流程自动化调和器。`decide`（`to_user` 的意见按 `rules.json` 的 `auto.decide` 自动结案，`decided.by=policy:auto-v1`；刷票、用户亲裁、版本漂移、C 类、看不清、置信不足的留着）、`prepare`（每章聚一批，book-text 里建 `auto/<书>-<章>-<日期>` 分支，套 `revise`、升版本、跑 `local_check`、提交一次，失败不留半成品）、`finish-pr`（CHANGES 的 `#TBD` 换 PR 号）、`finish-merged`（记 `applied`、格谱系、度量、`publish-status`）、`digest`（汇总）。意见池新增 `releases.jsonl`、`lineage.jsonl`、`metrics.jsonl`（只追加）；日志新增 kind `batched`／`pr_opened`／`published`／`reverted`／`policy_applied`，只有 `reverted` 改状态。`rules.json` 升 version 2，加 `auto` 段；合并进 book-text main 缺省不自动（`auto.merge.enabled=false`）。设计见 book-text `docs/design/2026-10-修订流程自动化设计.md`。

### Fixed
- 续跑加固（#454，A20）：manifest 追加写被杀留下半行时，读表跳过坏行（该页按没记过、重跑补），下一次追加先补换行，不再整册起不来；跑批锁冲突报错在同机时标注持有者 pid「在运行／已不在（锁可能被子进程握着）」。不碰任何 Step，`code_hash` 不变（L0）。
- seed_admit 放行护栏七条（A24，殿本 vol11/14/15 用 v0.5.9 重跑后逐格核出的错放；新开关缺省开，`seed_admit` 与 `groups/flow.py` 的 `code_hash` 变）：
  ① `context_variant_form_guard`：Step6 margin 按语义合并算，參㕘叅、簒/篡 等异体各占一半也报 margin 1.0，context 在异体里抓阄（vol14 235:7:4 两版一次 㕘 一次 叅）；放行字在 ranked 里有语义同字的对手、库形又分不开 → 落审（doubt `context_variant_form`）。
  ② `iron_ctx_guard`：铁证字与上下文第一名（概率 ≥0.5）语义不同、两字在库里近平手（差 <0.005）→ 落审（`iron_vs_ctx`；vol11 12:2:14 官→宫）。
  ③ `match_tie_guard`：库判非 same、库前两名语义不同且 cov 差 <0.003 时 match_ref／match_replace／match_margin 不放行（`match_tie`）：对位载体取库 top1，近平手时「库与整理本一致」是自证（vol14 60:1:5 拱→撰）。**缺省关**：vol16–20 离线回放每册多送审 160–400 格（日曰、人八等库近平手而整理本给对），只多拦 2 格。
  ⑤ `context_lib_dissent_gap`（0.03，`context_lib_dissent_cov` 0.93）：库 top1 与 context 字语义不同，context 字在库里落后 ≥0.03 或不在库候选（top1 cov ≥0.93）→ 落审（`context_lib_dissent`；vol14 𣏌→相、㳫→書、牽→事）。原 `context_guard_diff` 只拦库判 diff，这几格库判都是 unsure。
  ④ `group_flow_lift_ref_guard`：字组补放时只有文意给字、整理本字是组内另一字 → 不补放（`group_flow_ref_dissent`；vol15 118:4:15 面→而）；共字组联合判（日曰目）不受此限。
  ⑦ 同一开关下加坐标对位拦补放：现役对位缺格、坐标对位（`align_ref.coord`）是组外另一字 → 不补放（`group_flow_coord_dissent`；vol18 107:6:7 叔→叙、vol16 109:6:21 樊→彝）。坐标对位字只用来拦，不参与判字。
  ⑥ `context_page_end_review`：本页读序最后一格不走 context 放行（`context_page_end`）。对位只收两头被 equal 夹住的 replace，页末格常拿不到整理本字，没人拦 context：v0.5.7→v0.5.9 放行字变率页末格 1.94%／1.67%（vol12／vol14），其余格 0.07%／0.05%。每册约多送审 2–5 格；根治在对位侧，另查。

## [0.5.9] - 2026-10-22

PATCH（Sheldon 10-23 定发，为殿本 vol11–20 带格位表全体重跑）。

### Fixed
- Step3 row_segment 1.37（PATCH）：`layout_prior` 开着、表在、表里却没有本册时直接报错，不再悄悄当关。殿本 vol11–20 首跑就是册配置写了关、表里也没这 10 册，对表逐格全对只有 94.7%（vol04–10 带表 100%）。同时中心库补了 vol11–20 的页映射与格位表（rev 93491，15,825 列），册配置改回开。`row_segment` 的 `code_hash` 变了，缺省输出不变（有表的册逐字节相同）。
- `guji opinions publish-status`（GUJI-714 后续，PATCH）：① 上次发过、这次算不出状态的 target（意见重开、改判成不写的状态）写一行 `state:"open"`，网站 proofing-sync 据此撤回 KV 里的旧状态（原来旧状态一直留着，实时页与 COS 清单不一致）；② 人裁驳回又没写公开理由、判定为原文不误的，回复用模板句「此处原文作「甲」，暂不改」（原来读者只看到「未采纳」）；③ 撤销过 dup 的意见照常带回复（原来只要有过 dup 记录就不回）。不碰任何 Step，`code_hash` 不变。

## [0.5.8] - 2026-10-22

PATCH（sheldon 10-22 定发）。主要内容：Step0 反色带候选 `invert_detect`、切分 `row_segment` 1.36、字框收缩 `cell_shrink` 1.19–1.20、外框线回直线 `border_detect` 1.5、文意组加字形第二路（cv#429，新增 12 个组模板库 rr ts ly wj zh yh yt js em fc yr xz）、厯歴／呂吕／徵徴 判法调整、己已巳／日曰 收口、影子复核按册码位归一（v0.5.7 漏带）。相对 v0.5.7，`border_detect`、`border_detect_gate`、`column_warp`、`column_gate`、`row_segment`、`cell_shrink`、`seed_admit` 七步 `code_hash` 变，另新增 `invert_detect`，**各书 Step1 起全部判过期**；其余 11 步不变。新组 weiw shan di qin 要在册配置 `group_flow` 点名；组模板库变了，配套出全局层新底库、各册改钉。rc 上全量测试：3851 过、66 跳过、1 条报错；报错的是一条测试守卫，已修（装了 psycopg 而没给测试库时，`test_datastore_expbranch` 一条用例报错而不是跳过，只改测试）。

### Fixed
- seed_admit 影子复核 `shadow_veto` 比字按册 `codepoints` 归一（d54fe0fc）：別别、晚晩、出岀 不再被误降。v0.5.7 切 rc 时没带上，本版补发。`seed_admit` 的 `code_hash` 变。
- Step3 row_segment 1.36：字内空隙里的格线不再把字头、点留在上一格（人审截断「良」的点、「晉」的头、「其」的脚、「二」的上横）。干净格线两侧有一格格高偏离 period 超过 15% 也过一次 U-Net 探针（vol02 1,800 条，原来只有一高一矮的 6 条）；探针分歧 ≥100、扩池补来的候选（U-Net 引导缝 / 按格高找的缝）与 U-Net 分歧 ≤30px 时直接改选，不再只记候选交人：粘连切点要穿墨 ≤20px，原本干净的格线只换成同样不穿墨的缝（换成穿笔画的缝会把上字底横的一截切给下格，「一」就成了「二」）。vol02 改 40 处、vol05 改 76 处，看图都是修好或持平；Step3 时长略增。
- Step4 cell_shrink 1.19：列端粗版框不再带进字块（重跑 v0.5.7 时害了认字）。`strip_frame_line` 两处放宽：线跟字之间隔着白行、线外到下一道线只有框的毛边和连墨的，双边框内外两道一起剥（vol05 p92「乾」）；厚过 0.12 格但墨铺满 ≥80% 的线行段算粗版框，贴着字也剥（vol06 p149「者」、vol08 p59「尚」）。vol05 全册只改「乾」和一格框渣、vol09 全册 0 格变化。框线只剩贴着字的碎段的（vol06「將」「而」、vol09「講」）还没修。
- Step4 cell_shrink 1.20：双边框内框贴着字脚、两头没到窗边的，不再带进字块（vol06 p112「而」）。全页框线线位原来只在版框往内 0.4 格里找，内框离版框可到半格，找不着；改为找到 0.8 格，并记下每道线的线厚。列端格里跨度 ≥0.8 窗宽的实线，中线落在线位上、厚度跟那道线差不过 2 行，就当框线剥。字的底笔碰巧压在线位上的厚度、跨度对不上（「士」的底横 0.7 窗宽、「是」的捺脚只有 1 行）。vol05 改 17 格、vol09 改 41 格，看图都是剥掉框线或框渣，「燧」辶的捺尾跟框线连成一片，随框剥掉一截。「將」那列框线跟邻列对不上、「講」是虚线贴字，还没修。
- Step1 外框线也按横带证据回直线（`border_detect` 1.5，`border_geometry.snap_verticals_to_evidence`）：原来「折点只许在有界行支撑的横带偏离直线」只管内部界行，首尾两条外框线没人管。vol08 p2（卷首大印页）左外框下半段印得淡，三段折线被第 9 列字的竖笔吸进 42px，s15–21 七个字只罩住右半。外框线现在只认两种证据：线就压着的框线（偏 <8px）原位，否则回直线位（直线已挑过细内框）；不用文字缝、不往远处的粗外条挪；内部界行先定、外框线最后按定下来的邻线过间距护栏，内部界行与改前逐位相同。vol04/08/09 三册 555 页里 34 页的外框线动了，Step3–4 新旧对比：对格位表逐格全对 279/279 列不变，字框横向变了的 13 列看图都是变好或持平（vol08 p2 c9 罩全，vol04 p178 c1、p63 c1、p91 c1、vol08 p12 c1 甩掉框线渣）。各书 Step1 起判过期。
- 导出 cord 时同一格号的两个 blank 格只发一个 mark：夹注 a／b 两半都被 Step3 记空（`layout_frame_junk`）后同一格号有两个 blank、blank 没有 sub，mark id 撞，`guji export`／`republish.py from-pack` 在页检查报「id 重复」（v0.5.7 重跑 vol05 p3 第 4 列 slot 11、12）。只改导出，不动任何 Step，`code_hash` 不变；Step3 产物里的重复 blank 留着无害。

### Added
- R6 整页／整列丢字检查 `ops/col_gate`（GUJI-661）：读 Step3 与原图，报「整列没切出」与「单字墨段没被字格接住」，抹掉版框折角与污渍后再判。`scripts/zhengli/col_gate.py` 单跑，`collect_exit.py` 加 R6 项（`exit_report.py` 有数才判）。只报告，不改产物，不动任何 Step。殿本 v0.5.7 包 vol04–10 误报每册 0–12 处；自造缺陷召回：整列格记空 100%、整列没切出约 85%、整列错位 0.6 格约 65–73%；真书历史案例（vol03 57:1 等）云端没有当时的旧产物，未能复现。
- `feedback/exclusion_check.stale_by_binding` + `scripts/zhengli/stale_exclusions.py`：列出人裁排除名单里裁决锚点与当前切图对不上的格（只报告；GUJI-659／623）。
- 粗校出口 R4 异常表可写成 JSON（GUJI-666，`scripts/zhengli/collect_exit.py` 的 `load_anomaly`）：`{"rows": [{n, text, cause, concl, pages?, cols?}]}`，`pages`／`cols` 给了就不再从「现象」里抠 pN colM；格式错报具体位置（JSON 报行列和 `rows[i]`，md 报第几行），不再是整表悄悄 FAIL 或悄悄少读几行。老 md 表照读。体检结果带字形库指纹那一半早由 GUJI-710 做掉。
- `guji pipeline`／`guji step` 起跑前自检依赖（GUJI-654，`ops/preflight.py`）：这次要跑的步骤用得上的东西本机缺了就拒跑（退出码 2）并点名——Step3 切点裁判（`cut_judge=unet`）和 Step5-b 要 torch 与权重，册配置开了 `shadow_veto` 的 Step7 要 joblib／scikit-learn。以前这些都是悄悄退回旧办法或整页失败（10-21 vol08 缺 joblib，seed_admit 69 页全失败，pipeline 仍返回 0）。`--allow-missing-deps` 或 `GUJI_ALLOW_MISSING_DEPS=1` 放行。不动任何 Step 与 code_deps。
- 待审单雪碧图改成「文件名带内容哈希、真源进 R2」（GUJI-675，方案 B）：`scripts/zhengli/sprite_pub.py`——`republish.py prep` 把图改名 `<原名>.<sha8>.webp`、单子顶层写 `sprites[]`，`push` 先把图按 sha256 传进 R2 main 桶（`datastore/r2.py` 认 `webp` 后缀）再写单子；新增 `republish.py add-sprites` 给线上旧单补图（重建后逐格核坐标，一格对不上就不动）。网站 proofing-sync 读 `sprites[]` 发到 COS（kaiyuanguji-web 同步改）。不动任何 Step 与 code_deps。
- Step0 反色带候选 `invert_detect`（Sheldon 10-22 定「自动认＋送审，人点头才修」）：排在 Step1 之前，判据是「长横黑条里界行翻成白缝、带外接着是黑界行」，产物 `inverted` 列出每页候选黑条、翻白界行道数和建议修法（一条 `preclean:` 规则，量不到上下沿就退成矩形）。只送审、不自动修：殿本十册原图上已登记的 15 处全中，另报 13 页，Sheldon 看过都是粗外框或封面。已登记 `preclean:` 的页读修好的图，不再报。控制台卡片和点头后自动修在下一个 PR。
- 反色带送审与点头才修：控制台 Step0 页加「反色带候选」卡，一页一张，原图与照建议修法修后的预览并排，点「是／否」落 `inverted_band` 事件（问题 `invert_detect.page.is_inverted`，裁决表 `preprocess/inverted-band`）。点「是」的页 Step0 照规则修，修好的图放派生缓存 `<cache>/precleaned/<book>/<页>_<规则哈希>.png`，`effective_raw_path` 读它，原图 sha 变、各步自然判过期；人审放行不再过墨量闸。点「否」的页不再出卡（勾「含已否」可改判）。书 yaml `preclean:` 登记的页照旧以登记为准。接口 `/api/invert-review/cards`、`/api/invert-review/preview`。
- 反色带候选 `invert_detect` 1.1：先排掉不在正文里的黑条（Sheldon 10-22 嫌 1.0 误报多）。黑条不足 12 行（上框粗线）、上方是空白天头（页顶外框）、上下是满纸花纹（封面、书衣）都不报。殿本十册 1,707 页：已登记 15 处全中，误报 13 页降到 2 页（vol06 p40、vol08 p67，抬头格下的粗横线，与已登记的 vol02 p136 几何上分不开）。阈值在同一批十册上定，没有留出验证。
- 复查已登记反色带：vol05 p22、vol07 p78、vol09 p174/p175 四页修完还留着黑块（登记的横向范围漏了一截，vol07 p78 左两格的带上沿是台阶形），中心库 yaml 补全规则（vol07 p78 左两格改用矩形），`precleaned/` 四张图重生成。修后再跑 `invert_detect` 不报，逐页看图核对干净。四页 Step1 起判过期。
- 特殊符号进字符候选集（Sheldon 10-21 定，设计 `doc/design/特殊符号进字符候选集-设计.md`）：人定的符号（○□△⊙ 等，`hanzi.symbols` 登记过的）能进字形库，`glyphdb_admit` 与 `glyph_ledger` 不再把非汉字码位一律拒收；相似字按图认符号（模板余弦 ≥ 0.93 且高过本格最像的字才并入）；5-b 字表开关 `font.charset.symbols`、seed_admit `symbol_review`（放行成符号的格退回人审，除非本书同一符号已有 3 条以上人裁）；送审原因显示「可能是符号」。没开开关的册产物逐字节不变。（#362、#377、#384）
- 从产物包出待审单时，相似字现切字块图、一格没出就报错、`republish.py add-alt [--replace]` 原地补。（#362）
- 日曰分歧复核（sheldon 10-22，重跑后 4–10 册 39 格组流与库分歧，长上下文读原典逐格定字）：日曰 18 格里 10 格是文意表（L2）错杀或错放，根因是表只取 haiku、Sonnet high 异议不起作用（5 格 Sonnet 5/5 对）。新 `scripts/l2_apply_dissent.py` 离线改表（Sonnet high 异字→以 Sonnet 为准），不动 Step 代码、`code_hash` 不变；抽样 8 页：6 格由降审回到放行且字对，其余不变。新表（另加长上下文判定 3 格 vol07:73、vol09:40、vol10:109）sheldon 10-22 说「推」，已推中心库＝书库语料 v15（base b4，册钉还没改到 v15）；项目文件 `jys-ry-rm-1022/round4/ry.json`。

### Changed
- 厯歴 `lih` 改取下半框 HOG（`ids_online.SPECS`：size 48、`region=(0,1,0.5,1)`、门槛 0.25；模板库同一 122 格重建）：按册留出 119 对/3 弃/0 错（原 92/122）。区域在同批数据上选，偏乐观。经验总结与逐组评估见 `doc/design/M7-切分识别经验推广.md`。PATCH；只影响点名了 lih 的册，重跑归 M8。
- 呂吕 `lv` 门槛 0.5→0.3、徵徴 `zheng` 0.6→0.45（sheldon 10-22 同意）：判别台复核（`research/m7/bench/check_prod.py`）发现两组各有 1 格在线上门槛之上判「错」，sheldon 看图确认是原人裁错（vol02:125:8:4 实为吕、vol01:70:7:10 实为徴；数据集与中心库已更正）。更正后按册留一：呂吕 68 对/2 弃/0 错（原 62），徵徴 49 对/26 弃/0 错（原 38，错例最大 0.336）。与上一条合计 PATCH；只有 `seed_admit` 的 `code_hash` 变（相对 dev：8a8925fc0ffbd21a→72120ef3f1a81eec）。
- 文意组加字形第二路（sheldon 10-22「能不能再进一步优化算法」）：入人八 土士 論諭 問間 曾會 遺還 圓圖 甲申 而面 傅傳 一二 共 11 组，方法数组在文意之后加整字／取框 HOG（`registry.GLYPH2`、`ids_online.SPECS` 同名行，模板库 `config/groups/<组>/ids_bank.json`）。文意弃权时字形可单独补放，两路都给字须一致，复核时字形给了别的字就降审。新的 `IdsSpec.clean`（`ids_whole.clean_patch` 去邻格碎墨）与 `aspect`（宽高比不合弃权）；模板＝人裁格＋vol04–10 已放行格（每册每字 ≤20），字块都是线上同款 char_patch；门槛＝按册留一人裁 0 错且已放行格异议 ≤0.2%，最低 0.4。象彖𧰼 的「象族」形判（象／𧰼）用左半中段 HOG，只在很像象时给象，𧰼 不足 20 例永不自动给。vol04–10 抽样 106 页对 dev：补放 10 格（逐格读上下文，1 格组外字判错，甲申门槛 0.4→0.5 后挡住）、降审 1 格（文意对、字形误报）。大太 未末 王玉 目自 千干 十卜 戊戌戍 木本 不上。`seed_admit` 的 `code_hash` 05f5830d581fee12→f035a1fe19ee8836；新模板库进下一版语料（`repo:` 文件），重跑归 M8。
- 己已巳／日曰 第三轮收口（sheldon 10-22；`doc/research/己已巳日曰日目-送审收口-2026-10-22.md`「第三轮」节）：① 己已巳 `pair`：读序紧挨的两格都进了组 → 前「己」后「巳」（干支，總目参考文本两两相邻 37 处全是己巳），不跑方法；② `ctx_l2.add_review` 放宽：主模型 low/mid/「其他」都可，复核模型 high 的组内字就收，主模型有一遍 high 给了别的字则不收（己已巳 179 格标注上 9 格全对）；③ 日曰 `review_fix_strong`：L2 表答案 strong（`ctx_l2.add_confirm`：另跑一遍 haiku 和 Sonnet 都 high 同字）且字形没明显反对时，复核改掉别的通道按整理本放的字，否则照旧降审（日曰 98 格标注上 haiku＋Sonnet 都 high 同字 66 格错 1）；④ 影子闸不降字组按文意定的字——影子只是挑了同组另一个字时（原来改成曰后被影子降、又被坐标兜底按整理本放回日）。抽样 261 页对 dev：新放行／改字 13 格，逐格核 0 错、0 降审；三组送审（不含遮挡）69→56，其中 strong 标记与放宽复核要新 L2 表推中心库后才生效。PATCH；只有 `seed_admit` 的 `code_hash` 变（cb2434a4a4c41d6e→8a8925fc0ffbd21a）。

## [0.5.7] - 2026-10-21

PATCH（Sheldon 10-22 定发，vol04–10 重跑用）。相对 v0.5.6，`cell_shrink`（1.17）、`row_segment`（1.35）、`seed_admit`（1.21，`code_hash` 85052303fa79a800→bff8f652ceae4de9）三步 `code_hash` 变，**各书 Step3 起判过期**；其余 15 步不变。新增 `qin`／`shan`／`weiw` 三个字组模板库，要在册配置 `group_flow` 点名才生效。

### Added
- 字形判法扩面（sheldon 10-22，#393 方法数组之后）：衛衞 `weiw`、刪删 `shan`、扺抵 `di` 三个异体对上线取框 HOG＋岭回归（`ids_online.SPECS`，`registry` 配 `config/groups/<组>/ids_bank.json`）。模板＝数据集 `labels/unified.jsonl` 里 sheldon 人裁刻形与 `variant/*/crops` 字块（衛41／衞14、刪111／删5、抵90／扺10）；按册留出 0 错：衛衞 37／55 对、刪删 97／116、扺抵 78／100，次形（衞／删／扺）几乎都弃权送人审，不会被放成主形。只补放，需在册配置 group_flow 点名，重跑归 M8。`ids_online` 与 `registry` 变，`seed_admit` 的 `code_hash` 变。建库与评测脚本 `research/m7/glyph_expand/`。
- 禽會俞命舍（`qin`）整字字形组：曾會㑹 里被点「其他」的 14 格多为禽。整字 HOG 一对多，模板＝殿本 vol04–10 放行格（每类 ≤60，曾合愈进库但非组员）＋禽 11 格（sheldon 10-22 已确认），按册留出成员格 150 对／19 弃／0 错（门槛 0.5）。单独成表 `registry.SHAPE_GROUPS`（只进 `FLOW_GROUPS`，不进 `GROUPS`：成员有命舍會 等常用字，进了会改 glyph_match／rare_ref_coord 的全局行为）；`ids_online` 改查 `FLOW_GROUPS`；与 zh 共用「會」（互相声明 overlaps）。需在册配置 group_flow 点名。

### Changed
- 字框收缩 `cell_shrink` 1.18：归属图（`partition_strip`）里跨格界、又不算小部件的连通体，整块归**墨多**的那格（1.17 归伸得深的那格）。vol05 p163 c9「上」断开的底横左段带个钩伸过格界，墨大半在「上」，1.17 却整块分给了「下」（Sheldon 看图指出）。vol05/09 对 1.17 只改这一对格。
- 字框收缩 `cell_shrink` 1.17：整列先算一张归属图，每个墨像素至多归一格（`extractor.partition_strip`）。规则有三条：跨 Step3 折线、或两边都伸过 0.1 格的连通体按格界切开；高不过 0.25 格的小部件整块归离它近的字；其余整块归伸得深的那格。图块只留本格的墨，替掉原先按格界外扩 8% 裁块后的三道逐块清理（`drop_pad_only_components`、`drop_neighbor_parts`、`clip_unions_at_line`，已删）。vol05/09 对 1.16 改 75 格：多为去掉压在格边的邻字碎笔，另有本字越界的笔画补回来（「學」的子钩、「丹」的底横、列末「隱」原先只裁到上半）。
- 字框收缩 `cell_shrink` 1.16：两字粘成一块、跨格界两边都伸过 0.1 格的连通体，按格界切开，各格只留界内的半边（`extractor.clip_unions_at_line`）。原先图块按格界外扩 8% 裁、跨界部件整块保留，两格各带走邻字一截（「家」的竖钩连「之」的点、「左」的底横连「字」的宀）。vol05/09 改 1199/1570 格，多为去掉邻字连过来的笔画，本字越界的笔尖会被切掉几像素。
- 己已巳／日曰／日目 送审收口（`doc/research/己已巳日曰日目-送审收口-2026-10-22.md`）：① 文意 L2 表键容许远处漂移——目标字两侧各 3 字内逐字相同、远处至多差 2 个字位仍用表里的答案（`group_flow_l2_drift`，缺省 2；建表后重跑邻格放行字会变，约 40 格因此整条对不上）；② 共字组联合判——分差内候选单组装不下、装得下「组＋共字组」（日曰目三字紧咬）时也进流程，主组定字后共字组须同意或明说「其他」且 high（`group_flow_joint`，缺省开；目仍是真竞争者，不当陪衬）；③ 己已巳前一字也是族字（干支「己巳」第二字）时不查 L2 表。殿本 vol04–10 抽样 141 页对 dev：新放行 39、复核降审 1，逐格核 0 错；三组送审（不含遮挡）139→101，其中约 20 格靠补跑的 haiku 表，表推中心库后才生效。PATCH；只有 `seed_admit` 的 `code_hash` 变（85052303fa79a800→57ce247a18aaf27c）。
- 己已巳／日曰 第二轮收口（同一文档「第二轮」节）：① L2 表键比对时，本格窗口是「□」而表键有字的位不算差（坐标兜底等组流之后的补放遍会把邻格放进来，按成品建表时有字、组流时是 □；vol09:251「祭統曰春祭曰礿」6 格因此对不上，还漏掉 2 格放错的日）；② L1 规则 `jys-年號己巳`：年號末字＋己（或已／巳）＋◎ → 巳（参考文本 23 处 22 处是巳，另一处是语料讹字）；③ `ctx_l2.add_review`：建表时第二个模型复核，主模型同字只是置信不够、复核模型同字且 high 才收（sheldon 10-22 定；己已巳 104 格人工标注上 0 错），跑批仍只查表。抽样 250 页对 dev：新放行 32、降审 2（都是放错的日），逐格核 0 错；三组送审（不含遮挡）99→69，其中 23 格靠 Sonnet 复核后的 jys 表，表推中心库后才生效。PATCH；只有 `seed_admit` 的 `code_hash` 变（相对合并时的 dev：eeee3347742102a0→bff8f652ceae4de9）。
- 切分与印章三个开关改缺省开，不再逐册设（Sheldon 10-22 定）：`row_segment.layout_prior` 缺省读 `corpus/daizhige/layout_slots.jsonl`，本工作区没有这张表（没有逐列本的书）就当关、不报错；书 yaml 写了别的路径而表不存在照旧报错，写空串＝关。`seed_admit.seal_blank_page`、`lane_seal` 缺省开（殿本十册原本就逐册开着）。殿本 vol01–03 从此也走逐列格位约束：vol02／vol03 p4–40 从原图重跑 Step1–4，逐格全对 329→330、319→330（各 333 列），没有回退列。各册 yaml 里这几行变成多余，留着无害。vol01–03 的 Step3 起参数哈希变，判过期。
- vol07 p44（御製序首叶）抬头框整格被翻成实心黑条，登记 `inverted_rect` 预清理，`precleaned/vol07/44.png` 进仓；原来 Step1 抬头闸量不到第 7 列，「玉」整字丢出列图。配合中心库格位表覆盖（第 1、5、8、9 列出格抬一格，第 6 列从第 1 格起，daizhige 记错），这一页 36/36 列逐格全对。

## [0.5.6] - 2026-10-21

PATCH（sheldon 10-22 定发）。主要内容：印章系统化 1–4 期（新增 Step0 `seal_detect`，切分与遮挡格改读印章定位）、字框收缩 `cell_shrink` 1.10–1.15、字组判法重构成方法数组并新增五个码位归一组、旨㫖整字判法上线、啓啟与教敎模板库重建。相对 v0.5.5，`row_segment`、`cell_shrink`、`seed_admit` 三步 `code_hash` 变，另新增 `seal_detect`，**各书 Step0／Step3 起判过期**；其余 14 步不变。新组（zy sy sz gm xb zhi 及码位归一组 nei bie chu juan wan）要在册配置 `group_flow` 点名才生效；组模板库变了，配套出全局层新底库、各册改钉。rc 上全量测试：3786 过、39 跳过。

### Added
- Step0 印章定位 `seal_detect`（印章系统化第 1 期，用户 10-22 定）：排在 Step1 之前，只读原图，产物 `seals` 列出每页每方印的类别（`stain` 大印＝卷首叶、卷端页的斑驳藏书印；`crisp` 小印＝卷末「乾隆御覽之寶」）、规范空间外框、分数、来源。大印按 150 px 网格的中等墨点密度认（峰值 ≥ 20、近方形，排掉 p2 书签条）；小印用印章模板整页找，分数取「模板笔画处有墨比例 − 空白处有墨比例」，印压正文时也认得出（vol09 p265 原来认不出）。书级 `params.seal_detect.overrides` 可人核整页覆盖。殿本十册 1,707 页认出 26 页（大印 13、小印 13），我逐页看图没发现误报（待 Sheldon 核图定为标准）。这一期只新增产物，别的步还不读它，各书已有产物不过期（新步自己要算一遍）。设计见 Claude Doc「印章系统化设计」。
- 旨㫖（`zhi`）上线整字判法（`groups/ids_online` SPECS、`registry` 配 `config/groups/zhi`）：整字 HOG＋岭回归，模板来自 R2 整册产物对位文字（353 格，sheldon 更正 18 个旨→㫖），按册 5 折留出 margin 0.5 → 348 对／5 弃／0 错。`zhi` 需在册配置 group_flow 点名才生效，重跑归 M8。

### Changed
- 字组判法重构成**方法数组**（sheldon 10-22 定，`groups/methods.py`）：每组在 `FlowSpec.methods` 里登记一串方法，依次试，`combine=first` 遇放行即停、`agree` 全跑须一致；每个方法输出放行字或待定，带 0–1 置信度与留痕。八类：码位归一 `codepoint`（新；配新组 內内 nei、別别 bie、出岀 chu、卷巻 juan、晚晩 wan，单独成表 `CODEPOINT_GROUPS`、不进 `GROUPS`，glyph_match／rare_ref_coord 的全局字组集合不变，要在册配置 `group_flow` 点名才生效）、字频 `freq`、上下文固定匹配 `ctx_rule`、LLM 答案表 `llm`（两者合成子数组 `ctx`）、整字 HOG＋岭回归 `hog`、IDS 部件 `ids`、复合 `composite`（取框→方法，教敎、徵徴）、自定义函数 `custom`（量横、日曰宽高比、入人八分类器、库形最近）。算法与留痕名不变：殿本 vol04 共 65 页、56 组全开，seed_admit 产物与改前逐字节相同；再加五个码位归一组，65 页 9,688 格逐格不变（这批格已被 #372 的码位判等放行）。`seed_admit` 的 `code_hash` 变（`code_deps` 加 `groups.methods`，`flow`／`registry` 改写），其余步不变。
- 字框收缩 `cell_shrink` 1.15：1.13 挪走的跨格界部件，伸进本格超过 0.1 格的不再挪（`NEIGHBOR_PART_DEPTH`）。伸得深的多半是两字粘成一块，整块挪走挖掉了本字的笔画（vol09「兵」「標」「諸」、vol05「荃」「字」「後」，Sheldon 看图指出）。
- 小印压着的字也算遮挡格（印章系统化第 4 期，用户 10-22 定）：`occlusion.page_occluded` 在大印之外，加与小印框重叠 ≥ 0.3 的格，除去盖章空栏候选（格里的墨全在印笔画上）。这些格同大印：Step4 打 `seal_region` 旗，seed_admit 默认整理本字、审核卡归「印章遮挡」组，定字入库闸不建字形库。殿本 10 页小印页：新增 59 格，全在印压字的 vol09 p68／p162／p265、vol10 p87／p175（各 16／5／17／10／10）和 vol07 p134（1 格）；印落在空白处的 4 页不变。PATCH；`cell_shrink` 1.14、`seed_admit` 1.20。
- 字框收缩 `cell_shrink` 1.13：跨格界的连通体若不高于一字、墨至少六成二在格界外、离格外的墨不比格内的远，算邻字越界的笔画，从本格抹掉（`extractor.drop_neighbor_parts`；在上下各多一格的列条里找部件，Step3 选了折线的那条格界不查）。原先跨界的部件两格都留，一格多笔、一格缺笔（「上/下」「宜/賓」「聖/經」）。vol05/09 改 30/34 格，逐张看过，改坏 1 格（vol05 p122 c3「字」丢宀）。
- 切分 `row_segment` 1.34（印章系统化第 3 期）：大印压着列首的列（列首格一半以上在 `seals` 的大印框里）直接取逐列格位表的等距格网（抬头听表、格线就近落缝），不再在几张候选格网里按坏格挑。印泥斑点连着字，劈字、穿字都量不准：闸把列首斑点当抬头字（vol04 p3 c2/c3、vol05 p3 c3、vol10 p88 c1），DP 为躲斑点把格挤歪（vol07 p2 c1、vol09 p70 c1），字整列错一格而格号集合照样对得上。评测 `structcmp` 加「对位」口径（同页同格号的字格高度应一致，偏半格以上记错位），`flipcmp` 一并报，卷端页缺省在内。殿本七册 20 页印章页重跑：大印页错位列 12 → 0，逐格、字数两口径修好 0、改坏 0。PATCH；`row_segment` 的 `code_hash` 变。
- 遮挡格与盖章空栏改读印章定位 `seals`（印章系统化第 2 期之二）：`occlusion.page_occluded`（seed_admit `occluded_gate`、字形库入库闸、Step4 `seal_region` 旗共用的唯一入口）改为「与大印框重叠 ≥ 一半的格」，不再按格算墨点密度；`page_seal_blank` 改用小印框和它的笔画覆盖区（`seal_detect.stroke_mask`），不再在 (830,330) 窗口里找模板。修了两处旧坐标错：旧判据把右上原点的格框直接套在左上原点的原图上，量到的是左右镜像的位置，印正好在页中间才没出事。殿本十页大印页：遮挡格 1,226 → 1,290，新增的非空格 62 个（vol08 p2 印淡，旧判据只认出半方，占 57 格），减少 24 格（印框外的边角）。十页小印页：盖章空栏候选里的非空格减少 9 个（vol09 p162 c4、vol10 p87 c3/c4，都是压在印下的真字「文淵閣著錄」等，旧路径因坐标镜像误入候选），vol07 p134 多 2 个、少 1 个。没有 `seals` 产物的旧产物照旧走原判据。PATCH；`cell_shrink` 1.12、`seed_admit` 1.19，新读 `seals`，`code_hash` 变；`row_segment` 补登记 `seal_detect` 为代码依赖。
- 切分 `row_segment` 1.33（印章系统化第 2 期之一）：列端表空格「落在印里就记空」改读印章定位 `seals` 产物，删掉 `_seal_box`（窗口模板找印）和 `_empty_zone_seal`（表空段墨团）。大印按框量（格与印框重叠 ≥ 一半）；小印按笔画量：格里 ≥ 70% 的墨属于压着印笔画覆盖区的连通块（`_in_seal`），印边只压住一列一小半也认得出。顺带修好旧坐标错：原印框是左上原点、格是右上原点，卷末印正好在页中线附近才一直没出事。殿本七册 20 页印章页 Step3–4 重跑，与 dev 逐列对比：修好 0、改坏 0。PATCH；`row_segment` 的 `code_hash` 变，并新读 `seals`。
- 印章定位 `seal_detect` 1.1：大印外框改按版框定——紧贴版框上边与右边、边长＝版框宽（九列）的正方形（Sheldon 10-22 给的规律），不再用墨点密度区的外接框（偏大）；密度只判有没有大印。这一步因此挪到 `border_detect` 之后（读 `borders`），读不到版框才退回密度框。殿本 13 页大印逐页看图都贴合。小印不变。
- 啓啟（`qik`）整字模板库用 dataset 98 格重建（原 24 格＋R2 整册产物里对位文字与整字判法一致的 74 格）：按册留出门槛 0.5 → 97 对／1 弃／0 错（原 17／7／0）。qik 的 group_flow 指纹变。
- 中心库令牌缺省用读令牌：没设 `GUJI_DATA_TOKEN` 而有 `GUJI_DATA_TOKEN_READ` 时，`import open_guji_cv` 就把前者设成后者（云端 Default 环境只放 `_READ`／`_PROD`／`_EXP`，sheldon 10-21）。拉库、取 R2 字体包／产物包／语言模型不用再手动 export；推送照旧要显式设正式或实验令牌。不碰任何 Step，`code_hash` 不变。
- 字框收缩 `cell_shrink` 1.11：列端框线按全页线位认淡线。同一页各列的框线离版框一样远，先拿全页的实线定线位（`extractor.page_frame_line_offsets`，至少 3 列落在同一处），线位上下 0.04 格高内覆盖 0.1、跨度 0.6、断成至少 3 段的行也算线行——印得淡、断成虚点的框线单看一格认不出（覆盖 0.1–0.6、两头缺点）。压在线位上的字底横是一整笔（列尾「土」「士」），不剥。vol05／vol09 比 1.10 多改 161／248 格，逐格看图改坏 0，格的类型不变。PATCH；`cell_shrink` 版本与 `code_hash` 变，各书 Step4 起判过期。
- 字框收缩 `cell_shrink` 1.10：贴着版框的列尾格、列首格，把格里横贯内容窗口的版框细线（双边框的内框，印得细、常断成虚线）连同线外抹白（`extractor.strip_frame_line`）。原来 `strip_frame_debris`、`carve_end_edge` 剥不掉，殿本列尾字约一成带着一道横线进字块。线只在离格外沿 0.4 格高内找；线外还有成片墨的（「其」「兵」底横下的两点）是字自己的横，跳过；列首格要求线和字之间隔着白行；夹注格不剥。vol05／vol09 改 145／229 格，逐格看图改坏 0，格的类型不变。PATCH；`cell_shrink` 版本与 `code_hash` 变，各书 Step4 起判过期。
- 书级 `codepoints:` 并进 seed_admit 的语义判等（`codepoint_semantic`，缺省开；关掉回旧行为）：巻→卷、别→別、岀→出、晩→晚、內→内 在 `context_vs_ref`、`replace_align`、`match_replace` 等一切「语义同字」比较里按同一个字算，放行字最后落册指定码位；`group_flow` 文意 L2 表的键按码位归一再比（否则邻格新放行会让组内格误降）。起因：此前 `vmap` 不认这些码位对，整理本排异体、刻本与文意都对的格全被 `context_vs_ref` 拦下（殿本 vol04–10 送审里这类 217 格：卷巻 178、別别 33、出岀 4、晚晩 2）。没配 `codepoints` 的册产物不变；参数指纹不变（缺省值不进 dump）。PATCH；`seed_admit` 的 `code_hash` 变（合入 dev 时 5335145caae3→a4f8dc68effc），别的 Step 不变。抽样重跑这类格所在 140 页：新放行 216，降级 0，仍送审 1（被遮挡）。

## [0.5.5] - 2026-10-21

PATCH（Sheldon 10-21 定发）。glyph_match 的 `batch_knn`、`font_tier` 改为缺省开（vol06：glyph_match 959 s → 349 s，送审 142 → 143，两边都放行而字不同的 0 格）。相对 v0.5.4，8 步 `code_hash` 变：`border_detect`、`border_detect_gate`、`column_warp`、`column_gate`、`row_segment`、`cell_shrink`、`glyph_match`、`seed_admit`，**各书 Step1 起全部判过期**；其余 9 步不变。rc 上全量测试：3755 过、9 跳过；修了 8 条随 #366 进来、在有 CNN checkpoint 的机器上失败的测试（#370，只改测试）。

### Changed
- **glyph_match 两个提速开关改为缺省开**（用户 10-21 定，PATCH）：`batch_knn`（整页合批算近邻）与 `font_tier`（分级查库：先查刻本库，命中弱再查整库）。两个都开时两档都合批：刻本库那档每格都查，整库那档按 64 格一块惰性算，块里有命中弱的格才算，两档共用一份查询特征。显式写 `false` 关回去，关时不进参数 dump，参数指纹与 v0.5.4 的缺省相同。**会改产物**：glyph_match 参数指纹与 `code_hash`（4b3ff0e181cdc99d → a0b27c7c2fdaae05，其余 16 步不变）都变，各书 Step5-a 起判过期，下一次重跑整册重算。单开时的证据见 `doc/开关登记表.md`（batch_knn：vol06 1282 s → 367 s、送审 222 → 222；font_tier：粗校基准新增错放 0、送审 413 → 414）；两个同开（vol06 150 页，同一份上游，4 核云端，特征缓存热）：glyph_match 959 s → 349 s，从 glyph_match 到 seed_admit 1048 s → 431 s；`guji products diff` 送审 142 → 143（人审率 0.60% → 0.61%），放行转送审 2 格、送审转放行 1 格，**两边都放行而字不同的 0 格**。另修：库是空的（新书刻本库还没有字）时合批的矩阵乘出错、整页失败，改为逐格判。
- 切分 `row_segment` 1.32：印框的第二个来源——相邻列的表空段（表首字之上、末字之下，整列空的列就是整列）在同一高度都有像字的墨，就把这一团墨的外接框当印框（`_empty_zone_seal`），列端表空格落在里面的记空。补上模板认不出的空心印和模板框没盖住的印边。`_in_seal` 改收印框列表。PATCH；`row_segment` 的 `code_hash` 变。殿本修好 vol09 p68 c5/c6、p265 c4/c5/c6，vol05 p188 c7（另 p3 三列），vol09／05／06 全册改坏 0。
- 格位表 `scripts/dzg_layout.py`：读同目录 `layout_overrides.jsonl`（看原图核过的列，写要改的 slots/notes/half/raised 加 `why`），盖在 daizhige 推出的行上，重生成不丢；评测 `research/dzg_struct_prior/structcmp.py` 的参照同样按它改。首批 4 列（殿本 vol04 p11 c1/c4/c5、p79 c7：daizhige 起始格错一格、漏抬头、把「○」当空格）。代码不动，表变 → 用到这几页的 `row_segment` 产物过期。vol04 第 4 页起错列 3 → 1（另 2 列原来就切对了，错在参照）。
- 闸2 `column_gate` 1.12：页级周期估值偏离书级 `period_prior` 超过 `period_prior_tol`（缺省 10%，0 = 关）时回落先验，记 flag `period_fallback`。殿本正文页估值都在先验 ±5% 内；卷末大印、整页空白的页会被带偏（vol04 p127/128/220 估 89–95，vol05 p188 102，vol09 p69/162/163/224/225 79–127，先验 114–115），Step3 拿错的格高切，抬头格数、格网整列错位。修好 vol04 p127 c3（整列格线错半格）、vol09 p162 c3，表上改坏 0；其余页估值没偏，产物不变。没配 `period_prior` 的书不受影响。PATCH；`column_gate` 的 `code_hash` 与参数指纹变，各书 Step2 闸起判过期。
- 切分 `row_segment` 1.31：列端表空格记空（`_blank_frame_junk`）不再只看字格和單行小注格，被切成雙行小注半格（jiazhu_a/b）的印章墨也记空。PATCH；`row_segment` 的 `code_hash` 变。殿本修好 vol10 p175 c5、vol09 p265 c7，vol09、vol10 全册改坏 0（vol10 第 4 页起已无错列）。
- 切分 `row_segment` 1.30：格位表说只有一半有字（`half`）、判据又认成單行小注的格，按夹注半格发 `jiazhu_a`／`jiazhu_b`（缝取小注左缘，只发墨多的一半），不再发 `jiazhu_solo`。管列里没有雙行段时小写靠右的「臣」之类（1.26 只管列里有雙行段的）。`row_boundaries.segment_column` 的 `half_notes` 参数行为扩大，不传仍不变。PATCH；`row_segment` 与 `column_gate` 的 `code_hash` 变。殿本修好 vol04 p110 c1、vol07 p29 c9，两册全册改坏 0。
- 切分 `row_segment` 1.29：列端表空格里墨只是一两道竖线的格记空（有墨的像素列不到内容宽的 20%，`VLINE_COLS`；印框的边、界行残段）。PATCH；`row_segment` 的 `code_hash` 变。殿本 vol04／05 修好 vol04 p127 c7，改坏 0。
- 教敎（`groups/ids_online`，`jiao`）改用整字左上角一块（左 0–55%、上 0–46%）做 HOG＋岭回归：按册 5 折留出 93 格，门槛 0.4 → 87 对／6 弃／0 错（此前整字／U-Net／自动缝给字格 0 错覆盖 ≤8%）。`config/groups/jiao/ids_bank.json` 用 dataset 93 格重建（教 68／敎 25，含 vol01 四格教→敎更正）。jiao 的 group_flow 指纹变，seed_admit code_hash 变。记录见 `doc/research/形近字组实验记录.md`。

### Added
- `glyph_match.font_tier`（缺省关，GUJI-726）：分级查库，每格先只查刻本库；命中弱才查含字体域的整库，那一格与关着时相同。命中强＝判 same 或「unsure、首选 cov ≥ 0.98、比次优异字高 ≥ 0.03」，且首选字不是字组成员、没有形近对手。vol06 glyph_match 770 s → 606 s、vol05 1022 s → 770 s；粗校基准新增错放 0、送审 413 → 414。会改产物，开不开由 M9 定；关时产物与参数指纹不变（代码等价登记）。
- `guji cellvotes draft|write`（`feedback/web_votes.py`、`cli_cellvotes.py`）：网站精校页投票直接转人裁事件草稿。取票（数据目录快照／`--from-kv` 管理读／文件）→ 去测试票、同格同来源留最新 → 六档映射（与 ai-team `web_opinions.py` 同口径）→ 对正式库最新人裁（一致的跳过、要推翻的挂起）→ 对格位（现行 `cell_shrink` 对出单版 book-text `cord.json`，列被重切过的挂起）→ 「无字」缺省挂起；`write` 走控制台同一条写入路径（带锚、消费、按草稿内容判重）。殿本 vol04 004-r3 的 31 票回放：可写 19、格位对不上 6、无字 6，与 10-21 手工核对一致。不动 Step 模块，各书产物不过期。

### Fixed
- `guji pipeline` 每步一个子进程（`--isolate-steps`，多步时缺省）跑完后，父进程读 manifest 数失败页，有失败页就不自动存包、在 stderr 列出来（原来子进程里有页失败照样返回 0，父进程当全过：10-21 基线重跑 vol08 seed_admit 69 页全失败仍自动存了包）。返回码与单进程连跑一致（不加 `--stop-on-error` 仍是 0）。不动 Step 模块。

## [0.5.4] - 2026-10-20

PATCH（Sheldon 10-21 定发，vol04–10 基线重跑用）。`border_detect`（1.3）、`row_segment`（1.26、1.27）、`column_gate` 与形近字组 `group_flow` 的 `code_hash` 变，**各书 Step1 起全部判过期**。#345 改了 `config/groups/{jue,lih,qik,xu}/ids_bank.json`、新增 `xu/unet.npz`，配套语料库出全局层 b4，殿本 vol04–10 钉子账升 n=12、册 yaml 改钉 `corpus: 12`（v0.5.4 配 `corpus: 11` 会 CorpusDrift 拒跑）。
验收（rc 上）：全量测试 3709 过、14 跳过；修了 1 条随 #345 过时的测试（`test_repo_by_form_banks_load`：整字组不再要求 `by_form`）。

### Changed
- 边框探测 `border_detect` 1.4：抬头框加字凸出判据（`border_geometry._raised_text_top`，`detect_head_raise(text_rule=True)` 缺省开）。有的抬头框只印了粗外框、没有内细线，有的连顶线都没有，横线判据找不到，抬头字落在列图外。现在前面都没认下的列，主上边框上方 [btop−130, btop−45] 一段先去掉整段有墨的竖条（墙线），再按行看：像字的行（墨占比 0.1~0.6）占四成以上，并且至少一侧界行外 70px 内有墙线（覆盖 ≥ 0.5），就算抬头，inner_y 取抬头字上沿往上 8px。墙线这一道挡「上諭」那种字紧贴笔直版框的页。殿本 vol04／06／07 全部 506 页，只有预期的 6 列变（vol04 p65 c8、p84 c5、p11 c5，vol06 p58 c6，vol07 p46 c7、p77 c2）。Step1–4 重跑修好 4 列（vol04 p65 c8、p84 c5，vol06 p58 c6，vol07 p77 c2），改坏 0。PATCH；`border_detect` 的 `code_hash` 变，各书 Step1 起判过期。
- 切分 `row_segment` 1.28：印框记空挪进候选格网打分之前，跟框线碎墨一起「先记空再打分」（`_blank_frame_junk` 加 `in_seal` 判据；原来选完格网才记空的 `_blank_seal_cells` 删掉）。印框里列端表空格是單行小注格的也记空。印框查找抽成 `occlusion.find_seal_box`（`seal_blank_cells` 照用，输出不变）。PATCH；`row_segment` 与 `seed_admit`（`code_deps` 含 `occlusion`）的 `code_hash` 变。殿本 vol04／05／09 对旧产物修好 13 列、改坏 0（vol04 p130 页首噪点 5 列、p35、p191、p3 五列，vol09 p68 c7；对比基线里有些页不是最新代码出的，修好数偏高）。
- 形近字 IDS 路按组换法（`groups/ids_online`、`ids_unet`）：叙敘 用左右向 U-Net 一条折线切线（`config/groups/xu/unet.npz`，留出册覆盖 33%→87%）；絕絶、厯歴、啓啟 改整字岭回归；冊册 踢出 IDS 路（SPECS 删 `ce`）；教敎 不变。实验记录见 `doc/research/形近字组实验记录.md`。xu/jue/lih/qik 的 group_flow 指纹变。

### Fixed
- `glyphdb_admit` 取图前查绑定（规范 §9 F-10）：补消费积压时重切后格号顺移的按现格取字块，绑定判不该采信的不进库（计 `unbound`）。实时消费不受影响；不在任何 Step 的 `code_deps` 里，各书产物不过期。

### Added
- 字形库按版本钉（GUJI-727，设计 `doc/design/字形库按版本钉-细设计.md`）：`guji glyph-db snapshot` 出只读快照 g<N>（清单随 `config/` 进中心库、一个号只写一次，文本随 push 按 sha 进 R2），册 yaml `glyph_pin: N` 有快照时本册读字形库的步改用 `output/glyph-g<N>.db`、字形库指纹换成快照内容哈希；`pin-build`／`pin-list`／`pin-verify`／`snapshot-upload`，`db pull/sync` 与 `pipeline` 起跑前自动建库。没钉的册、钉了号没快照的册行为与指纹逐位不变；**17 步 `code_hash` 全部不变**。
- `scripts/zhengli/republish.py from-pack`：取别人跑好的产物包直接重发待审单，不重跑任何 Step——拉库、取包、按锚框核人裁绑定（包后新到的、按格号扣会扣错的、绑不上的都列进差异单「人裁合并」）、导出（文本版本读 book-text 线上值，单子头记包的 cv 版本）、prep，vol05 实测一条命令 4 分钟。`push --book-text` 顺带把同一次导出拷进 book-text、文本线升 minor、本地校验后提交到新分支；收尾提示请网站总管按顺序手动跑文本与待审单两段发布（每日定时里待审单比文本早 20 分钟）。不在任何 `code_deps` 里，各书产物不过期。
  - 后续修两处（vol04–10 实跑发现）：from-pack 自己设 `GUJI_WORKSPACE`（之前没设时人裁绑定读到 0 条）；原格号上有人裁、但人裁绑到别处或绑不上的格不再被 `pending_route` 按格号扣掉（新参数 `--keep`），照旧留在单上。
- `feedback/migrate_dedupe.py`：删整轮重发的人裁事件副本（规范 §9 M-3，原 O-8），记账、补锚档、金标 `source_events` 跟着改，带核对与 `gold rebuild` 比对；10-21 已写中心库（殿本 3,638 条、北行 76 条）。不动 Step 模块，各书产物不过期。

### Changed
- `guji pipeline` 整册（`--pages all`）从头跑到尾、没有失败页时，**缺省自动把产物打包存进 R2**（`products pack push`，标签 `<版本三段>-full`，不标 main；sheldon 10-21：免得忘）。`--no-pack` 或 `GUJI_AUTO_PACK=0` 关；没设 `GUJI_DATA_TOKEN`、存失败只提醒，不改返回码。不碰任何 Step，`code_hash` 不变。
- 边框探测 `border_detect` 1.3：抬头框向邻列延伸（`utils.border_geometry._extend_head_raise`，`detect_head_raise(extend=True)` 缺省开）。已认下的抬头列，邻列在同一高度（±18px）有淡一些的细锐线（墨占比 ≥ 0.12，够不上原来的 0.35）、线下有抬头字的墨（≥ 一半行）就并进同一个抬头块，再照旧过墙线判据。管内边框印得淡、被抬头字压着的列：原来这一列按普通列取窗，抬头字整个落在列图外。PATCH；`border_detect` 的 `code_hash` 变，**各书 Step1 起全部判过期**（Sheldon 10-21：过期不是顾虑），只有抬头框变了的页输出变。殿本 vol04／07／09 全部 621 页里 4 页的抬头框变了，Step1–4 重跑修好 4 列（vol04 p9 c8、vol07 p44 c8、vol09 p109 c5/c6），改坏 0（vol09 p106 c7 并进抬头块，切分不变）。
- 切分 `row_segment` 1.27：印框记空门槛 NCC 0.35 → 0.30（非印页实测最高 0.282；这里只动表说该空的列端格）。vol10 p175 修好 2 列；vol10、vol07 全册改坏 0。
- 切分 `row_segment` 1.26：`layout_prior` 加两处。格位表说只有一半有字的夹注格（`half`，如「無巡卷撫數採進」里的行内空格、段尾奇数字），列里有雙行段时按段缝（各段格缝的中位数）拆、只发墨多的那一半（`row_boundaries.segment_column` 新参数 `half_notes`，缺省 None 不变）。PATCH；`row_segment` 与 `column_gate`（`code_deps` 含 `utils.row_boundaries`，闸不传这个参数、输出不变）的 `code_hash` 变。殿本对 1.25：vol06 第 9/32/37/63 页、vol08 p46 修好 5 列，vol05 全册修好 3 列、改坏 0，vol09 全册不变。
  - 印框记空：模板（`config/seal_templates/`，「乾隆御覽之寶」）命中的印框里、表说该空的列端格记空（`steps.occlusion.seal_blank_cells`，NCC ≥ 0.35、重叠 ≥ 一半；进 `code_deps`）。管篆文刻得清楚、墨连成笔画的大印，碎墨判据认不出这种。vol05 p188、vol06 p149、vol09 p162、vol10 p87 修好 9 列；vol05、vol10 全册改坏 0。
- 跑批、冷启动再提速（GUJI-647 后续，PATCH；**17 步 `code_hash` 全部不变、产物逐字节不变**，改的都是引擎、登记表与不在任何 `code_deps` 里的模块）：
  - 页级并行新登记 6 步（`core/parallel.py`）：`column_warp`、`border_detect_gate`、`column_gate`、`row_segment_gate`、`align_ref`、`context_decide`（后两步 `warm_first`）。vol06 150 页串行／4 进程：8 步产物逐页 sha 相同，`column_raw`／`column_image` 各 1332 张列图逐张相同。`context_decide` 开了 `enable_online_llm` 时退回串行（新字段 `ParallelAudit.serial_when`）。
  - 跑一步期间每步参数只构造一次（`Engine._run_one_step` 与 `RunContext._params_memo`，并行 worker 每进程一次）：参数构造时要对 glyph.db 算人裁、库指纹，原来逐页在指纹、落盘、run_page 里各算一遍，vol06 seed_admit 主进程 600 多次。seed_admit 整册 185 s → 79 s，150 页产物与 manifest（指纹、参数哈希、上游）逐项相同。
  - `glyph-db rebuild` 补放人裁：遮挡查询（`feedback.consumers._occluded_lookup`）在一次 `glyphdb_admit` 里按册只解析一次 seed_admit 参数（原来逐页解析，补放 1180 条人裁、711 页占 95%）：补放 139 s → 25 s（剖析下），14 张表、补放报告、消费记账逐项相同。
  - `fold_compat`（`utils/cjk_compat`）只换正则扫到的兼容区段字符：整部语料有一个兼容字时原来逐字进 Python，align_ref 起跑折语料 4.5 s → 0.05 s，2 万条随机串与两部整理本逐字相同。
  - `guji db pull`：重建 glyph.db 的派生表示按 CPU 数多进程（同 `glyph-db rebuild`，原来单进程）；取图（R2）与向库要文本行同时跑；读令牌先问 `whoami`，不再白打一个注定存不上的快照包（约 9 s）。
  - 冷启动端到端第二轮（vol06 150 页，空数据目录、空图缓存、空缓存、空产物，4 核云端）：`db pull` 211 s（上轮图缓存是热的）→ 166 s（图全冷），`glyph-db rebuild` 133 s → 55 s，Step0–7 2028 s → 1878 s（seed_admit 185 → 99、column_warp 62 → 21、三道闸合计 62 → 35），close-check 35 s；合计约 41 分 → 36 分。

## [0.5.3] - 2026-10-20

PATCH（Sheldon 10-21 定发）。`row_segment`（1.23 → 1.25，新增 `code_deps` `utils.row_grid`）与 `column_gate`（`code_deps` 含 `utils.row_boundaries`，只加了缺省不走的格网入口，闸的输出不变）的 `code_hash` 变，各册 column_gate 与 Step3 起判过期；只有开了 `layout_prior`、命中格位表的页（殿本 vol04–10）输出变，别的书逐字节不变。

### Changed
- 切分 `row_segment` 1.25：`layout_prior` 列端表空格里的墨大多连不成笔画（落在面积 > 150 像素连通块里的不到 75%：印章的印泥斑点、篆文残笔）也记空。PATCH；`row_segment` 的 `code_hash` 变，各册 Step3 起判过期。殿本 vol04–10 全部页 10,620 列对 1.24 逐格 99.03% → 99.51%，修好 51 列、改坏 0（第 4 页起 99.33% → 99.55%，修好 23）；修的是各册首叶（p2/p3 藏书印）和卷端大印（vol04 p130、vol09 p70/p164、vol10 p88）。
- 切分 `row_segment` 1.24：逐列格位约束 `layout_prior` 加三处（只作用于命中格位表的页；开关关着、或没有表的书逐字节不变）。PATCH；`row_segment` 的 `code_hash` 变（新增 `code_deps` `utils.row_grid`，`utils.row_boundaries` 加了不跑 DP 的格网入口），各册 Step3 起判过期。殿本 vol04–10（第 4 页起 10,521 列）对 1.23 逐格 99.03% → 99.33%，修好 32 列、改坏 0；穿字格线七册合计 6061 → 5941。
  - 等距格网（`utils/row_grid`，用户 10-21：殿本正文每列严格 21 格、格高相近）作候选格网：格号按行墨投影的周期相位排，格线在 ±0.2 格内就近落缝。修列首印章、墨损处 DP 多切一格、整列格号错位（vol04 p6 c2、p8 c2/c4/c8，vol06 p33 c4）。
  - 各候选格网先把列端表空格里不像字的墨记空，再打分。
  - 不像字加「越过界行」（印章、墨污：墨伸到列的左右边上）；一页最后一列表行之后的列按整列空处理（卷末印章空列）。

## [0.5.2] - 2026-10-21

PATCH（sheldon 10-21 定发）。相对 v0.5.1 只有 `seed_admit` 的 `code_hash` 变（c1cc30263b355ed5 → e3566f98f5046f0d），其余 16 步不变。配套语料库（分层版本 P3 起）：全局层 b3（含 #332 的彝组模板库与 U-Net 权重）＋殿本书库 v10，十册钉子账 n=11、册 yaml 改钉 `corpus: 11`，`group_flow` 点名 `lv`、`zheng`（中心库 corpus-base rev 34273、siku-zongmu rev 34313）。**v0.5.1 配 `corpus: 9` 会因 `yi_560/ids_bank.json` 与 v9 清单不符被起跑校验拒跑**，各册重跑请用 v0.5.2。
验收（rc 上）：殿本 vol05–07 共 141 页 seed_admit，对 v0.5.1＋语料库 v9，送审 205 → 205、逐格无变化；全量测试 3695 过、38 跳过，1 失败 1 错误在 dev 上同样存在（`test_pagetype_model::test_model_roundtrip_and_gate_abstain`、`test_datastore_expbranch` 缺 PG）。

### Changed
- 彝组 `yi_560` 改走 U-Net 切三段（#332，`groups/ids_unet.py`，纯 numpy 推理，权重 `config/groups/yi_560/unet.npz` 1.0 MB；窗口法退为后备），模板库按 U-Net 切分重建。按册留出（超参也只在训练册选）82 格：79 对／2 弃权／1 错，窗口法同口径错 5。`seed_admit` 的 `code_hash` 变（38f5371fe3279014）。

### Fixed
- 中心库不再收人裁写锁 `*.write.lock`（空文件，曾被推进殿本、北行的 `files` 表，10-21 已从库里删掉）。

### Added
- 粗校基准（M9 D6-5，GUJI-669）：`open_guji_cv/exp/rough_bench.py`、`scripts/rough_bench.py build`（冻结页＋标签进测试集仓 `rough-bench/`）、`scripts/eval_rough_bench.py`（登记为 `guji eval run rough_bench`）。在各册 main 快照上用 `guji exp` 重跑 seed_admit（或从 `--from` 起），报正文送审率和有标签格的错放；有变体时**新增错放必须为 0**。人裁按绑定表对到快照切分，看图结论只收现行字＝当时显示字的格。不碰任何 Step，`code_hash` 不变。
- `scripts/zhengli/wave_report.py`（M9 D6-6，GUJI-670）：一波各册待审格按主成因码汇总，出成因分布、派单（按交给谁，列最常见的字对／字组码）、与上一波比的增减、粗校基准结果、下一波目标（`wave.json` + `wave.md`，贴 Jira）。只读产物。

### Changed
- 人裁事件规范 §9 F-6／F-7／F-8（原 O-1／O-6／O-7）：`guji db sync` 合并同批次撞号时本地新行顺延重编、本地记账等引用跟着改；`guji db import` 导完自动对导入的事件 route（`--no-route` 关）；`guji events lint` 新增 `W-unconsumed`；刻例库升格记账改写到 `feedback/promote.jsonl`，`migrate_v1` 能把旧的挪过去。不动任何 Step 的 code_hash。
- `guji exp`：`pages` 可以按册给（`{vol05: [3, 9], …}`）；`human_events` 标签读 `feedback/events/` 下全部文件、按 `target.book` 筛（原来只读 `<册>-*.jsonl`，H 道 `H-M7-…` 这类批名的人裁全漏了，vol04–10 只认出 1 条）；金标标签认 `expected.wrong`（只知道不是哪些字）。

## [0.5.1] - 2026-10-21

PATCH（sheldon 10-21 定发）。相对 v0.5.0，17 步 `code_hash` 全部不变（rc 上与 v0.5.0 逐步比对）。

### Added
- 语料库分层版本（#317，PATCH；**缺省不影响现有册**：没有钉子账的册，`corpus: N` 与指纹 `corpus-vN` 逐位不变，17 步 `code_hash` 不变）：语料库分全局（底库 b）／整套书（书库 v）／册 三层各一个整数版本；`guji corpus pin [--dev]`、`release`、`build/verify --vol`、`upload/fetch`；册有钉子账后指纹取清单内容哈希、不含版本号；册 yaml `corpus_dev: true` 开发中跳过清单校验（带它的册配置不许 `db push`）；≥1MB 的文本文件清单标 `store: r2`，内容按哈希存 R2。提示词模板占位符渲染 `groups/prompt_template.py`（不动 `ctx_l2`）。设计与 P3 迁移步骤见 `doc/design/语料库分层版本.md`。
- glyph_match 开关 `batch_knn`（GUJI-647 第 7 项，PATCH；**缺省关**，关着时产物与参数指纹逐字节不变）：一页的格每 64 个做一次「查询 × 整库」矩阵乘，库矩阵每 64 格才读一遍。库含字体域（17.4 万条、1.2 GB）时逐格算卡在内存带宽，vol06 全册 glyph_match 1282 s → 367 s。**会改产物**：浮点末位不同，vol06 23,517 格判决、字、cov 全同，8 格候选排序变；`guji products diff` 送审 222 → 222、变了的列 0。开不开按 M9 波次窗口定：书级 `params: {glyph_match: {batch_knn: true}}`。
- `guji audit changes <册> --base <上一基线产物根>`（M9 D5，GUJI-664）：列出新放行、放行字变了的格（`放行变化.md／json`）；zl.py 设 `ZL_BASE_PRODUCTS` 后这些格进联系页，看图闸要每格都有结论才过。联系页另存单格图与 `tiles.json`。
- `scripts/zhengli/vision_ask.py`（GUJI-665）：联系页每格交外部视觉模型看，`merge` 两家一致才算、不一致记看不清，`score` 对参照计分。智谱免费模型在 vol06 上误判太多（负结果，见 `doc/research/M9-粗校调研/E-…`），不默认接入。
- `guji audit reasons <册>`（M9 D6，GUJI-668）：每个待审格打一个主成因码（`review/causes.py`：A1–A9 切分／对位、B 码位异体、C 形近字组、D 遮挡、E 与整理本冲突、F 库缺字、G 对齐改字、H 库＝整理本仍被拦、I 证据不足），出 `reasons.json`／`reasons.md`（按码写交给谁）。`republish.py` 把码并进待审单的 `cause`、台账记 `reasons.cause`；`cls` 不动。vol06 175 格里「证据不足」8%。只读产物，不碰任何 Step。

### Changed
- 冷启动、内存、出口检查提速（GUJI-647，PATCH；**17 步 `code_hash` 全部不变**：`glyph_match`、`match`、`seeding` 的改动在 vol06 30 页、库含字体域时与改前逐字节相同，已登记代码等价）：
  - 字体域预建件（`clustering/font_pack.py`）：`glyph-db import-font` 先找同一套字体文件、字表、渲染代码出过的字体域（本机 `cache/fontdb/` 或 R2 `derived/fontdb/`，读令牌就够），整表拷进 glyph.db，与逐字渲染逐列相同、字体域指纹相同。两套 15.5 万字：渲染 12.6 分钟 → 拷表 43 秒（加下载约 1.8 GB）。从 R2 取来的包导完即删。推送手动：`glyph-db font-pack-push`（正式令牌）。`--no-pack` 强制渲染。
  - R2 通道（`datastore.packs.push_file`／`fetch_file`）改流式、可选 gzip，取时 8 段并发（实测单路 11 MB/s、8 路 44 MB/s）；旧 manifest 照认。
  - glyph_match 匹配器特征按内容缓存（`seeding._matcher_arrays`，`cache/glyph_feats/`）：字体域进库后库有 17.4 万条，每个进程建匹配器原要约 2 分钟（逐条解 PNG、算 HOG），命中缓存 2.4 秒；整库特征矩阵只存一份（原来列表一份、堆起来又一份），建库峰值 4.5 GB → 2.1 GB，命中时走 mmap、多进程共享页缓存。`GUJI_MATCHER_FEAT_CACHE=0` 关。
  - glyph_match 登记 `warm_first`：主进程建一次匹配器，fork 后共享。改前 dev 上库含字体域时 `--jobs 4` 四个 worker 各建一份（各约 3.5 GB），被 OOM 杀。
  - `guji pipeline` 跑多步时缺省每步一个子进程（`--isolate-steps`；`--no-isolate-steps` 退回单进程，`--json` 时不隔离）：vol06 单进程连跑到 seed_admit 主进程 3.5 GB，隔离后 seed_admit 1.95 GB、context_decide 1.48 GB。
  - 页级并行的内存登记：glyph_match 3.6 → 1.5 GB（warm_first 与特征缓存之后 worker 不再自建匹配器；vol06 冷启动主进程峰值 2.2 GB、主进程加 4 个 worker 合计 PSS 2.6 GB；按 3.6 算 13 GB 的容器只开得出 2 个进程），seed_admit 3.0 → 2.0 GB（实测主进程 1.95 GB、4 进程合计 PSS 3.3 GB）。
  - `glyph-db rebuild` 派生表示（归一、骨架、HOG）多进程算（`--jobs`，缺省 CPU 数），主进程按原顺序写库，14 张表与单进程逐行相同：殿本 1.85 万例 163 s → 38 s，整条命令连补放人裁 265 s → 133 s。`import-font` 的 `--jobs` 缺省仍是 1。
  - `close-check` 1a／`guji status`：一次 `status()` 里每步的参数只构造一次（构造时要对 glyph.db 算库指纹，库含字体域时 3 GB；原来逐页逐步现算）。vol06 close-check 粗校档 126 s → 31.5 s，各项结论逐行相同。
  - `guji cache verify`／`close-check` 1b：戳与现行产物对得上的页免查（引擎重跑一页先清再写、读时戳不对整页作废，这类缓存一定是这一代切的）。vol06 150 页 1.4 秒（原约 5 分钟）；`--full` 照旧全查。

### Fixed
- **seed_admit 并行时影子模型极慢（#255 引入，0.4.9、0.5.0 受影响）**：开了 `shadow_veto` 的册（vol05、vol09 等），影子模型（scikit-learn HistGradientBoosting）predict 用 sklearn 自带的 OpenMP，主进程暖机时按核数建好线程池，fork 出的 4 个 worker 各开 4 线程、16 线程抢 4 核，每页从几秒拖到约 700 s（vol09 实测）。worker 里用 threadpoolctl 把已加载的 OpenMP 运行库压到每 worker 线程数；vol09 20 页 4 进程 63 s、串行 102 s，产物逐页相同。产物从来不受影响，只是慢。
- 缓存页戳会把老缓存「洗白」（GUJI-647）：一页没戳、目录里却有记戳机制之前的老图时，惰性补一张新图（或 `cache warm` 收尾补戳）会给整页记上戳，`cache verify` 从此跳过它。现在这类页不记戳，留给内容校验。
- `--isolate-steps` 下某一步崩了（异常、护栏拒跑）父进程照样接着跑下游、最后返回 0；现在停在那一步、返回它的返回码。控制台取消工单（只 terminate 父进程）时把 SIGTERM 转给正在跑的那一步，不留孤儿接着写产物。

## [0.5.0] - 2026-10-20

MINOR（sheldon 10-20 定发 v0.5.0）。相对 v0.4.9 只有 `row_segment`（d5f4ceedcfbd2d06 → 89ea9a967e3dd407）、`cell_shrink`（17162d9e3ed6047f → f9206af1e771f0e5）、`seed_admit`（3337e7b0b2dc43ec → c1cc30263b355ed5）的 `code_hash` 变，其余 14 步不变；各册 Step3 起判过期。rc 上全量测试 3632 过、32 跳过，2 条失败在 v0.4.9 上同样失败（`test_cut_select::test_ckpt_fingerprint_empty_for_missing_file` 缺检查点，`test_datastore_workcopy::test_corpus_adopt_push_and_pull`）。

### Added
- 人裁事件规范 v1（#300，GUJI 人裁事件格式调研）：`doc/formats/人裁事件规范.md` 与 `formats/guji_feedback_event_v1.schema.json`；`guji events lint -w <工作区>` 按规范只读体检。全部「后到覆盖」统一按 `replay_key=(ts, batch, seq)`（`gold rebuild`、`route_and_consume`、`EventLog.resolve/pending`、`label_batches`、`vision` 重建、复核冲突、事件列表此前按批次名序，殿本 351 个单位、北行 11 个两种顺序取到的最终裁决不同，下次 `gold rebuild` 会按时间序改正）；`EventTarget` 从 key 补全空的 `book/page/col/slot`；`resolve(kinds=, unit=)`；控制台写入把秒级 `client_ts` 归一毫秒。PATCH；不在任何 Step 的 `code_deps` 里，17 步 `code_hash` 不变。
- 人裁事件历史遗留迁成现行格式（#321）：`python -m open_guji_cv.feedback.migrate_v1 --ws <工作区> [--apply]`（撞号／错文件、旧 id、空 target 字段、秒级 client_ts、`product_key` 两种形状；连带改 consumed、金标 `source_events`、补锚档；核对重放顺序与 `gold rebuild` 不变）；`datastore.importer.import_scans(only_paths=)` 只差分点名的文件。锚里切分产物的 sha 改写进 `anchor.cells_sha`，`product_key` 只留 `{step, key, fingerprint}`；lint 新增 `E-key-empty`、`E-product-key`，`E-id-shape`／`E-batch-file`／`E-client-ts-sec` 升为错误。中心库 10-21 已迁（殿本 import 118、北行 import 119）。PATCH；17 步 `code_hash` 不变。
- `scripts/check_release_tags.py`：发版后核对每个发进 main 的版本都有 `vX.Y.Z` tag、且 tag 在 main 主线的发版合并提交上（用户 10-20 定「打了 tag 才算发完」，写进 `doc/版本号规矩.md` 第三节第 5、9、10 条）。PATCH；不碰任何 Step，`code_hash` 不变。
- 字组：呂吕、徵徴 走在线 IDS 的「整字岭回归」判法（`groups/ids_whole.py`，`ids_online.IdsSpec.whole`；组 id lv、zheng）。按字分类（`by_form`）切缝比不了这两对（呂吕 差在中间连笔，徵徴 差在字中上部细节），改整字裁外框归一后二类岭回归（呂吕 取像素，徵徴 取字块中上部 HOG），判别值不够弃权。模板＝殿本 vol01–10 人裁事件格，建库与按册留一评测 `research/m7/lane1/build_whole_bank.py`。按册留一：徵徴 |d|≥0.6 → 38 对／37 弃权／0 错；呂吕 |d|≥0.5 → 62 对／8 弃权／0 错（vol07:4:4:21 按 sheldon 复看更正为呂）。PATCH；只有 seed_admit 的 `code_hash` 变（d277e5d75f708d82 → d8e0c8279a4419c2）。要在册配置 `group_flow` 点名才生效，字频表／册配置由收口线程改。

### Changed
- 切分 `row_segment` 1.23、`cell_shrink` 1.9：逐列格位约束 `layout_prior` 三处结构化改动（只作用于命中格位表的列；开关关着、或没有表的书逐字节不变）。PATCH；只有 row_segment（d5f4ceedcfbd2d06 → 89ea9a967e3dd407）、cell_shrink（17162d9e3ed6047f → f9206af1e771f0e5）的 `code_hash` 变，各册 Step3 起判过期。殿本 vol04–10（第 4 页起 10,521 列，对 v0.4.9 现行 main）逐格 98.79% → 99.03%，修好 27 列、改坏 1 列（vol09 p162 c3 卷末小计列，看图新切法更好，金标口径多一格）。
  - 候选格网统一打分：表格网、闸抬头格网（抬头级数表与闸不一致时）、无先验格网（前两者都劈了字、且不看表切出的字比表少时）按「坏格数＝劈开的字＋违表的格 → 劈字数 → 穿字格线」取最小。新增劈字判据 `_split_chars`（一个连通体被格线劈成两段、两段各占三成以上）。修 vol06 p94 c6 列首「二」被单切一格后丢失、vol07 p44 c8「年」被劈。
  - 列端框线残渣记空的范围从「物理首／末格」放宽到「表的首字之前、末字之后那一段表空格」，判据不变（首字上方隔一格的碎墨、斜笔残迹）。
  - Step3 给表认下的字格记 `layout_char`；Step4 列端渣格闸遇到这种格、且格里有成笔的墨时不判渣（列尾「一」被判 tail_junk，vol05–10 共 16 列）。白纸照样判空。
- 请审单（`guji audit sheet`）第 4 节按已导入的看图结论自动填「看图判错、人还没裁」的格，新增第 5 节「看不清」；原来要会话手工追加。不碰任何 Step，`code_hash` 不变（M9，GUJI-653）。
- `scripts/zhengli/zl.py`（M9 基线跑 vol06 整册后，GUJI-653／654）：新增 `db`（拉中心库）、`pending`（待审单草稿，只给 2c 核数、不上线）两步；书 yaml 改从数据目录 `books/` 找；稀疏克隆按 `<书目录>/data_full/<丛编>/<册>/` 取本册原图；BrokenProcessPool 归「疑似内存不足」，前台、后台都减半并行续跑；缓存只在校验报错时 `--fix`；导出不再缺省 `--text-version 0.1.0`，要 `ZL_TEXT_VERSION`；`close` 改跑粗校档 `--tier rough`，出 R1–R5 报告、2d 列交代草稿，剩下的活写 NEXT.md。`collect_exit.py` 加 `--close-check-json` 复用已跑的体检（省一遍约 5 分钟）。
- 新增 `scripts/zhengli/republish.py`（GUJI-680 第一步）：一册重跑后重发待审单。`prep` 按现行产物出新单（audit alt → pending_list → pending_route 扣已人裁 → 雪碧图），rev 按线上单自动加一，出差异单（去掉的格按「人裁过／机器放行了／格号没了」分，列出旧 rev 上的网站精校票）；`push --yes` 才写进数据目录并记台账，`--sync` 再推中心库。不碰任何 Step。

### Fixed
- 语料库清单不再收字组 `config/groups/*/prompt.md`（只给离线 L2 拼消息，Step 不读）；老清单里登记了的也跳过核对。此前改提示词（cc6f455f）会让钉了 corpus 的册在 glyph_match 起跑前报 CorpusDrift 拒跑（M9 基线跑 vol06 撞上，GUJI-636；PATCH，各步 code_hash 不变）。
- 并行限流按容器内存算：可用内存取 /proc/meminfo 与 cgroup 上限（减去已用、不算页缓存）中小的；glyph_match 单进程登记从 1 GB 改为 3.6 GB（导了字体域后 vol06 实测 3.4–3.7 GB，原登记让 4 进程在 14.3 GB 容器里被 OOM 杀）。只改进程数，产物与 code_hash 不变（M9 基线，GUJI-636）。

## [0.4.9] - 2026-10-20

PATCH（sheldon 10-20 定）。相对 v0.4.8 只有 `rare_candidates`（8d081ec338766152 → b92a99fa13957185）、`seed_admit`（19fbae2631200652 → 3337e7b0b2dc43ec）的 `code_hash` 变，其余 15 步不变。配套语料库：殿本 v9（日曰、入人八文意表按提示词 v2 重建，覆盖 vol01、vol04–10；`group_flow` 点名彝组 `yi_560`）——v9 清单登记了新提示词，旧版 CV 配 v9 会被语料钉拒跑，换版要同时改钉。
验收（rc 上，殿本 vol05–07 共 141 页 seed_admit，对 v0.4.8＋语料库 v7）：送审 223→205；新放行 19 格（日曰 15、彝 4）逐格核对全对；新送审 1 格（vol07:102:9:21「五事一曰貌至五曰」，v0.4.8 误放「日」，现被文意表拦下）；随机抽的 60 页无变化。

### Added
- 字组：第四批只看字频的异体组 爲為 說説（wei shuo；殿本人裁只见一形，≥10 且来自 ≥2 册）。PATCH；只有 seed_admit 的 `code_hash` 变。要在册配置 `group_flow` 点名才生效。
- `guji opinions publish-status`（M11 B2，GUJI-714；PATCH）：意见池里网站来源（改字、一段有问题）的处理结论按网站 target 聚合，写中心库 `feedback/lists/web/<书>/status.jsonl`（已进文本→adopted＋版本、已采纳→adopted、未采纳→rejected＋公开理由、交用户／讨论→discussing；精校票不发），幂等；网站 proofing-sync 读它回写 `/api/fixes`。顺手修回复草稿把模板句与公开理由叠在一起的毛病（GUJI-713）。不碰任何 Step，`code_hash` 不变。
- 控制台「相似字」字形图下的小标签：扩 B 以后、私用区的字改显示码位 `U+XXXXX`（悬停看原字），两套字体都渲染不出字形图时同样显示码位（`reviewClass.zhLabel`，用户 10-20）。控制台不带网页字体，原来这些字在阅审人电脑上多半是方框；字形图本身照旧由后端用 I.Ming／Jigmo 渲染。不碰任何 Step，`code_hash` 不变。
- M11 第一阶段：意见池、AI 初判的确定性部分、修订工具（GUJI-712／713／715，设计 `doc/design/M11-分块-第一阶段最小闭环.md`）。新包 `open_guji_cv/opinions/`（L4）与 `guji opinions …`：`ingest`（中心库 `feedback/lists/web/<书>/` 的改字／精校票、网站公开读 `/api/fixes`、`/api/feedback` 文字类 → 中心库 `feedback/lists/opinions/<书>/`，幂等，去测试票、记重复与转出）、`list`／`show`、`versions`（book-text CHANGES → `text_versions.json`）、`locate`、`normalize`、`pack`（IIIF 原图档裁格与列条带、上下文、marks，`sheet.png`／`sheet.md`）、`triage`（会话判、`config/opinions/rules.json` 定去向）、`to-user`／`decide`、`revise`（A／B／B′ 类改 book-text 冻结册 char／cord，伴生层跟随，调 `bump_original.py` 升 patch，CHANGES 引意见 id）、`reply-drafts`。PATCH；不碰任何 Step，17 步与闸 `code_hash` 不变。
- M10 小件（#286，v0.4.8 发版后直接合进了 main，dev 已含）：`resolved_manual_cells` 遇坏行改为逐行读、跳过并在 stderr 报出（原来一行坏整片静默退回自动切分），新增 `scripts/zhengli/check_manual_cells.py`（GUJI-692）；公众意见台账 `scripts/zhengli/opinion_ledger.py`（GUJI-690）；runbook S25「1.0 之后的修订」（GUJI-696）。`lookup.py` 不在任何 Step 的 `code_deps` 里，`code_hash` 不变。

### Changed
- 管线提速（#255，PATCH；产物逐字节不变，**只有 rare_candidates、seed_admit 的 `code_hash` 变了**，其余 15 步不变）：
  - 页级并行：`row_segment`、`cell_shrink`、`glyph_match`、`rare_candidates`、`seed_admit` 登记进 `core/parallel.py`（不进指纹）。四庫 vol04 46 页串行对 `--jobs 4` 逐字节相同：row_segment 65→26 s、cell_shrink 28→9 s、glyph_match 231→80 s、rare_candidates 65→24 s、seed_admit 82→50 s。worker 里 OpenBLAS／torch 压 1 线程、`cv2.setNumThreads` 置空（fork 子进程里调它会卡死）；seed_admit、rare_candidates 先在主进程暖机、`parallel_warm` 预建大缓存再 fork；进程数按可用内存压。seed_admit 并行前要先把字块缓存建好。
  - 代码等价登记（`core/code_equiv.py` + `scripts/code_equiv.py check`，用户 10-20 定）：新旧代码同一批页产物逐字节相同才登记，指纹换回旧哈希，各册不过期。
  - 热点：glyph_match 逐页 −24%（wmax 按需算、同格查找分桶、HOG 向量化）；seed_admit 每页 2.3→0.85 s（事件读缓存；铁证匹配器归一图按内容缓存）；context_decide 热缓存首页 6–7→2 s（本书与通用 LM 按语料内容 + 代码指纹缓存）；align_ref 起跑 16→7 s；印章遮挡每页 0.21→0.02 s。
  - 训好的语言模型跨机分发：本机没命中先用读令牌去 R2 取 `derived/lm/…`，`guji products pack push-index` 手动推（用户 10-20 定）。runbook S1 设 `GUJI_DATA_TOKEN=$GUJI_DATA_TOKEN_READ`。

### Fixed
- `font_candidates._row_norms` 按 `id(mat)` 缓存行模长：lru 挤掉的矩阵释放后 id 被复用、行数相同时用错模长，余弦全错、结果随页序变（#255）；seed_admit 补登记 `code_deps` 里的 `font_candidates`。**rare_candidates、seed_admit 判过期，各册要重跑这两步**（vol04 46 页上未触发，产物相同）。
- 并发写（#255）：`_stamps.json` 加跨进程锁、临时文件带进程号（原来并行再生图块会整页记失败、丢戳）；`ImageCache.put`、绑定逐页缓存、字体索引改原子写。

## [0.4.8] - 2026-10-20

### 流程
- 分支与发版流程改为 **dev 集成＋发版时切 rc**（用户 10-20 定，`doc/版本号规矩.md` 第三节）：日常 PR 投 `dev`；准备发版时从 dev 切 `rc/vX.Y.Z` 测试，rc 只收本版修复并合回 dev；测完 rc 用 merge commit 合进 main、打 tag；main 不直接收 PR。`scripts/check_rc_target.py` 跟着改：目标 `dev` 返回 0，`main` 返回 4。

### 并入 main 上 v0.4.7 之后直接合入的改动
- 汉字关系库 hanzi：总设计、B0/B1/B7（#256）、B2 全字表字形向量包（#276）、B3 以字找字候选池改由 hanzi 库给（#266）、B4 字统网按字典存派生事实（#267）、真书实测文档（#278）。
- Step3 `row_segment` 人工指定整列格 `manual_cells`（#251，main 上记作 1.20；没有指定的列逐字节不变）。
- hanzi 库 B2 续：向量包存 int8／fp16／fp32（#281）；真刻本评测过判据，Step5-b 也切 8 位向量包（#284）。
- M10：待审分流脚本 `pending_route.py`（GUJI-688）、冻结册运行护栏（GUJI-694）（#279）。
- 文档：人审率分析补列级对位救援的离线评估（#247）；M10 精校调研与总设计、已知错单脚本、`guji exit-check`（#273）。
- **`row_segment` 版本合为 1.22**（本线 1.20／1.21 的 layout_prior 改动＋main 的 manual_cells），`code_hash` e82f08017e79c63a（rc）／bb4f3830915bcdf0（main）→ d5f4ceedcfbd2d06：各册 Step3 起判过期，冻结册按冻结规则不受影响；开关（layout_prior、manual_cells）不开的列产物逐字节不变。其余各步 `code_hash` 与 rc/v0.4.8 相同（相对 v0.4.7 变了的步见下面各条）。

### Added
- 产物包按「三样版本」打标签、每册有 main（用户 10-20 定：不同版本的结果分开存、不覆盖，main 是最新正式结果；cv、字形库、语料库三个版本号共同决定结果）：`guji products pack push` 不给 `--label` 时标签拼成 `cv<版本>-c<语料库号>-g<字形库号>-<改动名>`（`--change`；字形库没钉写 `g-`＋人裁指纹前 6 位），三样完整值记进 manifest 的 `versions`；新 `pack promote <册> --label …`／`pack push --main` 追加 main 指针（`main-ptr/`，只增不改，Worker 不用改）；`fetch` 缺省取 main，没标过才取最新；`list` 标 ★ 并列三样版本。不碰任何 Step，`code_hash` 不变。

- 产物包记字形库的内容版本、没存包提醒、实验记录（用户 10-20 定）。不碰任何 Step，`code_hash` 不变：
  - 每条产物 manifest 新字段 `db_rev`（跑时本机数据对应的中心库版本 `<工作区>@<分支>:<rev>`，不进指纹）；包的 `versions` 加 `db_rev`、`db_revs`（seed_admit 各页的 rev 与页数）、`corpus_base`。`glyph_pin` 只钉指纹不钉内容，要复现某份包读的库就从这个 rev 开 Neon 分支。
  - `guji pipeline`／`step`／`status`／`close-check` 末尾：本机这册产物在最后一次存／取包之后又跑过（各步 `_manifest.jsonl` 摘要对不上，记在 `<产物根>/<册>/.pack.json`），印一行提醒存包。只提醒不挡。
  - `pack push` 在工作区仓写 `experiments/<册>/<标签>.md`（基线、三样版本、中心库 rev、册 yaml、`--report` 给的 diff 报告）；`promote`／`--main` 往页尾追「标为 main」。`--no-record` 不写。
  - 实验记录开头加「摘要」（用户 10-20：每跑完一次都在记录里简单总结配置和结果）：`pack push --summary "…"`（或 `@文件`）写目的、改了什么、结论；给了 `--report` 时自动加一行结果（送审前后、人审率、变了的列、逐格翻转）；从产物 manifest 自动列各步最后一轮的起止时刻（洛杉矶）与耗时，看得出这一轮从哪步起重跑、哪步最慢。

- `guji products exclusions <册> --a <重切前> [--b <重切后>] [--apply]`（`ops/exclusion_rebind.py`，用户 10-20 同意方向）：排除清单按格号记、不带框，重切后可能落到别的格。按重切前的框到重切后找 IoU ≥ 0.85 的格：没动不改、顺移改号（`rekey_from`）、找不到或改号撞上撤到 `crop_exclusions_retired.jsonl`。缺省只报计划。不碰任何 Step，`code_hash` 不变。

- 控制台记下选的字是从哪儿点来的（`doc/research/人审找字-以字找字与异体族按图排序.md` §5.3，用户 10-20 要量相似字的真实命中）：
  - **定字卡**：confirm 行多带 `pick_src`、`pick_rank`、`pivot`、`pick_from`（`reviewClass.pickFields`）。`pick_src` 取值：
    - `cand`：主候选，`rank` 为键位表第几个，`from` 为哪几路；
    - `alt`：相似字，带 `pivot`；
    - `alt_q`：键入近似字后的相似字；
    - `rare`：「查候选」；
    - `custom`：手输；
    - `jys`：己已巳卡；
    - `cnn`／`ctx`／`llm`／`ocr`／`ai`／`form`：证据行上的「采信」。
  - **Step8「都不对」**：`collate_verdict` 与 `confirm` 带 `pick_src`／`pick_rank`／`pivot`，取值为 `alt`／`alt_q`／`custom`。
  - 切分缺陷等档不带；没点过的行逐字段不变。网站精校页同名字段见 kaiyuanguji-web#531。不碰任何 Step，`code_hash` 不变。
- char 导出：阙文带推测字（GUJI-717，用户 10-20 定「录文以图为准」，guji-format#21 char v0.2 `guess_c`）。人裁 `confirm v=damaged` 带 `guess=X` 的格（9.1 写 `□{guess=X}`），`scripts/export_guji_format.py --format char-cord` 与 `scripts/convert_pages_to_char_cord.py` 改写成 `{"c": "□", "lacuna": true, "guess_c": "X"}`，不再写成残字 `guess: true`、`c: X`（阅读器显示灰字 X，与「图上无字录 □」相反）。`guji export format` 出的旧形态（lines.md、pages.json）不变。只有带这种格的册 `$schema` 写 char v0.2，其余册导出逐字节不变（book-text 现存 char 里 `guess: true` 为 0 处）。往返核对按 9.1 写法比；`formats/` 加 `guji_char_v0.2.schema.json`。PATCH；改 `formats/guji_char_cord.py`、两个导出脚本，不在任何 Step 的 `code_deps` 里，17 个 Step 和闸的 `code_hash` 全不变。
- `guji audit alt <册> --reviewed`：已人裁、已放行的格也算相似字（只写进 `cards.alt.json` 给 `alt-eval`，不进待审单），拿历史人裁量相似字的真实命中——这些格裁的时候人还看不到相似字，没有「看了候选才选它」的偏倚。10-20 殿本 vol01–03 实测：人定的字不在卡上原有候选里的难格 75 格，相似字前 5 命中 55 格、前 10 命中 59 格（79%），第 1 名 36 格。不碰任何 Step，`code_hash` 不变。

- `scripts/check_rc_target.py <rc 分支>`（GUJI-657）：合 PR 前核对目标待发分支是否已发版（远端有 `vX.Y.Z` 返回 1 并提示改投哪条；不是最新待发分支返回 2）。只读，用 `git ls-remote`。不碰任何 Step，`code_hash` 不变。
- 粗校出口报告单列「钉版」一行（GUJI-656）：`collect_exit.py` 读册配置的 `cv_version`、`corpus`、`glyph_pin`，没钉的标 ⚠，只提示、不挡出口；规矩见 `doc/版本号规矩.md` 第七节（每波开工发一个正式 tag，各册钉 tag＋语料号＋字形库号）。不碰任何 Step，`code_hash` 不变。
- `scripts/zhengli/ledger.py`（GUJI-667）：粗校台账与统一人审率口径（用户 10-20 定：正文页送精校的待审格 ÷ 正文页字格，不含标题槽、非字格；重切清单、非正文另报），`review_rate()` 纯函数＋CLI 追加一行到数据目录 `feedback/lists/ledger/<册>.jsonl`。不碰任何 Step，`code_hash` 不变。
- `scripts/ia_download_zongmu.py` 改按全书 99 册两段编号（`06061300`–`06061320`、`06066140`–`06066217`，GUJI-648 逐号核过；原来按「199 册连号」，照默认跑会从 vol22 起下别的书）：新 `--vols 11-20` 按册号选，缺省取 `_tif.zip`（与工作区现有原图逐像素一致）。书单 `doc/archive/runbook/书单-四庫總目.md`。不碰任何 Step，`code_hash` 不变。
- 粗校待审单脚本迁进本仓 `scripts/zhengli/`（GUJI-652）：`pending_list.py`、`sprite_build.py`、`ex_build.py`、`alt_build.py`、`decision_build.py`，原在 ai-team 工单目录、runbook 直接引用、没有测试；行为不变，`--cv-root` 缺省本仓根，各配单元测试。`ex_build`／`decision_build` 的用法示例仍写中心库切换前的路径，文件头注明。不碰任何 Step，`code_hash` 不变。

### Changed
- `scripts/export_guji_format.py --format char-cord` 的 `--text-version` 改为必填、不再缺省 0.1.0（GUJI-679）：已在 book-text 上的册要写线上现行版本，以前缺省写 0.1.0，出补丁前得先手工改回。`zl.py` 导出步显式传版本。不碰任何 Step，`code_hash` 不变。

### Fixed
- 产物包键的工作区名不再瞎猜（GUJI-671）：`datastore/packs._ws_name()` 先读 `.central.json` 的 ws，再读 `workspace.yaml` 的 id，都没有就报错；以前回退成目录名首段或 `ws`，vol01–03 的包因此落在 `products/ws/` 下、用 `-w` 取不到。不碰任何 Step，`code_hash` 不变。
- 中心库客户端超时分两档、超时快速重试（GUJI-707；国内节点连 data.open-guji.com 约 15% 卡在 TLS 握手，GUJI-703）：小 JSON 请求（查表、签名、状态、whoami、分支、追加事件）缺省超时 120 → 25 秒（`GUJI_DATA_TIMEOUT` 可改），超时走原有退避重试，且网络错至少试 4 次（原先查表、签名只试 2 次）；收发大块字节的（快照、备份、产物包、R2 直取图、`r2` 上传的 PUT）维持原值。`r2.upload_via_worker` 的签名请求同样用短超时。PATCH；不碰任何 Step，`code_hash` 不变。
- `guji close-check` 第 2c 项的待审单改读中心库（GUJI-711）：10-20 起公众待审单只在中心库 `feedback/lists/proofing/<书>/<章>.pending.json`，`--pending` 不给（或只写 `--pending`）就读数据目录里本册本章那份（书 id 按 `meta_<册>.json`，取不到在 `proofing/*/` 下找唯一一份；章号取 `--chapter`、导出目录唯一的 `NNN.lines.md` 或 `volNN`）；也认册（`vol04`）、章号、`<书>/<章>`；给了 book-text 的旧路径且文件不在，提示已迁移并指出新路径（新路径在就改读）。数据目录里没有就照旧只认重切清单，2c 说明里写清。runbook 同步。PATCH；不碰任何 Step，`code_hash` 不变。
- 字形库体检结果带库指纹，过期不出卡（GUJI-710）：`guji glyph-db selfcheck` 把开跑时的库指纹（本书套刻例 `(实例 id, 字, 图块 sha)` 排序后哈希）记进 `summary.json` 的 `db_fp`，每张卡记本例与本书对手的图块 sha；控制台体检 tab 出卡前核对，结果没带指纹或卡上刻例的图对不上（刻例重排编号）→ 409「体检结果已过期（库已变），请重跑 guji glyph-db selfcheck」，一张卡也不出；只是撤了、改了字的，那几张卡不出、其余照出。起因 GUJI-623：09-26 的结果在 09-27 重排编号后照样出卡，9 张错位。`glyphdb-audit` skill 与 `glyph_audit.py` 的说明改成中心库口径（数据目录、`guji db sync`，不再进 git）。PATCH；不碰任何 Step，`code_hash` 不变。
- 语料库任何内容变了都要改版本号（用户 10-20）：`guji db push`／`sync` 推送前，最新一版清单登记的工作区文件被改、缺，或清单之外多了新语料文件 → 拒绝，提示先 `guji corpus build` 出新版本一起推；已发布的某一版 `manifest.json` 库里已有且本地不同 → 拒绝（旧版本不可改）。只看工作区文件；引擎仓里的表仍由起跑前硬校验管。10-20 的起因：v1 登记的 `freq.json`、`l2/jys.json` 钉选后被重新生成，`glyph_match` 因此拒跑。改 `core/corpus_pin.py`、`datastore/workcopy.py`，`code_hash` 不变。
- `guji db pull`／`sync` 遇到库里引用、R2 上却没有（404）的图不再停下：跳过、stderr 打一行并在 `materialize` 结果的 `missing_images`（相对路径→sha）里列出，其余照常还原。要像以前一样遇到就停：`GUJI_DATA_MISSING_BLOBS=error`。不碰任何 Step，`code_hash` 不变。
- Step3 逐列格位先验 `layout_prior`：列端框线残渣记空。表说该空、又是整列物理上第一格或最后一格的「字格」，里面像字的墨行合计不到 0.15 个 period、满宽横线（±3 行）以外的墨占格面积不到 0.03 时改成 blank（产物 flags 记 `layout_frame_junk`）。起因：掩码故意不罚满宽密行，版框横线落进列首／列尾那格时被切成「字」，按 daizhige 算多切一格（vol05 p147 c1、vol06 p18 c6／p69 c2／p63 c1）。列中段的碎墨不碰：卷端页、整页破损页上印断的字（vol09 p164「經部十七」）不能批量判非字。殿本 vol04–09 实测改空 647 格，全部看图是框线、竖线、碎点；比 1.20 逐格多修好 19 列（4／5／6／7／8／9 册各 1／4／6／3／1／4）、改坏 0；穿字格线不变（只改格的类型，不动格线）。开关不开的书不受影响。PATCH；`row_segment` 版本 1.21，`code_hash` d4f420cf47082535 → e82f08017e79c63a。
- Step3 逐列格位先验 `layout_prior`：表的抬头级数与闸（`n_raised_hint`）不一致时，两种格网都切，取格线横穿字少的（打平照旧用表的）。起因：殿本 vol04 产物包对照组／版面先验组（`cv0.4.7-c1-g-82293e-*`）看图——①p84 c5、p65 c8「御」「欽」抬头在版框上方、列图没截到，按表硬设抬头格把首个看得见的字编成 -1，整列格网错一位劈字（84:5 放行错字「一」）；②p127 c1–2 低起列（从第 5 格起），按表压掉闸给的抬头余量后格网上挤半格。一律听闸也不行：书名列首字会被吸进 -1（vol04 实测新坏 10 列）。vol04 全册只有 7 列改走闸的格网（8:8、9:8、65:8、84:5、127:1、127:2、220:1），其余列与 v0.4.7 逐字节相同；穿字格线（对照组 1,810 条）旧版 1,808 → 新版 1,783。Step3 产物 flags 记 `layout_raise_gate`。开关不开的书不受影响。PATCH；`row_segment` 版本 1.20，`code_hash` b72e737b7a45a1df → d4f420cf47082535。
- `guji products diff --images` 看图页：`bbox_page` 是右上原点，原来直接当左上原点裁、画框，除正中那列外都画到镜像位置的另一列（vol04 R1 验收时发现）。现在先 `bbox_tr_to_tl` 再裁。报告数字不受影响。不碰任何 Step，`code_hash` 不变。
- `guji products pack push --label`：标签先在本地按 Worker 的规则校验（ASCII 字母、数字、`_.-`，≤96 字符），中文等不合法标签直接报清楚，不再到 Worker 才报 `bad_path`（重跑 vol04-10 线程 10-20 用「v0.4.6-粗校」撞上）。不碰任何 Step，`code_hash` 不变。

待发分支 `rc/v0.4.8`。

## [0.4.7] - 2026-10-20

### Fixed
- 标点分段（`render/siku_extract.py`、`render/reflow_text.py`，#239）：抬头／平抬／差一格改为软分段，连起来交模型断句后再定。只动渲染出口，不碰任何 Step，`code_hash` 不变。
- 导出（`formats/guji_page_cv.py`）：排除名单格（seg_defect／crop_defect）人已给字（`evidence.human_char`）的，字位 `method=human`、`review=human`，不再记 `pending`、不再标 `lacuna: defect`（文本本来就出这个字）。此前这类格在 pages.json 里仍是 pending（vol02 重跑后 124 格），顺带让待审单、2c 把它们当没裁。只动导出出口，不动任何 Step，`code_hash` 不变。非字、原刻残（damaged）、无人给字的名单格不变。

### Changed
- `guji close-check` 1a（非冻结册）改口径（用户 10-19 定「在跑它的那个版本下新鲜就行，不要求最新版本」）：只因「代码或版本变了」过期、且 manifest 条目记着正式版 `cv_version`（不带 `+N`／`+dirty`）的页算新鲜，过期也不再往下游传；detail 里另报这类页数与本册产物用到的 cv 版本。册配置变、参数变、上游产物变、缺失、失败、显式失效、老条目（没记版本）照旧算 FAIL。新参数 `--strict-cv` 回到旧口径。`Engine.status(code_ok=True)` 是同一件事（缺省 False，`guji status` 不变）。冻结册的 1a 不受影响。PATCH；只动 `core/engine.py`（不在任何 Step 的 `code_deps`）、`ops/close_check.py`、`cli_v2.py`，`code_hash` 不变。

### Added
- 受控重跑三件工具（[doc/参考/受控重跑.md](doc/参考/受控重跑.md)；方法论在 ai-team `domain/CV/规范/受控重跑方法论.md`）。都缺省关，不进任何 Step 的 `code_deps`，17 步 `code_hash` 不变：
  - 册钉字形库 `glyph_pin: N`（`core/glyph_pin.py`）：seed_admit 的人裁、近似字指纹换成 `glyph-gN`，别的对话推上来的人裁不再让本册 seed_admit 过期；号加一才落地新人裁。起因：重跑 vol04–10 时每次 `guji db sync` 都让已过粗校的册判过期、重跑、重做出口检查。不写 = 指纹逐位不变；第一次写上会让该册 seed_admit 过期一次。
  - `guji products diff <册> --a <前> [--b <后>] [--images N]`（`ops/products_diff.py`）：两份产物按位置逐列对比（切分变了也能比），出人审率前后、变了的列（切分／字／状态／框）、逐格翻转（含「放行字变」），`--images` 出原图并排看图页。
  - `guji products pack push|fetch|list` 与 `push-index|fetch-index`（`datastore/packs.py`）：一册 products、生僻字 embedding 索引存进 R2（guji-data Worker 新接口 `/v1/packs`，guji-workspace-data#15），新会话直接取，不再整册现算（云上一册 1.5–2.5 小时）、不再冷建索引（云上单进程约半小时，`--jobs 4` 约 8 分钟；取回 30 MB 约 4 秒）。按名字只增不改，取回先核 sha256。
- 相似字（以字找字，用户 10-19 定）：待审格的近似字（整理本字、上下文字、库前 3…）的异体族——本仓异体表＋部件檢索（新增 `config/variants/charcomp_rt.tsv`，非商业授权、文件头标来源）＋字统网一跳族（按需低频取、缓存在 `$GUJI_DATA_HOME/_shared/zitools/`，不进 git）——按字块图 CNN 余弦排序，每格 ≤30 个。`guji audit alt <册>` 出带 `alt` 的卡片 JSON 交 `pending_list.py`（`proof_fields` 带出 `alt`，网站精校页显示）；`guji audit alt-eval <册>` 人裁后量命中；控制台新路由 `GET /api/rare/alt/...`，定字卡与 Step8「都不对」下加「相似字」行和「以字找字」框。新模块 `clustering/variant_sources.py`、`review/alt_cands.py`；只出候选、不进放行；不碰任何 Step，17 步 `code_hash` 不变。PATCH。runbook S11-b，设计与读数 `doc/research/人审找字-以字找字与异体族按图排序.md`。

### Changed
- Step5-a `glyph_match`：借来的刻例降一档（共享方案 S6）。判 same 的库条目里有本书的，就用本书那条当证据；只有借来的条目（`glyph_lib.borrow` 装进来的，如共享刻例库 `glyphlib-qkp-v1`）判 same 时降成 unsure，字进候选交上下文裁决，记 `via="borrowed:<条目 id>"`，不再走共识升档与近形决胜。新硬参数 `borrow_fingerprint` 自动填被借库的名字，借的库换版本这一步判过期；没借库时是空串、不进参数 dump。**`glyph_match` 的 `code_hash` 变了**（改了 `steps/glyph_match.py` 与 `clustering/match.py`，`MatchResult` 多一个只在内存里用的 `same_hits`）；现在没有书借库，各册判决与参数哈希都不变，按版本号规矩算 PATCH，可以不重算。

### Fixed
- 语料库清单（`guji corpus build`／`init`／`build-base`）里的 `built_with.cv_version` 改读引擎仓 `pyproject.toml`：原来读装包元数据，可编辑安装后升了版本号它不更新，10-19 出的底库 b1 记成了 0.4.4（实为 v0.4.6 发版提交 `0194a152`，以清单里的 `repo_commit` 为准；b1 已发布不可改）。只是记录字段，不碰任何 Step，17 步 `code_hash` 不变。
- `row_segment` 缺省关的新开关（`colgold_prior`／`yolo_*`／`layout_prior` 及其指纹字段）不再进参数 dump（同 `border_detect` 的做法）：v0.4.6 把它们加进 `RowSegmentParams`，所有册的 `params_hash` 都变了，已冻结的册（`freeze:`）用 v0.4.6 跑 close-check 1a 被归成「册配置或参数被改：row_segment N 页」报警，而规矩是代码变只计数不报警。现在关着时参数哈希与 v0.4.5 逐位相同，开着照常进指纹。PATCH；`row_segment` 的 `code_hash` 因改了该模块变一次（对 v0.4.6）。

## [0.4.6] - 2026-10-19

PATCH。中心库拉取省流量与实验分支、借库与两级语料库清单、共享刻例库与升格候选命令；Step1／Step3 的新开关（`column_grid_pages`、`body_pages`、`colgold_prior`、`layout_prior`，缺省全关）；close-check 第 2 项不数重切清单上的格；殿本四联叶拆页表修正。

**`code_hash` 有变（对 v0.4.5，发版时实算）**：`border_detect` e7568862 → d452c5ab、`border_detect_gate` 8c0a7903 → fbc1b48d、`column_gate` 25658f2b → 922057a9、`row_segment` e5572a66 → f773bd3a；其余 13 步不变。新开关缺省关、关着时产物逐字节不变，各册这几步可以不重算；已登记 `freeze:` 的册代码变只计数不报警。

### Changed
- `guji close-check` 第 2 项「待审清零」不再数重切清单（`feedback/lists/<册>-重切清单.tsv`）上的格，detail 里另报「N 格在重切清单上，不计」。起因：vol01 有 66 格待审落在 cv 切不对、book-text 里手拼的列（职名表、p10:7、p196），格 id 与 cv 切分对不上，落不了格事件，永远清不掉；它们的去向由 2c／2d 把关。清单为空时行为不变。PATCH；只动 `ops/close_check.py`，`code_hash` 不变。
- 新机器第一次 `guji db pull` 先从 R2 下工作区快照（殿本约 6–7 MB，R2 下载不收费），库里只要快照之后变了的文件；`pull` 向库要过文件后、`sync` 拉下库里新改动后，把本机与库一致的文本打包存成新快照（只有能写该分支的令牌存得上，存不上不影响拉取）。快照只当缓存，逐文件对库里的 sha，坏了、旧了都退回从库里取。`GUJI_DATA_SNAPSHOT=0` 关掉。要 Worker 的 `/v1/snapshots`（guji-workspace-data#14）。不碰任何 Step，17 步 `code_hash` 不变。
- `guji db pull`／`sync`／借库拉取省 Neon 公网流量：本机已有、整文件 sha 与库里一致的文件直接用本机字节，只向库要变了的文件（按 `src_path` 查）；向库要行只取 `src_path`、`src_line`、`raw`，刻例图清单只取 `instance_id`、`patch_sha`。起因：Neon 免费档每月 5 GiB 公网流量，10-18 建库后 1.6 天用掉 4.75 GB，因为每次 sync 只要库里有新写入就把整个工作区按 `SELECT *` 重读一遍（殿本约 120 MB）。改后小改动的一次 sync 只传变了的那几个文件。要 Worker 认 `cols` 与同列多值（guji-workspace-data#13）；旧 Worker 自动退回整行取、逐值查。新机器第一次拉仍是全量。不碰任何 Step，17 步 `code_hash` 不变。

### Added
- 升格候选命令（共享方案 S7，语料部分）：`guji promote mine -w <工作区>` 只读，从对勘裁决挖形近对、异体对候选，对照引擎仓的形近表、异体表标出已有的，出清单待人审。新文件 `ops/promote.py`，不碰任何 Step，17 步 `code_hash` 不变。
- 共享刻例库命令（共享方案 S5）：`guji glyphlib build -w <来源书> --name glyphlib-<族>-v<N>` 按门槛（人裁在几个不同批次确认过、体检干净、非近似字、每字几张）从一本书精选刻例，出共享刻例库工作区（刻例图逐字节照搬，实例 id 加来源前缀，附升格记录 `feedback/events/promote.jsonl`）；`--push` 以升级脚本身份推进中心库，每版只写一次。新文件 `ops/glyphlib.py`，不碰任何 Step，17 步 `code_hash` 不变。见 `doc/参考/datastore.md` 第六节「共享刻例库」。
- 中心库实验分支能整套用了：`guji db pull/push/sync --branch exp/GUJI-<号>-…`（或 `GUJI_DATA_BRANCH`）把整个工作区换到实验分支，数据目录、glyph.db、products 都放进该分支自己的目录（`$GUJI_DATA_HOME/exp__GUJI-…/<工作区>/`），不碰 main 的副本；push 经 Neon API 找到分支端点，新图进实验桶，拉图时正式桶没有的去实验桶取。新命令 `guji db diff` 逐文件比实验分支与 main。原来 push／sync 只许 main，`pull --branch` 会把实验分支的数据拉进 main 的数据目录。不设分支时行为不变；不碰任何 Step，17 步 `code_hash` 不变。见 `doc/参考/datastore.md` 第六节「实验分支」。
- 两级语料库清单（共享方案 S2）：引擎仓的语料文件登记进底库 `b<M>`（中心库只读工作区 `corpus-base`，`guji corpus build-base` 出、记 `repo_commit`）；书库清单可写 `base: M`，只登记工作区里的文件（`guji corpus build --base latest`，新书 `guji corpus init`）；`db pull`／`sync` 顺带拉底库清单的只读副本。旧的单级清单（殿本 v1）不变。**起跑前硬校验**：册钉了 `corpus: N` 时，读语料的五步开跑前清单里的文件有改动或缺失就拒绝（`GUJI_CORPUS_DRIFT=warn` 临时绕过），新出现的文件只警告；殿本 v1 现在改动 0、缺失 0。改 `core/engine.py`、`core/corpus_pin.py`、`ops/corpus_pack.py`、`datastore/workcopy.py`，17 步 `code_hash` 不变。见 `doc/参考/datastore.md` 第六节「两级语料库清单」。
- 中心库借库（共享方案 S4）：迁过的工作区在 `workspace.yaml` 的 `glyph_lib.borrow` 写被借工作区的名字，`guji db pull`／`db sync` 把它的字形库拉成只读副本（`$GUJI_DATA_HOME/<分支>/.borrowed/<工作区>/`），带上它重建 glyph.db，被借库有新写入才重拉重建；`guji glyph-db rebuild` 也认工作区名。原来配了借库 `db pull` 直接报错。共享层工作区 `corpus-base`、`glyphlib-*` 普通 push／sync 拒绝，只有升级脚本能写，`glyphlib-*` 只写一次。见 `doc/参考/datastore.md` 第六节。不碰任何 Step，17 步 `code_hash` 不变。
- `border_detect_gate` 新参数 `body_pages`（缺省空；空时不进参数 dump、产物逐字节不变）：册配置点名的页不论页型规则判成什么都按正文切，manifest 记 flag `page_type_forced`。起因：殿本 vol06 p88 卷十末叶只有一列小注「部一卷皆附存目」、其余空栏，被判成 cover 整页跳过，丢 7 字；`params: {border_detect_gate: {body_pages: [88]}}` 后整页切出、7 字放行。`border_detect_gate` 的 `code_hash` 变（下游产物逐字节不变，不连带过期）。
- Step1 `border_detect` 新参数 `column_grid_pages`／`grid_col_pitch`（缺省空；空时两项都不进参数 dump、产物逐字节不变）：点名的页竖线走网格模式，其余页照书级配置。起因：殿本 vol05 p55、p123，vol04 p80 界行断续，自由模式挑了假竖线或漏一条界行，整列没切出来（vol05 p55「明王宣撰…」、p123「行故居足之左右…」、vol04 p80「今說易諸書無所偏主…」），现有闸都拦不住；`params: {border_detect: {column_grid_pages: [55, 123], grid_col_pitch: 185}}` 后列距全回到 180–190px，正常页逐位不变。`border_detect` 的 `code_hash` 变。
- `column_grid_pages` 点名页另做一步：最外一列窄于内列中位的 0.8 倍时，把那条外框线按中位列距往外推（记成插值线），只动外框两条。起因：殿本 vol04 p63 右框只下三分之一有墨，探到的「框」落在首列字上，首列只剩 117px、「聖人非因之以作易…」半列丢字；网格模式本身选不到这条残框。正常页不触发（vol04 p62、p80，vol05 p55、p123 逐位不变）。
- Step3（row_segment）加两个开关，**缺省都关，关着时产物与原来逐位相同**（殿本测试 B 100 页实测）（doc/design/19）：`colgold_prior` 读逐列字数金标（daizhige 与 yolo_tool release 两源字数一致的列，`scripts/dzg_import.py colgold` 生成 `corpus/daizhige/colgold.jsonl`），本列切出的字数与金标差 1–2 时按目标格数重切一次，重切后字数对上才采用；`yolo_merge` 用 yolo_tool 原生 ONNX 模型（`model_dir` 指过去，新可选依赖 `pip install -e ".[yolo]"`）提议并格（同一 YOLO 字框覆盖本列相邻两格），两者合用时先 D 后 C；带任何人裁（格数、切点、钉线、强制正文/小注）的列两个开关都不动；开关开着而表或模型不存在时报错。殿本测试 B（900 列）逐列字数 97.0% → 98.44%（修 13 列、新错 0），殿本全书 10 册（现行生产）96.84% → 97.83%（修 149、新错 1）。另加全书评测 `guji eval run column_counts`（金标分片 `char-segmentation/column-counts`，open-guji-dataset）。PATCH；只 `row_segment` 的 `code_hash` 变（e5572a664ad5b088 → a9f270b156c01af1），开关不开的书产物内容不变，但会按指纹判过期一次。
- Step3 逐列格位先验 `row_segment.layout_prior`（缺省关，关时产物逐字节不变）：读 `scripts/dzg_layout.py` 由 daizhige 逐列本生成的逐列格位表（`corpus/daizhige/layout_slots.jsonl`），按表定抬头级数、DP 逐格软罚分（`row_boundaries.fit_row_boundaries(slot_mask=…)`，新函数 `slot_mask_from_occupied`）、两半都有字的夹注格与正文格强制。**与 `colgold_prior`／`yolo_merge` 同列互斥**：表里有的列不跑那两个；带任何人裁（逐列字数、切点、钉线、强制正文/小注）的列三个先验都不碰（人裁按格号记，抬头级数一改就错位；vol01 p40–80 实测修前会动 3 列人裁列）。殿本十册离线：普通正文页逐格全对 95.76% → 98.51%，劈字 19 → 0；vol04/05 同基线下与逐列字数先验对照，字数口径 98.80% vs 98.25%、逐格口径 98.64% vs 94.71%；选法见 `doc/经验/切分四步-研发记录.md`「Step3 结构先验」（`doc/research/切分现状梳理与新方向-2026-10-19.md` §六、§八）。`close-check` 2d 另报「一页 ≥3 列没交代」的页，提示整页进重切清单（只提示，不改判定）。PATCH；**`code_hash` 变：`column_gate` 25658f2bf469a339 → 922057a98646e7d7、`row_segment` a9f270b156c01af1 → f773bd3aa6c4cd11**（`row_boundaries` 是两步的 code_deps），各册从 Step2 交接闸起判过期一次，缺省输出不变。

### Fixed
- 拆页表 `doc/formats/samples/guji_page_v0.2/split_table_siku.json`：殿本 IA 四联叶 vol04 第 216 叶（页 216–218）、vol07 第 128 叶（页 128、130）、vol09 第 258 叶（页 258–261）9 个半叶的裁线没落在版心，右半叶丢一整列或多裁进版心和邻页两列。按原图在版心两条界行 ±8px 处改 x、w（y、h 不变），重裁后每张正好 9 列；guji-workspace 的原图同步替换。拆页算法本身的改进另见 GUJI-625。不碰任何 Step，`code_hash` 不变（图变了，这几页 Step1 起按内容判过期）。

## [0.4.5] - 2026-10-19

PATCH。整理本和语料库清单进中心库；中心库取图不经 Worker；字组第四批与日目组补回；close-check 加 1c、2c、2d；人裁绑定缓存键修正；兼容汉字折成统一汉字。

**`code_hash` 有变（对 v0.4.4，发版时实算）**：`align_ref` e66b1c3f → e3043722、`rare_candidates` 4168770d → 8d081ec3（兼容汉字折叠 #200）、`seed_admit` 50bdd1fb → 52867bcf（#200 与字组 #206 合计）；其余 14 步不变。各册这三步的产物会判过期，重不重算看各册需要（各书重跑现在暂停）。

### Changed
- 中心库取图不再经 Worker（服务端改动，已部署，guji-workspace-data#12）：正式桶挂公开域名 `blob.open-guji.com`，Worker 签下载时回公开地址，各版本客户端都自动生效。从空目录整库拉殿本的 Worker 请求从约 1.85 万次降到 173 次。本仓只改文档与注释（`doc/参考/datastore.md`、`datastore/client.py`），`code_hash` 不变。

### Added
- 补进 #184、#192（它们在 v0.3.5 发版后才合进旧待发分支 rc/v0.3.5，没进 v0.4.x；册配置已开 `xz` `wyu` `yt` `rm`，v0.4.x 跑 seed_admit 报「未登记的字组 'xz'」）。原条目如下：
  - group_flow 第四批形近字组（2026-10-19，sheldon 定）：象彖 `xz`、王玉 `wyu`、圓圖 `yt`，做法同第三批（L1 规则＋逐册 L2 haiku 表，只补放不复核；彖傳／象傳、玉篇／帝王篇、方圓等两可词弃权）。vol04 A/B 组外格 0 变化，放行 +1（该册这三组几乎都已被放行，收益在没放行的册），L1 对整理本零冲突。`seed_admit` 的 `code_hash` f0f2713200ae880e → c3dbd4dac0582b47，其余 16 步不变。报告 [group_flow-4-vol04-报告](doc/exp/group_flow-4-vol04-报告.md)。
  - group_flow：允许组成员重叠＋形近组复核＋日目组 `rm`（2026-10-19，sheldon 定）：①`GroupSpec.overlaps`（须互相声明），`flow.entry` 一个字可属多个组——补放选第一个装得下「分差内全部候选＋整理本字」的组，复核选第一个声明了 `review` 且装得下整理本字的组；日曰 `ry` 与新组日目 `rm`（L1＋L2 haiku 表）共用「日」，日曰候选归 ry、日目候选归 rm、三者混杂留人审。②已放行格复核（只降审、不改字）：`ry wxs ly dt wj zh yh xz wyu yt rm` 打开 `review`（原来只有 jys／rr）。③`seed_admit` 的待审补放通道（witness3／coord_fallback）不再把复核判了 `group_flow_disagree`／`_conflict` 的格放回去（原来降审被 coord_fallback 按整理本字又放行，白降；含 jys／rr 原有的降审）。vol04 A/B：复核降审 8 格（象彖 4、大太 2、問間 1、入人八 1，原来被放回去的那 1 格），无改字；日目 L2 表 57 格答 37；组外格仅 iron 通道 +3（本机重拉字形库后库内容变化所致，与本改动无关）。`seed_admit` `code_hash` c3dbd4dac0582b47 → f0c37eac6214999c，其余 16 步不变。报告 [group_flow-5-vol04-报告](doc/exp/group_flow-5-vol04-报告.md)。
- 整理本和语料库清单进中心库（共享方案 S1）：`corpus/**` 进新表 `corpus_files`（文件进 R2，同锚图做法），清单挪到数据目录 `config/corpus-pack/`（随 `files` 表）。迁过的工作区再跑一次 `guji db migrate` 把工作区根留下的 `corpus/`、`corpus-pack/` 补迁进数据目录，再 `guji db push`。`corpus_path()`／`pack_root()` 先找数据目录。要配合 guji-data Worker 新版（已部署）；旧 Worker 上照常 pull。殿本 10 册 17 步 `self_hash` 搬家前后逐位相同，17 步 `code_hash` 不变。见 `doc/参考/datastore.md` 第六节「整理本与语料库清单」。
- `guji close-check` 加两条放行硬项（用户 10-19 定，GUJI-624；粗校档、终校档都计）：2c「□ 有去向」，导出文本里每个阙文格要在公众待审单（新参数 `--pending <NNN.pending.json>`）或 `feedback/lists/<册>-重切清单.tsv` 上；2d「整理本对不上的列有交代」，align_ref `coord_fallback` 的每一列要在 `feedback/lists/<册>-对不上列交代.tsv`（处理：重切／改字／说明／一致）或重切清单上。`scripts/zhengli/collect_exit.py` 透传 `--pending`（`ops/release_gates.py`）。PATCH；不碰任何 Step，`code_hash` 不变。
- `guji close-check` 加 1c「模型在场」：本机没装 torch 或缺切点裁判／识别权重时 FAIL（这时 1a 是拿「没模型」比「没模型」，照报新鲜）；Step5-b 产物里有字要查却一条 embedding 候选都没出的页也 FAIL（没 torch 跑的 Step5-b 指纹照样新鲜，只能看产物）。D 10-19 云端重跑 vol01 时踩到。PATCH；只动 `ops/close_check.py`，`code_hash` 不变。

### Fixed
- 兼容汉字一律折成统一汉字（如 福 U+FA1B → U+798F，`utils/cjk_compat.py`，#200）：字表、整理本对齐、人裁事件、产物读写都按统一汉字比较。改了 `align_ref`、`rare_candidates`、`seed_admit` 的 `code_hash`（见本节开头）。发版时补记。
- 人裁绑定表（`feedback/bindings.py`）的页缓存键加上字块那一步（`cell_shrink`）的产物 sha，比指纹时字块图也验戳：此前只认 Step3 的 sha，Step3 不变、字块重算了，旧缓存照样采信，行里的指纹是对着旧字块算的，人裁判成 review 不采信。D 10-19 云端整册重跑 vol01 时，10-16 的人裁 100 多格因此丢成 □。缓存版本 6→7，各机绑定缓存下次读时自动重算一遍。`seed_admit` 的指纹仍不含绑定结果，这类丢格靠 close-check 2b（已定字却没出字）兜底，2b 不为 0 的页 `guji step seed_admit … --force`。PATCH；`bindings.py` 不在任何 Step 的 `code_deps` 里，`code_hash` 不变。

## [0.4.4] - 2026-10-18

PATCH。Worker 超资源时自动缩批；借库不再把被借库的人裁算成本书的。17 步 `code_hash` 都不变，不用重算。

### Fixed
- 中心库 Worker 超资源（Cloudflare 1102，客户端看到 503）不再让 `guji db sync|pull` 整次失败（10-19 服务器 siku 拉 4 条新改动时失败）：查表每页 5000 → 2000 条，遇 503 页减半再试（最小 100）；下载签名每批 1000 → 250 张，遇 503 对半拆开；上传签名每批 200 → 40 张（每张要在 Worker 里查一次桶）。10-19 05:00–06:00 UTC 有 65 次 exceededResources。
- 更正 v0.4.1 的说法：取图的签名直链指向 Worker 自己（`/v1/blob/…`），**每张图算一次 Worker 请求**（免费档每天 10 万次）。新机器拉一遍 siku 约 1.8 万次；10-19 05:00 UTC 那一小时用了 7.6 万次。拉过的图在本地缓存里，不重复取。
- 只动 `datastore/`，17 步 `code_hash` 不变。
- 借库（`workspace.yaml` 的 `glyph_lib.borrow` → `rebuild_from_store(extra_stores=...)`）不再把被借库的人裁算成本书的人裁：被借库的 `admissions` 不装，借来实例的 `label_status='human'` 改记 `borrowed_human`；借来的刻例照旧参与匹配。原先人裁通道（`glyph_fp.HUMAN_SQL`）、铁证匹配器、`glyph_match` 共识升档都会把它们当本书人裁：中心库真数据实测全唐文借殿本，人裁查询 2,139 → 5,470 条，共识升档的字 126 → 491 个；修后回到只本书的数（共享方案 3.4 节，S3）。现在没有工作区开着借库。只动 `clustering/glyph_db.py`（不进任何 Step 的 `code_deps`），17 步 `code_hash` 不变。

## [0.4.3] - 2026-10-18

PATCH。push 只上传库里没有的图（只动 `datastore/`），17 步 `code_hash` 不变。

### Fixed
- `guji db push`／`sync` 推送时只把库里没有的图交给上传（先查一次该工作区 `glyph_instances.patch_sha` 与 `anchor_patches_meta.sha256`）。原先每次推都把全部约两万张图逐批签名核对一遍，要十几分钟，期间数据库连接闲置被 Neon 断掉，事务一开就失败（10-19 D 推 vol01 裁决两次失败，库里没有写入）。只动 `datastore/workcopy.py`，17 步 `code_hash` 不变。

## [0.4.2] - 2026-10-18

PATCH。push 删除检查算上锚图（只动 `datastore/`），17 步 `code_hash` 不变。

### Fixed
- `guji db push`／`sync` 推送前的删除检查把锚图（`anchor_patches_meta`）也算进去：v0.4.0 及更早版本 pull 的数据目录里没有锚图，原先会把库里的锚图当本地删掉一并推走（10-19 D 推 vol01 裁决前在 dry-run 里发现，没推）。现在不加 `--allow-delete` 就整次拒绝。只动 `datastore/workcopy.py`，17 步 `code_hash` 不变。

## [0.4.1] - 2026-10-18

PATCH。中心库拉图提速、锚图还原（只动 `datastore/`），17 步 `code_hash` 不变，不用重算。

### Fixed
- `guji db sync|pull|migrate` 拉图提速（10-19 D 反馈：18,481 张刻例图拉了约 20 分钟）：签名本来就每 1000 张批量签，慢在取图一张一次 TLS 握手、只开 8 线程。`WorkerSource.fetch_blobs` 改为每线程留 HTTPS 长连接（走系统代理的 CONNECT 隧道）、缺省 32 线程（`GUJI_DATA_FETCH_WORKERS` 可改），闲置连接被关立刻重连；超过 2000 张时每 2000 张在 stderr 报一次进度。云端实测 3000 张小图：约 30 张/秒 → 约 220 张/秒。取图走签名直链（更正见 0.4.4：直链指向 Worker，每张图算一次 Worker 请求）。
- 锚图（`feedback/anchor_patches/**.png`）只记在 `anchor_patches_meta`、不进 `source_files`，`pull`／`sync` 从没把它们还原到数据目录，`migrate` 则把检出里的每张锚图都报成「与中心库不一致」（服务器 siku-zongmu 报 1946 个）。`_db_manifest` 与 `materialize` 现在把这张表算进来。
- 只动 `datastore/`（不进任何 Step 的 `code_deps`），17 步 `code_hash` 不变。

## [0.4.0] - 2026-10-18

MINOR（用户 2026-10-19 同意：609 改指纹、没冻结的册重算一次）。release note 见 `RELEASES.md`。

### Changed
- 字形库指纹改成「步骤读到的内容」的哈希（GUJI-609，工作包 8.8）。写入切换后 glyph.db 每拉到新字形库就从中心库整库重建，旧指纹的 `(条数, 最大 rowid, 时间戳)` 会随 rowid 重排白白变。新模块 `clustering/glyph_fp.py`（不进任何 Step 的 `code_deps`）：
  - `seed_admit.human_fingerprint` 改取人裁通道真正读的 `(实例 id, 字头)` 排序后的哈希（`h1:<条数>:<哈希>`），与 `_human_shapes` 同一条查询（`glyph_fp.HUMAN_SQL`）。复制、VACUUM、重建、撤了同字重进、机器准入都不变；人裁进库、撤裁、字头改判才变。
  - `rare_candidates` 加参数 `db_font_fingerprint`（字体域清单哈希，自动填，库里没有字体域是 `none`）：中心库重建的 glyph.db 不带字体域，要另跑 `glyph-db import-font`，带不带、导的哪版字体从此看得见。`import-font` 导入时在新表 `font_manifests` 记字体文件 sha256、字表 sha256、渲染数（这张表不导出进账本）；更早导入的退回按实例数。
  - 设计第六节写的是「库版本号 rev」。改用内容哈希：产物在各自机器上，同一份内容在不同机器、不同时候拉到的 rev 不同；本地人裁还没推时没有 rev；推完 rev 变了内容没变会白白再过期一次。精度相同。
  - `glyph_match.db_fingerprint` 不动：它是软参数（只记漂移不判过期），重建后同内容的库戳本来就相同（实测两次重建逐位一致），为它改 `glyph_match` 会让最贵的一步全书重跑。
  - **影响**：`seed_admit`（f0f2713200ae880e → 50bdd1fb5f0bcbd1）、`rare_candidates`（ac757fe8b73ba312 → 4168770d80cbde67）的 `code_hash` 变，参数指纹也变；没冻结的册这两步及其下游重算一次，判决不变（产物里只有指纹字段变）。冻结册按冻结基线比快照，不受影响。其余 15 步不变。

## [0.3.5] - 2026-10-18

PATCH。中心库客户端与写入切换（数据迁出工作区、`guji db sync` 自动合并、每日备份；GUJI-606/608/611），group_flow 第三批形近字组。相对 v0.3.4 只有 `seed_admit` 的 `code_hash` 变（6a4e2bd27c35fa8a → f0f2713200ae880e），其余 16 步不变；没迁进中心库的工作区行为不变。

### Added
- 字组：按字分类的异体组再加 啓啟 厯歴 絕絶（qik lih jue），模板来自 sheldon 10-20「异体对第二批」人裁（vol01、vol04–10），按册留一 0 错。册配置 `group_flow` 点名才生效。
- 字组：两形混用的异体组 叙敘 冊册 教敎（xu ce jiao）走在线 IDS 新判法「按字分类」（`IdsSpec.by_form`）：自动缝切开，取有差别的那段与各字的同段真实刻例比最近邻。模板来自 sheldon 10-20 合审的殿本人裁（vol04–10），按册留一 0 错。册配置 `group_flow` 点名才生效。
- 字组：第三批只看字频的异体组 刊刋 既旣 清淸 顚顛 淄湽 青靑（kan jiw qx dx zx qy；殿本全书人裁只见一形，sheldon 10-20 合审定）。要在册配置 `group_flow` 点名才生效。
- 字频解法阈值 20→10，且主形人裁须来自至少两册（2026-10-20，sheldon 定）：`seed_admit.group_flow_freq_major` 缺省 10、新参数 `group_flow_freq_min_vols` 缺省 2（0＝不查）；字频表新增 `vols`（每个刻形有人裁的册数，旧表没有就不查册数）。现有数据里新放行的只有 變𠮓（17，来自 vol01–03）；彙彚 12 只来自 vol01，仍弃权。`seed_admit` 的 `code_hash` 变，参数哈希变（用 group_flow 的册）。
- `guji db status|pull|branch|import`：中心库客户端（GUJI-606，工作包 8.5）。`pull -w <工作区>` 经 guji-data Worker 把字形库账本按当前版本还原到 `<工作区>/output/central/<分支>/output/glyph_store/`（每个文件核 sha256，刻例图按 sha 从 R2 拉进本地缓存 `GUJI_DATA_CACHE`、去重），再重建 `glyph.db`，等价于 `glyph-db rebuild --no-replay --no-borrow`；git 管着的 `output/glyph_store/` 不动，库旁写 `glyph.db.central.json` 记分支与 rev。`--rev N` 只在该工作区 N 之后没变时放行（中心库不存旧内容），`--with-feedback` 连 feedback/ 一起还原。`branch create|delete` 开删实验分支，`import --from exp/<名>` 把实验分支的事件显式导入正式库（经 Worker `/v1/events`，按事件 id 幂等；写入切换 GUJI-608 前 Worker 不接受写 main）。连接只认 `GUJI_DATA_URL`／`GUJI_DATA_TOKEN`／`GUJI_DATA_BRANCH`。新模块 `datastore/client.py`、`materialize.py`、`pull.py`、`cli_db.py`，不进任何 Step 的 `code_deps`，**17 步 `code_hash` 全部不变**（逐步对照验过）；不用就没有任何影响。`python -m open_guji_cv.datastore r2-plan --via worker` 改为每 200 张调一次 `/v1/assets/sign-batch`（旧版 Worker 退回逐张签）。

- **数据迁出工作区**（GUJI-608，2026-10-19，用户定）：中心库是册 yaml、人裁事件、台账、批次、人工配置、字形库唯一的家，工作区里只留 `workspace.yaml` 和标记 `.central.json`，数据在工作区外的数据目录 `$GUJI_DATA_HOME/<分支>/<工作区 id>/`（缺省 `~/.guji-data`）。`core/workspace` 加 `data_root`／`books_dir`／`ws_config_dir`，见到标记就把数据路径指向数据目录，没有标记照旧；各处从工作区根直拼的路径改走这些函数（`core/book`、`corpus_pin`、`seed_admit`、`groups/freq`、`groups/ids_online`、`collate_consumers`、`snap/*`、`deploy_check`、控制台工作区列表），守卫 `tests/test_central_paths.py`。新命令 `guji db migrate`（核对后挪数据、写标记，glyph.db 不动）、`guji db pull`（中心库 → 数据目录，拉到新字形库才重建 glyph.db）、`guji db push`（拿库锁后先比版本号，别人先写过整次拒绝；只追加台账少行、整个文件丢了也拒绝；glyph.db 改过先导出；新图先经 Worker 传正式桶；连库用 `GUJI_DATA_PG_DSN`，没有就从 `NEON_DATABASE_URL` 自动起 443 桥）。迁过的工作区上 `guji store commit|check` 改为推中心库，close-check 第 8 项改查没推的改动。新模块 `datastore/workcopy.py`、`ops/central_glyph.py`；`importer.import_scans` 从 `import_commit` 拆出（加 `guard` 钩子）；旧的 `db pull` 只读快照（`output/central/`）删掉。**`seed_admit` 的 `code_hash` 变**（50b4c7c96150b33d → f0f2713200ae880e，字组表改从数据目录找；本版字组第三批已经让它变过一次），其余 16 步不变。没迁的工作区行为一字不变。

- `guji db sync -w <工作区> [--dry-run] [--watch 秒]`（GUJI-608 B 块）：拉＋合并＋推一步做完。别人先写过时不再整次拒绝：库里改了本地没改的取库里的，只追加台账（events、consumed、anchors）两边都追加了就把两边的新行都留下，其它文件两边都改了才停（`SyncConflict`，本地不动）。`--watch` 定时反复做，冲突与断网只记日志，用来替代服务器上 30 分钟一次的 `guji-glyph-store-sync.timer`（往 guji-workspace git 提交）。只动 `datastore/workcopy.py`、`cli_db.py`，17 步 `code_hash` 不变。

- 中心库备份与恢复演练（GUJI-611）：`python -m open_guji_cv.datastore backup` 在一个只读快照里把全部表 `COPY` 出来、gzip，附清单（每表列、行数、排序后哈希、序列值、rev），经 Worker `/v1/backups` 存进正式桶 `backup/<日期>/`，清掉超过 30 天的；`restore-check --endpoint <ci 端点>` 取最新一份完整备份恢复到 main 以外的分支（给 main 的端点直接拒绝）并逐表核对。首次实测（10-19，rev 1356）：26 张表 189,964 行，备份 12 MB、31 秒；恢复到 ci 分支 39 秒，逐表行数与哈希全部一致。连库抽成 `datastore/connect.py`。

### Removed
- 往 guji-workspace git 提交数据的旧路径（GUJI-608/611，2026-10-19，用户定「后面这些数据在中心库的就不应该再出现在 workspace 里面」）：删 `scripts/glyph_store_sync.py`（服务器 30 分钟一次的 `guji-glyph-store-sync.timer`，由 `guji db sync --watch` 替代）、`scripts/snapshot_glyph_store.py`、`clustering/store_merge.py`（git 三方合并）、`ops/store_commit.py`（`guji store commit` 的 git 路径）及其测试。`guji store check|commit` 现在只推中心库，没迁的工作区直接提示先 `guji db migrate`；close-check 第 8 项同理。近似字 store 导出与重建的两条用例挪进 `tests/test_approx_store_export.py`。runbook S14、`workspace_layout`、`.claude/CLAUDE.md` 等文档改成中心库口径。17 步 `code_hash` 不变。

### Fixed
- 中心库 push／sync 判「glyph.db 改过要先导出」改用导出签名（`ops/central_glyph.export_signature`，即原 `glyph_store_sync.db_signature`），不再用匹配器库指纹：只标了／撤了近似字、改了实例 label／ids 时匹配器指纹不变，此前这类改动会漏推。
- 中心库客户端与 `r2-plan --via worker` 遇到断流（`http.client.IncompleteRead`）也退避重试，不再整次中断（2026-10-18 正式桶上传时碰到）。
- group_flow 第三批形近不同义字组（2026-10-19，sheldon 定）：論諭 `ly`、大太 `dt`、問間 `wj`、曾會 `zh`、遺還 `yh`，按文意（L1 规则＋haiku 答案表，只收 conf=high，只补放不复核）。注册表加 5 个 `GroupSpec`，配置 `config/groups/{ly,dt,wj,zh,yh}/{rules.yaml,prompt.md}`，扩展脚本 `ext_enum_cells.py`／`ext_make_batches.py` 加 `--groups`。缺省关（书 yaml 的 `group_flow` 点名才生效）。vol04 A/B：组外格逐格不变，放行 +10（曾會，均无强真值可对），报告 `doc/exp/group_flow-3-vol04-报告.md`。PATCH；**`seed_admit` 的 `code_hash` 变**（6a4e2bd27c35fa8a → 50b4c7c96150b33d），其余 16 步不变。
- group_flow 第四批形近字组（2026-10-19，sheldon 定）：象彖 `xz`、王玉 `wyu`、圓圖 `yt`，做法同第三批（L1 规则＋逐册 L2 haiku 表，只补放不复核；彖傳／象傳、玉篇／帝王篇、方圓等两可词弃权）。vol04 A/B 组外格 0 变化，放行 +1（该册这三组几乎都已被放行，收益在没放行的册），L1 对整理本零冲突。`seed_admit` 的 `code_hash` f0f2713200ae880e → c3dbd4dac0582b47，其余 16 步不变。报告 [group_flow-4-vol04-报告](doc/exp/group_flow-4-vol04-报告.md)。
- group_flow 第五批八组（2026-10-19）：目自 `mz`（与日目 `rm` 共用「目」，互相声明 `overlaps`）、一二 `yr`、千干 `qg`、十卜 `sb`、甲申 `js`、而面 `em`、傅傳 `fc`、木本 `mb`，均形近不同义、按文意（L1 规则先行，弃权查 L2 haiku 表，只收 conf=high），补放也复核（只降审不改字）。L1 规则由整理本奇偶册交叉验证生成（两半都不矛盾才收），再手工剔掉「蔡傳」「王宗傳」「草本」类两可词，对 vol02–10 整理本零冲突；一二的 haiku 表对整理本有 5% 分歧，不稳，**一二只用 L1、不挂 L2 表**。vol04 A/B：组内格 0 降审、0 改字，补放 +4（千 1、十 1、傅 1、一 1；其中三格整理本为空，未逐格看图），其余 4000 多个组内格都是「文意与现放行字一致」；原因是这八组在 vol04 几乎都已被基线放对。`seed_admit` `code_hash` f0c37eac6214999c → e05fed6d5f32f4b7，其余 16 步不变。报告 [group_flow-6-vol04-报告](doc/exp/group_flow-6-vol04-报告.md)。
- group_flow：允许组成员重叠＋形近组复核＋日目组 `rm`（2026-10-19，sheldon 定）：①`GroupSpec.overlaps`（须互相声明），`flow.entry` 一个字可属多个组——补放选第一个装得下「分差内全部候选＋整理本字」的组，复核选第一个声明了 `review` 且装得下整理本字的组；日曰 `ry` 与新组日目 `rm`（L1＋L2 haiku 表）共用「日」，日曰候选归 ry、日目候选归 rm、三者混杂留人审。②已放行格复核（只降审、不改字）：`ry wxs ly dt wj zh yh xz wyu yt rm` 打开 `review`（原来只有 jys／rr）。③`seed_admit` 的待审补放通道（witness3／coord_fallback）不再把复核判了 `group_flow_disagree`／`_conflict` 的格放回去（原来降审被 coord_fallback 按整理本字又放行，白降；含 jys／rr 原有的降审）。vol04 A/B：复核降审 8 格（象彖 4、大太 2、問間 1、入人八 1，原来被放回去的那 1 格），无改字；日目 L2 表 57 格答 37；组外格仅 iron 通道 +3（本机重拉字形库后库内容变化所致，与本改动无关）。`seed_admit` `code_hash` c3dbd4dac0582b47 → f0c37eac6214999c，其余 16 步不变。报告 [group_flow-5-vol04-报告](doc/exp/group_flow-5-vol04-报告.md)。

## [0.3.4] - 2026-10-18

PATCH。语料库 corpus-vN（清单、册钉子、补指纹缺口）、group_flow 第二批异体组、清理旧字组代码。相对 v0.3.3 只有 `seed_admit` 的 `code_hash` 变（9d3e5deb232d84f2 → 6a4e2bd27c35fa8a），其余 16 步不变；各册 Step7 本来就要用新字组重算，下面各条自述的中间 `code_hash` 以此为准。没写 `corpus:` 的册其余指纹逐位不变。

### Added
- 册钉了语料库版本（`corpus: N`）后，读语料的 5 步（`glyph_match`、`rare_candidates`、`context_decide`、`align_ref`、`seed_admit`）的指纹整步多带一个 `corpus-vN`（P2，2026-10-18）：补上此前没有内容指纹的输入——形近表（`confusable_*`、`NEVER_MATCH_FAMILIES`）、`context_decide`／`align_ref` 的异体表、`rare_candidates` 的字表与部件库。几何步不受语料库升级影响。名单登记在 `core/corpus_pin.CORPUS_STEPS`（不放进 `StepSpec`，免得改 Step 源码让 `code_hash` 变）。没钉的册指纹逐位不变，17 步 `code_hash` 不变。
- 册 yaml 可钉语料库版本 `corpus: 1`（P1，2026-10-18，sheldon 定）：钉了之后，`params_for` 把参数里的语料类内容指纹（`core/corpus_pin.PIN_FIELDS`：整理本参考文本、证人、用字账、异体表、异体图、夹注词表、铁证形近、group_flow 字频／规则／答案表共 9 个字段）整体换成 `corpus-v1`，**指纹只认版本号，不看内容**；钉的版本没有清单就报错，清单之后文件被改只警告一次。**不写 `corpus:` 的册一字不变**；17 步 `code_hash` 全部不变（逐步对照 rc/v0.3.4 验过）。字形库、人裁排除名单、模型不属语料，指纹照旧。`ops/corpus_pack.py` 的清单读取与扫描挪进 `core/corpus_pin.py`。
- `guji corpus build|verify|list`（P0，2026-10-18，sheldon 定）：语料库 corpus-vN 的清单，登记流程里读的 51 份语料类文件（整理本参考文本、字频表、L2 答案表、规则、IDS、异体表、形近表、字表）的 sha256 和 `NEVER_MATCH_FAMILIES` 哈希，落 `<工作区>/corpus-pack/vN/manifest.json`；版本号递增、不覆盖；`verify` 发现清单之后又被改的文件。**只登记，Step 仍读原位置，指纹不变，17 步 `code_hash` 全部不变。** 方案见 `doc/design/语料库版本化方案.md`。
- group_flow 第二批异体组（2026-10-18，sheldon 定）：即卽（`ji`）、卿𨜊（`qing`）、變𠮓（`bian`）、彙彚（`hui`），只看字频：主形人裁 ≥20 且次形 0 才放行，数据不够送人审，重算字频表后自动放行。缺省关，按册在 `group_flow` 里点名。`seed_admit` 的 `code_hash` 6f24d51db9b8ebcb → 51a72b61d8354196（注册表在其 `code_deps` 里），其余 16 步不变。字形库清了 3 格误标（變 2、旨 1，工作区 events）。A/B 配置 `doc/exp/group_flow-2-vol04.yaml`、`group_flow-2-vol02-vol03.yaml`：vol04、vol02、vol03 三册新增放行共 3 格（都是卿），變 1 格弃权送审，旨㫖字频解封后放行不变，其余格一格没变。

### Removed
- 清理被 `group_flow` 取代、已无调用的旧字组代码（2026-10-18，sheldon 定）：删 `utils/ry_group.py`（日曰 ry-v2 答案表）、`utils/ji_yi_si_clf.suggest`（己已巳旧答案表）、`groups/backends.py` 的 `RyV2TableBackend`／`JysSuggestBackend`、`eval/groups` 的 `suggest:` 后端与 ry-v2 表识别（`table:` 只认 `group_clf/1`），及对应测试、`research/char_groups/{ry/build_cache,jys/build_clf_table}.py`、`scripts/_from_overview` 里量 group_decide 口径的 `ctx_caliber_compare.py`。`seed_admit` 的 `code_hash` 9d3e5deb232d84f2 → 6f24d51db9b8ebcb（改了 `utils/ji_yi_si_clf` 源码，在其 `code_deps` 里），其余 18 步不变。vol04 A/B：旧码 vs 新码，`seed_admit` 产物逐格一致。
- 删 `seed_admit.rare_cp_ctx_review`（罕用码位×context 落审，缺省关，无书在用；2026-10-18 sheldon 定）：参数、`_rare_cp_ctx_pass`、测试 `test_seed_admit_rare_cp_ctx.py` 及 `test_w5_demoted_from` 里的一条。`seed_admit` 的 `code_hash` 6f24d51db9b8ebcb → eba68e984cd2a5ae，其余 18 步不变。

## [0.3.3] - 2026-10-18

PATCH。字组统一流程 group_flow（新 variant-tie）：收编全部旧字组开关、字频与在线 IDS 两个新解法；删 Step5-c／Step6b。

### Added
- 字组统一流程 `seed_admit.group_flow`（新 variant-tie，2026-10-18 sheldon 定，缺省关）：点名注册表里声明了 `flow` 的字组（首批七个异体组 蒙𫎇／點㸃／參㕘叅／讖識䜟／隸𨽾／慎愼／旨㫖，三个形近组 己已巳／日曰／入人八）；没放行的格若库候选（与 top1 分差 <0.03）＋整理本字全在一组，按组声明的解法给字放行（通道 `group_flow`）或留人审，己已巳、入人八另对已放行格复核；每格写 `evidence.group`。新解法「字频」：按人裁刻形冻结每套书一张表（`python -m open_guji_cv.groups.freq <工作区>`），主形 ≥20 且次形为 0 才给字。`groups/registry.py` 新增 `FlowSpec` 与七组（`groups/flow.py`、`groups/freq.py` 进 `seed_admit` 的 `code_deps`）。PATCH；**`seed_admit` 的 `code_hash` 变**（与下面删 5-c 合计 a995ac96→03ad95f1），关时产物不变。
- `group_flow` 的 `ids` 解法接上在线判别（方案 S7，sheldon 10-18 定）：新模块 `groups/ids_online.py`，字块图自动缝一刀 → 决定字的那一段在冻结模板库里最近邻 → margin ≥ 门槛且该类刻例 ≥8 才给字，否则弃权，`evidence.group` 里留 IDS、部件、margin、各部件分数。首批只开 參㕘叅（`can`，门槛 0.04；人标池 74 格留一 59 对／15 弃权／0 错，留一册 57／17／0；叅只 2 例永不给），模板库 `config/groups/can/ids_bank.json` 由 `python -m open_guji_cv.groups.ids_online build can --dataset <dataset>` 从 dataset 人标池建（工作区 `config/groups/ids/<组>.json` 优先）；模板库、判法参数、`ids_override.tsv`、`ids_lv1.txt` 的哈希进 `group_flow_fingerprint`（没有在线 IDS 的组不加，旧指纹不变）。其余组（彝、慎愼、旨㫖…）没有模板库，照旧弃权且不取图。`groups/ids_online`、`ids`、`ids_two`、`ids_parts`、`ids_segment`、`ids_solver` 进 `seed_admit` 的 `code_deps`。PATCH；**`seed_admit` 的 `code_hash` 变**（ce3a31cce2908038→332a5956257e5a6b），关时产物不变。
- `group_flow` 的表路径：相对路径按工作区解释；没给时用工作区 `config/groups/freq.json`、`config/groups/l2/<组>.json`（有才用）。PATCH；`seed_admit` 的 `code_hash` 变，关时产物不变。
- 字频表计数也认字形库体检的改字／撤库事件（`glyph_audit` relabel／evict），同格按时间取最晚。PATCH；`seed_admit` 的 `code_hash` 变，关时产物不变。

### Changed
- 字组统一流程 `group_flow` 收编旧 m7 的全部字组（方案 S6，2026-10-18 sheldon 定「旧的都并进来、旧的删掉、每册都开」）：注册表给 土士 `ts`、未末 `wm`（文意＋量横）、戊戌戍 `wxs`（文意）补 `FlowSpec`；`FlowSpec` 加三个旋钮——`review_fix`（复核时文意给了别的字就改字，己已巳用）、`review_abstain`（复核时文意弃权就降审，己已巳用，接替旧 `ji_yi_si_clf` 对规则不命中的 `split_ref` 退役）、`lift_needs`（补放必须有这几路之一给字；入人八要文意，字形分类器不许单独补放）；复核时解法互相冲突也降审；形近护栏（`never_match`／`conflict`／`near_form`）不再挡字组；取上下文窗口时剔除排除名单格（与建 L2 表同一取法）。`always_review` 缺省仍是「己已巳」：vol04 A/B 上留着它比改成空多放 3 格对的、少 2 格错降（报告 `doc/exp/group_flow-S6-vol04-报告.md`）。**没在 `group_flow` 里点名 `jys` 的书，`split_ref` 放行的就是整理本字、不再复核**（旧 `_resolve_ji_yi_si` 删了）。vol04 A/B（旧开关全删＋13 组 vs 现行配置）：组外格逐格不变，放行 +47，强真值上放行 72 对 0 错 → 81 对 0 错，错降 1。PATCH；**`seed_admit` 的 `code_hash` 变**（与下条删旧开关合计，以 S7 之后为底 332a5956257e5a6b → 9d3e5deb232d84f2），各册该步判过期，其余 16 步不变。

### Removed
- 旧字组开关并进 `group_flow` 后删除（方案 S6）：`SeedAdmitParams` 删 `ji_yi_si_review`、`ji_yi_si_ctx_rule`（`_purity`／`_min_n`／`_fingerprint`）、`ji_yi_si_clf`（`_llm`／`_margin`／`_table`／`_fingerprint`）、`ry_group`（`_cache`／`_fingerprint`）、`rr_clf`（`_p`／`_model`／`_fingerprint`）、`m7_groups`／`m7_l2_tables`／`m7_fingerprint`／`m7_bars`、`variant_tie`（`_cov`／`_extra`）共 24 个字段；删 `_resolve_ji_yi_si`、`_ji_yi_si_clf_cell`、`_ctx_known`、`_ry_group_pass`、`_rr_clf_pass`、`_m7_group_pass`、`_variant_tie_ok` 与主循环的 `variant_tie` 通道；删 `groups/m7_pass.py`（`judge`／`fingerprint` 挪进 `groups/flow.py` 为 `ctx_judge`／`ctx_fingerprint`）、`groups/apply.py` 与注册表的 `GroupPolicy`／`GroupSpec.policy`、`utils/ji_yi_si_clf.STRONG_CHANNELS`。`seed_admit` 的 `code_deps` 去掉 `utils.near_form_ctx`、`utils.ry_group`、`groups.m7_pass`、`groups.apply`（`utils/ry_group.py`、`utils/near_form_ctx.py` 只剩离线评测用）。书 yaml 里的旧键读进来被忽略（pydantic 缺省忽略多余字段，不报错），应从十册 yaml 里删掉；`tests/test_group_params_guard.py` 的白名单清空。PATCH；`code_hash` 见上条。
- 删两个不再用的步骤（2026-10-18，sheldon 定）：Step6b `group_decide`（连同产物 `group_decision`、书级 `group_decide:`）与 Step5-c `ocr_candidates`（连同产物种类、书级 `ocr_candidates:`、控制台开关 `PUT /api/books/{book}/ocr_candidates` 与汇总 `GET /api/ocr-candidates/{book}/summary`、前端 5-c 子页）；两条 pipeline yaml 去掉这两步，老 yaml 里的两个键读进来无作用。`align_ref`／`context_decide`／`seed_admit` 不再把 `ocr_candidates` 列为可选上游，OCR 一路恒缺席（等价于原先开关关着，四庫 vol01–10 输出语义不变）。**这三步 `code_hash` 变**（215217611967ce6c→e66b1c3f632c469a、043c75a9ba56ddae→4a12db2db381a543、a995ac964c981e29→03ad95f1c34eb510（连同本版 group_flow）），各册这三步判过期；其余 14 步不变。

## [0.3.2] - 2026-10-17

PATCH。版本护栏、冻结基线、`archive fetch`、`rerun --stale`、规矩文档（没赶上 0.3.1 的 4 个 PR），中心库导入（`datastore`），以及 GUJI-555／622 积下的几个缺省关开关（夹注忽略 rule_bar、遮挡救回、绑定严格档、column_gate 周期先验）。

### Added
- 产物 manifest 每条记 `cv_version`（最近正式 tag，不在 tag 上写 `0.3.0+N`，有未提交改动加 `+dirty`）与 `cv_commit`（完整 sha）；册配置可写 `cv_version`，`guji step`／`pipeline` 发现装的版本不同就拒跑（`--allow-cv-mismatch` 放行），`status`／`progress` 只提醒（GUJI-577，版本号规矩第五节）。PATCH；`core/engine.py`、`core/book.py`、`core/cv_version.py`、`products/manifest.py` 都不在任何 Step 的 `code_deps`，新字段不进 `book_deps`，19 步 `code_hash` 不变。
- 冻结基线（GUJI-601，规矩见 ai-team `domain/CV/规范/冻结基线与重跑分级.md`）：册 yaml 写 `freeze: {at, cv_version, snapshot|manifest}` 后，`guji close-check` 1a 改比快照 manifest 的产物 sha256，不再因 cv 升版、人裁进库报过期；只有产物被改／缺、册配置或参数被改才不过（各步 `_manifest.jsonl` 不比；旧条目分不清代码还是册配置的单列请人核）；另报「基线后新人裁 N 条待落地」（`ops/freeze.py`）。PATCH；`ops/`、`core/book.py` 不在任何 Step 的 `code_deps`，`freeze` 不进 `book_deps`，19 步 `code_hash` 不变。
- 新命令 `guji archive fetch <tag> --out <空目录>`：取回 open-guji-dataset Release 上的归档 tar，按 `--sha256` 或资产自带 digest 核对后安全解包（拒越界路径、设备文件；跟随重定向跨域时去掉 token）（`ops/archive_fetch.py`，GUJI-601）。PATCH（10-18 起新 CLI 命令只算 PATCH）；不碰任何 Step。
- 新命令 `guji rerun --stale <册>`：只重跑 manifest 里显式标了失效（人裁落定等）的页，逐步往下传，只把上游真重算了的页交给下游；上游跳过的页不往下传，因 cv 升版、字形库变化而过期的页不跑（`ops/rerun_stale.py`，GUJI-578，设计 §5.2 第 4 条）；与 pipeline 一样过 cv 版本护栏（`--allow-cv-mismatch` 放行）。PATCH；不碰任何 Step，19 步 `code_hash` 不变。
- 中心库 `open_guji_cv/datastore/`（GUJI-603／605）：Postgres 表结构 `schema.sql`；从 guji-workspace 某个提交幂等导入（`python -m open_guji_cv.datastore import`，按主键比内容哈希、全局 rev、只追加台账的删除护栏）；库与提交逐行核对（`verify`）；刻例图与锚图按 sha256 上 R2 的计划与上传（`r2-plan`，默认只出清单）。新 extra `datastore`（psycopg、boto3、websockets）；只通 443 时用 `datastore.wsbridge` 经 Neon 的 WebSocket 连库。说明见 `doc/参考/datastore.md`。PATCH；新包，19 步 `code_hash` 不变。
- 闸2 `column_gate` 两个周期开关（GUJI-622／GUJI-364，vol01 p196）：`period_prior_pages`（点名页不估页级周期，直接用书级 `period_prior`，记 flag `period_fallback`）与 `period_edge_fallback`（估值贴窗口下界 ≤ int(先验×0.7)+1 时回落先验）。都缺省关，关时不进参数 dump、产物逐字节不变。PATCH；**`column_gate` 的 `code_hash` 变**（8935ff6f → 25658f2b），各册该步判过期，重跑后产物不变、下游不重算。
- 人裁绑定 R1/R3 严格档（环境变量 `GUJI_BINDINGS_STRICT`，缺省关，关时行为逐字节不变；GUJI-555）：补锚 ink 路径 rebound 且上下文核对 `differ`→待审；同页同列整列同量偏移无 ctx 旁证→待审；`human_chars` 同格更晚事件不可用时更早事件不顶上、rebound 落点有更晚原生事件时让位。动 `feedback/`，19 步 `code_hash` 不变（worktree 复算）；开关不进参数指纹，开了要手动重算 seed_admit。
- `seed_admit.nonchar_jiazhu_ignore_rule_bar`（缺省关，方案 A）：开了 `nonchar_gate` 对夹注格不再因 `rule_bar` 撤回放行；关着不进参数哈希（GUJI-555，vol04 p216／p218）。动 `seed_admit` 的 `code_hash`，**seed_admit 及下游步产物判过期**，窗口合并，同 cv#102 只让该步过期一次。
- `seed_admit` 参数 `occluded_rescue_ink`（缺省 0＝关）：遮挡块里格内大块墨占比 ≥ 该值的清楚的字格不算遮挡（GUJI-555，vol04 p130 前 8 格误判 occluded）。`cell_shrink`、`seed_admit` 的 `code_hash` 变（`steps/occlusion.py` 在二者 `code_deps` 里），关着时输出不变。

### Changed
- 版本号规矩（`doc/版本号规矩.md` 第二、三、六节，用户 2026-10-18 定）：任何时候都有一条待发分支 `rc/vX.Y.Z`（缺省 PATCH 加一，CHANGELOG 记在 `## [X.Y.Z] - 待发` 节），功能分支合进它、不直接合 main；合进来的改动缺省关、随时可发，谁都可以发 PATCH；MINOR 收紧为「对大部分册值得重跑一遍」，新增 CLI 命令或参数只算 PATCH。文档改动，PATCH。

### Fixed
- `close-check` 2b「人裁字≠放行字」：字形与放行字互为规范字／异体（埀↔垂 类）的单列 `kind=canon`，不再混进正文一类（GUJI-555）。PATCH；仅 `review/verdict_view`、`cli_v2`，19 步 `code_hash` 不变。

Step 的 `code_hash` 相对 `v0.3.1`：`column_gate`（GUJI-622）、`seed_admit`（夹注忽略 rule_bar、遮挡救回）、`cell_shrink`（`steps/occlusion.py`）3 步变，其余 16 步不变；新开关全部缺省关，关时产物不变。

## [0.3.1] - 2026-10-17

集成分支 `rc/v0.3.1`，M7 扩展（第二阶段）；各功能 PR 合入时在此补条目。

### Added
- M7 上下文路扩展：戊戌戍／未末／土士的 L1 规则与 L2 提示词（`config/groups/{wxs,wm,ts}`）及研究脚本 `research/m7/ctx/ext_*.py`（#118）。**尚未接线**（registry 无对应 GroupSpec），不生效；19 步 `code_hash` 不变。
- M7 量横画法：土士／未末按两横长短取字的研究脚本 `research/m7/bars/` 与结论文档（#119）。仅研究脚本与文档，19 步 `code_hash` 不变。

- 量横长短 ts／wm 接进 `seed_admit`（书级开关 `m7_bars`，缺省关）与 registry 的 wxs／wm／ts 登记（#120、#121）；IDS 两段版 `groups/ids_two.py` 与參㕘叅配置（#117，未接 Step）。

Step 的 `code_hash` 相对 `v0.3.0`：仅 `seed_admit` 变（684cd42c → a60d8f25），其余 18 步不变。vol04 组合 A/B 见 `doc/exp/m7_rc031-vol04-报告.md`：组外差异 0。

### Fixed
- 引擎页级并行（`--jobs>1`）：worker 改由主进程直接传入册、管线、合并后的参数与产物／缓存根目录，不再按 id 重新加载。以前 CLI `--params` 与管线 yaml 的 `params:` 在并行步（`border_detect`、`line_detect`）上全丢，产物按缺省参数算、指纹却记覆盖后的参数；沙箱 `ProductStore` 也被忽略（GUJI-580）。PATCH；`core/engine.py` 不在任何 Step 的 `code_deps`，19 步 `code_hash` 不变。

## [0.3.0] - 2026-10-17

### Added
- Step1 `border_detect`：窄对合并 `merge_narrow_pair`（缺省关，不进参数 dump）：相邻两条内部窄列、宽度和≈一列时用 `expected_cols−1` 重探，去掉把大字列劈成窄条的伪竖线（GUJI-572，vol04 p80／p217）。`border_detect`、`border_detect_gate`、`column_gate` 的 `code_hash` 变，关着时输出逐字节不变。
- M7 形近字优化算法（GUJI-563）的库代码 `open_guji_cv/groups/`：IDS 路（`ids*.py`，彝六字形，通用 IDS 语法、折线切分、字体模板二选一）与上下文路（`context.py`/`ctx_l1.py`/`ctx_l2.py`，日曰／己已巳／入人八，上下各 20 字）；注册表加 `kind`／`solvers`／`config_dir`；`config/groups/<组>/` 规则与提示词。**尚未接进任何 Step**，缺省不生效。
- `seed_admit` 的 M7 接线开关 `m7_groups`／`m7_l2_tables`（缺省关）与 `groups/m7_pass.py`（GUJI-563）；`doc/exp/m7_groups-vol04.yaml`、`doc/exp/跑实验经验.md`。
- 设计与评测：`doc/design/M7-*.md`、`research/m7/`。
- `scripts/zhengli/collect_exit.py`＋`exit_report.py`：对一册自动取粗校出口 R1–R5 的数并拼固定格式报告（GUJI-556）。PATCH；仅 `scripts/`，19 步 `code_hash` 不变。
- `guji close-check --tier rough|final`（缺省 `final`，行为不变）：粗校档第 2 项「待审清零」只报数、不计（GUJI-555）。PATCH；仅 `ops`/`cli_v2`，19 步 `code_hash` 不变。
- `guji-cv pipeline --isolate-steps`：每个 Step 一个独立子进程跑（默认关），整册跑时内存不再逐步叠加（GUJI-555）。PATCH；仅改 `cli_v2`，19 步 `code_hash` 不变。
- `scripts/relanding/`：重落后核对脚本（manifest_cmp／relanding_diff／products_snapshot），从 guji-workspace 的 exports 迁入（GUJI-555）。PATCH；仅 `scripts/`，19 步 `code_hash` 不变。

### Fixed
- `guji snap import` 认 `GUJI_PRODUCTS_DIR`（沙箱），不再无视它写进工作区本体的 `products/`（GUJI-555）。PATCH；`snap/` 不在任何 Step 的 `code_deps`，19 步 `code_hash` 不变。
- 导出（`export format`／`export_guji_page.py`）：看图判错、人还没裁的放行格记 `review: pending`（并带 `vision_flag` 标记），不再当已校对写进 char.json；与 close-check／控制台待审同口径（GUJI-555）。PATCH；`formats`/`feedback` 不在任何 Step 的 `code_deps`，19 步 `code_hash` 不变。

Step 的 `code_hash` 相对 `v0.2.1`：`border_detect`、`border_detect_gate`、`column_gate`、`seed_admit` 4 步变化，其余 15 步不变（实算 `core.engine.code_hash`）；新参数缺省关、关时不进参数 dump。

## [0.2.0] - 2026-10-17

### Added
- guji-proof 0.2 审阅字段模块 `open_guji_cv/review/proof_fields.py`。
- 统一字组接口 `open_guji_cv/groups/` 与统一评测 `open_guji_cv/eval/groups.py`（尚未被任何 Step 引用）。
- 字组参数守卫 `tests/test_group_params_guard.py`：不许再往 `SeedAdmitParams` 加新的字组参数。
- 包分层守卫 `tests/test_architecture.py` 与 `doc/参考/module_map.md`。

### Changed
- 版本号规矩改为 `vX.Y.Z` tag、按 PR 滚动升版。

### Removed
- 旧 exe 发布流水线 `release.yml`（移至 `doc/archive/release.yml.legacy`）。
- 死代码：`steps/step6_signals.py`、v1 桥。

Step 的 `code_hash` 相对 `cv-v0.1.0` 无变化（19 步逐位相同）。
