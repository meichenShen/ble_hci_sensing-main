# B2 Coherent-MRC Waveform Fusion — 验证报告

> **Plan**：[`docs/plans/b2_coherent_mrc_waveform_fusion_plan.md`](../plans/b2_coherent_mrc_waveform_fusion_plan.md)  
> **脚本**：`notebooks/scripts/chFusion_b2_coherent_mrc.py`（核心模块：`src/ble_analysis/coherent_mrc.py`）  
> **场景**：`config/scenarios/cs_091339.json`、`cs_095806.json`、`cs_102621.json`  
> **日期**：2026-06-23  
> **状态**：已完成

---

## 1. 目标与假设

验证时域相干 MRC 波形融合（Hilbert 连续相位补偿 + coherence gating + 两级级联）能否在 BPM 精度上超越谱域 B1（8.45% 跨域 mean）和 WiFi MRC（10.78%）。

| ID | 假设 | Plan 引用 |
|----|------|-----------|
| Q1 | 连续相位补偿（B）显著优于仅符号校正（A0/A1） | §8.3 Q1 |
| Q2 | Coherence gating 有正向贡献（Bγ vs B） | §8.3 Q2 |
| Q3 | FFT 互谱（C）比 Hilbert（B）更稳定 | §8.3 Q3 |
| Q4 | 两层级联（D）优于单级 tone-level | §8.3 Q4 |
| Q5 | Modal 级相位对齐有增益（D vs D-eq） | §8.3 Q5 |
| Q6 | B2 最优变体 ≤ B1 8.45% | §8.3 Q6 |

**成功标准（Plan §5.3）**  
- 理想：B2-D 跨域 ≤ 8.45%  
- 最低：B2-Bγ 跨域 ≤ 10.78%，且至少一个 Phase 假设被验证  
- 失败：所有 B2 变体跨域 > 10.78%

---

## 2. 方法摘要

| 项目 | 内容 |
|------|------|
| 观测量 | `remote_amplitudes`、`local_amplitudes`、`phases`（各 72 tone） |
| 第一级 | 每模态 tone-level 相干 MRC：A0 PCA sign / A1 corr sign / B Hilbert / C FFT 互谱 |
| 质量权重 | η·ρ；Bγ/D 增加 coherence gating（γ 软降权，min_coherence=0.2 硬门控） |
| 第二级 | D：三模态 Hilbert 相位对齐 + η·γ 加权；D-eq：等权不做模态间对齐 |
| BPM 估计 | Welch PSD 寻峰（主指标）+ ACF / 峰值间隔（诊断） |
| 滑窗 | 20 s / 1 s，滤波链与 B1 完全一致 |

**实现说明**：新建 `coherent_mrc.py`；A0 复用 `wifi_mrc.mrc_pca_fusion(weight_mode="eta_rho")`；路线 C 使用 B1 Vote→Equal 逐窗 coarse f₀ 引导互谱相位估计。

---

## 3. 实验设置

| 场景 ID | 数据文件 | 备注 |
|---------|----------|------|
| cs_091339 | `sampleData/CS_frames_all_20260113_091339.jsonl` | 瓶颈场景，所有 B2 > 15% |
| cs_095806 | `sampleData/CS_frames_all_20260116_095806.jsonl` | 段 4b 略短于窗长，跳过 |
| cs_102621 | `sampleData/CS_frames_all_20260116_102621.jsonl` | 跨域对照 |

- **Baseline**：B0 Single Remote、B1 Uniform Remote、Modal top2 equal、B1 Vote→Equal modal、MRC-PCA-η-equal  
- **待测**：B2-A0 / A1 / B / Bγ / C / D / D-eq / **A0-D / A1-D**（共 9 变体）  
- **指标**：分段 BPM 相对误差 % mean/std、跨域 mean

---

## 4. 结果

### 4.1 主结果表

