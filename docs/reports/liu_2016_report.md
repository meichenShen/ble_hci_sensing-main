# Liu et al. 2016 baseline validation / 基于 Liu et al. 2016 的基线验证

## Summary / 摘要

This report documents a complete implementation and validation of the Liu 2016 style baseline for BLE CS breathing BPM estimation. The method was implemented in `src/ble_analysis/liu_2016.py` and validated through the notebook and script workflow.

本报告记录了 Liu 2016 风格基线在 BLE CS 呼吸 BPM 估计中的实现与验证。方法已实现于 `src/ble_analysis/liu_2016.py`，并通过 notebook 与脚本完成实验验证。

## What is a tone? / 什么是 tone？

In this BLE CS context, a "tone" refers to one frequency subcarrier within the 72-tone channel sounding measurement, not a separate physical RF channel. Each tone produces one filtered time series. The Liu 2016 baseline estimates one BPM candidate from each tone's waveform and fuses them across tones.

在 BLE CS 中，"tone" 指的是 72 个子载波中的一个频率子载波，而不是我们平时说的独立物理射频通道。每个 tone 在滤波后会得到一条时域信号。Liu 2016 基线从每个 tone 的时域波形中单独估计 BPM，然后再对这些候选值进行融合。

In the code, "channel" may also be used to index tone-based streams, but the key idea is per-tone BPM candidate generation followed by tone-level fusion.

在代码中，"channel" 有时也用于表示 tone 的索引，但核心思想是先生成每个 tone 的 BPM 候选值，再进行 tone 级融合。

## Implementation details / 实现详情

1. Method concept / 方法概念
   - Per-tone BPM estimation: estimate one BPM candidate for each tone and each sliding window.
   - Tone quality scoring: compute a tone-level quality weight using breath-band energy and spectral prominence.
   - Weighted fusion: fuse the tone BPM candidates with a weighted median, with a dominant-tone fallback if needed.

   逐 tone BPM 估计：对每个滑窗内每个 tone 的滤波信号分别估计 BPM 候选值。
   tone 质量评分：通过呼吸带能量和谱峰突出度为每个 tone 计算质量权重。
   加权融合：对所有 tone 的 BPM 候选值做加权中位数融合，必要时回退到权重最高的 tone。

4. Clarifications / 澄清
   - Which variable is used? / 使用了哪些变量
     - The implementation collects and evaluates all three modal variables: `remote_amplitudes`, `local_amplitudes`, and `phases` (see `MODAL_LIU_VARIABLES` in `src/ble_analysis/liu_2016.py`). For each segment/window we gather bandpass-filtered waveforms from available `variable|ch` entries and treat each as a separate "tone" candidate.

   - What algorithms / filters / weights are used? / 使用了哪些算法、滤波与权重
     - Filtering: per-segment pipeline uses `FilterParams` (median filter, highpass 0.05 Hz, bandpass 0.1–0.35 Hz, see `src/ble_analysis/segments.py`). The code reads `bandpass_filtered` and `highpass_filtered` outputs for scoring and BPM estimation.
     - Per-tone BPM: `_bpm_from_waveform` fits a sinusoidal basis over the configured breath band and selects the best frequency by least-squares score, returning BPM = 60 * f.
     - Quality scores: two conservative metrics are used — energy ratio η (`_energy_ratio`): breath-band energy / total energy; and peak ratio ρ (`_tone_band_quality`): peak power / total breath-band power. These are computed per tone/window.
     - Fusion rule: per-window weights = clip(η * ρ) (with small `eps` safeguard). If all weights are near-zero, uniform weights are used. Final BPM is the weighted median of per-tone BPMs; if a single tone dominates the weights and has a valid BPM, the implementation falls back to that dominant-tone BPM.

   - Additional diagnostics / 额外诊断图
     - I generated more diagnostic figures to inspect per-window and per-tone behaviour (see Figures below). These include window-level BPM curves, window-level error histograms, segment-level relative-error bars, and a tone-quality scatter (η vs ρ with BPM colormap) per selected segment.

2. Code location / 代码位置
   - `src/ble_analysis/liu_2016.py`
   - `notebooks/scripts/chFusion_liu_2016.py`
   - `notebooks/liu_2016_step_by_step.ipynb`
   - `tests/test_liu_2016.py`

3. Pipeline alignment / 与现有管道对齐
   - Reuses the filtered multichannel segment cache and the same segment configuration used by the BLE CS pipeline.
   - Uses the standard sliding window parameters defined in `BreathMetricParams` and `ChFusionConfig`.

   复用 BLE CS 管道中的多通道滤波缓存与段落配置。
   使用 `BreathMetricParams` 和 `ChFusionConfig` 中定义的滑窗参数。

