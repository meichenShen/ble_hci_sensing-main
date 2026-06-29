# BLE CS 呼吸感知 — 方法注册表

> **用途**：记录当前已验证的全部方法，标注物理自洽性、实现位置、实验结论和维护状态。  
> **更新规则**：新实验产生可部署的方法或推翻既有结论时，更新本文档对应条目。  
> **最后更新**：2026-06-23

---

## 1. 当前推荐方法

### 1.1 物理自洽最优：B1 Vote→Equal (8.45%)

| 字段 | 内容 |
|------|------|
| **代号** | B1（Systematic B1 = `b1_vote_modal_equal`） |
| **描述性全称** | 逐模态 η·ρ Voting → 三模态等权谱融合 |
| **跨域 mean** | **8.45%**（cs_091339: 13.22%, cs_095806: 6.50%, cs_102621: 5.63%） |
| **物理自洽性** | ✅ 自洽 — 两层均为质量驱动 + 对称对待 |
| **信道融合** | 逐模态 η·ρ Voting（per-tone 质量加权直方图投票 → conf 加权谱平均） |
| **模态融合** | Equal（remote_amp : local_amp : phase = 1:1:1） |
| **门控** | 无 |
| **实现** | `src/ble_analysis/systematic_fusion.py` → `per_modal_voting_spectrum()` + `modal_fusion_from_spectra(weight_mode="equal")` |
| **Plan** | [`docs/plans/systematic_modal_channel_fusion_plan.md`](../plans/systematic_modal_channel_fusion_plan.md) |
| **Report** | [`docs/reports/systematic_modal_channel_fusion_report.md`](../reports/systematic_modal_channel_fusion_report.md) |
| **成果汇报** | [`docs/achievements/systematic_modal_channel_fusion_achievement_report.md`](../achievements/systematic_modal_channel_fusion_achievement_report.md) |
| **实现指南** | [`docs/methods/b1_implementation_guide.md`](b1_implementation_guide.md) — 从原始信号到 BPM 的完整教程 |
| **状态** | ✅ **推荐部署（跨域默认）** |

**为何是"物理自洽最优"**：

- 信道融合：η·ρ 是 per-tone per-window 的信号质量代理——权重由每窗实际数据动态决定
- 模态融合：1:1:1 等权——不预设 remote 优于 local 或 phase，遵循"三种变量对称对待"原则
- 无硬编码 fallback、无预设模态偏好

**已知限制**：
- 102621 上 5.63% vs G4 4.51%（差 1.12 pp）— 该场景下门控 fallback→Remote 恰好有效
- 091339 上 13.22% — 所有方法在此场景 >12%，非 B1 特有问题

---

## 2. 方法排行榜（跨域 mean 升序）