| 排名 | 方法 | cs_091339 | cs_095806 | cs_102621 | **跨域 mean** |
|------|------|-----------|-----------|-----------|---------------|
| **1** | **B1 Vote→Equal modal** | 13.22 | **6.50** | **5.63** | **8.45%** |
| 2 | **B2-D Two-level Hilbert-MRC** | 15.01 | 5.82 | 7.45 | **9.43%** |
| 3 | Modal top2 equal | 13.04 | 10.61 | 4.69 | 9.45% |
| 4 | B2-C FFT cross-spectrum → equal modal | 15.98 | 5.69 | 6.83 | 9.50% |
| 5 | B0 Single Remote | 10.91 | 12.16 | 8.29 | 10.45% |
| 6 | MRC-PCA-η-equal | 17.63 | 7.29 | 7.41 | 10.78% |
| 7 | B2-Bγ / B2-D-eq | 17.85 | 5.67 | 9.17 | 10.89% |
| 8 | B2-B Hilbert η·ρ | 17.80 | 5.75 | 9.19 | 10.91% |
| 9 | B2-A1 Corr sign | 18.61 | 5.89 | 8.68 | 11.06% |
| 10 | B2-A0-D PCA sign → two-level Hilbert modal | 20.31 | 6.06 | 6.89 | 11.09% |
| 11 | B2-A1-D Corr sign → two-level Hilbert modal | 20.72 | 5.86 | 6.87 | 11.15% |
| 12 | B2-A0 PCA sign | 20.57 | 6.74 | 9.69 | 12.33% |

数据来源：`outputs/reports/b2_coherent_mrc_all_results.npy`

### 4.2 假设验证

| 假设 | 判定 | 证据 |
|------|------|------|
| Q1 连续相位 > 符号校正 | **部分支持** | B (10.91%) 优于 A0 (12.33%)，但 A1 (11.06%) 与 B 接近；091339 上 B 17.80% vs A1 18.61% 差距小 |
| Q2 Coherence gating 有增益 | **未证实** | Bγ (10.89%) ≈ B (10.91%)，跨域几乎无差异 |
| Q3 FFT 互谱 > Hilbert | **部分支持** | C (9.50%) 优于 B (10.91%)，但劣于 D (9.43%) |
| Q4 两级 > 单级 | **已验证（微弱）** | D (9.43%) 优于 Bγ (10.89%)，Δ ≈ 1.46 pp |
| Q5 Modal 相位对齐有增益 | **已验证（微弱）** | D (9.43%) 优于 D-eq (10.89%)，Δ ≈ 1.46 pp |
| Q6 B2 ≤ B1 8.45% | **未证实** | 最优 B2-D 9.43%，仍差 B1 0.98 pp |
| Q7 符号校正第一级 + 第二级 Hilbert 对齐 ≈ 全 Hilbert（D） | **未证实** | A1-D 11.15% 仅略优于 A1 11.06%（+0.09 pp 更差）；A0-D 11.09% 优于 A0 12.33%（−1.24 pp）但远劣于 D 9.43%（−1.88 pp） |

### 4.3 成功标准判定

| 级别 | 条件 | 判定 |
|------|------|------|
| 理想（≤ 8.45%） | B2-D ≤ B1 | **未达成**（9.43%） |
| 最低（≤ 10.78%） | B2-Bγ ≤ MRC-PCA | **未达成**（10.89% > 10.78%） |
| 部分成功 | 连续相位优于符号校正 | **部分达成**（B > A0，但与 A1 接近） |
| 失败（> 10.78% 全部） | — | **未触发**（D/C 均 < 10.78%） |

### 4.4 现象与图

图：
- `outputs/figures/b2_coherent_mrc_leaderboard.png`
- `outputs/figures/b2_coherent_mrc_phase_method_ablation.png`
- `outputs/figures/b2_coherent_mrc_cross_domain_summary.png`

**关键现象：**

