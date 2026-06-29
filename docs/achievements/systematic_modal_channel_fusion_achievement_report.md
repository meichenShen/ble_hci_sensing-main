# 模态×信道 系统性融合 — 成果汇报

> **面向**：人（研究员 / 合作者）  
> **来源**：[`systematic_modal_channel_fusion_plan.md`](../plans/systematic_modal_channel_fusion_plan.md) → [`systematic_modal_channel_fusion_report.md`](../reports/systematic_modal_channel_fusion_report.md)  
> **日期**：2026-06-08  
> **验证状态**：已完成（P0 Block A/B/C；P1 D1–D3 未做）

---

## 1. 摘要

- **目标**：分离信道融合策略和模态融合策略的独立贡献，填补两种维度交叉的盲区，找到 (信道策略 × 模态策略) 二维网格中的全局最优组合。
- **结论**：**B1（Vote per modal → 三模态等权谱融合）以跨域 mean 8.45% 成为新的全局最优**，突破了理想成功标准（< 8.5%），超越了 G4（8.65%）。但原计划预期的 Vote→Top2 路径（H3）未成立——最优模态融合权重是 **Equal** 而非 Top2。**信道策略与模态策略存在显著交互效应**（H2 已验证），验证了本 plan 核心方法论的正确性。
- **关键数字**：
  - 全局最优：B1 = **8.45%**（vs G4 8.65% / T0-V3 9.20% / Modal top2 9.45%）
  - 理想标准（< 8.5%）**已达成**
  - 良好标准（< 9.0%）达成的还有 G4、C2（9.15%）、B2（9.16%）
  - Vote→Top2（B3 = 9.92%）**未达成**最低标准
  - Phase voting 跨域 11.07%（vs Remote voting 9.20%）— H1/H4 **仅单场景支持**
  - Persistence 在模态融合下严重退化（A2 17.49%, B4 16.59%）— H5 **已废弃**

---

## 2. 方法与实验设置

### 2.1 问题背景

回顾所有既有实验，每种"方法"实际上在信道策略和模态策略两个维度上各取了一个点：

```
Single Remote   = 信道: Single best × 模态: Remote only
T0-V3           = 信道: 72-tone voting × 模态: Remote only
Modal top2      = 信道: Single best per modal × 模态: Top2 谱融合
```

**当我们在 leaderboard 上比较这些方法时，无法区分**：T0-V3（9.20%）低于 Modal top2（9.45%），是因为 voting（信道策略）不如 single-best？还是因为"只用 remote"（模态策略）不如"三模态 top2 融合"？

本实验系统性地填充了 **信道策略 C × 模态策略 M** 的二维网格中 12 个关键盲区单元格。

### 2.2 二维策略网格

**信道策略（C 维度）**——每模态独立执行：

| 代号 | 策略 | 说明 |
|------|------|------|
| C-Single | max-η 单信道 | 与现有 Single 一致 |
| C-Uniform | 72 信道谱等权平均 | 与现有 Uniform 一致 |
| C-Vote | 72 信道 η·ρ 加权 BPM 投票 | T0-V3 的 per-tone voting |
| C-VoteP | Persistence-filtered voting | G6：剔除不稳定 tone 后 voting |

**模态策略（M 维度）**——融合三种模态的频谱：

| 代号 | 策略 | 说明 |
|------|------|------|
| M-Remote | 只用 remote | 基线 |
| M-Phase | 只用 phases | 验证 phase voting |
| M-Equal | 三模态等权谱融合 | Modal equal |
| M-η | 三模态 η 加权谱融合 | Modal η-weight |
| M-Top2 | 每窗取 top2 模态等权谱融合 | Modal top2 equal |

### 2.3 新增方法（P0，8 个）

