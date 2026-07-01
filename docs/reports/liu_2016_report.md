# Liu et al. 2016 基于 BLE CS 的基线验证

## 摘要

本报告记录了 Liu 2016 风格基线在 BLE CS 呼吸 BPM 估计中的完整实现与验证。方法实现于 `src/ble_analysis/liu_2016.py`，并通过 notebook 与脚本完成实验验证。

## 什么是 tone？

在 BLE CS 中，"tone" 指 72 个 tone 中的一个频率子载波，而非独立的物理射频通道。每个 tone 在滤波后会得到一条时域波形。Liu 2016 基线对每个 tone 的时域信号分别估计 BPM 候选值，再对这些候选值进行融合。

在代码中，`channel` 有时也用于表示 tone 的索引，但核心思想是先生成每个 tone 的 BPM 候选值，再进行 tone 级融合。

## 实现详情

1. 方法概念
   - 逐 tone BPM 估计：对每个滑窗内每个 tone 的滤波信号分别估计 BPM 候选值。
   - tone 质量评分：通过呼吸带能量和谱峰突出度为每个 tone 计算质量权重。
   - 加权融合：对所有 tone 的 BPM 候选值做加权中位数融合，必要时回退到权重最高的 tone。

2. 变量与澄清
   - 使用了哪些变量：实现对三种模态变量（`remote_amplitudes`、`local_amplitudes` 和 `phases`）进行采集和评估。对每个段落/窗口，我们采集每个可用 `variable|ch` 对应的带通滤波波形，将其作为独立的 "tone" 候选。

   - 使用了哪些算法、滤波与权重：
     - 滤波：逐段使用 `FilterParams` 管线（中值滤波、高通 0.05 Hz、带通 0.1–0.35 Hz，见 `src/ble_analysis/segments.py`）。代码读取 `bandpass_filtered` 和 `highpass_filtered` 输出用于评分和 BPM 估计。
     - 逐 tone BPM：`_bpm_from_waveform` 在配置的呼吸频带内拟合正弦基，通过最小二乘评分选择最优频率，返回 `BPM = 60 * f`。
     - 质量评分：使用两个保守指标——能量比 η（`_energy_ratio`）：呼吸带能量/总能量；峰值比 ρ（`_tone_band_quality`）：峰值功率/呼吸带总功率。这些指标按 tone/窗口计算。
     - 融合规则：逐窗权重 = clip(η * ρ)（带小 eps 保护）。若所有权重接近零，使用均匀权重。最终 BPM 是逐 tone BPM 的加权中位数；如果单个 tone 主导权重且有有效 BPM，则回退到该 tone 的 BPM。

   - 额外诊断图：生成了更多诊断图以检查逐窗和逐 tone 行为（见下面的图表）。包括窗级 BPM 曲线、窗级误差直方图、段落级相对误差柱状图，以及选定段落的 tone 质量散点图（η vs ρ，以 BPM 为颜色）。

3. 代码位置
   - `src/ble_analysis/liu_2016.py`
   - `notebooks/scripts/chFusion_liu_2016.py`
   - `notebooks/liu_2016_step_by_step.ipynb`
   - `tests/test_liu_2016.py`

4. 与现有管道对齐
   - 复用 BLE CS 多通道滤波缓存和段落配置。
   - 使用 `BreathMetricParams` 和 `ChFusionConfig` 中定义的标准滑窗参数。

## 详细实现（可复现说明）

1) 变量采集
- 代码对三种模态变量 `remote_amplitudes`、`local_amplitudes` 和 `phases` 的每个 `variable|channel` 组合进行采集。每个组合产出 `bandpass_filtered` 和 `highpass_filtered` 两个数组，作为独立的 tone 候选信号。

2) 准确的滤波参数
- `FilterParams`（见 `src/ble_analysis/segments.py`）— notebook 中使用的默认值：
  - `median_window = 3`
  - `highpass_cutoff = 0.05` Hz，`highpass_order = 1`
  - `bandpass_lowcut = 0.1` Hz，`bandpass_highcut = 0.35` Hz，`bandpass_order = 2`

3) 滑窗和 BPM 窗口参数
- `BreathMetricParams`（默认值）：`breath_freq_low = 0.1` Hz，`breath_freq_high = 0.35` Hz，`window_length_sec = 20.0`，`step_length_sec = 1.0`。
- 样本级窗口长度 = round(window_length_sec * fs)，步长 = round(step_length_sec * fs)。