| 排名 | 代号 | 描述性名称 | 跨域 mean | 091339 | 095806 | 102621 | 物理自洽 | 状态 |
|------|------|-----------|-----------|--------|--------|--------|----------|------|
| 1 | G4-B1-v2 | 窗级门控：三候选最近对共识 | 8.05% | 12.36 | 6.31 | 5.50 | ❌ fallback 硬编码 Remote | 实验（不推荐） |
| 2 | **B1** | **逐模态 Voting → 三模态等权谱融合** | **8.45%** | 13.22 | 6.50 | 5.63 | ✅ | **推荐** |
| 3 | G4 | 窗级门控：双候选共识→分歧回退 Single Remote | 8.65% | 12.39 | 9.05 | 4.51 | ❌ fallback 硬编码 Remote | 实验（不推荐） |
| 4 | T0-V3 | Per-Tone η·ρ 加权直方图投票（仅 Remote） | 9.20% | 13.77 | 6.84 | 6.99 | ⚠️ 仅 Remote 单模态 | Baseline |
| 5 | **B2-D** | **两级 Hilbert-MRC：tone 级相干 + modal 级 Hilbert 对齐** | **9.43%** | 15.01 | 5.82 | 7.45 | ✅ | 挂起（波形路线保留） |
| 6 | Modal top2 | 逐模态 max-η 最优信道 → Top2 等权谱融合 | 9.45% | 13.04 | 10.61 | 4.69 | ✅ | Baseline |
| 7 | B2-C | FFT 互谱相位 MRC + B1 f₀ 引导 → 三模态等权 | 9.50% | 15.98 | 5.69 | 6.83 | ✅ | 实验（不推荐部署） |
| 8 | B0 Single Remote | max-η 单信道（Remote 幅值） | 10.45% | 10.91 | 12.16 | 8.29 | ✅ | Baseline |
| 9 | MRC-PCA-η-equal | √η-MRC + PCA 符号校正 → 三模态等权 | 10.78% | 17.63 | 7.29 | 7.41 | ✅ | 实验（不推荐部署） |
| 10 | B2-Bγ | Hilbert 连续相位 + coherence gating → 三模态等权 | 10.89% | 17.85 | 5.67 | 9.17 | ✅ | 实验（不推荐部署） |
| 11 | B1 Uniform Remote | 72 tone 等权谱平均（Remote 幅值） | 11.02% | 17.09 | 9.15 | 6.82 | ✅ | Baseline |
| 12 | B2-A0 | PCA 符号校正 MRC → 三模态等权 | 12.33% | 20.57 | 6.74 | 9.69 | ✅ | 实验（不推荐部署） |

> **物理自洽判定标准**（来自 CLAUDE.md）：  
> ✅ remote/local 物理对等，不得硬编码偏好；三种变量对称对待；决策由 per-window 信号质量动态驱动。  
> ⚠️ 部分违反（如仅使用单一模态，但不硬编码哪一 modal 更优）。  
> ❌ 硬编码特定模态/信道偏好，或将特定场景下的经验有效性强加为通用规则。

---

## 3. Baseline 方法（定义与实现）

以下方法构成项目的最简方法集。所有新实验必须至少包含这些 baseline 作为参照。

### 3.1 B0 — Single Remote

| 字段 | 内容 |
|------|------|
| **描述** | 每窗选 η 最大的 tone，对其 Remote 幅值 bandpass 波形做 FFT 寻峰 |
| **跨域 mean** | 10.45% |
| **实现** | `src/ble_analysis/chfusion.py` → `estimate_segment_bpm_methods(methods=("single",), variable="remote_amplitudes")` |
| **单信道选择** | `_find_best_channel(channel_metric="energy_ratio")` |
| **模态** | 仅 Remote 幅值 |
| **物理自洽** | ✅ — 不硬编码特定 tone，max-η 每窗动态选择 |
| **备注** | 最简基线；在 091339 上 10.91% 意外地强（该场景 Remote 恰好优） |

### 3.2 B1 (old) — Uniform Remote

| 字段 | 内容 |
|------|------|
| **描述** | 72 tone 的 Remote 幅值归一化频谱等权平均后寻峰 |
| **跨域 mean** | 11.02% |
| **实现** | `src/ble_analysis/chfusion.py` → `estimate_segment_bpm_methods(methods=("uniform",), variable="remote_amplitudes")` |
| **模态** | 仅 Remote 幅值 |
| **物理自洽** | ✅ |
| **备注** | 等权不加质量区分——劣质 tone 同等贡献。被 B1（η·ρ 加权）系统性超越 |

### 3.3 B2 — Modal top2 equal

| 字段 | 内容 |
|------|------|
| **描述** | 逐模态选 max-η 最优信道 → 三模态各得一条谱 → 按 η 取 top2 模态等权谱融合 → 寻峰 |
| **跨域 mean** | 9.45% |
| **实现** | `src/ble_analysis/chfusion.py` → `estimate_modal_best_channel_fusion(weight_mode="top2_equal")` |
| **信道融合** | Single best per modal（逐模态 max-η 单信道） |
| **模态融合** | Top2 equal（每窗按 η 取前二模态，等权） |
| **物理自洽** | ✅ — Top2 每窗动态选择，不预设哪两个模态更优 |
| **备注** | Plan2 阶段最优；被 Voting 系列超越后降为 baseline |

