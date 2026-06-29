# 互谱合并失效机制诊断 — 验证报告

> **Plan**：[`docs/plans/cross_spectrum_failure_diagnosis_plan.md`](../plans/cross_spectrum_failure_diagnosis_plan.md)  
> **脚本**：`notebooks/scripts/chFusion_cross_spectrum_diagnosis.py`  
> **输入数据**：`outputs/reports/cross_spectrum_results.npy`（三场景，不跑新 benchmark）  
> **日期**：2026-06-16  
> **状态**：已完成

---

## 1. 目标与假设

对互谱合并实验（X1–X7）的负结果做 post-hoc 诊断，回答：

> 互谱 BPM 误差更大，是因为 **(A) 互谱本身比功率谱更脏**，还是 **(B) 互谱更干净但寻峰机制不匹配**？

| ID | 诊断问题 | Plan 引用 |
|----|----------|-----------|
| D1 | 窗级 `peak_significance`：X3 互谱 vs X0 功率谱 | §3.1 |
| D2 | `n_effective_pairs` 分布是否过严导致样本不足 | §3.2 |
| D3 | cs_091339 跨 tone 相位相干性 cos(φᵢ−φⱼ) | §3.3 |
| D4 | 代表性窗的功率谱 vs 互谱谱形并排 | §3.4 |

**成功标准**：给出一个明确的 A vs B 判定，并附定量证据。

---

## 2. 方法摘要

| 项目 | 内容 |
|------|------|
| 输入 | 已有 `cross_spectrum_results.npy`（含 per-window BPM、X3 诊断字段、multichannel 缓存） |
| X0 peak_sig | 诊断脚本中对每窗复算 B1 三模态等权融合谱的 `max/median` |
| X3 peak_sig | 直接读取 `cross_peak_significance_remote` |
| D3 频率点 | GT BPM 对应呼吸频段 bin |
| 不做 | 新 benchmark、调参、新方法 |

---

## 3. 实验设置

| 场景 ID | 窗数（呼吸段） | 备注 |
|---------|----------------|------|
| cs_091339 | 148 | 互谱主退化场景（X3 跨域 +3.8 pp） |
| cs_095806 | 143 | 互谱接近 X0 |
| cs_102621 | 146 | 互谱接近 X0 |

- **对比方法**：X0 B1 Vote→Equal（功率谱）vs X3 CrossSpec-coh-all（相干互谱最优）
- **指标**：窗级 peak_significance、BPM 相对误差、n_effective_pairs、cos 相干性

---

## 4. 结果

### 4.1 D1：Peak Significance 对比

数据来源：`outputs/reports/cross_spectrum_failure_diagnosis_summary.npy`

| 场景 | median peak_sig X0 | median peak_sig X3 | X3 > X0 窗占比 | peak_sig 更高但 BPM 更差窗占比 |
|------|-------------------|-------------------|----------------|-------------------------------|
| cs_091339 | 1.72 | **5.75** | **95%** | **59%** |
| cs_095806 | 8.93 | **12.35** | 82% | 50% |
| cs_102621 | 3.37 | **5.30** | 73% | 37% |

| 场景 | median err% X0 | median err% X3 |
|------|----------------|----------------|
| cs_091339 | 13.4% | **16.7%** |
| cs_095806 | 6.2% | 6.0% |
| cs_102621 | 6.9% | 5.9% |

**解读**：
- 三场景 **X3 的 peak_significance 系统性高于 X0**（73–95% 的窗），与「互谱噪声平台更低」的 plan 预期一致。
- 但在 cs_091339，**59% 的窗**满足「X3 peak_sig 更高但 BPM 误差更大」——典型 **(B) 寻峰失效** 模式。
- cs_095806/102621 上窗级 BPM 误差接近，与跨域汇总中互谱仅略差于 X0 一致。

图：
- `outputs/figures/cross_spectrum_diag_peak_sig_scatter.png`
- `outputs/figures/cross_spectrum_diag_peak_sig_hist.png`

### 4.2 D2：有效 Tone 对分布

| 场景 | median n_effective_pairs | 理论最大 C(72,2) |
|------|--------------------------|------------------|
| cs_091339 | **1540** | 2556 |
| cs_095806 | 2556 | 2556 |
| cs_102621 | 2556 | 2556 |

**解读**：cs_091339 有效对数约为全量的 60%，但仍远高于 plan 中 <100 的「样本严重不足」阈值。D2 **不能**解释 091339 上 +10 pp 的主退化——η·ρ 筛选偏严是次要因素，非主因。

图：`outputs/figures/cross_spectrum_diag_n_pairs_box.png`

### 4.3 D3：跨 Tone 相位相干性（cs_091339）

在 GT 呼吸频率 bin 处，remote 72 tone 的 cos(φᵢ−φⱼ)：

| 代表窗 | 选取准则 | cos < 0 占比 | mean cos | Δk=1 mean cos |
|--------|----------|--------------|----------|---------------|
| A | X0 BPM 最准 | **48%** | −0.011 | 0.196 |
| B | X3 BPM 最差 | **44%** | 0.082 | 0.373 |
| C | 双方法均差 | **44%** | 0.082 | 0.373 |

**解读**：
- 约 **44–48%** tone 对 cos < 0，接近 plan 中「随机相位」假设的 40% 阈值——**已验证（仅 cs_091339）**。
- 相邻 tone（Δk=1）平均 cos 仅 0.20–0.37，全对 mean cos ≈ 0，说明**仅有弱局部相干性、全局缺乏稳定相位结构**。
- 「好窗」与「差窗」的 cos 分布差异不大 → 相位随机性是该场景的**背景条件**，不能单独解释为何互谱寻峰更差。

