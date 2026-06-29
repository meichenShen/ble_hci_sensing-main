# 互功率谱合并 (Cross-Spectrum Combining) — 验证报告

> **Plan**：[`docs/plans/cross_spectrum_combining_plan.md`](../plans/cross_spectrum_combining_plan.md)  
> **脚本**：`notebooks/scripts/chFusion_cross_spectrum.py`（核心模块：`src/ble_analysis/cross_spectrum.py`）  
> **场景**：`config/scenarios/cs_091339.json`、`cs_095806.json`、`cs_102621.json`  
> **日期**：2026-06-16  
> **状态**：已完成

---

## 1. 目标与假设

验证将 B1 信道融合步骤从功率谱 η·ρ 加权平均替换为互功率谱合并，能否利用 BLE CS 跨 tone 相位一致性进一步改善 BPM 估计。

| ID | 假设 | Plan 引用 |
|----|------|-----------|
| H1 | 至少一种互谱模式（X1–X7）跨域 mean ≤ 8.45%（优于 X0/B1 功率谱） | §5.3 良好 |
| H2 | 相邻 tone 实部（X5）优于全 tone 对实部（X2） | §4.3 |
| H3 | 相干互谱（X3）略优于幅值互谱（X1） | §4.3 |
| H4 | 互谱对 cs_091339（voting 退化场景）有独特改善 | §8.1 Q5 |

**成功标准（Plan §5.3）**：跨域 mean < 8.45% 为良好；全部 X* > 9.5% 且无场景改善为失败。

---

## 2. 方法摘要

| 项目 | 内容 |
|------|------|
| 观测量 | `remote_amplitudes`、`local_amplitudes`、`phases`（实信号 rFFT，无 Hilbert） |
| 信道融合 | **替换**：功率谱加权 → 互谱合并（magnitude / real / coherent × 全对/Δk=1/Δk=5） |
| 模态融合 | Equal（与 B1 一致，不变） |
| 滑窗与寻峰 | 20 s 窗 / 1 s 步；0.1–0.35 Hz；`_bpm_from_fused_spectrum()` argmax + 抛物线插值 |

---

## 3. 实验设置

| 场景 ID | 数据文件 | 备注 |
|---------|----------|------|
| cs_091339 | `sampleData/CS_frames_all_20260113_091339.jsonl` | voting 退化场景 |
| cs_095806 | `sampleData/CS_frames_all_20260116_095806.jsonl` | B1 优势场景 |
| cs_102621 | `sampleData/CS_frames_all_20260116_102621.jsonl` | 跨域对照 |

- **Baseline X0**：B1 Vote→Equal（`b1_vote_modal_equal`，自 `systematic_fusion_results.npy` 导入）
- **待测方法**：X1–X7（七种互谱变体，本实验新跑）
- **参考 Baseline**（导入，不重跑）：B0、B1 Uniform、B2 Modal top2、T0-V3、G4
- **指标**：分段 BPM 相对误差 %（mean / std）、跨域 mean

---

## 4. 结果

### 4.1 主结果表

数据来源：`outputs/reports/cross_spectrum_cross_domain.npy`

| 方法 | cs_091339 | cs_095806 | cs_102621 | 跨域 mean |
|------|-----------|-----------|-----------|-----------|
| **X0 B1 Vote→Equal** | **13.22** | **6.50** | **5.63** | **8.45** |
| X3 CrossSpec-coh-all | 23.20 | 7.38 | 6.16 | 12.25 |
| X2 CrossSpec-real-all | 27.16 | 7.18 | 5.41 | 13.25 |
| X5 CrossSpec-real-d1 | 26.38 | 6.95 | 6.82 | 13.38 |
| X1 CrossSpec-mag-all | 27.56 | 7.56 | 5.64 | 13.59 |
| X6 CrossSpec-mag-d5 | 27.04 | 7.03 | 6.99 | 13.69 |
| X4 CrossSpec-mag-d1 | 26.72 | 7.23 | 7.28 | 13.75 |
| X7 CrossSpec-real-d5 | 26.66 | 10.59 | 7.60 | 14.95 |
| G4 Single fallback（参考） | — | — | — | 8.65 |
| T0-V3 Per-Tone η·ρ（参考） | — | — | — | 9.20 |

### 4.2 与 plan 预期对比

| 预期（Plan §4.3 / §5.3） | 实际 | 是否一致 |
|--------------------------|------|----------|
| 至少一种 X* ≤ 8.45% | 最优 X3 = 12.25% | ❌ |
| X5 优于 X2（相邻 tone 实部最优） | X5 13.38% vs X2 13.25%（略差） | ❌ |
| X3 略优于 X1 | X3 12.25% vs X1 13.59% | ✅（但均远差于 X0） |
| X4 相当或略优于 X1 | X4 13.75% vs X1 13.59%（略差） | ❌ |
| 互谱改善 cs_091339 | 091339 全部 X* ≈ 23–28%，远差于 X0 13.22% | ❌ |