4) 逐 tone BPM 估计算法（`_bpm_from_waveform`）
- 前提条件：对窗化信号做去均值并要求有限样本。
- 频率网格：`freqs = linspace(cfg.breath_freq_low, cfg.breath_freq_high, 512)`（呼吸频带内 512 点扫描）。
- 对每个候选频率 f，构造两个基向量 sin(2π f t) 和 cos(2π f t)，计算最小二乘系数以拟合信号。
- 评分 = dot(sig, fit) / (||sig|| * ||fit|| + eps)（归一化相关性样评分）。选择评分最高的 f，返回 `60 * f` 作为 BPM。

5) Tone 质量指标（权重）
- 能量比 η：在 `_energy_ratio` 中实现 — 计算窗化（Hann）信号的 FFT 功率；呼吸带功率求和除以总配置频带功率。返回 [0,1] 范围内的比率。
- 峰值比 ρ：在 `_tone_band_quality` 中实现 — 计算呼吸带 FFT 功率，返回 `峰值功率/总频带功率`（保守的峰突出度）。
- 逐 tone 组合权重：`w_c = clip(η * ρ, 0, +inf) + eps`。若 sum(w_c) ≤ eps，代码使用均匀权重。

6) 融合：加权中位数 + 主导 tone 回退
- 加权中位数：`_weighted_median(values, weights)` 对值排序，计算累积归一化权重，返回 0.5 分位数处的值。
- 主导 tone 回退：如果 `argmax(weights)` 得到有有效 BPM 的 tone，立即返回该 BPM（这反映了论文对高置信度 tone 的实际偏好）。

7) 伪代码（逐窗）

```text
对每个滑窗：
  采集每个 (variable, channel) 的 bandpass_filtered 波形 -> x_i(t)
  计算 eta_i = _energy_ratio(highpass(x_i))
  计算 rho_i = _tone_band_quality(bandpass(x_i))
  估计 bpm_i = _bpm_from_waveform(bandpass(x_i))
  w_i = clip(eta_i * rho_i) + eps
  如果 sum(w_i) <= eps: w_i = ones
  dominant = argmax(w_i)
  如果 isfinite(bpm_dominant): bpm_out = bpm_dominant
  否则: bpm_out = weighted_median(bpm_i, w_i)
```

8) 可复现命令
- 为单个场景/段落生成诊断和图表：
```bash
PYTHONPATH=src python notebooks/scripts/chFusion_liu_2016_diagnostics.py --scenario cs_091339 --segment 3
```
- 为所有场景生成诊断：
```bash
PYTHONPATH=src python notebooks/scripts/chFusion_liu_2016_diagnostics.py --all
```
- 运行完整 benchmark 并保存合并结果：
```bash
PYTHONPATH=src python notebooks/scripts/chFusion_liu_2016.py --all
```

9) 生成的图表（示例）
- `outputs/figures/liu_2016_cs_091339_segment_3_window_bpm_curve.png`
- `outputs/figures/liu_2016_cs_091339_segment_3_tone_quality.png`
- `outputs/figures/liu_2016_cs_091339_segment_3_window_error_hist.png`
- `outputs/figures/liu_2016_cs_091339_segment_rel_err.png`
- 汇总图表：`segment_error_analysis.png`、`segment_window_error_distribution.png`

10) 关键文件（实现和运行器）
- `src/ble_analysis/liu_2016.py` — Liu 风格估计器和窗口聚合
- `src/ble_analysis/chfusion.py` — 通用辅助函数：`_energy_ratio`、`_weighted_median`、`_seg_bpm_stats`、FFT 辅助函数
- `src/ble_analysis/segments.py` — `FilterParams` 和滑窗辅助函数
- `notebooks/liu_2016_step_by_step.ipynb` — 交互式演示
- `notebooks/scripts/chFusion_liu_2016.py` — 批量运行脚本
- `notebooks/scripts/chFusion_liu_2016_diagnostics.py` — 诊断图生成器

如果需要，还可以补充 LS 拟合和加权中位数定义的准确公式（LaTeX），或附加一个可直接运行的 `Makefile` 片段以生成所有图表和报告 PDF。

## 执行步骤

### 步骤 1：环境准备

- 确保 notebook 或脚本从仓库根目录运行。
- 在导入 `ble_analysis` 之前将 `src` 加入 `PYTHONPATH`。
- 使用 `ble_analysis.bootstrap.init_notebook(project_root)` 初始化环境。

### 步骤 2：加载场景

- 通过 `load_scenario(scenario_id, project_root=project_root)` 加载场景 `cs_091339`。
- 确认场景包含 9 个段落：7 个呼吸段和 2 个暂停段。

### 步骤 3：多通道预处理