## Detailed implementation (for reproducibility) / 详细实现（可复现说明）

1) Variables collected
- The code evaluates every available `variable|channel` pair for the three modal variables: `remote_amplitudes`, `local_amplitudes`, and `phases`. Each such `variable|ch` entry yields a pair of filtered arrays (`bandpass_filtered`, `highpass_filtered`) and is treated as an independent "tone" candidate for that sliding window.

2) Exact filter parameters
- `FilterParams` (see `src/ble_analysis/segments.py`) — defaults used in the notebook:
  - `median_window = 3`
  - `highpass_cutoff = 0.05` Hz, `highpass_order = 1`
  - `bandpass_lowcut = 0.1` Hz, `bandpass_highcut = 0.35` Hz, `bandpass_order = 2`

3) Sliding-window / BPM windowing
- `BreathMetricParams` (defaults): `breath_freq_low = 0.1 Hz`, `breath_freq_high = 0.35 Hz`, `window_length_sec = 20.0`, `step_length_sec = 1.0`.
- Window length in samples = round(window_length_sec * fs), step = round(step_length_sec * fs).

4) Per-tone BPM estimation algorithm (`_bpm_from_waveform`)
- Precondition: zero-mean the windowed signal and require finite samples.
- Frequency grid: `freqs = linspace(cfg.breath_freq_low, cfg.breath_freq_high, 512)` (512-point scan inside breath band).
- For each candidate frequency f, form two basis vectors sin(2π f t), cos(2π f t) and compute least-squares coefficients to fit the signal.
- Score = dot(sig, fit) / (||sig|| * ||fit|| + eps) (normalized correlation-like score). Choose f with maximal score and return `60 * f` as BPM.

5) Tone quality metrics (weights)
- Energy ratio η: implemented in `_energy_ratio` — compute FFT power of windowed (Hann) signal; sum power in breath band divided by total power in configured total band. Returns a ratio in [0,1].
- Peak ratio ρ: implemented in `_tone_band_quality` — compute breath-band FFT power, return `peak_power / total_band_power` (conservative peak prominence).
- Combined per-tone weight: `w_c = clip(η * ρ, 0, +inf) + eps`. If sum(w_c) ≤ eps, the code uses uniform weights.

6) Fusion: weighted median + dominant-tone fallback
- Weighted median: `_weighted_median(values, weights)` sorts values, computes cumulative normalized weights, and returns the value at the 0.5 quantile.
- Dominant-tone fallback: if `argmax(weights)` yields a tone with finite BPM, that BPM is returned immediately (this mirrors the paper's pragmatic preference for a very-high-confidence tone).

7) Pseudocode (per-window)

```text
For each sliding window:
  collect bandpass_filtered waveform for every (variable, channel) -> x_i(t)
  compute eta_i = _energy_ratio(highpass(x_i))
  compute rho_i = _tone_band_quality(bandpass(x_i))
  estimate bpm_i = _bpm_from_waveform(bandpass(x_i))
  w_i = clip(eta_i * rho_i) + eps
  if sum(w_i) <= eps: w_i = ones
  dominant = argmax(w_i)
  if isfinite(bpm_dominant): bpm_out = bpm_dominant
  else: bpm_out = weighted_median(bpm_i, w_i)
```

8) Reproducible commands
- Generate diagnostics and figures for a single scenario/segment:
```bash
PYTHONPATH=src python notebooks/scripts/chFusion_liu_2016_diagnostics.py --scenario cs_091339 --segment 3
```
- Generate diagnostics for all scenarios:
```bash
PYTHONPATH=src python notebooks/scripts/chFusion_liu_2016_diagnostics.py --all
```
- Run the full benchmark and save combined results:
```bash
PYTHONPATH=src python notebooks/scripts/chFusion_liu_2016.py --all
```

9) Generated figures (examples)
- `outputs/figures/liu_2016_cs_091339_segment_3_window_bpm_curve.png`
- `outputs/figures/liu_2016_cs_091339_segment_3_tone_quality.png`
- `outputs/figures/liu_2016_cs_091339_segment_3_window_error_hist.png`
- `outputs/figures/liu_2016_cs_091339_segment_rel_err.png`
- summary figures: `segment_error_analysis.png`, `segment_window_error_distribution.png`

