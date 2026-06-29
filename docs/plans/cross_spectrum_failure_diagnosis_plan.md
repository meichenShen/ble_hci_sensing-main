# 互谱合并失效机制诊断 — 实现计划

> **来源**：[`cross_spectrum_combining_report.md`](../reports/cross_spectrum_combining_report.md) — 互谱合并 (X1–X7) 全局劣于 B1 功率谱 (X0)  
> **Review 结论**：[`cross_spectrum_combining_plan.md`](cross_spectrum_combining_plan.md) — not supported，全部假设被推翻  
> **目标报告**：`docs/reports/cross_spectrum_failure_diagnosis_report.md`（模板：`docs/templates/algorithm_validation_report.md`）  
> **建议 plan 路径**：`docs/plans/cross_spectrum_failure_diagnosis_plan.md`  
> **日期**：2026-06-16  
> **验证状态**：已完成

---

## 1. 动机与背景

### 1.1 已知事实

互谱合并实验（X1–X7）产生了清晰的负结果：

| 方法 | cs_091339 | cs_095806 | cs_102621 | 跨域 mean |
|------|-----------|-----------|-----------|-----------|
| X0 B1 Vote→Equal (功率谱) | 13.22% | 6.50% | 5.63% | **8.45%** |
| X3 CrossSpec-coh-all (互谱最优) | 23.20% | 7.38% | 6.16% | **12.25%** |
| Δ (X3 − X0) | **+9.98 pp** | +0.88 pp | +0.53 pp | **+3.80 pp** |

cs_091339 是主退化源（+10 pp），cs_095806/102621 上差距较小（<1 pp）。

### 1.2 未回答的关键问题

Plan §3.5 要求输出 `cross_peak_significance`（互谱峰与噪声平台的比值）作为窗级诊断量。代码已采集（`cross_spectrum.py:317-318`），但报告正文**未做定量分析**。

这导致一个根本问题无法回答：

> 互谱的 BPM 误差更大，是因为 **(A) 互谱本身比功率谱更脏**（呼吸峰淹没在噪声中），还是因为 **(B) 互谱更干净但寻峰机制不匹配**（例如互谱谱形不同，argmax 选到了错误的峰）？

如果是 (A)：关闭互谱/MRC 方向，转向 diversity combining 框架的其他分支  
如果是 (B)：互谱仍有价值——修复寻峰机制（如引入先验约束、多峰检测等）

### 1.3 本 plan 定位

| 项目 | 说明 |
|------|------|
| 问题 | 互谱合并失效的根因是频谱质量下降还是寻峰失效？ |
| 输入 | **已有数据**（`cross_spectrum_results.npy`），不跑新实验 |
| 定位 | **纯诊断**——只分析、不训练、不调参、不产生新方法 |
| 与既有关系 | 对 `cross_spectrum_combining_plan.md` 的实验结果做 post-hoc 诊断 |

---

## 2. 诊断设计

### 2.1 诊断问题层级

```text
D1: 频谱质量对比
  互谱的 cross_peak_significance 是否确实系统性地低于/高于功率谱？
  → 若 X3 > X0：频谱更干净 → 问题在寻峰 (B)
  → 若 X3 < X0：频谱更脏   → 问题在频谱质量 (A)

D2: 有效 tone 对分析
  n_effective_pairs 的分布如何？是否大量窗口只有极少数有效 pairs？
  → 若 n_effective_pairs 中位数 < 50（vs 理论最大 2556）
    → 质量筛选过严或大部分 tone 质量太低，互谱样本不足

D3: 跨 tone 相位相干性（仅 cs_091339）
  抽取代表性窗，计算 72×72 的 cos(φᵢ−φⱼ) 矩阵
  → 若 >50% 的 tone 对 cos < 0：验证"随机相位"假设
  → 若相邻 tone（Δk=1）的 cos 分布显著优于远距离 tone
    → 说明仅邻近对有效，但邻近对数量不足支撑可靠 BPM

D4: 互谱谱形诊断
  并排对比 X0 功率谱 vs X3 互谱在同一个窗的谱形
  → 互谱的呼吸峰是否仍然是最高峰？
  → 若呼吸峰存在但非最高 → 问题在寻峰
  → 若呼吸峰消失 → 问题在频谱质量
```

### 2.2 诊断优先级

| 优先级 | 诊断 | 工作量 | 决定什么 |
|--------|------|--------|----------|
| ★★★ | D1 跨场景 peak significance 对比 | ~30 行代码 | 核心判断 A vs B |
| ★★★ | D4 互谱谱形并排（扩展现有图） | ~30 行代码 | 直观验证 |
| ★★ | D2 n_effective_pairs 分布 | ~20 行代码 | 解释退化程度 |
| ★★ | D3 cos(φᵢ−φⱼ) 矩阵（cs_091339） | ~40 行代码 | 物理机制确认 |

---

## 3. 算法步骤

### 3.1 D1：窗级 Peak Significance 对比

