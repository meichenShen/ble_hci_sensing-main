# Consensus Gating 窗级共识门控融合 — 成果汇报

> **面向**：人（研究员 / 合作者）  
> **来源**：[`voting_gating_plan.md`](../plans/voting_gating_plan.md) → [`voting_gating_report.md`](../reports/voting_gating_report.md)  
> **日期**：2026-06-08  
> **验证状态**：已完成（G1–G6；G7–G9 待文献调研）

---

## 1. 摘要

- **目标**：通过窗级共识门控（Consensus Gating）在 T0-V3 per-tone voting 与 Modal top2 之间动态选择，解决两者在不同场景中的互补性退化问题（voting 在 091339 弱、095806 强；Modal 反之）。
- **结论**：门控方案有效。**G4 Single fallback 跨域 mean 8.65%**，优于 Modal top2（9.45%）和 T0-V3 voting（9.20%），为当前所有已验证方法中的**跨域最优**。同时发现**无单一门控策略在所有场景均为最优**——不同门控在不同场景有不同优势。
- **关键数字**：
  - 跨域最优：G4 = **8.65%**（vs Modal 9.45%/T0-V3 9.20%）
  - 091339 最优：G5 双峰性门控 = **12.27%**（vs Modal 13.04%/T0-V3 13.77%）
  - 095806 最优：G6 persistence voting = **6.55%**（vs T0-V3 6.84%/Modal 10.61%）
  - 102621 最优：G2 置信度优先 = **4.36%**（vs Modal 4.69%）
  - 理想成功标准（跨域 < 8.5%）**未达成**；最低标准（< 9.45%）**已达成**

---

## 2. 方法与实验设置

### 2.1 问题背景

两个独立实验线程揭示了同一个模式——T0-V3 per-tone voting 和 Modal top2 的优劣势是**场景条件性**的：

| 方法 | 091339 | 095806 | 102621 | 跨域 mean |
|------|--------|--------|--------|-----------|
| T0-V3 Per-Tone η·ρ voting | 13.77% | **6.84%** | 6.99% | 9.20% |
| Modal top2 equal | **13.04%** | 10.61% | **4.69%** | 9.45% |

注意：在 095806 上 T0-V3 以 6.84% vs 10.61% 大幅超越 Modal；但在 091339 上 Modal 以 13.04% vs 13.77% 反超。两种方法在**不同场景**有互补优势。

**核心物理洞察**（来自 voting 增强诊断，commit `7330738`）：频率选择性衰落导致 tone 间 BPM 估计系统性分化——某些 tone 追踪呼吸频率，某些被多径抵消产生半频，某些被其他周期信号主导。这意味着 **voting 内部的 conf_vote（票数）不足以区分"正确共识"和"错误共识"**——稳定的错误簇也会有高票数。

### 2.2 门控策略

六种门控策略在每窗内并行计算 T0-V3 voting、Modal top2 和 Single Remote 的 BPM，然后根据门控信号动态选择：

| 策略 | 核心规则 | 设计动机 |
|------|----------|----------|
| **G1** 简单共识 | δ=3 BPM, τ=0.30；共识+高conf → 加权平均；分歧+高conf → vote；否则 fallback | 基础 v1 |
| **G2** 置信度优先 | δ=2 BPM, τ=0.35；分歧时比较 conf/η 优先级 | 更严格的门控 |
| **G3** 自适应 δ | δ 随 max(η) 在 2–5 BPM 之间自适应 | η 高时容忍度小 |
| **G4** Single fallback | 共识 → 加权平均；**分歧 → Single Remote**（不依赖 τ） | 直接简洁，避免 τ 选择 |
| **G5** 双峰性门控 | bimodality_score < 0.5 → vote；双峰 + 主峰≈modal → 平均；否则 modal/fallback | 直接检测"多簇竞争"——091339 特征 |
| **G6** Persistence voting | 剔除跨窗 BPM 步长 > 2.0 BPM 的 noise tone 后 voting；稳定 tone < 12 → modal | 用时域稳定性筛除噪声选民 |