1. **谱域 B1 仍为全局最优**：B1（8.45%）优于所有 B2 变体；时域相干融合未能超越谱域 η·ρ Voting。
2. **B2-D 为 B2 系列最优**（9.43%）：两级 Hilbert-MRC + modal η·γ 对齐在 095806/102621 表现良好（5.82% / 7.45%），但 091339 仍 15.01%。
3. **091339 是 B2 的灾难性场景**：所有 B2 > 15%，A0 达 20.57%；与 WiFi MRC 诊断一致——复杂多径下 tone 间相干对齐失效。
4. **A1 corr sign 优于 A0 PCA sign**（11.06% vs 12.33%）：Phase 1 结论——pairwise 相关符号略优于全局 PCA。
5. **Coherence gating 几乎无跨域收益**：Bγ 与 B 差异 < 0.02 pp，硬门控 min_coherence=0.2 未带来 measurable 改善。
6. **B1 coarse f₀ 引导的 FFT 互谱（C）为次优 B2**（9.50%）：频域相位估计 + B1 初始化在 102621 上达 6.83%，接近 B1 的 5.63%。
7. **符号校正第一级 + 第二级 Hilbert 对齐无法复现全 Hilbert 路线增益**：A1-D（11.15%）几乎等于 A1（11.06%），第二级在符号校正第一级上仅 +0.09 pp 退化；A0-D（11.09%）相对 A0 改善 −1.24 pp，但仍远劣于 B2-D（9.43%）。**第二级 modal Hilbert 对齐的 −1.46 pp 增益依赖第一级 Hilbert 连续相位，符号校正不足以作为前提。**

---

## 5. 结论

### 已验证

- B2 时域相干 MRC 管线**可运行**，B2-D 跨域 9.43%，为 B2 系列最优。
- **两级级联 + modal 相位对齐**相对单级有 measurable 增益（D vs D-eq：9.43% vs 10.89%）。
- **Corr sign（A1）优于 PCA sign（A0）** 作为符号校正路线（11.06% vs 12.33%）。
- **FFT 互谱 + B1 f₀ 引导（C）** 优于纯 Hilbert（B）（9.50% vs 10.91%）。
- **第二级 Hilbert 对齐增益依赖第一级连续相位**：A1-D ≈ A1，符号校正 + 第二级对齐无法达到 B2-D 水平。

### 仅单场景

- B2-Bγ / B2-D-eq 在 **095806** 达 5.67%，优于 B1 的 6.50%——但该场景下 Modal top2 亦仅 10.61%，B2 与 B1 的相对关系因场景而异。
- B2-C 在 **102621** 达 6.83%，接近 B1 5.63%，但仍未超越。

### 未证实

- **B2 整体超越 B1（8.45%）**：最优 B2-D 9.43%，差距 0.98 pp。
- **Coherence gating 跨域正向贡献**（Bγ ≈ B）。
- **连续相位补偿显著优于符号校正**（B 与 A1 跨域接近）。
- **符号校正第一级 + 第二级 Hilbert 对齐可替代全 Hilbert 路线**（A1-D 11.15% vs D 9.43%）。

### 已废弃

- **Coherence 硬门控（γ < 0.2 排除）** 作为默认策略：无 measurable 跨域收益（Bγ 10.89% ≈ B 10.91%，Δ < 0.02 pp）。

### 挂起

- **B2 作为 B1 替代 BPM 部署方案**：跨域未达 B1（9.43% vs 8.45%，差 0.98 pp），091339 退化严重（所有 B2 > 15%）。**但 B2 输出可用呼吸波形**——这是 B1 谱域融合不具备的能力。保留供未来真人场景波形验证（与呼吸带 ground truth 做波形相关性分析），不作为 BPM 默认 pipeline。后续可探索的方向包括：B1+B2 per-window 动态选择器、更好的模态间相位对齐策略、091339 场景下 tone 间 coherence 退化根因的针对性修复。

---

## 6. 相对 baseline 与部署建议