```text
输入: cross_spectrum_results.npy（三场景分别加载）

对每个场景:
  1. 提取 X0 (x0_b1_vote_equal) 和 X3 (x3_cross_coh_all) 的结果
     — 注意: X0 来自 B1 Vote→Equal，其原始 per_modal_voting_spectrum 未输出 peak_significance
     — 补救: 从 X0 的融合谱反算 peak_significance = max(spectrum) / median(spectrum)
       或: 重新在已有 bandpass 数据上对 X0 窗口计算 power_peak_significance
     
  2. 对每个 breath 段:
     a. 收集每个窗的 X0 和 X3 的 peak_significance 值
     b. 计算 X0 和 X3 各自的 BPM 估计值
     c. 计算 X0 和 X3 各自的 BPM 误差 |BPM − GT|

  3. 输出:
     — 全场景散点图: X0 peak_sig vs X3 peak_sig（每个点一个窗）
     — 按场景分别的 peak_sig 分布直方图（X0 vs X3 叠加）
     — 按场景分别的 "peak_sig 高但 BPM 误差大" 的窗占比
     
  4. 判定:
     若 X3 的 peak_sig > X0 但 BPM 误差也 > X0:
       → 寻峰问题 (B) — 互谱谱形不同，argmax 未命中呼吸峰
     若 X3 的 peak_sig < X0:
       → 频谱质量问题 (A) — 互谱噪声平台未如预期降低
```

### 3.2 D2：有效 Tone 对分布

```text
输入: 同上，提取 X3 的 n_effective_pairs_remote 字段

对每个场景:
  1. 汇总所有呼吸段所有窗的 n_effective_pairs
  2. 输出: 箱线图（三场景并排）
  3. 标注: 理论最大值 C(72,2)=2556 和 C(72,2, Δk≤1)=71

  判定:
    若 n_effective_pairs 中位数 < 100（全对模式）:
      → η·ρ 筛选过严，大量 tone 质量不足，互谱建立在极薄弱的样本上
```

### 3.3 D3：跨 Tone 相位相干性矩阵

```text
仅对 cs_091339（退化最严重的场景）做此诊断:

  1. 选 3 个代表性窗:
     — 窗 A: X0 BPM 误差最小的窗（"好窗"对照）
     — 窗 B: X3 BPM 误差最大的窗（"互谱最差窗"）
     — 窗 C: X0 和 X3 误差都大的窗（"都差窗"对照）

  2. 对每个窗，取 remote_amplitudes 的 72 tone bandpass 波形:
     a. Hanning 窗 → rFFT → 取呼吸频段
     b. 对每个频率 bin k（呼吸频段内）:
        — 构造 72×1 复向量 X[:, k]
        — 计算 72×72 互谱矩阵 C = X · X^H（外积）
        — 提取相位差矩阵: cos_mat = Re{C} / |C|（逐元素）
     c. 在呼吸峰频率 bin 处（GT BPM 对应的频率）:
        — 输出 72×72 cos(φᵢ−φⱼ) 热力图
        — 输出 cos 值的直方图
        — 按 Δk = |i−j| 分组的平均 cos 值曲线

  3. 判定:
     若 cos < 0 的 tone 对占比 > 40%:
       → 确认"随机相位"假设 — 多径导致 tone 间缺乏相位相干性
     若 Δk=1（相邻 tone）的 cos 均值 > 0.3 但全体的 cos 均值 ≈ 0:
       → 仅有邻近对有效，但有效对数量 (≤71) 不足以获得统计增益
```

### 3.4 D4：谱形并排诊断（扩展现有图）

```text
扩展 cross_spectrum_vs_power_spectrum.png 的内容:

  对 cs_091339（退化场景）和 cs_095806（接近场景）各选 3 个代表性窗:
    — 窗 1: X0 BPM ≈ GT 且 X3 BPM ≈ GT（都好的窗）
    — 窗 2: X0 BPM ≈ GT 但 X3 BPM ≠ GT（互谱独差的窗）
    — 窗 3: X0 BPM ≠ GT 且 X3 BPM ≠ GT（都差的窗）

  每个窗并排显示:
    — 左: X0 功率谱（标注 argmax 峰位和 GT 位置）
    — 右: X3 互谱（同上）
    — 共同标注: peak_significance 值

  输出: 一张 6 窗格图 (3 窗 × 2 谱 = 6 panels)
```

---

## 4. 预期产出

| 产出 | 路径 |
|------|------|
| 诊断报告 | `docs/reports/cross_spectrum_failure_diagnosis_report.md` |
| D1 散点图 | `outputs/figures/cross_spectrum_diag_peak_sig_scatter.png` |
| D1 分布图 | `outputs/figures/cross_spectrum_diag_peak_sig_hist.png` |
| D2 箱线图 | `outputs/figures/cross_spectrum_diag_n_pairs_box.png` |
| D3 热力图 | `outputs/figures/cross_spectrum_diag_cos_matrix.png` |
| D3 分组曲线 | `outputs/figures/cross_spectrum_diag_cos_vs_delta_k.png` |
| D4 谱形图 | `outputs/figures/cross_spectrum_diag_spectrum_shape.png` |