| ID | 方法 | 信道 × 模态 | 目的 |
|----|------|-------------|------|
| A1 | Phase η·ρ voting | C-Vote × M-Phase | Phase voting 是否优于 Remote voting？ |
| A2 | Phase persistence voting | C-VoteP × M-Phase | Persistence 在 phases 上是否有效？ |
| B1 | Vote→Equal modal | C-Vote per modal × M-Equal | **核心**：Voting + 三模态等权融合 |
| B2 | Vote→η modal | C-Vote per modal × M-η | Voting + η 加权融合 |
| B3 | Vote→Top2 modal | C-Vote per modal × M-Top2 | **核心**：Voting + top2 模态融合 |
| B4 | VoteP→Top2 modal | C-VoteP per modal × M-Top2 | Persistence voting + top2 |
| C1 | Uniform→Top2 modal | C-Uniform per modal × M-Top2 | Uniform 替代 single-best 做信道 |
| C2 | Uniform→η modal | C-Uniform per modal × M-η | Uniform + η 加权模态 |

### 2.4 场景与 Baseline

| 场景 | 数据 | 特点 |
|------|------|------|
| cs_091339 | `CS_frames_all_20260113_091339.jsonl` | voting 退化场景 |
| cs_095806 | `CS_frames_all_20260116_095806.jsonl` | voting 优势场景；段 4b 略短于窗长 |
| cs_102621 | `CS_frames_all_20260116_102621.jsonl` | 跨域对照 |

**实验参数**：滑窗 20 s / 1 s 步，呼吸带 0.1–0.35 Hz。Voting→谱构造方式 = conf 加权全 tone 谱平均（方案 B）。

---

## 3. 核心结果

### 3.1 主结果表

| 排名 | 方法 | cs_091339 | cs_095806 | cs_102621 | **跨域 mean** |
|------|------|-----------|-----------|-----------|---------------|
| **1** | **B1 Vote→Equal modal** | 13.22 | **6.50** | 5.63 | **8.45%** |
| 2 | G4 Single fallback | 12.39 | 9.05 | **4.51** | 8.65% |
| 3 | C2 Uniform→η modal | 13.43 | 7.93 | 6.10 | 9.15% |
| 4 | B2 Vote→η modal | 15.65 | 6.47 | 5.35 | 9.16% |
| 5 | T0-V3 Per-Tone η·ρ | 13.77 | 6.84 | 6.99 | 9.20% |
| 6 | Modal top2 equal | **13.04** | 10.61 | 4.69 | 9.45% |
| 7 | Modal η-weight | 13.25 | 10.50 | 4.60 | 9.45% |
| 8 | T3 Voting+Modal hybrid | 14.92 | 7.94 | 6.24 | 9.70% |
| 9 | C1 Uniform→Top2 modal | 13.85 | 8.64 | 7.10 | 9.86% |
| 10 | B3 Vote→Top2 modal | 17.86 | 6.44 | 5.47 | 9.92% |
| — | A1 Phase η·ρ voting | 17.37 | 5.81 | 10.05 | 11.07% |
| — | A2 Phase persistence voting | 28.06 | 5.88 | 18.52 | 17.49% |
| — | B4 VoteP→Top2 modal | 29.56 | 6.39 | 13.81 | 16.59% |

> 粗体 = 该场景最优。排名按跨域 mean 升序。A1/A2/B4 因跨域 > 15% 不参与正式排名，以 "—" 标记。

### 3.2 跨域排行榜

![跨域排行榜](../outputs/figures/systematic_fusion_leaderboard.png)

**解读**：
- **B1 以 8.45% 登顶**，比 G4（8.65%）改善 0.20 pp，比 T0-V3（9.20%）改善 0.75 pp，比 Modal top2（9.45%）改善 1.00 pp（相对改善 ~10.6%）。
- 新增方法中，B1/B2/C2 三者跨域 < 9.5%，优于或接近 T0-V3。但 B3/B4/A1/A2 未能超越 baseline——说明 Voting→谱→模态融合的组合**不是无条件有效的**，权重模式和 persistence 是关键变量。
- G4 仍排名第二（8.65%），说明门控作为一种元策略仍有竞争力，且 G4 与 B1 的优劣是场景条件性的。

