# Liu 2016 BLE 变量消融实验报告

## 定位说明

本报告只讨论 BLE 数据中的四类变量对比：

- `remote_amplitudes`
- `local_amplitudes`
- `phases`
- `combined (remote+local+phases)`

这部分是 **BLE 变量消融实验**，不是 Liu et al. 2016 原文严格复现。Liu 2016 原文方法只基于 WiFi CFR/CSI 幅度子载波，因此四变量对比不能写成 Liu 原文方法，也不能混入 `liu_2016_paper` 主结果。

本报告对应的是已有 BLE 适配基线，即 `liu_eta_rho_adapted` / 历史 Liu-style adapted pipeline。它使用本项目已有的多通道缓存、BLE 变量构造和适配性质量指标。严格原文复现结果见 [liu_2016_results_report.md](</Users/shenmeichen/26 X program/ble_hci_sensing-main/docs/reports/liu_2016_results_report.md>)。

## 数据来源

结果来自此前运行：

```bash
PYTHONPATH=src python notebooks/scripts/chFusion_liu_2016_modal_comparison.py --all
```

主要 CSV：

- `outputs/reports/liu_2016_cs_091339_modal_comparison.csv`
- `outputs/reports/liu_2016_cs_095806_modal_comparison.csv`
- `outputs/reports/liu_2016_cs_102621_modal_comparison.csv`
- `outputs/reports/liu_2016_cross_scenario_modal_summary.csv`

新整理的紧凑图表放在：

- `outputs/figures/liu_2016_ble_ablation/liu_2016_ble_ablation_cross_variable_summary.png`
- `outputs/figures/liu_2016_ble_ablation/liu_2016_ble_ablation_scenario_heatmap.png`
- `outputs/figures/liu_2016_ble_ablation/liu_2016_ble_ablation_cs_091339_summary.png`
- `outputs/figures/liu_2016_ble_ablation/liu_2016_ble_ablation_cs_095806_summary.png`
- `outputs/figures/liu_2016_ble_ablation/liu_2016_ble_ablation_cs_102621_summary.png`

## 跨场景总体结果

| 变量 | 跨场景平均相对误差 | 排名 | 解释 |
|---|---:|---:|---|
| `combined (remote+local+phases)` | 8.66% | 1 | 总体最低，说明 BLE 多变量融合在适配基线中有收益。 |
| `remote_amplitudes` | 8.93% | 2 | 与 combined 非常接近，是单变量中最稳定的一类。 |
| `phases` | 10.95% | 3 | 整体可用，但跨场景波动更明显。 |
| `local_amplitudes` | 14.02% | 4 | 总体最差，主要受 `cs_091339` 中大误差拖累。 |

总体结论：在这个 BLE adapted baseline 中，`combined` 平均最好，`remote_amplitudes` 接近 `combined`，`phases` 次之，`local_amplitudes` 最弱。

## 分场景结果

| 场景 | 最优变量 | 最优平均误差 | 变量排序 |
|---|---|---:|---|
| `cs_091339` | `remote_amplitudes` | 13.20% | `remote_amplitudes` ≈ `combined` < `phases` < `local_amplitudes` |
| `cs_095806` | `phases` | 6.43% | `phases` ≈ `local_amplitudes` < `combined` < `remote_amplitudes` |
| `cs_102621` | `local_amplitudes` | 5.05% | `local_amplitudes` < `combined` < `remote_amplitudes` < `phases` |

分场景结果说明，四变量表现并非完全固定。`combined` 的优势主要体现在跨场景平均稳定，而不是每个场景都第一。单场景里，`phases` 或 `local_amplitudes` 也可能达到更低误差。

## 分场景数值表

| 场景 | `combined` | `remote_amplitudes` | `phases` | `local_amplitudes` |
|---|---:|---:|---:|---:|
| `cs_091339` | 13.42% | 13.20% | 16.02% | 29.45% |
| `cs_095806` | 6.95% | 7.69% | 6.43% | 6.48% |
| `cs_102621` | 5.36% | 5.74% | 9.75% | 5.05% |

## 图表说明

推荐使用新整理的紧凑图，而不是旧的多子图长标签版本：

1. `liu_2016_ble_ablation_cross_variable_summary.png`
   - 展示四变量跨场景平均误差；
   - 用于报告总览。

2. `liu_2016_ble_ablation_scenario_heatmap.png`
   - 展示场景 × 变量的误差矩阵；
   - 用于说明“combined 总体最好，但单场景最优变量会变化”。

3. `liu_2016_ble_ablation_{scenario}_summary.png`
   - 每个场景一张紧凑柱状图；
   - 用于逐场景解释变量差异。

旧图已归档到 `outputs/figures/liu_2016_ble_ablation/legacy_modal/` 下，例如 `liu_2016_cs_091339_modal_comparison_bars.png` 和 `liu_2016_cs_091339_modal_by_segment.png`。这些图可以作为历史输出，但因为标签较长、版式较拥挤，不建议作为最终报告主图。

### 推荐主图

**图 1：四变量跨场景平均误差**

![四变量跨场景平均误差](../../outputs/figures/liu_2016_ble_ablation/liu_2016_ble_ablation_cross_variable_summary.png)

**图 2：场景 × 变量误差热图**

![场景与变量误差热图](../../outputs/figures/liu_2016_ble_ablation/liu_2016_ble_ablation_scenario_heatmap.png)

**图 3：分场景变量对比**

![cs_091339 变量对比](../../outputs/figures/liu_2016_ble_ablation/liu_2016_ble_ablation_cs_091339_summary.png)

![cs_095806 变量对比](../../outputs/figures/liu_2016_ble_ablation/liu_2016_ble_ablation_cs_095806_summary.png)

![cs_102621 变量对比](../../outputs/figures/liu_2016_ble_ablation/liu_2016_ble_ablation_cs_102621_summary.png)

## 结果解释

四变量对比的主要意义是回答：在 BLE CS 数据中，哪类变量更适合承载 Liu-style 呼吸频率估计流程。结果显示，`remote_amplitudes` 单独已经接近 `combined`，说明远端幅度变量可能是当前 BLE 数据中最接近 CFR 幅度信息的一类变量。

`combined` 的跨场景平均误差最低，说明融合多个 BLE 变量可以提升总体稳健性。但是这属于 BLE adaptation，不属于 Liu 2016 原文方法。写论文或报告时应表述为：

> 在 BLE 适配基线中，四变量消融显示 `combined` 与 `remote_amplitudes` 表现最好；但严格 Liu 2016 原文复现仍以 amplitude-like variable 为主输入。

`local_amplitudes` 在 `cs_091339` 中误差显著偏高，但在 `cs_102621` 中反而最好，说明 local amplitude 对场景或采集条件更敏感。`phases` 在 `cs_095806` 中最好，但整体均值不如 amplitude 类变量稳定。

## 结论

四变量对比可以作为 BLE adaptation 的补充实验，用来解释不同 BLE 变量的信息量和稳定性。它不能替代 `liu_2016_paper`，也不能作为 Liu 2016 原文严格复现结果。

建议最终文档中采用如下结构：

1. `liu_2016_paper`：严格原文复现，只使用 `amplitudes`。
2. `liu_eta_rho_adapted`：BLE 适配基线。
3. 本报告：BLE 四变量消融，解释 `remote/local/phase/combined` 的相对表现。