### 2.3 场景与 Baseline

| 场景 | 数据 | 特点 |
|------|------|------|
| cs_091339 | `CS_frames_all_20260113_091339.jsonl` | voting 退化验证场景 |
| cs_095806 | `CS_frames_all_20260116_095806.jsonl` | voting 优势验证场景 |
| cs_102621 | `CS_frames_all_20260116_102621.jsonl` | 跨域对照 |

Baseline：B0 Single Remote、B1 Uniform Remote、B2 Modal top2 equal、B3 Modal η-weight。  
对照：T0-V3 Per-Tone η·ρ voting。  
待测：G1–G6 共 11 方法（含 4 baseline + T0-V3 + 6 gating）。

**实验参数**：滑窗 20 s / 1 s 步，呼吸带 0.1–0.35 Hz，所有方法与 Plan2 一致的滤波链（median → highpass → bandpass）。

---

## 3. 核心结果

### 3.1 主结果表

| 排名 | 方法 | cs_091339 | cs_095806 | cs_102621 | **跨域 mean** |
|------|------|-----------|-----------|-----------|---------------|
| **1** | **G4 Single fallback** | 12.39 | 9.05 | 4.51 | **8.65%** |
| 2 | G5 Bimodality gating | **12.27** | 7.09 | 6.80 | 8.72% |
| 3 | G1 Simple consensus | 13.60 | 8.75 | 4.51 | 8.95% |
| 4 | G2 Conf priority | 13.88 | 8.74 | **4.36** | 8.99% |
| 5 | G6 Persistence voting | 13.43 | **6.55** | 7.00 | 9.00% |
| 6 | G3 Adaptive δ | 13.38 | 8.39 | 5.23 | 9.00% |
| 7 | T0-V3 Per-Tone η·ρ | 13.77 | 6.84 | 6.99 | 9.20% |
| 8 | B2 Modal top2 equal | 13.04 | 10.61 | 4.69 | 9.45% |
| 9 | B3 Modal η-weight | 13.25 | 10.50 | 4.60 | 9.45% |
| 10 | B0 Single Remote | 10.91 | 12.16 | 8.29 | 10.45% |
| 11 | B1 Uniform Remote | 17.09 | 9.15 | 6.82 | 11.02% |

> 粗体 = 该场景最优；排名按跨域 mean 升序。

### 3.2 跨域排行榜

![跨域排行榜](../outputs/figures/voting_gating_comparison_bars.png)

**解读**：
- 所有六种门控策略（G1–G6）的跨域 mean 均在 8.65–9.00% 之间，**全部优于** T0-V3（9.20%）和 Modal top2（9.45%）。这说明门控作为一个方法类，整体优于无门控的单一方法。
- G4（Single fallback）以 8.65% 登顶，比 Modal top2 改善了 **0.80 个百分点**（相对改善 ~8.5%）。G4 仅比 T0-V3 改善了 0.55 个百分点。
- G1–G4（基于共识/conf 的门控）和 G5–G6（基于物理诊断的门控）之间没有系统性差距——两类策略的最优者分别排名第 1 和第 2。

### 3.3 关键发现

**发现 1：无全局最优门控策略**

不同场景的最优方法不同：

| 场景 | 最优方法 | err% | 第二优 | err% |
|------|----------|------|--------|------|
| 091339 | G5 双峰性 | 12.27% | G4 Single fallback | 12.39% |
| 095806 | G6 Persistence | 6.55% | T0-V3 | 6.84% |
| 102621 | G2 Conf priority | 4.36% | G1/G4 | 4.51% |

这意味着**场景自适应的门控参数选择**（或基于场景特征的自动策略切换）可能是进一步改善的方向。

**发现 2：G4 的简洁性优势**