### 3.3 二维策略热力图

![二维热力图](../outputs/figures/systematic_fusion_2d_heatmap.png)

**解读**：
- **最优单元格 = (Vote, Equal)**：跨域 8.45%，热力图最浅色（最绿）。
- (Vote, Remote) = 9.20%（T0-V3），(Vote, Top2) = 9.92%——说明在 Vote 信道策略下，**Equal > Remote > Top2**，这个排序与 Single 信道策略下的排序（Top2 ≈ η-weight > Remote）不同——这就是 H2 的核心证据：**模态策略的最优选择依赖于信道策略**。
- (VoteP, Phase/Top2) 均 > 15%——persistence 筛选破坏了 voter 多样性，尤其在 phases 和模态融合中。

### 3.4 关键发现

**发现 1：B1（Vote→Equal）是当前全局最优 pipeline 候选**

B1 跨域 8.45%，优于所有既有方法。B1 的优势主要来自 095806 场景：B1 = 6.50% vs G4 = 9.05%（改善 2.55 pp）。但需注意 B1 在 102621 上输给 G4（5.63% vs 4.51%，差 1.12 pp）——B1 不是在所有场景无条件最优。

**发现 2：Vote→Top2（B3 = 9.92%）系统性失败**

这是本实验最反直觉的发现。直觉上 Top2 模态选择应该优于 Equal（踢出最差模态），但 Vote 信道策略下恰好相反。对比 B1（Equal, 8.45%）和 B3（Top2, 9.92%）的 1.47 pp 差距，说明在 Voting 降低模态间差异后，Top2 选择退化为随机剔除——反而损失了三模态等权的稳定性。

**发现 3：Phase voting 场景分化极强**

A1（Phase voting）在 095806 上 5.81%（优于 T0-V3 6.84%），但在 091339 上 17.37%（比 T0-V3 13.77% 差 3.60 pp）。Phase voting 的非平稳性远超 Remote voting——**phases 在某些多径环境下可以提供卓越的呼吸信号，但在另一些环境下系统性不可靠**。

**发现 4：Persistence 在模态融合框架下完全失效**

A2（17.49%）和 B4（16.59%）的大幅退化表明，G6 中有效的 persistence filtering（剔除 mean_step_L1 > 2.0 的 tone）在 per-modal voting→谱融合中产生了灾难性后果。可能机制：persistence 筛除了"跨窗 BPM 不稳定但窗内信息有效"的 tone，减少了 voter 多样性，使得 voting 更容易被少数稳定噪声 tone 绑架。

**发现 5：091339 是所有方法的瓶颈**

包括 B1 在内的所有方法在 091339 上 > 12%。B1 = 13.22% 仅比 T0-V3 13.77% 微降 0.55 pp。跨域改善主要来自 095806 和 102621，而非突破 091339。

---

## 4. 假设逐一验证

### H1：Phase voting 跨域优于 Remote voting

**判定**：**未证实**。

| 对比 | 跨域 mean | 091339 | 095806 | 102621 |
|------|-----------|--------|--------|--------|
| A1 Phase voting | 11.07% | 17.37% | **5.81%** | 10.05% |
| T0-V3 Remote voting | **9.20%** | **13.77%** | 6.84% | **6.99%** |

Phase voting 仅在 095806 单场景优于 Remote voting（+1.03 pp）。跨域上 Phase voting 反而差 1.87 pp。H1 被推翻。

**物理讨论**：Phase 作为 72 tone voting 的输入，其 η（能量比）天然更高（phase 无 DC 分量），但 phase 的 tone 间 BPM 差异可能比 remote amplitude 更大——因为相位旋转在多径下的非线性更强，导致某些 tone 的相位波形被严重畸变。在 095806 的特定多径条件下，这种畸变恰好较小；但在 091339/102621 下，畸变主导。