---

## 5. 实现要点

### 5.1 建议文件

| 类型 | 路径 |
|------|------|
| 诊断脚本 | `notebooks/scripts/chFusion_cross_spectrum_diagnosis.py` |
| 可复用模块 | 无需新建——复用 `cross_spectrum.py` 的 `_collect_tone_fft_data()` |
| 输入数据 | `outputs/reports/cross_spectrum_results.npy`（三场景） |

### 5.2 复用 API

```python
from ble_analysis.cross_spectrum import (
    _collect_tone_fft_data,  # 用于 D3: 获取复频谱
    CrossSpectrumConfig,
    per_modal_cross_spectrum,
)
from ble_analysis.chfusion import (
    ChFusionConfig,
    _next_pow2,
    _bpm_from_fused_spectrum,
)
from ble_analysis.segments import BreathMetricParams, _sliding_window_indices
```

### 5.3 核心实现提示

**D1 的 peak_significance 计算**：

X3 的 `cross_peak_significance_remote` 已存储在结果中（`cross_spectrum.py:317`）。X0/B1 的 `per_modal_voting_spectrum()` 原本不输出此值——需要在诊断脚本中，对 X0 的融合谱后计算：

```python
# 对 X0 的 per_modal_voting_spectrum 输出的 fused spectrum:
peak = np.max(fused_spectrum)
noise_floor = np.median(fused_spectrum) + eps
peak_sig = peak / noise_floor
```

**D3 的 cos(φᵢ−φⱼ) 矩阵**：

```python
# 对呼吸峰所在的频率 bin k_breath:
X_peak = x_fft[:, k_breath]  # (72,) complex
# 相位差矩阵
cross = np.outer(X_peak, np.conj(X_peak))  # (72, 72)
cos_mat = np.real(cross) / (np.abs(cross) + eps)
# cos_mat[i,j] = cos(φ_i - φ_j)
```

### 5.4 不做的事

- 不跑新的 benchmark 实验
- 不修改 `cross_spectrum.py` 或任何现有模块
- 不训练模型、不调参数
- 不生成新方法或新 leaderboard 排名

---

## 6. 风险与保留问题

| ID | 问题 | 备注 |
|----|------|------|
| Q1 | X0 的 peak_significance 需要后计算（原 pipeline 未输出），可能与 X3 的在线计算方式不完全一致 | 使用相同的 `peak / median(spectrum)` 公式确保可比 |
| Q2 | 若 D1 显示 X3 peak_sig > X0 but BPM 更差 → 确认寻峰问题；此时需后续 plan 设计互谱专用寻峰策略 | 不在本 plan 范围 |
| Q3 | 若 D1 显示 X3 peak_sig < X0 → 确认频谱质量问题；建议关闭互谱/MRC 路线 | 写入诊断报告结论 |

---

## 7. 验证状态

| 字段 | 内容 |
|------|------|
| **验证状态** | 已完成 |
| **实际脚本** | `notebooks/scripts/chFusion_cross_spectrum_diagnosis.py` |
| **报告链接** | `docs/reports/cross_spectrum_failure_diagnosis_report.md` |
| **诊断摘要** | `outputs/reports/cross_spectrum_failure_diagnosis_summary.npy` |
| **图表** | `outputs/figures/cross_spectrum_diag_*.png`（6 张） |
| **一句话结论** | 互谱失败主因是寻峰不匹配 (B)：X3 peak_sig 系统性高于 X0，但 091339 上 59% 窗 BPM 更差；非频谱质量下降 (A) |

遗留问题：
- 互谱专用寻峰是否可挽回 091339 → 需新 plan
- diversity combining 其他分支 → `diversity_combining_exploration_plan.md`

---

## 给执行 Agent 的首条指令

请在 Cursor Composer 中启用 `BLE CS 执行 Agent`，并严格执行：

`docs/plans/cross_spectrum_failure_diagnosis_plan.md`

**任务概要**：

1. 新建 `notebooks/scripts/chFusion_cross_spectrum_diagnosis.py`（~150 行）
2. 基于已有的 `outputs/reports/cross_spectrum_results.npy`（三场景），完成 §3.1–§3.4 的四项诊断（D1–D4）
3. 生成 `docs/reports/cross_spectrum_failure_diagnosis_report.md`
4. 生成 §4 列出的六张诊断图

**关键点**：
- **不跑新 benchmark**——所有数据从已有 `.npy` 文件读取
- D1 的 X0 peak_significance 需要从 X0 的融合谱后计算（原 pipeline 未存此值，需在诊断脚本中对 X0 窗复算）
- D3 仅做 cs_091339（退化最严重场景）
- 诊断报告的核心产出是**一个明确的判定**：互谱失败是频谱质量问题 (A) 还是寻峰问题 (B)