### 3.4 B3 — Modal η-weight

| 字段 | 内容 |
|------|------|
| **描述** | 同 Modal top2，但模态融合改为三模态 η 加权（不踢出第三模态） |
| **跨域 mean** | 9.45%（与 B2 相同） |
| **实现** | `src/ble_analysis/chfusion.py` → `estimate_modal_best_channel_fusion(weight_mode="energy_ratio")` |
| **备注** | 与 B2 性能持平——在 Single-best 信道策略下 η-weight 和 top2 equal 无显著差异 |

### 3.5 T0-V3 — Per-Tone η·ρ Voting

| 字段 | 内容 |
|------|------|
| **描述** | 72 tone 各自独立估计 BPM → η·ρ 加权直方图投票（仅 Remote 模态） |
| **跨域 mean** | 9.20% |
| **实现** | `src/ble_analysis/voting_fusion.py` → `VotingConfig(voting_strategy="eta_rho_weighted")` |
| **模态** | 仅 Remote 幅值 |
| **物理自洽** | ⚠️ — 信道融合质量驱动，但仅用 Remote 单模态 |
| **备注** | Deng 2024 范式的 BLE CS 实现；095806 上 6.84% 极强，但 091339 上退化 |

---

## 4. 实验性方法（记录但不推荐部署）

### 4.1 G4 — Single fallback gating (8.65%)

| 字段 | 内容 |
|------|------|
| **描述** | 窗级：T0-V3 与 Modal top2 一致 → 加权平均；不一致 → 回退 Single Remote |
| **跨域 mean** | 8.65% |
| **实现** | `src/ble_analysis/consensus_gating.py` → `GatingConfig(strategy="single_fallback")` |
| **不推荐原因** | ❌ 分歧时硬编码回退 Single Remote — 违反 remote/local 物理对称性原则。102621 上 4.51% 可能是该场景 Remote 恰好最优的巧合 |
| **Plan** | [`docs/plans/voting_gating_plan.md`](../plans/voting_gating_plan.md) |
| **Report** | [`docs/reports/voting_gating_report.md`](../reports/voting_gating_report.md) |

### 4.2 G4-B1-v2 — 三候选最近对共识 (8.05%)

| 字段 | 内容 |
|------|------|
| **描述** | G4 的扩展：第三候选加入 B1 → 三候选（T0-V3 / Modal top2 / B1）最近一对共识 |
| **跨域 mean** | 8.05% |
| **实现** | `src/ble_analysis/b1_gating_diagnosis.py` → `_g4_b1_decision()` |
| **不推荐原因** | ❌ 共识失败时同 G4 — fallback 到 Single Remote |
| **Plan** | [`docs/plans/b1_gating_and_diagnosis_plan.md`](../plans/b1_gating_and_diagnosis_plan.md) |
| **Report** | [`docs/reports/b1_gating_and_diagnosis_report.md`](../reports/b1_gating_and_diagnosis_report.md) |

### 4.3 G5 — 双峰性门控 (8.72%)

| 字段 | 内容 |
|------|------|
| **描述** | Voting BPM 分布双峰时回退 Modal（不含硬编码 Remote） |
| **跨域 mean** | 8.72% |
| **备注** | 091339 最优（12.27%）— 双峰检测命中了 voting 多簇竞争模式。但 102621 退化。物理上无硬编码问题，但跨域未超越 B1 |

### 4.4 X1–X7 — 互谱合并 (12.25–14.95%) ← 已结案