### 4.3 现象与图

- **跨域结论**：全部七种互谱变体均显著劣于 X0/B1 功率谱（Δ = +3.8 ~ +6.5 pp）；Plan §5.3「失败」档成立。
- **场景分化**：cs_095806 / cs_102621 上互谱与 X0 差距较小（~0.5–2 pp）；**cs_091339 是主要退化源**（互谱 ~27% vs X0 13.22%）。
- **模式对比**：相干互谱 X3 为互谱族最优（12.25%），但仍不如功率谱；tone 间距扫描未显示邻近对优势（X5 未优于 X2）。
- 图：
  - `outputs/figures/cross_spectrum_leaderboard.png`
  - `outputs/figures/cross_spectrum_cross_domain_aggregate_bars.png`
  - `outputs/figures/cross_spectrum_pair_spacing_scan.png`
  - `outputs/figures/cross_spectrum_vs_power_spectrum.png`

---

## 5. 结论

| 结论 | 证据强度 |
|------|----------|
| 互谱合并不能替代 B1 功率谱加权作为全局信道融合策略 | **已验证**（三场景一致劣化） |
| 互谱在 cs_091339 复杂多径场景严重失效 | **已验证** |
| cs_095806/102621 上互谱接近但未超越 X0 | **已验证** |
| 相邻 tone 实部（X5）为互谱族中 095806 最优 | **仅单场景**（6.95% vs X0 6.50%） |
| 互谱 noise floor 显著低于功率谱 | **未证实**（BPM 结果不支持） |

**相对 baseline**：全部 X* 相对 X0/B1（8.45%）**更差**；相对 G4（8.65%）、T0-V3（9.20%）亦更差。

**部署建议**：**不推荐**将互谱合并纳入默认 pipeline。功率谱 η·ρ 加权在实信号 bandpass 波形上已足够；tone 间 cos(φᵢ−φⱼ) 在多径下不满足同相假设，互谱交叉项未能带来理论预期的噪声压制。

### 已验证

- 七种互谱变体（X1–X7）在三场景全部跑齐，结果可复现。
- 互谱合并全局劣于 B1 功率谱（跨域 mean 12.25%–14.95% vs 8.45%）。

### 仅单场景

- X5 在 cs_095806 为 6.95%，与 X0 6.50% 差距最小（+0.45 pp），不足以支持全局切换。

### 未证实

- 互谱 peak significance 高于功率谱（诊断图未量化写入数值表；BPM 指标不支持该假设）。
- phase 变量互谱特别受益（本实验三模态 Equal 融合，未单独剥离）。

### 已废弃

- 将 magnitude/real/coherent 互谱作为 B1 信道融合的直接替换方案。

---

## 6. 开放问题与下一步

| ID | 问题 | 建议 |
|----|------|------|
| Q1 | cs_091339 互谱为何崩溃至 ~27%？ | 诊断 cos(φᵢ−φⱼ) 分布、有效 tone 对数；考虑是否多径导致大量 tone 对反相 |
| Q2 | 实信号互谱 vs 复包络互谱 | 若仍探索，下一 plan 用 remote·e^{jφ} 复构造后再测 |
| Q3 | 互谱是否仅适合单模态 remote？ | 消融：仅 remote 互谱 + 不做三模态 Equal |

---

## 7. 复现

```bash
python notebooks/scripts/chFusion_cross_spectrum.py
```

| 产出 | 路径 |
|------|------|
| 数值结果 | `outputs/reports/cross_spectrum_results.npy` |
| 跨域汇总 | `outputs/reports/cross_spectrum_cross_domain.npy` |
| 排行榜图 | `outputs/figures/cross_spectrum_leaderboard.png` |
| 互谱 vs 功率谱 | `outputs/figures/cross_spectrum_vs_power_spectrum.png` |
| 间距扫描 | `outputs/figures/cross_spectrum_pair_spacing_scan.png` |
| 跨域汇总图 | `outputs/figures/cross_spectrum_cross_domain_aggregate_bars.png` |

---

## Self Check

- Plan read: yes
- Baseline confirmed: yes（X0 自 systematic_fusion 导入）
- Scenario JSON used: yes
- Script executed: yes
- Results generated: yes
- Figures generated: yes
- Report generated: yes
- Plan updated: yes
- Hardcoded frame index risk: no
- Baseline changed: no
- Metric definition changed: no
- Ready to commit: yes（待用户确认）