### H2：信道策略与模态策略存在交互效应

**判定**：**已验证**。

二维热力图直接展示了交互效应：

- 在 **Single** 信道策略下：Top2（9.45%）≈ η-weight（9.45%）> Remote（10.45%）— 模态融合有效
- 在 **Vote** 信道策略下：Equal（8.45%）> η-weight（9.16%）> Remote（9.20%）> Top2（9.92%）— 模态融合权重是关键，且排序反转
- 在 **Uniform** 信道策略下：η-weight（9.15%）> Top2（9.86%）— 同样排序不同于 Single

不存在"无条件最优"的信道或模态策略。

### H3：Vote per modal + Modal top2 优于 T0-V3 和 Modal top2

**判定**：**未证实**。

| 方法 | 跨域 mean |
|------|-----------|
| B3 Vote→Top2 | 9.92% |
| T0-V3 | 9.20% |
| Modal top2 | 9.45% |

B3 同时劣于两个 baseline（+0.72 pp vs T0-V3, +0.48 pp vs Modal top2），最低成功标准未达成。但 **B1 Vote→Equal（8.45%）** 同时优于两者——H3 的核心直觉（Voting + 模态融合 > 单一维度优化）在 Equal 权重下成立，但在 Top2 下不成立。

### H4：Phase voting 在 095806 特别有效

**判定**：**仅单场景支持**。

095806 上 A1 = 5.81% vs T0-V3 = 6.84%（改善 1.03 pp），但 091339（+3.60 pp 退化）和 102621（+3.06 pp 退化）均为系统性衰退。不能泛化。

### H5：Persistence voting 可迁移到 phases / 模态融合

**判定**：**已废弃**。

| 对比 | 未加 persistence | 加 persistence | Δ |
|------|-----------------|----------------|---|
| A1 vs A2（Phase voting） | 11.07% | 17.49% | **+6.42 pp** |
| B3 vs B4（Vote→Top2） | 9.92% | 16.59% | **+6.67 pp** |

两种情况均大幅退化。G6 中 persistence 的有效性**不能**迁移到 per-modal voting→谱融合框架。机制诊断是本 plan 的开放问题 Q1。

---

## 5. 诊断分析

### 5.1 消融瀑布图

![消融瀑布图](../outputs/figures/systematic_fusion_ablation_waterfall.png)

**解读**（从左到右 = 逐步叠加策略变化，绿 = 改善，红 = 退化）：

1. **B0 Single Remote（10.45%）→ A1 Phase voting（11.07%）**：红色。Phase voting 单独使用比 Single Remote 差。
2. **→ T0-V3 Remote voting（9.20%）**：绿色。从 Phase voting 回到 Remote voting，改善 1.87 pp——Remote voting 确实有效。
3. **→ Modal top2（9.45%）**：红色。在 voting 基础上叠加 modal fusion 如果方式不对（Top2），反而退化。
4. **→ B3 Vote→Top2（9.92%）**：红色加剧。从 Single-best→Top2 改为 Vote→Top2 后进一步退化。
5. **→ G4 Gating（8.65%）**：绿色。门控挽回了局面。

**关键洞察**：B1（8.45%）未被绘入瀑布图——如果将它作为第 0 步插入，它将是最左端最低的柱。实际上从 B0 到 B1 的过程应该理解为"信道从 Single→Vote（改善 1.25 pp）+ 模态从 Remote→Equal（再改善 0.75 pp）"，两步均为绿。

### 5.2 模态选择分布（B3 Vote→Top2）

![模态选择分布](../outputs/figures/systematic_fusion_modal_selection.png)

**解读**（基于 cs_091339）：
- B3 在大多数窗选择的模态对与 Modal top2（single-best→Top2）不同——Voting 改变了每个模态的 quality score（使用 conf_vote 而非 η）。
- conf_vote 作为 modal selector 的行为与 η 有系统性差异：conf_vote 倾向于选择 voting 票数集中的模态，而非呼吸信号信噪比最高的模态。

