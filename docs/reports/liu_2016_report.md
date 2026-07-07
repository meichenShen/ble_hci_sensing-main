# Liu et al. 2016 复现说明与文件整理

## 范围与命名

本项目现在把 Liu 2016 相关实现分成两条清楚的线，后续写报告、画图和比较时都按这个命名使用：

1. **`liu_2016_paper`**：按照 Liu et al. 2016 原文流程实现的严格复现版本，用于 BLE CS 幅度频点。
2. **`liu_eta_rho_adapted`**：已有的 BLE 适配基线，使用本项目自定义的信号质量指标。

`liu_2016_paper` 不使用 `η·ρ` 权重、谱峰突出度权重、dominant-tone fallback、投票、PCA/SVD、门控、top-k 融合或多模态融合。`remote/local/phase/combined` 只能作为后续 BLE 消融实验，不能写成 Liu 原文方法。

## 文件整理

当前与 Liu 复现直接相关的文件如下：

| 文件 | 当前定位 |
|---|---|
| `src/ble_analysis/liu_2016.py` | Liu 2016 相关算法实现；同时保留 `liu_2016_paper` 和 `liu_eta_rho_adapted` 两条路径。 |
| `notebooks/scripts/chFusion_liu_2016_paper.py` | 严格原文复现实验入口；默认只跑 `amplitudes`。 |
| `notebooks/scripts/chFusion_liu_2016.py` | 历史 Liu-style/适配版运行脚本；保留兼容，但不再作为严格复现入口。 |
| `notebooks/scripts/chFusion_liu_2016_modal_comparison.py` | BLE 多变量消融实验；不能表述为 Liu 原文复现。 |
| `tests/test_liu_2016.py` | 同时测试严格原文复现和 BLE 适配基线，并在测试名中区分。 |
| `docs/reports/liu_2016_report.md` | 本文件：方法说明、命名约定、输出结构。 |
| `docs/reports/liu_2016_results_report.md` | 结果报告：本次运行结果、图表索引和解释。 |

## 原文严格复现版本

参考论文：

> Xuefeng Liu, Jiannong Cao, Shaojie Tang, Jiaqi Wen, and Peng Guo, "Contactless Respiration Monitoring Via Off-the-Shelf WiFi Devices," IEEE Transactions on Mobile Computing, 15(10), 2466-2479, 2016.

Liu 2016 原文输入是 WiFi CFR/CSI 的子载波幅度。对应到本项目的 BLE CS 数据，严格复现默认使用 `amplitudes`，因为 `load_ble_frames` 读出的原始帧中包含逐频点的 `channels[*]["amplitude"]`，这是当前数据结构里最接近 CFR 幅度的变量。

### 算法流程与分步输出

对每个 breath 段落：

1. 根据帧的 `index`、`timestamp_ms` 和 `channels` 提取逐频点的原始 `amplitude`。
2. 对每个频点执行 Liu-style 预处理：
   - Hampel 异常点去除；
   - 线性插值到均匀时间网格；
   - 四层 `db4` 小波近似重构。
3. 对每个 20 s 窗口、每个频点估计呼吸频率：
   - 对窗口信号做 FFT；
   - 在配置的呼吸频段内寻找正频率 FFT 峰值；
   - 只保留峰值 bin 及其左右相邻 bin，即 peak ± 1；
   - 其他频率 bin 置零后做 inverse FFT，得到复数窄带时域信号；
   - 对相位展开，通过相位斜率细化估计更高分辨率的频率。
4. 计算周期性指标：
   - 固定上一步估计出的频率 `f`，拟合 `a sin(2*pi*f*t) + b cos(2*pi*f*t) + D`；
   - 计算 `A = sqrt(a^2 + b^2)`；
   - 计算拟合误差 `RMSE`；
   - 使用 Liu 原文的周期性水平 `pr = A / RMSE`。
5. 对所有频点的频率候选值使用 Liu 原文 modified Z-score 去除离群值。
6. 对剩余频率候选值使用 `pr` 归一化权重做加权中位数融合。
7. 将最终频率转换为 BPM。

Liu 原文中提到用 Nelder-Mead 拟合正弦参数。由于本实现中频率 `f` 已由前一步估计并固定，剩余参数可写成等价的线性最小二乘形式 `a sin(2*pi*f*t) + b cos(2*pi*f*t) + D`。报告和代码中均按这个等价形式说明。

每一步的输出不再只给一个总表，而是拆成三类 CSV 和多类图：

| 步骤 | 表格/图 | 用途 |
|---|---|---|
| 预处理可行性 | `diagnostics/liu_2016_paper_{scenario}_diagnostics.csv` 与 `*_preprocessing_status.png` | 检查每个频点是否通过原始预处理，特别是 `db4` level 4 样本数是否足够。 |
| 窗口估计 | `windows/liu_2016_paper_{scenario}_window_results.csv` 与 `*_window_diagnostics.png` | 查看每个窗口的 BPM、保留频点数、`pr`、离群比例。 |
| 段落汇总 | `summary/liu_2016_paper_{scenario}_summary.csv` 与 `*_segment_errors.png` | 计算每个呼吸段的预测 BPM、相对误差、有效窗口数。 |
| 跨场景汇总 | `liu_2016_paper_cross_scenario_summary.csv`、`*_coverage_heatmap.png`、`*_cross_scenario_summary.png` | 查看有效段覆盖率和跨场景误差。 |