G4（共识 → 平均；分歧 → Single）是六种策略中最简单的——它不依赖 conf_vote 阈值 τ 的选择，也不需要 bimodality 或 persistence 的计算。它的跨域最优地位说明：**在当前阶段，保守地 fallback 到 Single Remote，比精细地调 τ 更有效**。

**发现 3：G5 和 G6 在特定场景有显著改善**

- G5 双峰性门控在 091339（voting 退化最严重的场景）上达到 12.27%，比 T0-V3（13.77%）改善 **1.50 个百分点**，也比 Modal top2（13.04%）改善了 0.77 个百分点。双峰性检测直接命中了 091339 的"多簇竞争"模式——voting 的 BPM 分布呈多峰时，自动退回 modal。
- G6 persistence voting 在 095806 上达到 6.55%，比 T0-V3（6.84%）改善 0.29 个百分点，比 Modal（10.61%）改善 **4.06 个百分点**。但 G6 在 102621 上反而退化（7.00% vs T0-V3 6.99%），未能实现"三场景全面改善"的预期。

**发现 4：门控在 095806 上普遍低于 T0-V3**

这是门控的"代价"——除 G6 外，所有门控策略在 095806（voting 天然优势场景）上都比 T0-V3 差：

| 方法 | 095806 err% | vs T0-V3 (6.84%) |
|------|-------------|-------------------|
| G6 | 6.55% | −0.29 ✅ |
| G5 | 7.09% | +0.25 |
| G3 | 8.39% | +1.55 |
| G1 | 8.75% | +1.91 |
| G2 | 8.74% | +1.90 |
| G4 | 9.05% | +2.21 |

门控在"阻止 091339 退化"和"保留 095806 优势"之间存在 trade-off——保守的门控（G4/G5）在 091339 表现好，但在 095806 损失了 voting 的部分优势。

---

## 4. 假设逐一验证

### H1：T0-V3 和 Modal 优劣势窗存在可检测信号特征差异

**判定**：**部分支持**。

- G5 双峰性门控在 091339 上的改善（12.27% vs T0-V3 13.77%）表明 **bimodality_score 是一个有效的门控信号**——voting BPM 分布的双峰程度确实与 voting 可靠性相关。
- G6 persistence 在 095806 上的改善（6.55% vs T0-V3 6.84%）表明 **tone 时域稳定性是另一个有效信号**。
- 然而，这些信号的可检测性在窗级（oracle 选对率普遍 < 70%）仍然不足——存在可检测特征，但当前特征的判别力有限。

**证据图**：Oracle 选对率热力图如下。

![Oracle 选对率热力图](../../outputs/figures/voting_gating_oracle_heatmap.png)

**解读**：
- 091339 段 3（voting 占优段）G6 选对率最高达 82%——说明 persistence filtering 在 voting 天然占优的段效果很好。
- 095806 段 1a G5/G6 选对率分别达 95%/97%——基于物理诊断的门控在 voting 优势段几乎完全选对。
- 但 102621 多个段的选对率偏低（G5 在段 1b 仅 46%，段 4a 仅 21%）——G5 在 102621 上的退化有明确的窗级证据。
- 所有段的平均选对率约 45–60%，说明门控信号仍需进一步优化。

### H2：跨方法共识可稳定组合 voting + modal 优势

**判定**：**部分支持**。

- ✅ 跨域改善成立：G4 8.65% < T0-V3 9.20% < Modal 9.45%。
- ❌ 095806 上 G1–G4 均损失了 T0-V3 的优势（G1 8.75% vs T0-V3 6.84%）。
- 门控有效地阻止了 091339 上的 voting 退化，但代价是在 voting 天然优势场景上变得保守。

### H5：双峰性门控（G5）在 091339 多簇竞争窗上优于 G1

**判定**：**已验证**。

- G5 091339: 12.27% vs G1 091339: 13.60%，改善 1.33 个百分点。
- G5 在 091339 段 1b 的 oracle 选对率达 48%（G1 仅 21%）——双峰性检测在"多簇竞争"场景下确实比 conf_vote + peak_dist 更精确。
- 但 G5 在 102621 上退化（6.80% vs G1 4.51%），说明双峰性是一种**场景特异性**的门控信号，在谱峰本身就集中的场景（102621）中反而引入了误判。