| 字段 | 内容 |
|------|------|
| **描述** | 将 B1 的功率谱加权平均替换为 tone 间互功率谱合并（magnitude/real/coherent × 全对/Δk=1/Δk=5） |
| **跨域最优** | 12.25%（X3 coherent）vs B1 8.45%（X0 功率谱） |
| **不推荐原因** | 全局劣于 B1。**失效机制已确认——寻峰不匹配 (B)，非频谱质量下降 (A)**：互谱 `peak_significance` 系统性高于功率谱（median 高 2–4×），噪声平台降低的同时假峰更尖锐，argmax 被劫持；cs_091339 上 44–48% tone 对 cos(φᵢ−φⱼ) < 0，缺乏全局相位相干性 |
| **Plan** | [`docs/plans/cross_spectrum_combining_plan.md`](../plans/cross_spectrum_combining_plan.md) |
| **Report** | [`docs/reports/cross_spectrum_combining_report.md`](../reports/cross_spectrum_combining_report.md) |
| **诊断 Plan** | [`docs/plans/cross_spectrum_failure_diagnosis_plan.md`](../plans/cross_spectrum_failure_diagnosis_plan.md) |
| **诊断 Report** | [`docs/reports/cross_spectrum_failure_diagnosis_report.md`](../reports/cross_spectrum_failure_diagnosis_report.md) |
| **状态** | ❌ **已结案——永久废弃。** 可作未来 baseline 负对照引用 |

**收尾结论**：

互谱合并路线经两轮实验（combining + failure diagnosis）已完整闭环：

```text
第一轮（combining）：X1–X7 七种互谱变体，全局最优 X3 = 12.25%，vs B1 8.45%（+3.80 pp）
    ↓ 问题：无法区分是频谱质量差 (A) 还是寻峰失效 (B)
第二轮（diagnosis）：四项诊断（D1–D4）确认：
    D1: X3 peak_sig 系统性高于 X0（73–95% 窗），091339 上 59% 窗「更高 peak_sig + 更差 BPM」
    D2: n_effective_pairs median 1540（≠ 样本不足）
    D3: cs_091339 呼吸峰处 44–48% tone 对 cos(φᵢ−φⱼ) < 0，全局缺乏相位相干性
    D4: 互谱呼吸峰存在但非全局最高——尖锐假峰劫持 argmax
    → 结论：寻峰不匹配 (B)，非频谱质量下降 (A)
```

**互谱的根本问题**是物理层面而非工程层面：BLE CS 72 tone 跨越 72 MHz 带宽，室内多径相干带宽仅 ~1–3 MHz——tone 间缺乏天然相位相干性的场景（如 cs_091339）下，互谱的"噪声平台降低"同时放大了假峰，而 argmax 寻峰没有区分呼吸峰与假峰的机制。修复方案（多峰检测 + 先验约束）在缺乏相位相干性的场景仍无理论优势——互谱合并的上限仍取决于 tone 间 cos(φᵢ−φⱼ)，而这是由多径环境决定的，不可控。

**后续引用时**：若未来新方法需要互谱作为 baseline 负对照，直接引用 X3 = 12.25%（跨域）即可，无需重跑实验。

### 4.5 SA 系列 — 信号自适应门控 (10.66%)

| 字段 | 内容 |
|------|------|
| **描述** | 基于 per-window 信号特征（三候选一致性 / η 质量）自动选择门控策略 |
| **跨域 mean** | 10.66%（SA-v2 最优） |
| **不推荐原因** | 未超越 B1 (8.45%) |
| **Plan** | [`docs/plans/signal_adaptive_gating_plan.md`](../plans/signal_adaptive_gating_plan.md) |
| **Report** | [`docs/reports/signal_adaptive_gating_report.md`](../reports/signal_adaptive_gating_report.md) |

### 4.6 Vote→Top2 系列 (B3, 9.92%)

| 字段 | 内容 |
|------|------|
| **描述** | 逐模态 Voting → Top2 模态融合 |
| **不推荐原因** | Voting 降低模态间频谱相似度 → Top2 选择退化为随机剔除 → Equal (B1) 严格优于 Top2 (B3) |
| **诊断发现** | B1 的模态间频谱余弦相似度 0.864 vs Single-best 0.772（091339）— 机制级解释见 [`b1_gating_and_diagnosis_achievement_report.md`](../achievements/b1_gating_and_diagnosis_achievement_report.md) §D1 |