10) Files of interest (implementation and runners)
- `src/ble_analysis/liu_2016.py` — Liu-style estimator and window aggregation
- `src/ble_analysis/chfusion.py` — common helpers: `_energy_ratio`, `_weighted_median`, `_seg_bpm_stats`, FFT helpers
- `src/ble_analysis/segments.py` — `FilterParams` and sliding-window helpers
- `notebooks/liu_2016_step_by_step.ipynb` — interactive walkthrough
- `notebooks/scripts/chFusion_liu_2016.py` — batch runner
- `notebooks/scripts/chFusion_liu_2016_diagnostics.py` — diagnostic figure generator

If you want, I can also add a short math box with the exact formulas for the LS fit and the weighted median definition in LaTeX, or append a ready-to-run `Makefile` snippet that produces all figures and the report PDF.

## Execution steps / 执行步骤

### Step 1: Environment setup / 环境准备

- Ensure the notebook or script runs from the repository root.
- Add `src` into `PYTHONPATH` before importing `ble_analysis`.
- Initialize environment with `ble_analysis.bootstrap.init_notebook(project_root)`.

- 确保 notebook 或脚本从仓库根目录运行。
- 在导入 `ble_analysis` 之前，将 `src` 加入 `PYTHONPATH`。
- 使用 `ble_analysis.bootstrap.init_notebook(project_root)` 初始化环境。

### Step 2: Scenario load / 加载场景

- Load scenario `cs_091339` by calling `load_scenario(scenario_id, project_root=project_root)`.
- Confirm the scenario contains 9 segments: 7 breathing and 2 apnea.

- 通过 `load_scenario('cs_091339', project_root=project_root)` 加载场景。
- 确认场景包含 9 个段落：7 个呼吸段和 2 个暂停段。

### Step 3: Multichannel preprocessing / 多通道预处理

- Use `load_multichannel_for_scenario(...)` with `FilterParams()` and a cache directory.
- The validated notebook reported cache hits for all variables and segments.
- Output: `fs=1.80 Hz`, variables `['remote_amplitudes', 'local_amplitudes', 'phases']`.

- 调用 `load_multichannel_for_scenario(...)`，使用 `FilterParams()` 和缓存目录。
- notebook 中验证显示所有变量和段落都命中了缓存。
- 输出：采样率 `fs=1.80 Hz`，可用变量为 `['remote_amplitudes','local_amplitudes','phases']`。

### Step 4: Liu 2016 benchmark run / 运行 Liu 2016 基线

- Execute `run_liu_2016_benchmark(None, scenario.segment_config, ...)`.
- The benchmark uses filtered multichannel data and the same window/step settings.
- It returns a results dictionary with one entry per segment.

- 执行 `run_liu_2016_benchmark(None, scenario.segment_config, ...)`。
- benchmark 使用滤波后的多通道数据和相同的滑窗参数。
- 返回一个包含每个段落结果的字典。

### Step 5: Result summary / 结果汇总

- Use `_overall_rel_error(bench['results'], 'liu_2016')` to summarize performance.
- Print segment IDs and relative error values for each segment.

- 通过 `_overall_rel_error(...)` 汇总性能指标。
- 打印每个段落的相对误差。

### Step 6: Single segment diagnosis / 单段诊断

- Select `seg_name='3'` for detailed analysis.
- Extract `row['liu_2016']['bpm_per_window']` and ground truth `row['bpm_gt']`.
- Plot the sliding-window BPM curve and save the figure.

- 选取段落 `3` 进行详细分析。
- 提取 `bpm_per_window` 和真值 `bpm_gt`。
- 绘制窗级 BPM 曲线并保存图像。

## Results / 结果

| Scenario | Mean Relative Error (%) | Std Relative Error (%) | Notes |
|---|---|---|---|
| cs_091339 | 14.62 | 8.50 | moderate accuracy |
| cs_095806 | 39.45 | 38.02 | large error and poor stability |
| cs_102621 | 4.21 | 1.71 | good performance |

- `cs_091339` 表现为中等准确度，结果稳定性尚可。
- `cs_095806` 误差很大，方差也高，说明该方法在此场景下不稳定。
- `cs_102621` 结果最佳，说明当 tone 质量分布较好时，Liu 风格方法是有效的。

## Figures / 图表

### Figure A: Segment 3 window-level BPM curve / 段落 3 窗级 BPM 曲线

![](../../outputs/figures/liu_2016_cs_091339_segment_3_window_bpm_curve.png)

This figure shows the estimated BPM per sliding window for `cs_091339` segment `3`, together with the ground truth BPM.

该图展示了 `cs_091339` 段落 `3` 的窗级 BPM 估计曲线，并叠加了真值 BPM。

### Figure B: Segment 3 tone quality scatter / 段落 3 tone 质量散点图