- 使用 `load_multichannel_for_scenario(...)` 和 `FilterParams()` 及缓存目录。
- 验证后的 notebook 报告所有变量和段落都命中缓存。
- 输出：`fs=1.80 Hz`，变量 `['remote_amplitudes', 'local_amplitudes', 'phases']`。

### 步骤 4：运行 Liu 2016 基线

- 执行 `run_liu_2016_benchmark(None, scenario.segment_config, ...)`。
- Benchmark 使用滤波后的多通道数据和相同的窗/步长设置。
- 返回一个包含每个段落结果的字典。

### 步骤 5：结果汇总

- 使用 `_overall_rel_error(bench['results'], 'liu_2016')` 汇总性能。
- 打印每个段落的 ID 和相对误差值。

### 步骤 6：单段诊断

- 选取 `seg_name='3'` 进行详细分析。
- 提取 `row['liu_2016']['bpm_per_window']` 和真值 `row['bpm_gt']`。
- 绘制滑窗 BPM 曲线并保存图表。

## 结果

| 场景 | 平均相对误差 (%) | 标准差 (%) | 备注 |
|---|---|---|---|
| cs_091339 | 14.62 | 8.50 | 中等精度 |
| cs_095806 | 39.45 | 38.02 | 误差大且稳定性差 |
| cs_102621 | 4.21 | 1.71 | 表现良好 |

- `cs_091339` 表现为中等准确度，结果稳定性尚可。
- `cs_095806` 误差很大，方差也高，说明该方法在此场景下不稳定。
- `cs_102621` 结果最佳，说明当 tone 质量分布较好时，Liu 风格方法是有效的。

## 图表

### 图表 A：段落 3 窗级 BPM 曲线

![](../../outputs/figures/liu_2016_cs_091339_segment_3_window_bpm_curve.png)

该图展示了 `cs_091339` 段落 `3` 的逐窗估计 BPM，并叠加了真值 BPM。

### 图表 B：段落 3 tone 质量散点图

![](../../outputs/figures/liu_2016_cs_091339_segment_3_tone_quality.png)

该散点图展示了段落 3 某个窗口中逐 tone 的能量比 η 与峰值比 ρ；颜色表示每个 tone 估计的 BPM 候选值。

### 图表 C：段落 3 窗级 BPM 误差直方图

![](../../outputs/figures/liu_2016_cs_091339_segment_3_window_error_hist.png)

`cs_091339` 段落 `3` 逐窗绝对 BPM 误差的分布。

### 图表 D：段落相对误差柱状图

![](../../outputs/figures/liu_2016_cs_091339_segment_rel_err.png)

场景中各段落的相对误差 (%)。

### 汇总图表

![](../../outputs/figures/segment_error_analysis.png)

![](../../outputs/figures/segment_window_error_distribution.png)

## 分析

### 优势

- 实现严格遵循 Liu 2016 概念，未引入额外的启发式融合步骤。
- 能够平顺集成到 BLE CS 多通道管道中，并复用缓存数据。
- 在 `cs_102621` 上表现出色，表明当 tone 级质量良好时，该方法很有潜力。

### 弱点

- 方法对场景变化敏感：`cs_095806` 显示明显较大的误差和较高方差。
- 当前加权融合在只有少数 tone 具有高质量时可能比较脆弱。
- 目前尚未与现有基线（如 `Modal top2`、`Uniform` 或 `chFusion`）进行直接并排对比。

### 后续建议

- 在相同场景集上将 Liu 2016 基线与当前模态融合基线进行对比。
- 检查 `cs_095806` 中的 tone 级质量和 BPM 候选值分布。
- 如果缺少计划文件，补齐 `docs/plans/liu_2016_plan.md`，明确假设和评估设计。
- 若当前 tone 加权中位数仍不足够稳健，考虑加入窗级门控或共识机制。

## 验证命令

- 回归测试：
  - `python -m pytest -q tests/test_liu_2016.py`
- 场景 benchmark 运行：
  - `PYTHONPATH=src python notebooks/scripts/chFusion_liu_2016.py --all`
- Notebook 运行：
  - 打开 `notebooks/liu_2016_step_by_step.ipynb` 并执行所有单元。

## Git 状态

当前已修改或未跟踪的文件：

- `src/ble_analysis/__init__.py`
- `docs/reports/liu_2016_report.md`
- `notebooks/liu_2016_step_by_step.ipynb`
- `notebooks/executed_liu_2016_step_by_step.ipynb`
- `notebooks/scripts/chFusion_liu_2016.py`
- `src/ble_analysis/liu_2016.py`
- `tests/test_liu_2016.py`