### 4.8 B2 Coherent-MRC 系列 — 时域波形融合（B2-D 9.43%）← 挂起

| 字段 | 内容 |
|------|------|
| **描述** | 时域相干 MRC 波形融合：Hilbert 连续相位补偿 + coherence gating + 两级级联（tone 级 → modal 级），输出可用呼吸波形 |
| **跨域最优** | **B2-D 9.43%**（两级 Hilbert-MRC：tone 级 Hilbert + coherence gating → modal 级 Hilbert 相位对齐 + η·γ 加权） |
| **跨域次优** | B2-C 9.50%（FFT 互谱相位 + B1 f₀ 引导）、B2-Bγ/B/D-eq 10.89–10.91%、B2-A1 11.06%、B2-A0-D 11.09%（PCA sign + 二级 Hilbert 对齐）、B2-A1-D 11.15%（Corr sign + 二级 Hilbert 对齐）、B2-A0 12.33% |
| **补充消融** | A0-D/A1-D（符号校正第一级 + Hilbert 模态对齐第二级）均远劣于 B2-D（9.43%），证实第二级 Hilbert 对齐增益依赖第一级连续相位 |
| **vs B1 (8.45%)** | 差 0.98 pp — BPM 精度未超越谱域 B1 |
| **vs WiFi MRC (10.78%)** | 优 1.35 pp — 时域路线实质性进展 |
| **关键发现** | ① 第二级 modal Hilbert 相位对齐贡献 −1.46 pp（跨域），占 B2 总提升 ~50%，但场景依赖（091339 −2.84 pp, 095806 +0.15 pp）；② Coherence gating 跨域几乎无增益（Bγ ≈ B, Δ < 0.02 pp）；③ B2-D-eq 与 B2-Bγ 三场景数值完全相同——仅加二级结构不做相位对齐 = 零增益；④ **两阶段交互效应**：第一阶段 Hilbert 单独仅优 Corr sign 0.15 pp，但在两级架构中差距放大至 1.72 pp——第一阶段 Hilbert 是第二阶段 −1.46 pp 增益的"解锁器"（A1-D ≈ A1, 11.15% vs 11.06%，第二阶段在符号校正上无效）；⑤ 计算量：Hilbert 比 PCA 便宜 ~30×，绝对值 < 1 ms/窗 |
| **不推荐原因** | BPM 精度未超越 B1；091339 退化严重（所有 B2 > 15%）。但 **B2 输出可用呼吸波形**，保留供未来真人场景波形验证（与呼吸带 ground truth 做波形相关性分析） |
| **实现** | `src/ble_analysis/coherent_mrc.py` |
| **Plan** | [`docs/plans/b2_coherent_mrc_waveform_fusion_plan.md`](../plans/b2_coherent_mrc_waveform_fusion_plan.md) |
| **Report** | [`docs/reports/b2_coherent_mrc_waveform_fusion_report.md`](../reports/b2_coherent_mrc_waveform_fusion_report.md) |
| **状态** | ⏸️ **挂起 — BPM 路线不推荐部署，波形路线保留供未来探索** |

### 4.9 WiFi MRC 迁移 — 外部 baseline 验证 ← 已结案

WiFi 呼吸感知文献（Fan 2024 / Yu 2021 WiFi-Sleep）中的时域 MRC 方法迁移到 BLE CS。BPM 估计全部劣于 B1（8.45%）。