### 参数设置

| 参数 | 当前值 | 说明 |
|---|---:|---|
| 窗长 | 20 s | Liu 2016 主实验设置 |
| 步长 | 1 s | 本项目滑窗评估设置 |
| 呼吸频段 | 0.1-0.35 Hz | 覆盖当前 GT：8.675-16.17 BPM |
| Modified Z-score 阈值 | 3.5 | Liu 原文阈值 |
| Modified Z-score 系数 | 0.7645 | Liu 2016 PDF 公式 (4) 中显示的数值 |
| 小波 | db4, level 4 | Liu 原文预处理 |

需要特别说明：`0.7645` 与常见 modified Z-score 系数 `0.6745` 不同。本实现以 Liu 2016 PDF 公式中显示的 `0.7645` 为准，并在 `Liu2016PaperConfig` 中保留可配置项。

### BLE 采样率限制

Liu 原文 WiFi 设置约每 50 ms 发送一个数据包，即约 20 Hz。本项目 BLE CS 示例数据的采样率约为 1.7-1.9 Hz。因此，严格实现会在每个完整段落、每个频点上检查是否足够支持 `db4` level 4 小波分解。

如果 `pywt.dwt_max_level(n_samples, db4.dec_len) < 4`，该频点会被跳过，并在诊断表中记录 `skip_reason=wavelet_level_insufficient`。实现不会静默降级到更低的小波层数。

这意味着：本项目实现了基于原始数据的 Liu-style 预处理，但 BLE 低采样率会限制可参与严格复现的段落和频点数量。

## 已有 BLE 适配基线

历史实现保留为：

- `estimate_liu_eta_rho_adapted_window_bpms`
- `run_liu_eta_rho_adapted_benchmark`

为了兼容旧 notebook，`estimate_liu_style_window_bpms` 和 `run_liu_2016_benchmark` 等旧名称仍然存在，但它们指向的是 BLE 适配基线，不是严格 Liu 2016 复现。

该适配基线使用：

- 本项目的呼吸频段能量比例；
- 谱峰质量指标；
- `η·ρ` 权重；
- dominant-tone fallback。

它可以作为 BLE 基线使用，但不能写成 Liu et al. 2016 原文方法。

## 复现命令

严格原文复现：

```bash
PYTHONPATH=src python notebooks/scripts/chFusion_liu_2016_paper.py --scenario cs_091339
PYTHONPATH=src python notebooks/scripts/chFusion_liu_2016_paper.py --all
```

单元测试：

```bash
.venv/bin/python -m unittest tests/test_liu_2016.py -v
```

## 输出文件

严格复现结果单独输出到 `liu_2016_paper` 子目录：

- `outputs/reports/liu_2016_paper/summary/liu_2016_paper_{scenario}_summary.csv`
- `outputs/reports/liu_2016_paper/windows/liu_2016_paper_{scenario}_window_results.csv`
- `outputs/reports/liu_2016_paper/diagnostics/liu_2016_paper_{scenario}_diagnostics.csv`
- `outputs/reports/liu_2016_paper/liu_2016_paper_cross_scenario_summary.csv`
- `outputs/reports/liu_2016_paper/liu_2016_paper_results_report.md`
- `outputs/figures/liu_2016_paper/liu_2016_paper_{scenario}_segment_errors.png`
- `outputs/figures/liu_2016_paper/liu_2016_paper_{scenario}_preprocessing_status.png`
- `outputs/figures/liu_2016_paper/liu_2016_paper_{scenario}_segment_{segment}_window_diagnostics.png`
- `outputs/figures/liu_2016_paper/liu_2016_paper_coverage_heatmap.png`
- `outputs/figures/liu_2016_paper/liu_2016_paper_cross_scenario_summary.png`

关键字段包括：`scenario`、`segment`、`method`、`variable`、`bpm_gt`、`bpm_pred`、`mean_rel_err_pct`、`std_rel_err_pct`、`n_windows`、`median_n_tones`、`median_n_kept`、`mean_outlier_frac`、`mean_pr`、`zscore_scale`、`breath_freq_low`、`breath_freq_high`、`preprocessing_mode` 和 `skip_reason`。

## 图表目录整理

当前 Liu 相关图表按用途分为三类：

| 目录 | 用途 |
|---|---|
| `outputs/figures/liu_2016_paper/` | 严格原文复现主图和窗口诊断图。 |
| `outputs/figures/liu_2016_ble_ablation/` | BLE 四变量消融实验主图。 |
| `outputs/figures/liu_2016_adapted_legacy/` | 旧版 BLE 适配基线诊断图归档。 |

严格复现报告和 BLE 消融报告中已经直接插入推荐主图。`legacy_flat` 和 `legacy_modal` 子目录只作历史输出归档，不建议作为最终报告主图。

本次严格复现结果和解释见 [liu_2016_results_report.md](</Users/shenmeichen/26 X program/ble_hci_sensing-main/docs/reports/liu_2016_results_report.md>)。

BLE 四变量对比已单独整理为消融实验报告，见 [liu_2016_ble_ablation_report.md](</Users/shenmeichen/26 X program/ble_hci_sensing-main/docs/reports/liu_2016_ble_ablation_report.md>)。该报告不属于 Liu 2016 原文严格复现主结果。