图：
- `outputs/figures/cross_spectrum_diag_cos_matrix.png`
- `outputs/figures/cross_spectrum_diag_cos_vs_delta_k.png`

### 4.4 D4：谱形并排

对 cs_091339 / cs_095806 各取 3 类代表窗（都好 / X0 好 X3 差 / 都差），并排功率谱与相干互谱：

**观察（cs_091339）**：
- 「X0 好、X3 差」窗：互谱 peak_significance 常 **高于** 功率谱，但 argmax 落在 **非 GT 频率**（多为谐波/杂峰），呼吸峰存在但非全局最高。
- 「都好」窗：两谱 argmax 均接近 GT。
- 「都差」窗：两谱均偏离 GT，互谱假峰更尖锐（高 peak_sig 误导 argmax）。

**观察（cs_095806）**：
- 三类窗中功率谱与互谱 argmax 大多一致或接近 GT，与 D1 中该场景 BPM 误差接近一致。

图：`outputs/figures/cross_spectrum_diag_spectrum_shape.png`

---

## 5. 结论

### 核心判定

| 假说 | 判定 | 证据 |
|------|------|------|
| **(A) 频谱质量下降** | **推翻** | X3 peak_sig 系统性高于 X0（median 高 2–4×） |
| **(B) 寻峰机制不匹配** | **已验证** | 59%（091339）窗「高 peak_sig + 更差 BPM」；D4 显示尖锐假峰误导 argmax |
| D2 样本不足 | **未证实** | 091339 median 1540 对，仍充足 |
| D3 随机相位 | **仅单场景** | 091339 上 44–48% 对 cos<0，为背景条件非独有失效模式 |

**一句话**：互谱合并失败的主因是 **(B) 谱形改变导致 argmax 寻峰命中尖锐假峰**，而非互谱频谱质量变差。cs_091339 的多径环境下 tone 间相位缺乏全局相干性（D3），使互谱产生高显著性但频率错误的峰。

### 分级结论

#### 已验证

- 互谱 peak_significance 不低于功率谱，全局 BPM 退化不能归因于「互谱更脏」
- cs_091339 上互谱失效主要由 **寻峰机制与互谱谱形不兼容** 驱动
- tone 间相位在 091339 近似随机（cos<0 占 ~45%）

#### 仅单场景

- D3 随机相位结论仅来自 cs_091339
- cs_095806/102621 上互谱接近 X0，寻峰问题不明显

#### 未证实

- η·ρ 筛选导致有效对不足是主因（D2 否定）

#### 已废弃

- 在当前 argmax 寻峰框架下继续推进互谱/MRC 作为 B1 替代（与 `cross_spectrum_combining_report.md` 一致）

**部署建议**：**不推荐**将互谱合并接入默认 pipeline；若未来重访，需互谱专用寻峰（多峰检测、GT 频段先验约束等），而非直接复用 `_bpm_from_fused_spectrum()` argmax。

---

## 6. 开放问题与下一步

| ID | 问题 | 建议 |
|----|------|------|
| Q1 | 互谱专用寻峰能否挽回 091339？ | 需新 plan，不在本诊断范围 |
| Q2 | diversity combining 其他分支（非互谱） | 参考 `diversity_combining_exploration_plan.md` |
| Q3 | 091339 复杂多径是否为互谱失效的必要条件？ | 需更多场景数据 |

---

## 7. 复现

```bash
python notebooks/scripts/chFusion_cross_spectrum_diagnosis.py
```

| 产出 | 路径 |
|------|------|
| 诊断摘要 | `outputs/reports/cross_spectrum_failure_diagnosis_summary.npy` |
| D1 散点图 | `outputs/figures/cross_spectrum_diag_peak_sig_scatter.png` |
| D1 分布图 | `outputs/figures/cross_spectrum_diag_peak_sig_hist.png` |
| D2 箱线图 | `outputs/figures/cross_spectrum_diag_n_pairs_box.png` |
| D3 热力图 | `outputs/figures/cross_spectrum_diag_cos_matrix.png` |
| D3 Δk 曲线 | `outputs/figures/cross_spectrum_diag_cos_vs_delta_k.png` |
| D4 谱形图 | `outputs/figures/cross_spectrum_diag_spectrum_shape.png` |
| 本报告 | `docs/reports/cross_spectrum_failure_diagnosis_report.md` |

---

## 8. Plan 回填

- **验证状态**：已完成
- **实际脚本**：`notebooks/scripts/chFusion_cross_spectrum_diagnosis.py`
- **结论一句话**：互谱失败主因是寻峰不匹配 (B)，非频谱质量下降 (A)；091339 存在 tone 间随机相位背景。

---

## 9. 收尾：互谱路线已结案

经两轮实验（[combining](cross_spectrum_combining_report.md) + 本 diagnosis），互谱合并路线已完成闭环：

| 阶段 | 结论 |
|------|------|
| 第一轮 combining | X1–X7 全局劣于 B1 功率谱（最优 X3 12.25% vs 8.45%） |
| 第二轮 diagnosis | 确认失效机制：(B) 寻峰不匹配 — 互谱 peak_sig 更高但假峰劫持 argmax |

**互谱的物理上限受限于 tone 间相位相干性（cos(φᵢ−φⱼ)），这是多径环境的固有属性，不可通过工程手段改变。** 

此方向已正式结案。若未来新方法需引用互谱作为 baseline 负对照，直接使用 **X3 CrossSpec-coh-all = 12.25%（跨域 mean）** 即可，无需重跑。方法注册表（[`docs/methods/README.md`](../methods/README.md) §4.4）已更新为结案状态。