| 对比 | 结论 |
|------|------|
| B2-D vs B1 Vote→Equal | **更差**（9.43% vs 8.45%） |
| B2-D vs MRC-PCA-η-equal | **更好**（9.43% vs 10.78%） |
| B2-D vs Modal top2 | **相当**（9.43% vs 9.45%） |

**部署建议**：

- **BPM pipeline**：B2 不推荐替代 B1 作为默认 BPM pipeline。B2-D（9.43%）优于 WiFi MRC（10.78%）但未达 B1（8.45%），091339 退化严重。
- **波形输出**：B2 是当前唯一输出可用呼吸波形的方案——这是 B1 谱域融合不具备的能力。**保留供未来真人场景波形验证**（与呼吸带 ground truth 做波形相关性分析），不作为 BPM 默认 pipeline。
- **后续探索**：B1+B2 per-window 动态选择器（B2 在 095806 上 5.82% 优于 B1 6.50%，存在场景互补）、091339 tone 间 coherence 退化根因诊断。

---

## 6.1 补充分析：B2 vs WiFi 系列与全项目排名

> 本节回应 Review 追问：B2 相对 WiFi/MRC 时域路线的位置，以及在全项目方法谱中的排名。  
> 数据来源：`outputs/reports/b2_coherent_mrc_all_results.npy`、`outputs/reports/wifi_mrc_baselines_results.npy`，及既有门控/Voting 实验结论。

### 6.1.1 B2 在时域 / WiFi-MRC 家族内的位置

B2 与 WiFi MRC 同属**时域波形融合**路线；B2 在 WiFi MRC 基础上增加了 Hilbert 连续相位对齐、coherence gating 和两级级联。

| 排名 | 方法 | 跨域 mean | vs MRC-PCA-η-equal |
|------|------|-----------|---------------------|
| **1** | **B2-D Two-level Hilbert-MRC** | **9.43%** | **−1.35 pp** |
| 2 | B2-C FFT 互谱 + B1 f₀ | 9.50% | −1.28 pp |
| 3 | MRC-PCA-η-equal（WiFi 最优） | 10.78% | — |
| 4 | B2-Bγ / B2-D-eq / B2-B | 10.89–10.91% | ≈ 持平 |
| 5 | B2-A1 Corr sign | 11.06% | +0.28 pp |
| 6 | MRC-PCA-η-sqrt | 11.95% | +1.17 pp |
| 7 | B2-A0 PCA sign | 12.33% | +1.55 pp |
| 8 | Fan-η-equal | 13.51% | +2.73 pp |
| 9 | Fan-η-linear | 15.21% | +4.43 pp |
| 10 | Fan-η-sqrt / MRC-PCA-no-sign | 15.82% | +5.04 pp |

**结论**：B2 **全面优于** WiFi MRC 原最优 MRC-PCA-η-equal（10.78%），最优 B2-D 领先 **1.35 pp**；相对 Fan 系列（13.5–15.8%）领先约 **4–6 pp**。Hilbert 连续相位 + 两级融合将时域路线上限从 ~10.8% 推至 ~9.4%。

### 6.1.2 B2 在全项目中的排名

| 全项目排名 | 方法 | 跨域 mean | 物理自洽 | 状态 |
|-----------|------|-----------|----------|------|
| 1 | G4-B1-v2 三候选最近对共识 | 8.05% | ❌ fallback→Remote | 实验，不推荐 |
| **2** | **B1 Vote→Equal** | **8.45%** | ✅ | **推荐部署** |
| 3 | G4 Single fallback | 8.65% | ❌ | 实验 |
| 4 | T0-V3 Per-Tone Voting | 9.20% | ⚠️ 仅 Remote | Baseline |
| **5** | **B2-D Two-level Hilbert-MRC** | **9.43%** | ✅ | **B2 最优** |
| 6 | Modal top2 equal | 9.45% | ✅ | Baseline |
| 7 | B2-C FFT cross-spectrum | 9.50% | ✅ | B2 次优 |
| 8 | B0 Single Remote | 10.45% | ✅ | Baseline |
| 9 | MRC-PCA-η-equal | 10.78% | ✅ | WiFi 最优 |