### H6：Persistence-filtered voting（G6）三场景均优于 T0-V3

**判定**：**未证实**。

- 091339: 13.43% vs 13.77%（略优 ✅）
- 095806: 6.55% vs 6.84%（优 ✅）
- 102621: 7.00% vs 6.99%（略差 ❌）
- 102621 上 G6 的退化极小（+0.01%），但确实未能实现"三场景全面改善"的预期。Persistence 阈值（2.0 BPM）和稳定 tone 数下限（12）可能需要场景级调优。

---

## 5. 诊断分析

### 5.1 门控决策分布

![门控决策分布](../outputs/figures/voting_gating_decision_pie.png)

**G1 全场景窗级决策分布解读**：
- `consensus_high`（一致+高置信 → 平均）和 `consensus_low`（一致+低置信 → modal）合计占比反映 voting-modal 共识程度。
- `vote_high_conf`（分歧+高conf → vote）对应于 095806 模式——voting 自信但 modal 不同意。
- `fallback`（都不好 → Single）对应于 091339 模式——两种方法都不好。
- 如果 fallback 占比过高（>70%），说明门控退化为 Single Remote——这恰好是 plan 中提到的风险。实际数据显示 fallback 并未过度主导。

### 5.2 门控失败模式

| 失败模式 | 表现 | 机制解释 |
|----------|------|----------|
| **过度保守** | G1–G4 在 095806 上比 T0-V3 差 1–2% | voting 在 095806 天然强，但门控因 modal 不一致而频繁退回 Single/Modal |
| **双峰误判** | G5 在 102621 上退化到 6.80% | 102621 的谱峰较集中，双峰性检测可能将正常的小波动误判为"竞争" |
| **Persistence 场景敏感** | G6 在 102621 上退化到 7.00% | persistence_threshold=2.0 在 102621 可能过松或过紧 |
| **小段不稳定** | 段 2b/4b 等极小段（n=1–2）oracle 选对率极端 | 小段统计意义不足，门控在这些段上本质上是噪声决策 |

### 5.3 为什么理想标准未达成？

跨域 8.65% vs 目标 8.5%，差距 0.15 个百分点。主要瓶颈在 091339：
- 091339 最优方法（G5 12.27%）仍比 Single Remote（10.91%）差。门控改善的是 voting 退化，但未能超越 Single 这个"朴素强 baseline"。
- 如果 091339 能达到 11%（接近 Single），跨域 mean 将降至 ~8.0%——达到理想标准。

这提示：**在 091339 这类"voting 系统性不可靠"的场景，fallback 到 Single Remote 可能是更优的选择**，而不是试图在 voting 和 modal 之间精细门控。G4（分歧 → Single）和 G5（双峰 → modal）分别代表了这两种哲学，而 Single fallback 在跨域上略优于双峰性。

---

## 6. 部署建议

### 6.1 推荐方法

| 优先级 | 方法 | 适用场景 | 理由 |
|--------|------|----------|------|
| **首选** | G4 Single fallback | 未知场景 / 通用部署 | 跨域最优（8.65%），实现简单，无需调 τ |
| **备选** | G5 双峰性门控 | 怀疑 voting 多簇竞争（如复杂多径环境） | 091339 最优（12.27%），直接检测 voting 可靠性 |
| **备选** | G6 Persistence voting | voting 历史表现好的场景 | 095806 最优（6.55%），保留 voting 优势 |

### 6.2 不推荐

- **不建议将任一 G 策略作为默认 pipeline 替换 Modal top2**：改善幅度（0.80 pp）有限，且引入门控复杂度和参数选择风险。
- **G1–G3 不建议单独使用**：G4 在更简单的规则下实现了更好的跨域表现——τ 的选择似乎没有带来额外收益。
- **B1 Uniform Remote 不推荐**：跨域 11.02%，在所有场景均差于 Single 或 Modal。