![](../../outputs/figures/liu_2016_cs_091339_segment_3_tone_quality.png)

This scatter plots per-tone energy ratio η vs peak ratio ρ for one window in segment 3; color indicates the BPM candidate estimated per tone.

该散点图展示了段落 3 某一窗中每个 tone 的 η 与 ρ 值，颜色表示该 tone 的 BPM 候选值。

### Figure C: Segment 3 window-level BPM error histogram / 段落 3 窗级误差直方图

![](../../outputs/figures/liu_2016_cs_091339_segment_3_window_error_hist.png)

Distribution of absolute BPM errors per window for `cs_091339` segment `3`.

该图展示 `cs_091339` 段落 3 中窗级 BPM 绝对误差的分布。

### Figure D: Segment-level relative error bars / 段落相对误差柱状图

![](../../outputs/figures/liu_2016_cs_091339_segment_rel_err.png)

Segment-level relative error (%) across the scenario.

场景中各段落的相对误差（%）。

### Existing summary figures

![](../../outputs/figures/segment_error_analysis.png)

![](../../outputs/figures/segment_window_error_distribution.png)

## Analysis / 分析

### Strengths / 优势

- The implementation adheres closely to the Liu 2016 concept without introducing extra heuristic fusion steps.
- It integrates smoothly into the BLE CS multi-channel pipeline and reuses cached data.
- It achieves strong performance on `cs_102621`, suggesting the approach is promising when tone-level quality is good.

- 实现严格遵循 Liu 2016 思路，未引入额外启发式融合步骤。
- 能顺利集成到 BLE CS 多通道管道中，并复用缓存结果。
- 在 `cs_102621` 上表现良好，说明当 tone 质量分布较好时，该方法有潜力。

### Weaknesses / 弱点

- The method is sensitive to scene variation: `cs_095806` shows much larger error and high variance.
- The current weighted fusion can be brittle if only a few tones carry high quality.
- There is not yet a direct side-by-side comparison with the existing baselines such as `Modal top2`, `Uniform`, or `chFusion`.

- 方法对场景变化敏感，`cs_095806` 误差显著升高。
- 当前加权融合在只有少数高质量 tone 时可能比较脆弱。
- 目前尚未与 `Modal top2`、`Uniform`、`chFusion` 等基线进行直接对比。

### Next steps / 后续建议

- Compare Liu 2016 baseline against the current modal fusion baselines on the same scenario set.
- Inspect tone-level quality and candidate BPM distributions in `cs_095806`.
- Create `docs/plans/liu_2016_plan.md` if missing, with clear hypotheses and evaluation design.
- Consider adding window-level gating or consensus if the current tone-weighted median is too fragile.

- 将 Liu 2016 基线与当前 modal 融合基线在相同场景集上直接对比。
- 检查 `cs_095806` 中 tone 质量分布和 BPM 候选值分布。
- 如果缺少计划文件，则补齐 `docs/plans/liu_2016_plan.md`，明确假设和评估设计。
- 如果当前加权中位数方法不够稳健，可考虑加入窗级门控或共识机制。

## Verification commands / 验证命令

- Regression test:
  - `python -m pytest -q tests/test_liu_2016.py`
- Scenario benchmark run:
  - `PYTHONPATH=src python notebooks/scripts/chFusion_liu_2016.py --all`
- Notebook run:
  - open `notebooks/liu_2016_step_by_step.ipynb` and execute all cells.

- 回归测试：`python -m pytest -q tests/test_liu_2016.py`
- 场景 benchmark 运行：`PYTHONPATH=src python notebooks/scripts/chFusion_liu_2016.py --all`
- notebook 运行：打开 `notebooks/liu_2016_step_by_step.ipynb` 并执行所有单元。

## Git status / 当前 Git 状态

The following files are currently modified or untracked:

- `src/ble_analysis/__init__.py`
- `docs/reports/liu_2016_report.md`
- `notebooks/liu_2016_step_by_step.ipynb`
- `notebooks/executed_liu_2016_step_by_step.ipynb`
- `notebooks/scripts/chFusion_liu_2016.py`
- `src/ble_analysis/liu_2016.py`
- `tests/test_liu_2016.py`

当前文件状态：

- `src/ble_analysis/__init__.py`
- `docs/reports/liu_2016_report.md`
- `notebooks/liu_2016_step_by_step.ipynb`
- `notebooks/executed_liu_2016_step_by_step.ipynb`
- `notebooks/scripts/chFusion_liu_2016.py`
- `src/ble_analysis/liu_2016.py`
- `tests/test_liu_2016.py`

