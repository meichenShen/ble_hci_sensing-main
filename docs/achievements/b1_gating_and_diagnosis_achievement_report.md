# B1 联合门控与 Vote→Equal 机制诊断 — 成果汇报

> **文档性质**：Cursor Composer 底稿（非正式成果汇报）  
> **说明**：由执行 Agent 在未经 Achievement Report Mode 定稿前生成，供 Claude/DeepSeek 或用户改写；请勿与 Claude 正式成果汇报等同。  
> **面向**：人（研究员 / 合作者）  
> **来源**：[`b1_gating_and_diagnosis_plan.md`](../plans/b1_gating_and_diagnosis_plan.md) → [`b1_gating_and_diagnosis_report.md`](../reports/b1_gating_and_diagnosis_report.md)  
> **日期**：2026-06-08  
> **验证状态**：已完成（P0）

---

## 1. 摘要

- **目标**：在 B1（Vote→Equal modal，跨域 8.45%）基础上，将 B1 纳入 G4 三候选门控，并诊断 Equal 优于 Top2 的机制及 091339 退化原因。
- **结论**：**G4-B1-v2（Top2 consensus）跨域 8.05%** 为当前所有已验证方法最优，优于 B1 与 G4。**H2 已验证**：Voting 路径的模态间频谱相似度显著高于 Single-best 路径，解释 B3 相对 B1 的退化。G5-B1 与 H3 **未证实**。
- **关键数字**：
  - 跨域最优：G4-B1-v2 = **8.05%**（vs B1 8.45% / G4 8.65%）
  - 095806 最优：G4-B1-v2 = **6.31%**（vs B1 6.50%）
  - 102621：G4 仍最优 **4.51%**（G4-B1-v2 5.50%）
  - D1：Vote 谱相似度 091339 **0.864** vs Single-best **0.772**

---

## 2. 方法与实验设置

### 2.1 问题背景

Systematic fusion 确立 B1（Vote→Equal）为跨域最优（8.45%），但存在三处短板：

1. 102621 上 B1（5.63%）输给 G4（4.51%）
2. B3（Vote→Top2，9.92%）显著差于 B1，机制不明
3. 091339 所有方法 mean err% > 12%

本实验在 G4 框架中增加 **B1 为第三候选**，并做 D1–D3 机制诊断。

### 2.2 主方法与诊断

| 类别 | 内容 |
|------|------|
| **G4-B1 v1–v4** | 窗级在 T0-V3 / Modal top2 / B1 间门控（δ=3 BPM） |
| **D1** | Vote 谱 vs Single-best 谱的模态间余弦相似度 |
| **D2** | 091339 双峰/单峰窗的 B1 error 对比 |
| **D3** | 谱构造 ablation：conf / winning-bin / top-K |
| **G5-B1** | 091339 专项：剔除双峰模态后再 Equal |