### 5.3 B1 成功的机制（推测）

B1（Vote→Equal）有效的关键可能在于：

1. **Voting 降低了模态内噪声**：per-tone η·ρ voting 对每种模态内 72 tone 做了信息筛选，产出的 conf 加权谱比 Single-best 信道谱更干净。
2. **Equal 不要求模态间差异**：与 Top2 不同，Equal 融合不依赖模态间的 quality ranking——它只是将三个"已经去噪"的频谱等权平均。这规避了 Voting 后模态间差异缩小导致的 selector 退化。
3. **Voting 为每个模态独立工作**：remote/phases/local 三种模态各自有 72 tone voting → 各自的归一化谱。三种谱来自同一物理过程（呼吸），但受不同噪声模式影响。等权平均等价于隐式的多证据平均。

### 5.4 失败模式

| 失败模式 | 涉及方法 | 表现 | 机制 |
|----------|----------|------|------|
| **Vote→Top2 退化** | B3 | 9.92% vs 8.45% (B1) | Voting 后三模态频谱高度相似，Top2 选择≈随机剔除有效模态 |
| **Persistence + 模态融合灾难** | A2, B4 | 17.49%/16.59% | Persistence 筛除大量 tone → voter 多样性低 → voting 被噪声簇绑架 |
| **Phase voting 091339 退化** | A1 | 17.37% vs 13.77% (T0-V3) | Phase 在 091339 多径条件下 tone 间一致性远差于 Remote |
| **091339 天花板** | 所有方法 | > 12% | 该场景呼吸信号本身可能较弱或多径过于复杂，物理信噪比限制了所有方法 |

---

## 6. 部署建议

### 6.1 推荐方法

| 优先级 | 方法 | 跨域 mean | 适用条件 | 理由 |
|--------|------|-----------|----------|------|
| **首选** | **B1 Vote→Equal** | **8.45%** | 通用部署 | 当前全局最优，三场景无灾难退化 |
| **备选** | G4 Single fallback | 8.65% | 102621 类场景（Modal 占优） | 102621 上 4.51% vs B1 5.63% |
| **组合** | B1 + G4 联合门控 | 待验证 | 追求三场景全最优 | 下一轮 plan 核心方案 |

### 6.2 不推荐

- **B3 Vote→Top2**：9.92%，同时劣于 B1 和 Modal top2。Voting 信道策略下不宜使用 Top2 模态选择。
- **Phase voting（A1）单独使用**：跨域 11.07%，场景分化过大。但 phases 作为三模态之一参与 B1 Equal 融合有价值——不推荐单独使用，但推荐作为融合的一部分。
- **Persistence-filtered voting（A2/B4）**：在模态融合框架下灾难性退化，不建议在当前形态下使用。如需保留 persistence 机制，需要完全不同的实现方式（如在频谱层面而非 tone BPM 层面筛选）。

### 6.3 条件与限制

- **仅金属板三场景验证**：B1 的 8.45% 仅限 cs_091339/095806/102621。真实部署的多径、体动、距离变化可能改变 Voting→Equal 的有效性。
- **091339 仍是短板**：B1 = 13.22% 在 091339 上仍需改善。如果部署环境类似 091339（复杂多径），B1 的优势会缩水。
- **计算成本**：B1 = 3 模态 × 72 tone voting / 窗 ≈ 3× T0-V3 计算量。在实时部署中可能需要优化（如仅对有足够帧数的窗计算）。
- **Voting→谱构造方式敏感**：当前使用 conf 加权全谱（方案 B），更换构造方式可能改变 B1 的相对排名（见下一轮 plan D3 ablation）。

---

## 7. 开放问题与下一步