### 6.3 条件与限制

- **仅金属板三场景验证**：所有结论限于三个 cs_* 场景。真实部署场景的多径环境、体动干扰、距离变化等因素可能改变门控信号的有效性。
- **102621 上 G5/G6 退化**未被解决：场景自适应的门控参数选择是必要条件。
- **滑窗参数固定**（20 s / 1 s）：窗长变化可能影响 per-tone voting 的 BPM 分布特征，进而影响门控信号。

---

## 7. 开放问题与下一步

| ID | 问题 | 优先级 | 建议 |
|----|------|--------|------|
| Q1 | 能否根据场景特征自动选择门控策略？ | 高 | 训练简单的场景级分类器（如基于 mean η/ρ/bimodality 分布） |
| Q2 | δ 和 τ_hi 能否跨场景联合优化？ | 中 | 三场景 grid search δ ∈ [1,5]、τ ∈ [0.2,0.5] |
| Q3 | Fallback 用 Single 还是 Modal？ | 高 | G4 跨域最优但 095806 差；需要场景级自适应（091339 → Single; 095806 → Modal） |
| Q4 | G7–G9（TRRS / SVM / Bimodal CSI 门控）能否进一步改善？ | 中 | 待文献调研 plan 后追加实验 |
| Q5 | Voting + Modal 门控框架能否扩展到 PCA-Modal3？ | 低 | PCA plan Q3 预留了相同框架 |

**下一轮建议**：

1. **文献调研**（急迫）：完成 TR-BREATH [7] / Wi-Breath [6] / Bimodal CSI [10] 的调研，评估 TRRS、SVM confidence、motion detection 是否可作为更优的门控信号。
2. **场景自适应门控**：基于 Q1/Q3，探索"091339 → G5/Single dominant, 095806 → G6/voting dominant, 102621 → Modal dominant"的场景级策略选择。
3. **δ/τ grid search**：对 G1–G4 进行系统的 δ ∈ [1,5] × τ ∈ [0.2,0.5] 扫描，确认当前默认值是否接近最优。

---

## 附录 A：产出清单

| 类型 | 路径 |
|------|------|
| Plan | [`docs/plans/voting_gating_plan.md`](../plans/voting_gating_plan.md) |
| 验证报告 | [`docs/reports/voting_gating_report.md`](../reports/voting_gating_report.md) |
| 实验脚本 | `notebooks/scripts/chFusion_voting_gating.py` |
| 核心模块 | [`src/ble_analysis/consensus_gating.py`](../../src/ble_analysis/consensus_gating.py) |
| 数值结果 | `outputs/reports/voting_gating_results.npy` |
| 跨域汇总 | `outputs/reports/voting_gating_cross_domain.npy` |
| Oracle 统计 | `outputs/reports/voting_gating_oracle_stats.npy` |
| 决策分布图 | ![pie](../../outputs/figures/voting_gating_decision_pie.png) |
| 排行榜图 | ![bars](../../outputs/figures/voting_gating_comparison_bars.png) |
| Oracle 热力图 | ![heatmap](../../outputs/figures/voting_gating_oracle_heatmap.png) |

## 附录 B：方法缩写对照

| 缩写 | 全称 |
|------|------|
| T0-V3 | Per-Tone η·ρ weighted histogram voting |
| Modal top2 | top2 模态（remote, local, phase）谱融合 |
| Single | max-η tone 独立 FFT 寻峰 |
| G1–G4 | 基于共识/置信度的窗级门控（§2.2） |
| G5 | 双峰性门控（bimodality gating） |
| G6 | Persistence-filtered voting |
| η | 呼吸频段能量比 |
| ρ | 谱峰峰度（peak prominence） |

---

*本报告由 Claude (Achievement Report Mode) 基于 Cursor Composer 的实验结果生成。所有数字来自实际运行结果，未编造或估算。*