方法代号与信道/模态融合含义见文末 [**附录**](#附录-方法代号与信道模态融合对照)。

### 2.3 场景

| 场景 | 用途 |
|------|------|
| cs_091339 | 主诊断 + G5-B1 |
| cs_095806 | B1 优势验证 |
| cs_102621 | G4 优势对照 |

---

## 3. 核心结果

### 3.1 主结果表

| 排名 | 方法 | cs_091339 | cs_095806 | cs_102621 | **跨域 mean** |
|------|------|-----------|-----------|-----------|---------------|
| **1** | **G4-B1-v2 Top2 consensus** | 12.36 | **6.31** | 5.50 | **8.05%** |
| 2 | G4-B1-v1 / v3 | 12.38 | 7.56 | **4.80** | 8.25% |
| 3 | B1 Vote→Equal | 13.22 | 6.50 | 5.63 | 8.45% |
| 4 | G4 Single fallback | 12.39 | 9.05 | **4.51** | 8.65% |
| 5 | G5 Bimodality | 12.27 | 7.09 | 6.80 | 8.72% |
| 6 | T0-V3 | 13.77 | 6.84 | 6.99 | 9.20% |
| 7 | Modal top2 | 13.04 | 10.61 | 4.69 | 9.45% |

> 粗体 = 该场景最优或跨域最优。

### 3.2 跨域排行榜

![B1 门控跨域排行榜](../outputs/figures/b1_gating_leaderboard.png)

**解读**：G4-B1-v2 以 8.05% 登顶，比 B1 改善 0.40 pp，比 G4 改善 0.60 pp。v1/v3 在 102621 上更贴近 G4（4.80%），但跨域仍略逊于 v2。

### 3.3 诊断图

**D1 — 模态频谱相似度**

![D1 模态频谱相似度](../outputs/figures/b1_diag_spectral_similarity.png)

Voting 路径（B1/B3 所用）的三模态谱更相似 → Top2 踢模态的收益变小，**支持 H2**。

**D2 — 091339 双峰 vs 单峰 B1 error**

![D2 双峰窗 error](../outputs/figures/b1_diag_bimodal_error.png)

双峰窗 error（15.17%）并未高于单峰窗（17.20%）→ **H3 未证实**。

**D3 — 谱构造 ablation**

![D3 谱构造 ablation](../outputs/figures/b1_diag_spectrum_mode.png)

winning-bin B1（8.24%）略优于 conf B1（8.45%），但未使 B3 超越 B1。

**G4-B1-v1 窗级决策分布**

![G4-B1 决策分布](../outputs/figures/b1_gating_decision_pie.png)

---

## 4. 假设逐一验证

### H1：G4-B1 三候选门控跨域 < 8.3%

**判定**：**部分支持**。G4-B1-v2 = 8.05% 达标；但 102621 上 5.50% 仍差于 G4 4.51%。

### H2：Voting→谱模态间相似度高于 Single-best→谱

**判定**：**已验证**。三场景 Vote 相似度均高于 Single-best（见 §3.3 D1 图）。

### H3：091339 双峰窗是 B1 退化主因；G5-B1 可改善

**判定**：**未证实**。双峰窗 error 不更高；G5-B1 = 15.74% >> B1 13.22%。

### H4：winning-bin 谱使 B3 超越 B1

**判定**：**未证实**。D3-A B3 跨域 9.40% 仍差于 B1。

---

## 5. 部署建议

| 场景 | 建议 | 理由 |
|------|------|------|
| **跨域默认** | G4-B1-v2 | 跨域 8.05% 当前最优 |
| **102621** | G4 Single fallback | 4.51% 仍优于 v2（5.50%） |
| **091339** | 暂无单一最优；v2 略优于 B1 | 12.36% vs 13.22% |
| **不推荐** | G5-B1 | 091339 显著退化 |

---

## 6. 开放问题与下一步

1. 102621 上 v2 为何弱于 G4？需分析 vote–modal 接近窗的决策。
2. 091339 退化根因待查（非双峰 conf 污染）。
3. 场景自适应门控（102621→G4，其余→v2）需新 plan，且不得硬编码场景。

---

## 附录：方法代号与信道/模态融合对照

> 与 [`b1_gating_and_diagnosis_report.md` 附录 A](../reports/b1_gating_and_diagnosis_report.md#附录-a方法代号与信道模态融合对照) 一致。

### 两层结构

```text
72 信道 ──[信道融合]──► 每模态一条谱/BPM ──[模态融合]──► 候选 BPM
                                              ↑
                              （可选）窗级门控在多个候选 BPM 间选择
```

三模态：**remote 幅值 / local 幅值 / 总相位**。

### 信道融合

| 代号 | 做法 |
|------|------|
| **Single** | 每模态选 η 最大信道 |
| **Uniform** | 72 信道谱等权平均 |
| **Vote (T0-V3)** | 每 tone BPM + η·ρ 权重 → 直方图投票；谱 conf 加权 |
| **VoteP** | Vote + 剔除跨窗不稳定 tone |
| **Single-best per modal** | Modal top2 信道侧：每模态选能量比最高信道 |

### 模态融合

| 代号 | 做法 |
|------|------|
| **Equal** | remote / local / phase 1:1:1 |
| **Top2** | 按 score 保留 top2 模态等权 |
| **η-weight** | 三模态 η 加权 |

### 本报告主要方法速查

| 代号 | 信道融合 | 模态融合 | 门控 |
|------|----------|----------|------|
| **B1** Vote→Equal | 每模态 Vote | Equal | — |
| **B3** Vote→Top2 | 每模态 Vote | Top2 | — |
| **T0-V3** | Vote（仅 remote） | 无 | — |
| **Modal top2** | Single-best per modal | Top2 | — |
| **G4** | （候选内见上） | （候选内见上） | T0-V3 vs Modal；分歧 → Single |
| **G4-B1-v2** | 同上 + B1 | 同上 | 三候选最近一对共识 |

```text
G4-B1-v2 (8.05%) = 窗级: T0-V3 vs Modal_top2 vs B1 → 最近一对共识
B1     (8.45%)   = Vote(每模态) → Equal(三模态)
G4     (8.65%)   = 窗级: T0-V3 vs Modal_top2 → 分歧则 Single
```

> **命名注意**：Systematic **B1**（`b1_vote_modal_equal`）≠ Baseline **B1 Uniform Remote**（`b1_uniform_remote`）。