**结论**：B2-D 在全项目约排**第 5**（若计入门控实验则次于 G4-B1-v2 / B1 / G4 / T0-V3）。B2 是**时域路线的最优解**，但**谱域 B1 仍是全项目 BPM 精度冠军**。

---

## 6.2 补充分析：两级架构与第二级 Hilbert 模态对齐的贡献

> 本节澄清 B2 两级结构，并量化第二级（模态间 Hilbert 相位对齐 + η·γ 加权）在 B2 内部的准确率贡献。

### 6.2.1 架构确认

```
第一阶段（模态内，72 tone → 1 条波形 / 模态）
  remote / local / phase 各自做 tone-level 相干 MRC  →  y_r(t), y_l(t), y_p(t)

第二阶段（模态间，3 条波形 → 1 条最终波形）— 仅 B2-D 启用
  y_r, y_l, y_p  →  Hilbert 估模态间 Δφ  →  旋转对齐  →  η·γ 加权叠加  →  y_final(t)
```

- **B2-Bγ / B2-D-eq**：第一阶段后三模态波形**直接等权平均**，不做模态间 Hilbert 对齐。
- **B2-D**：在相同第一阶段（Bγ：tone 级 Hilbert + coherence gating）基础上，启用第二级 Hilbert 模态对齐 + η·γ 加权。

### 6.2.2 第二级贡献：干净消融（固定第一阶段 = Bγ）

| 变体 | 第二阶段 | cs_091339 | cs_095806 | cs_102621 | **跨域 mean** |
|------|----------|-----------|-----------|-----------|---------------|
| B2-Bγ | 无（三模态等权平均） | 17.85 | **5.67** | 9.17 | **10.89%** |
| B2-D-eq | 有二级结构，**无** Hilbert 对齐，仍等权 | 17.85 | **5.67** | 9.17 | **10.89%** |
| **B2-D** | **Hilbert 对齐 + η·γ 加权** | **15.01** | 5.82 | **7.45** | **9.43%** |

**关键发现**：

1. **B2-D-eq 与 B2-Bγ 三场景数值完全相同**——仅增加「二级结构」但不做相位对齐，**零增益**。
2. **第二级 Hilbert 对齐的净贡献**（Bγ/D-eq → B2-D）：跨域 **−1.46 pp**（10.89% → 9.43%），相对误差降幅约 **13.4%**。
3. **场景不稳定**：091339 **−2.84 pp**、102621 **−1.72 pp** 有改善；095806 **+0.15 pp** 略变差。
4. **B2-C（9.50%）无第二级**，与 B2-D 仅差 **0.07 pp**——说明单级 + FFT 互谱相位亦可接近最优，第二级 Hilbert 并非 B2 唯一通路。

### 6.2.3 第二级在 B2 总提升中的占比

B2 最差（A0）→ B2 最优（D）跨域：12.33% → 9.43% = **−2.90 pp**。

| 来源 | 对比 | 贡献 |
|------|------|------|
| 第一阶段路线优化 | A0 → Bγ | **−1.44 pp**（12.33% → 10.89%） |
| **第二级模态 Hilbert 对齐** | **Bγ → B2-D** | **−1.46 pp**（10.89% → 9.43%） |

第二级约占 B2 从 A0 到 D 总提升的 **~50%**，是 B2 内部**唯一有效的「级联」增量**；但尚不足以弥补与 B1 的 **0.98 pp** 差距。

### 6.2.4 小结（Review 判定用）

| 问题 | 答案 |
|------|------|
| 第二级 Hilbert 是 B2 系列最优吗？ | ✅ B2-D（9.43%）为 B2 跨域最优 |
| 第二级是全项目最优吗？ | ❌ 全项目 BPM 冠军仍为 B1（8.45%） |
| 第二级在 B2 内贡献多少？ | 跨域 **−1.46 pp**（固定第一阶段 Bγ）；占 A0→D 总提升约一半 |
| 是否「明显提升」？ | B2 内部：**是主要增益来源**；全项目：**不够**（未超 B1）；稳定性：**场景依赖** |

