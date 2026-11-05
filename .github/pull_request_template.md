## 改了什么

<!-- 一两句话。动代码的在 CHANGELOG `## [未发版]` 下加一行。 -->

## 档位与影响（doc/版本号规矩.md 第二节、第七节）

- 档位：PATCH / MINOR（MINOR 先问用户）
- `code_hash` 变了的步（对比合并前的 dev 实算）：无 / …
- 缺省输出变不变：不变（新行为缺省关） / 变（附 A/B，见 doc/开关登记表.md 门槛）
- 影响的书/Step/指纹变化：无 / 殿本 … / 史記 … / 全唐文 …（写明哪几步指纹变）
- 降人审轮次档：不涉及 / D 档（只到 `seed_admit`，不动格号） / S 档（切分、页型、图源、语料、字形库，格号可能变）

## 验证

- [ ] 全量测试（装 torch 的环境）
- [ ] `python scripts/check_rc_target.py <目标分支>` 返回 0
- [ ] `guji-manager iterate freeze check --file <ai-team>/domain/CV/质检/迭代降人审框架/冻结日历.yaml --books … --steps …` 没撞冻结（只冻 S 轮）