| 代号 | 描述性名称 | 跨域 mean | 091339 | 095806 | 102621 | 物理自洽 |
|------|-----------|-----------|--------|--------|--------|----------|
| MRC-PCA-η-equal | √η-MRC + PCA 符号校正 → 三模态等权 | 10.78% | 17.63 | 7.29 | 7.41 | ✅ |
| MRC-PCA-η-sqrt | √η-MRC + PCA 符号校正 → Best modal | 11.95% | 19.09 | 8.41 | 8.33 | ✅ |
| Fan-η-equal | η-MRC + 三模态等权 | 13.51% | 18.78 | 11.79 | 9.97 | ✅ |
| Fan-η-linear | η-MRC → Best modal（Fan 2024 原文） | 15.21% | 20.31 | 13.37 | 11.95 | ✅ |
| Fan-η-sqrt / MRC-PCA-no-sign | √η-MRC → Best modal | 15.82% | 21.17 | 14.06 | 12.23 | ✅ |

> **收尾结论**：
>
> - 时域 MRC 在 BLE ~2 Hz 低采样率下可运行，**PCA 符号校正确实有效**（no-sign 15.82% → η-sqrt 11.95%，+3.9 pp），确认 BLE tone 间存在呼吸波形反相。
> - 但最优 MRC（10.78%）仍差 B1（8.45%）**2.33 pp**，时域相干融合未能复现 WiFi 文献中的相对优势。
> - B1 的优势来自两方面，已由 A1 消融定量分解：① **η·ρ 质量指标**贡献 **+2.73 pp**（Fan-η-equal 13.51% → Fan-ηρ-equal 10.78%），峰度抑制假峰 tone；② **Voting 谱域信道融合**贡献 **+2.33 pp**（Fan-ηρ-equal 10.78% vs B1 8.45%），保留了 tone 间相位差异信息，MRC 时域平均丢失了这些信息。
> - **部署建议**：不推荐将 Fan-BLE / MRC-PCA-BLE 作为默认 BPM pipeline。PCA 符号校正思路可保留供未来 B2 波形融合参考。
> - **论文意义**：本实验确认 BLE CS + Voting 谱域融合（B1, 8.45%）在 BPM 估计上**系统性地优于** WiFi MRC 方法（Fan 2024: 13.51–15.82%, Yu 2021: 10.78–15.82%），三个场景一致，不存在单场景巧合。

| 字段 | 内容 |
|------|------|
| **Plan** | [`docs/plans/wifi_mrc_baselines_plan.md`](../plans/wifi_mrc_baselines_plan.md) |
| **Report** | [`docs/reports/wifi_mrc_baselines_report.md`](../reports/wifi_mrc_baselines_report.md) |
| **诊断 Plan** | [`docs/plans/wifi_mrc_diagnosis_plan.md`](../plans/wifi_mrc_diagnosis_plan.md) |
| **实现** | `src/ble_analysis/wifi_mrc.py` |
| **状态** | ❌ **已结案——BPM 全局劣于 B1，不推荐部署。** 可作论文中「proposed vs SOTA WiFi baseline」引用 |

---

## 5. 物理自洽性判定细则

判断一个方法是否"物理自洽"，逐项检查下表。来自 CLAUDE.md 第 2 节。

| # | 检查项 | B1 | G4 | G4-B1-v2 | Modal top2 | T0-V3 |
|---|--------|----|----|----------|------------|-------|
| 1 | remote/local 对称对待 | ✅ | ❌ | ❌ | ✅ | ⚠️ |
| 2 | 三种变量对称对待 | ✅ | ❌ | ❌ | ✅ | ❌ |
| 3 | 信道/模态选择由 per-window 信号质量动态决定 | ✅ | ✅ | ✅ | ✅ | ✅ |
| 4 | 无硬编码 fallback 到特定模态/信道 | ✅ | ❌ | ❌ | ✅ | ✅ |
| 5 | 不使用总幅值（无独立物理意义） | ✅ | ✅ | ✅ | ✅ | ✅ |

**判定**：
- 全部 ✅ → 物理自洽，可推荐部署
- 任一项 ❌ → 标记为"实验性"，不推荐部署（无论跨域 mean 多低）

---

## 6. 场景与参数

所有方法共用：