| ID | 问题 | 优先级 | 建议 |
|----|------|--------|------|
| Q1 | 为何 Vote→Equal 有效但 Vote→Top2 无效？ | **最高** | 诊断模态间频谱相似度 + Top2 被踢出模态分析（下一轮 plan D1） |
| Q2 | B1 与 G4 能否组合超越 8.45%？ | **最高** | G4-B1 联合门控（下一轮 plan 主实验） |
| Q3 | 091339 能否通过 B1 + 双峰性门控改善？ | 高 | B1+G5 专项（下一轮 plan D2） |
| Q4 | 谱构造方式对 B1/B3 排名的影响？ | 高 | winning-bin / top-K ablation（下一轮 plan D3） |
| Q5 | conf_vote 作为模态 selector 是否不如 η？ | 中 | 对比 conf_vote vs η 作为 modal quality score |
| Q6 | P1 扩展实验（Local voting, PCA+modal, TopK voting）是否值得做？ | 低 | B1 确立后优先级降低；可在联合门控验证后视情况推进 |

**下一轮 plan**：[`docs/plans/b1_gating_and_diagnosis_plan.md`](../plans/b1_gating_and_diagnosis_plan.md)

---

## 附录 A：产出清单

| 类型 | 路径 |
|------|------|
| Plan | [`docs/plans/systematic_modal_channel_fusion_plan.md`](../plans/systematic_modal_channel_fusion_plan.md) |
| 验证报告 | [`docs/reports/systematic_modal_channel_fusion_report.md`](../reports/systematic_modal_channel_fusion_report.md) |
| 实验脚本 | `notebooks/scripts/chFusion_systematic_fusion.py` |
| 核心模块 | [`src/ble_analysis/systematic_fusion.py`](../../src/ble_analysis/systematic_fusion.py) |
| 数值结果（全量） | `outputs/reports/systematic_fusion_results.npy` |
| 单场景结果 | `outputs/reports/systematic_fusion_{091339,095806,102621}_results.npy` |
| 跨域汇总 | `outputs/reports/systematic_fusion_cross_domain.npy` |
| 排行榜图 | ![leaderboard](../../outputs/figures/systematic_fusion_leaderboard.png) |
| 二维热力图 | ![heatmap](../../outputs/figures/systematic_fusion_2d_heatmap.png) |
| 消融瀑布图 | ![waterfall](../../outputs/figures/systematic_fusion_ablation_waterfall.png) |
| 模态选择图 | ![modal](../../outputs/figures/systematic_fusion_modal_selection.png) |

## 附录 B：方法缩写对照

| 缩写 | 全称 |
|------|------|
| B1 Vote→Equal | 三种模态各自 72-tone voting → 三模态归一化谱等权平均 → 寻峰 |
| B3 Vote→Top2 | 同上，但模态融合时按 conf_vote 取前 2 模态等权（即 Modal top2 逻辑） |
| T0-V3 | remote_amplitudes 单模态 72-tone η·ρ 加权直方图投票 |
| Modal top2 | 每种模态选 max-η 单信道 → 三模态 top2 η 等权谱融合 |
| G4 | T0-V3 vs Modal top2 → 共识取平均 / 分歧 fallback Single Remote |
| G5 | 基于 voting BPM 直方图双峰性的窗级门控 |
| G6 | 剔除跨窗 BPM 不稳定 tone 后的 persistence-filtered voting |
| C-Vote | 单模态 72 tone η·ρ 加权 BPM 直方图投票 + conf 加权谱平均 |
| C-VoteP | C-Vote + persistence mask（剔除 unstable tone） |
| C-Uniform | 单模态 72 信道归一化谱等权平均 |
| η | 呼吸频段能量比 |
| ρ | 谱峰峰度（peak prominence） |
| conf_vote | voting 直方图中最大 bin 票数占比（票数集中度） |

---

*本报告由 Claude (Achievement Report Mode) 基于 Cursor Composer 的实验结果生成。所有数字来自实际运行结果，未编造或估算。*