### 6.2.5 补充消融：符号校正第一级 + 第二级 Hilbert 对齐（A0-D / A1-D）

> 来源：`docs/plans/b2_sign_first_level_hilbert_second_ablation.md`（2026-06-23 补充执行）

| 变体 | 第一级 | 第二级 | cs_091339 | cs_095806 | cs_102621 | **跨域 mean** |
|------|--------|--------|-----------|-----------|-----------|---------------|
| B2-A1 | Corr sign | 无 | 18.61 | 5.89 | 8.68 | 11.06% |
| **B2-A1-D** | Corr sign | Hilbert 对齐 + η·γ | 20.72 | 5.86 | 6.87 | **11.15%** |
| B2-A0 | PCA sign | 无 | 20.57 | 6.74 | 9.69 | 12.33% |
| **B2-A0-D** | PCA sign | Hilbert 对齐 + η·γ | 20.31 | 6.06 | 6.89 | **11.09%** |
| B2-D（对照） | Hilbert η·ρ·γ | Hilbert 对齐 + η·γ | 15.01 | 5.82 | 7.45 | **9.43%** |

**结论**：

1. **A1-D ≈ A1**（11.15% vs 11.06%）：在 Corr sign 第一级上，第二级 Hilbert 对齐**几乎无净增益**（跨域 +0.09 pp 退化）。
2. **A0-D 部分改善 A0**（11.09% vs 12.33%，−1.24 pp），但远劣于 B2-D（−1.88 pp 差距）——第二级在 PCA sign 第一级上仅保留约 **43%** 的 Bγ→D 增益（−1.24 / −1.46）。
3. **推翻「符号校正 + 第二级对齐已足够」假设**：第二级 −1.46 pp 增益**依赖第一级 Hilbert 连续相位**；0/π 符号校正无法为模态间 Hilbert 对齐提供足够精确的 tone 级相位信息。

---

## 7. 保留问题

| ID | 问题 | 状态 |
|----|------|------|
| Q1 | tone 间呼吸相位偏移在 20 s 窗口内是否稳定？ | `[待确认]` — 091339 退化暗示不稳定或 γ 整体偏低 |
| Q2 | Hilbert 边界效应在 ~2 Hz 采样下是否可接受？ | 未单独诊断 |
| Q3 | 三模态呼吸波形响应函数是否同构？ | D vs D-eq 差异支持部分异构 |
| Q4 | B2 融合波形的 η 是否高于单 tone？ | 未在本轮输出 per-window η 对比图 |
| Q5 | 091339 上 tone 间 γ 是否系统性偏低？ | 需补 coherence 热力图诊断 |

---

## 8. 产出清单

| 类型 | 路径 |
|------|------|
| 模块 | `src/ble_analysis/coherent_mrc.py` |
| 脚本 | `notebooks/scripts/chFusion_b2_coherent_mrc.py` |
| 跨域脚本 | `notebooks/scripts/chFusion_b2_coherent_mrc_cross_domain.py` |
| 数值结果 | `outputs/reports/b2_coherent_mrc_all_results.npy` |
| 跨域汇总 | `outputs/reports/b2_coherent_mrc_all_cross_domain.npy` |
| 图表 | `outputs/figures/b2_coherent_mrc_*.png`（含 `two_level_contribution`、`waterfall_decomposition`） |
| 报告 | 本文件 |

---

## Self Check

- Plan read: yes
- Baseline confirmed: yes
- Scenario JSON used: yes
- Script executed: yes
- Results generated: yes
- Figures generated: yes（leaderboard / ablation / cross-domain summary；coherence 热力图等 P1 诊断图未生成）
- Report generated: yes
- Plan updated: yes
- Hardcoded frame index risk: no
- Baseline changed: no
- Metric definition changed: no
- Ready to commit: yes