| 参数 | 值 |
|------|-----|
| 滑窗 | 20 s 窗长 / 1 s 步长 |
| 滤波链 | median → highpass (0.05 Hz) → bandpass (0.1–0.35 Hz) |
| 呼吸频段 | 0.1–0.35 Hz (6–21 BPM) |
| FFT | rFFT, Hanning 窗, nfft = next_pow2(4 × win_len) |
| 寻峰 | argmax + parabolic 插值 |

| 场景 | 数据文件 | 特点 |
|------|----------|------|
| cs_091339 | `CS_frames_all_20260113_091339.jsonl` | 复杂多径，所有方法 >12% |
| cs_095806 | `CS_frames_all_20260116_095806.jsonl` | Voting 优势场景 |
| cs_102621 | `CS_frames_all_20260116_102621.jsonl` | 跨域对照 |

---

## 7. 模块与脚本索引

| 模块 | 实现的方法 |
|------|-----------|
| `chfusion.py` | B0 Single, B1 Uniform, B2 Modal top2, B3 Modal η-weight, 公共滤波/寻峰/评估 |
| `voting_fusion.py` | T0-V1/V2/V3, T1-K4/K8/K16, T2, T3（per-tone voting 系列） |
| `systematic_fusion.py` | B1 Vote→Equal, B2 Vote→η, B3 Vote→Top2, C1, C2, A1, A2, B4 |
| `consensus_gating.py` | G1–G6（窗级门控系列） |
| `b1_gating_diagnosis.py` | G4-B1-v1/v2/v3/v4, G5-B1, D1–D3 诊断 |
| `signal_adaptive_gating.py` | SA-v1, SA-v2 |
| `cross_spectrum.py` | X0–X7（互谱合并系列） |
| `wifi_mrc.py` | Fan-η-linear/√η/equal, MRC-PCA-η-sqrt/equal/no-sign（WiFi MRC 外部 baseline） |
| `coherent_mrc.py` | B2-A0/A1/B/Bγ/C/D/D-eq（时域相干 MRC + 两层级联波形融合） |
| `pca_svd.py` | PCA/SVD 降维系列 |
| `segments.py` | 滑窗、分段、滤波参数 |
| `metrics.py` | 评估指标（`_overall_rel_error`, `_seg_bpm_stats`） |

---

## 8. 更新日志

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-23 | 补充 B2 消融数据（A0-D 11.09%, A1-D 11.15%）到 §4.8；更新 header 日期 | 补充消融确认：第二级 Hilbert 对齐增益依赖第一级连续相位，符号校正+二级对齐无法复现 B2-D |
| 2026-06-23 | 新增 §4.8 B2 Coherent-MRC 系列（B2-D 9.43%），标记为挂起（波形路线保留）；新增 `coherent_mrc.py` 到模块索引；更新 §2 排行榜 | Review B2 报告：B2-D 跨域 9.43% 未超越 B1（8.45%），但全面优于 WiFi MRC（10.78%）；BPM 不推荐部署，波形输出保留供未来真人验证 |
| 2026-06-16 | 新增 §4.7 WiFi MRC 外部 baseline（Fan-η-linear/√η/equal, MRC-PCA-η-sqrt/equal/no-sign），全部劣于 B1，标记为已结案不推荐 | Review 确认 MRC-PCA-η-equal 10.78% vs B1 8.45%（差 2.33 pp） |
| 2026-06-16 | 初版 | 汇总 Voting → Gating → Systematic → Cross-Spectrum 全部实验结论 |
| 2026-06-16 | B1 标记为推荐；G4/G4-B1-v2 标记为实验（不推荐） | 物理自洽性审查——硬编码 Remote fallback |
| 2026-06-16 | 互谱 X1–X7 标记为已废弃 | 跨域 12.25–14.95%，全局劣于 B1 |
| 2026-06-16 | **互谱 X1–X7 正式结案**：失效机制已确认 → 寻峰不匹配 (B)，非频谱质量下降 (A)；附收尾结论 | diagnosis plan (D1–D4) 确认：互谱 peak_sig 更高但假峰劫持 argmax；cos(φᵢ−φⱼ) 随机相位背景不可控 |
