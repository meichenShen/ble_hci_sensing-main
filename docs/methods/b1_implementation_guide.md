# B1 Vote→Equal：从 BLE CS 原始信号到呼吸频率 — 完整实现指南

> **方法**：逐模态 η·ρ Voting → 三模态等权谱融合  
> **跨域 mean BPM err%**：8.45%（cs_091339: 13.22%, cs_095806: 6.50%, cs_102621: 5.63%）  
> **物理自洽性**：✅ — 所有决策由 per-window 信号质量动态驱动，无硬编码偏好  
> **状态**：当前推荐部署（2026-06-16）

---

## 目录

1. [概述](#1-概述)
2. [原始数据：BLE CS 信号](#2-原始数据ble-cs-信号)
3. [Stage 1：逐信道滤波](#3-stage-1逐信道滤波)
4. [Stage 2：滑窗切分](#4-stage-2滑窗切分)
5. [Stage 3：逐模态 Voting（信道融合）](#5-stage-3逐模态-voting信道融合)
6. [Stage 4：三模态等权谱融合（模态融合）](#6-stage-4三模态等权谱融合模态融合)
7. [Stage 5：BPM 估计与评估](#7-stage-5bpm-估计与评估)
8. [完整调用示例](#8-完整调用示例)
9. [参数速查表](#9-参数速查表)

---

## 1. 概述

### 1.1 方法定位

B1 解决的核心问题是：**如何从 BLE CS 的 72 tone × 3 模态 = 216 维信道信息中，稳定提取呼吸频率？**

B1 采用两层融合结构：

```text
┌─────────────────────────────────────────────────────────┐
│                     B1 Vote→Equal                        │
│                                                          │
│  层1 — 信道融合（逐模态 Voting）                           │
│    remote_amplitudes (72 tone) ──► Voting ──► 融合谱_r   │
│    local_amplitudes  (72 tone) ──► Voting ──► 融合谱_l   │
│    phases            (72 tone) ──► Voting ──► 融合谱_p   │
│                                                          │
│  层2 — 模态融合（Equal）                                   │
│    融合谱_r + 融合谱_l + 融合谱_p ──► 1:1:1 平均 ──► BPM │
└─────────────────────────────────────────────────────────┘
```

### 1.2 物理原理（一句话）

每个 tone 的信道频率响应不同（频率选择性衰落）。B1 对每个 tone 独立评估呼吸信号质量（η·ρ），让高质量 tone 在频谱融合中贡献更多——相当于在功率谱域做"质量加权的分集合并"。

### 1.3 实现位置

| 组件 | 文件 |
|------|------|
| 滤波管线 | [`src/ble_analysis/chfusion.py`](../../src/ble_analysis/chfusion.py) — `run_multichannel_segment_filtering()` |
| 滑窗 | [`src/ble_analysis/segments.py`](../../src/ble_analysis/segments.py) — `_sliding_window_indices()` |
| 逐模态 Voting | [`src/ble_analysis/systematic_fusion.py`](../../src/ble_analysis/systematic_fusion.py) — `per_modal_voting_spectrum()` |
| 投票权重 | [`src/ble_analysis/voting_fusion.py`](../../src/ble_analysis/voting_fusion.py) — `_vote_weights()`, `vote_bpm_weighted_histogram()` |
| 模态融合 | [`src/ble_analysis/systematic_fusion.py`](../../src/ble_analysis/systematic_fusion.py) — `modal_fusion_from_spectra()` |
| BPM 估计 | [`src/ble_analysis/chfusion.py`](../../src/ble_analysis/chfusion.py) — `_bpm_from_fused_spectrum()` |
| 完整入口 | [`src/ble_analysis/systematic_fusion.py`](../../src/ble_analysis/systematic_fusion.py) — `estimate_systematic_fusion_segment()` |

---

## 2. 原始数据：BLE CS 信号

### 2.1 数据格式

BLE CS 测量以 JSONL 文件存储。每行一个 JSON 对象，代表一帧 CS 测量结果。

关键字段：

```text
每帧（1 次 CS process = 双向测量）：
  timestamp_ms: 时间戳
  channels: [
    {
      channel_index: 0..71           ← 72 tone 之一
      frequency_mhz: 2402 + index    ← 载波频率
      pct_initiator: { i: float, q: float }   ← 本地设备测得的 PCT（IQ）
      pct_reflector: { i: float, q: float }   ← 远端设备测得的 PCT（IQ）
    },
    ...
  ]
```

### 2.2 从原始 IQ 到三种可用变量

BLE CS 硬件层完成 PCT 向量乘法后，应用层获得：

| 变量 | 计算方式 | 物理含义 |
|------|----------|----------|
| `remote_amplitudes` | \|PCT_reflector\| | 对方测到本设备发出信号的 PCT 幅值 |
| `local_amplitudes` | \|PCT_initiator\| | 本设备测到对方发出信号的 PCT 幅值 |
| `phases` | ∠(PCT_initiator × PCT_reflector) | 两端 PCT 向量相乘后的总相位（LO 漂移已抵消） |

> ⚠️ `amplitudes = remote_amplitudes × local_amplitudes`（总幅值）**不使用**——它是双方噪声的乘积，无独立物理意义。
>
> ⚠️ 单端相位（PCT_initiator 或 PCT_reflector 各自的相位）**不使用**——含有未抵消的 LO 漂移。

### 2.3 场景分段

每个场景配置文件（`config/scenarios/cs_*.json`）将连续帧切分为 breath 段和 apnea 段：

```json
{
  "segments": {
    "breath_1a": { "start_frame": 0, "end_frame": 400, "bpm_gt": 12.0 },
    "breath_1b": { "start_frame": 500, "end_frame": 900, "bpm_gt": 15.0 },
    "apnea_2a":  { "start_frame": 1000, "end_frame": 1200 }
  }
}
```

BPM 估计仅在 breath 段进行（apnea 段跳过）。`bpm_gt` 是 ground truth，仅用于评估，不参与算法。

---

## 3. Stage 1：逐信道滤波

### 3.1 目的

对每个 tone × 每个模态变量，独立施加滤波链，提取呼吸频段信号。

### 3.2 入口函数

```python
from ble_analysis.chfusion import run_multichannel_segment_filtering

multichannel_by_var = {}
for variable in ["remote_amplitudes", "local_amplitudes", "phases"]:
    mc, fs = run_multichannel_segment_filtering(
        frames,           # 原始 JSONL 帧列表
        segment_config,   # 场景分段配置
        variable=variable,
        filter_params=FilterParams(),
        verbose=True,
        cache_dir="outputs/cache",
    )
    multichannel_by_var[variable] = mc
```

### 3.3 滤波链详解

对每个 tone 的每个分段，依次施加：

```text
原始序列 x[n]
  │
  ├─ (仅 phases) Unwrap: 消除 2π 跳变
  │
  ├─ Median filter (窗口=3)
  │   去除脉冲噪声和偶发的异常采样点
  │
  ├─ Highpass filter (f_c = 0.05 Hz, order=1)
  │   去除 DC 分量和极低频漂移（如缓慢的温度变化）
  │   输出: highpass_filtered → 用于计算 η（能量比）
  │
  └─ Bandpass filter (0.1–0.35 Hz, order=2)
      仅保留呼吸频段（6–21 BPM）
      输出: bandpass_filtered → 用于 FFT 和 BPM 估计
```

### 3.4 输出数据结构

```python
multichannel_by_var["remote_amplitudes"] = {
    "breath_1a": {
        "metadata": {"bpm_gt": 12.0, "sampling_rate": 50.0, ...},
        "channels": {
            0: {  # tone index
                "remote_amplitudes": {
                    "original":          np.ndarray,  # 原始序列
                    "median_filtered":   np.ndarray,  # 中值滤波后
                    "highpass_filtered": np.ndarray,  # 高通滤波后
                    "bandpass_filtered": np.ndarray,  # 带通滤波后
                }
            },
            1: {...}, ..., 71: {...}
        }
    },
    "breath_1b": {...},
    "apnea_2a":  {...},  # BPM 估计时跳过
}
```

---

## 4. Stage 2：滑窗切分

### 4.1 参数

| 参数 | 值 | 说明 |
|------|-----|------|
| 窗长 | 20 秒 | 覆盖 ≥2 个完整呼吸周期（最慢 6 BPM = 10 s/周期） |
| 步长 | 1 秒 | 相邻窗重叠 19 s——保证时间分辨率 |
| FFT 点数 | `next_pow2(4 × win_len_samples)` | 频域插值使 bin 宽度 ≈ 0.25 BPM |

### 4.2 实现

```python
from ble_analysis.segments import _sliding_window_indices

fs = 50.0                       # 采样率（Hz），由帧时间戳自动估算
win_len = int(round(20.0 * fs)) # 1000 samples
step_len = int(round(1.0 * fs)) # 50 samples

starts = _sliding_window_indices(total_len, win_len, step_len)
# → [0, 50, 100, 150, ...]
```

### 4.3 FFT 设置

```python
import numpy as np

nfft = 2 ** int(np.ceil(np.log2(4 * win_len)))  # 4096 for 1000-sample window
freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)       # 0..25 Hz
band_mask = (freqs >= 0.1) & (freqs <= 0.35)    # 呼吸频段内的 bin 索引
band_freqs = freqs[band_mask]                     # 呼吸频段内的频率值（Hz）
hann = np.hanning(win_len)
```

- `nfft = 4096`：频率分辨率 ≈ 0.0122 Hz ≈ 0.73 BPM
- `band_freqs` 仅保留 0.1–0.35 Hz 范围内的频率（约 21 个 bin）——BPM 搜索空间

---

## 5. Stage 3：逐模态 Voting（信道融合）

这是 B1 的核心。对每个模态（remote_amp / local_amp / phase）独立执行，输出一条融合谱。

### 5.1 入口函数

```python
from ble_analysis.systematic_fusion import per_modal_voting_spectrum
from ble_analysis.voting_fusion import VotingConfig

vcfg = VotingConfig(voting_strategy="eta_rho_weighted")

fused_spec, voting_bpm, info = per_modal_voting_spectrum(
    ch_list,          # 72 tone 的索引列表
    ch_map,           # 该段该模态的 channels dict
    variable,         # "remote_amplitudes"
    st, end,          # 窗起止样本索引
    fs,               # 采样率
    cfg,              # ChFusionConfig
    vcfg,             # VotingConfig
    nfft, band_mask, band_freqs, hann,
)
# info = {
#     "conf": 0.42,            ← 投票置信度（winning mass / total weight）
#     "mean_eta": 0.15,        ← 有效 tone 的平均 η
#     "n_effective_tones": 68, ← 有效 tone 数（权重 > 0）
# }
```

### 5.2 Step-by-step

#### 5.2.1 步骤 A：Per-Tone 质量评估

对 72 个 tone 中每个，计算两个质量指标：

**η（呼吸频段能量比）** — 来自 `_energy_ratio()`（[chfusion.py:370](../../src/ble_analysis/chfusion.py#L370)）：

$$\eta_i = \frac{\sum_{f \in [0.1, 0.35]\text{ Hz}} P_i^{\text{(hp)}}(f)}{\sum_{f \in [0.05, 0.8]\text{ Hz}} P_i^{\text{(hp)}}(f)}$$

- 输入：该 tone 的 **highpass_filtered** 切片
- 物理含义：高通滤波后的信号有多大比例集中在呼吸频段
- 值域：[0, 1]，越高越好

**ρ（谱峰峰度）** — 来自 `_peak_prominence()`（[chfusion.py:1066](../../src/ble_analysis/chfusion.py#L1066)）：

$$\rho_i = \frac{\max_{f \in [0.1, 0.35]\text{ Hz}} P_i^{\text{(bp)}}(f)}{\text{median}_{f \in [0.1, 0.35]\text{ Hz}} P_i^{\text{(bp)}}(f) + \epsilon}$$

- 输入：该 tone 的 **bandpass_filtered** 切片
- 物理含义：呼吸频段内的最高峰有多突出
- ρ ≈ 1 → 频谱平坦（无清晰呼吸峰），ρ ≫ 1 → 有尖锐呼吸峰

**综合权重**（来自 `_vote_weights()`，[voting_fusion.py:115](../../src/ble_analysis/voting_fusion.py#L115)）：

$$w_i = \eta_i \cdot \rho_i$$

无效 tone（η·ρ ≤ 0 或波形过短）被跳过。

#### 5.2.2 步骤 B：Per-Tone BPM 估计（用于投票）

对每个有效 tone，独立做 BPM 估计（来自 `_bpm_from_waveform()`，[voting_fusion.py:93](../../src/ble_analysis/voting_fusion.py#L93)）：

```text
bandpass_slice → 去均值 → Hanning 窗 → rFFT → 功率谱
  → 呼吸频段内 argmax → parabolic 插值细化 → f_peak → BPM_i = f_peak × 60
```

#### 5.2.3 步骤 C：加权直方图投票

来自 `vote_bpm_weighted_histogram()`（[voting_fusion.py:148](../../src/ble_analysis/voting_fusion.py#L148)）：

```text
BPM bins: [6.0, 7.0, 8.0, ..., 30.0]（1 BPM bin 宽，覆盖呼吸范围 6–21 BPM）

对每个有效 tone i:
  将其权重 w_i 投入 BPM_i 所在 bin

winning_bin = argmax(bin_weights)
winning_bpm = bin_center(winning_bin)
conf = bin_weights[winning_bin] / Σ w_i   ← 投票置信度
```

#### 5.2.4 步骤 D：Conf 加权频谱平均

这是 B1 与纯 Voting（T0-V3）的关键区别——B1 融合的是**频谱**而非仅融合 BPM。

来自 `_weighted_spectrum_average()`（[systematic_fusion.py:167](../../src/ble_analysis/systematic_fusion.py#L167)）：

```text
对每个有效 tone i:
  计算归一化功率谱 P_i(f)（来自 _channel_spectrum_and_q, chfusion.py:283）
  权重 spec_weight_i = w_i（即 η_i·ρ_i）

融合谱 P_fused(f) = Σ spec_weight_i · P_i(f) / Σ spec_weight_i
```

输出：
- `fused_spec`：该模态的融合谱（仅呼吸频段）
- `voting_bpm`：直方图投票 BPM
- `info["conf"]`：投票置信度（后续模态融合的 score）
- `info["n_effective_tones"]`：有效 tone 数

### 5.3 对三个模态各执行一次

```python
# 对 remote_amplitudes
spec_r, bpm_r, info_r = per_modal_voting_spectrum(..., variable="remote_amplitudes", ...)
# 对 local_amplitudes
spec_l, bpm_l, info_l = per_modal_voting_spectrum(..., variable="local_amplitudes", ...)
# 对 phases
spec_p, bpm_p, info_p = per_modal_voting_spectrum(..., variable="phases", ...)
```

三条融合谱 `{spec_r, spec_l, spec_p}` 和对应 scores `{conf_r, conf_l, conf_p}` 进入模态融合。

---

## 6. Stage 4：三模态等权谱融合（模态融合）

### 6.1 入口函数

```python
from ble_analysis.systematic_fusion import modal_fusion_from_spectra

spectra_by_var = {
    "remote": spec_r,
    "local":  spec_l,
    "phase":  spec_p,
}
scores_by_var = {
    "remote": info_r["conf"],
    "local":  info_l["conf"],
    "phase":  info_p["conf"],
}

bpm, selected_modals = modal_fusion_from_spectra(
    spectra_by_var,
    scores_by_var,
    weight_mode="equal",  # ← B1 使用 equal
    band_freqs=band_freqs,
    cfg=cfg,
)
```

### 6.2 融合规则

来自 `modal_fusion_from_spectra()`（[systematic_fusion.py:265](../../src/ble_analysis/systematic_fusion.py#L265)）：

```text
weight_mode = "equal":
  w_remote = w_local = w_phase = 1.0

P_final(f) = (P_remote(f) + P_local(f) + P_phase(f)) / 3
```

> **为什么是 Equal 而非 η-weight 或 Top2？**
>
> B1 的信道融合（Voting）已经将各模态内部的 72 tone 按质量加权。Voting 使三模态的频谱**彼此更相似**（模态间余弦相似度 0.864 vs Single-best 的 0.772，091339 场景）。此时 Top2（踢出最差模态）误踢风险高，而 Equal（三个都保留）更稳健。
>
> 详见 [`b1_gating_and_diagnosis_achievement_report.md`](../achievements/b1_gating_and_diagnosis_achievement_report.md) §D1。

---

## 7. Stage 5：BPM 估计与评估

### 7.1 BPM 估计

来自 `_bpm_from_fused_spectrum()`（[chfusion.py:275](../../src/ble_analysis/chfusion.py#L275)）：

```text
P_final(f) → argmax in [0.1, 0.35] Hz → k
f_peak = parabolic_interp(band_freqs, P_final, k)
BPM = f_peak × 60
```

Parabolic 插值（[chfusion.py:263](../../src/ble_analysis/chfusion.py#L263)）使频率分辨率突破 FFT bin 间距：

```python
# 三点抛物线插值
delta = 0.5 * (y[k-1] - y[k+1]) / (y[k-1] - 2*y[k] + y[k+1])
f_peak = f[k] + delta * df
```

### 7.2 逐窗循环

对每个呼吸段的每个滑窗，执行 Stage 3–5，得到该窗的 BPM 估计：

```python
bpms = []
for st in starts:
    end = st + win_len
    # Stage 3: per-modal voting (× 3 modalities)
    # Stage 4: modal fusion (equal)
    # Stage 5: BPM estimation
    bpm = ...  # 该窗的 BPM 估计
    bpms.append(bpm)
```

### 7.3 评估指标

来自 `_seg_bpm_stats()` 和 `_overall_rel_error()`（[chfusion.py](../../src/ble_analysis/chfusion.py)）：

```python
# 分段级评估
bpm_gt = 12.0  # ground truth
errors = [abs(bpm - bpm_gt) / bpm_gt * 100 for bpm in bpms]
mean_err_pct = np.mean(errors)
std_err_pct = np.std(errors)

# 跨域评估
cross_domain_mean = np.mean([scene_091339_mean, scene_095806_mean, scene_102621_mean])
```

---

## 8. 完整调用示例

### 8.1 最小复现脚本

```python
"""复现 B1 Vote→Equal — 最小示例"""
import sys
from pathlib import Path
import numpy as np

# 项目路径
project_root = Path.cwd()
sys.path.insert(0, str(project_root / "src"))

from ble_analysis.chfusion import (
    ChFusionConfig, load_multichannel_for_scenario,
)
from ble_analysis.scenarios import load_scenario
from ble_analysis.segments import BreathMetricParams, FilterParams
from ble_analysis.voting_fusion import VotingConfig
from ble_analysis.systematic_fusion import (
    estimate_systematic_fusion_segment,
    _overall_rel_error,
)

# ── 配置 ──
scenario_id = "cs_091339"
filter_params = FilterParams()
metric_params = BreathMetricParams()
chfusion_cfg = ChFusionConfig(
    breath_freq_low=0.1,
    breath_freq_high=0.35,
    window_length_sec=20.0,
    step_length_sec=1.0,
)
vcfg = VotingConfig(voting_strategy="eta_rho_weighted")

# ── 加载场景与数据 ──
scenario = load_scenario(scenario_id, project_root=project_root)
multichannel_by_var, fs, _ = load_multichannel_for_scenario(
    scenario,
    filter_params=filter_params,
    cache_dir=str(project_root / "outputs" / "cache"),
)

# ── 逐段运行 B1 ──
results = {}
for seg_name in multichannel_by_var["phases"]:
    row = estimate_systematic_fusion_segment(
        multichannel_by_var,
        seg_name,
        channel_strategy="vote",       # ← B1 的信道策略
        modal_strategy="equal",        # ← B1 的模态策略
        config=chfusion_cfg,
        metric_params=metric_params,
        vcfg=vcfg,
    )
    if row is not None:
        results[seg_name] = row

# ── 评估 ──
stats = _overall_rel_error(results, "b1_vote_modal_equal")
print(f"B1 Vote→Equal | {scenario_id}")
print(f"  mean BPM err: {stats['mean_rel_err_pct']:.2f}%")
print(f"  std:          {stats['std_rel_err_pct']:.2f}%")
print(f"  n_segments:   {stats['n_segments']}")
print(f"  n_windows:    {stats['n_windows']}")
```

### 8.2 完整 Benchmark 入口

```python
from ble_analysis.systematic_fusion import run_systematic_fusion_benchmark

benchmark = run_systematic_fusion_benchmark(
    frames,
    segment_config,
    filter_params=FilterParams(),
    metric_params=BreathMetricParams(),
    config=ChFusionConfig(),
    cache_dir="outputs/cache",
)
# benchmark["results"] 包含所有 breath 段的所有方法结果
```

完整脚本参考：`notebooks/scripts/chFusion_systematic_fusion.py`

---

## 9. 参数速查表

### 9.1 FilterParams

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `median_window` | 3 | 中值滤波窗口（样本数） |
| `highpass_cutoff` | 0.05 Hz | 高通截止频率 |
| `highpass_order` | 1 | 高通滤波器阶数 |
| `bandpass_lowcut` | 0.1 Hz | 带通下限（6 BPM） |
| `bandpass_highcut` | 0.35 Hz | 带通上限（21 BPM） |
| `bandpass_order` | 2 | 带通滤波器阶数 |

### 9.2 BreathMetricParams

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `breath_freq_low` | 0.1 Hz | 呼吸频段下限 |
| `breath_freq_high` | 0.35 Hz | 呼吸频段上限 |
| `window_length_sec` | 20.0 s | 滑窗长度 |
| `step_length_sec` | 1.0 s | 滑窗步长 |

### 9.3 ChFusionConfig

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `breath_freq_low` | 0.1 Hz | FFT 寻峰频段下限 |
| `breath_freq_high` | 0.35 Hz | FFT 寻峰频段上限 |
| `total_freq_low` | 0.05 Hz | η 计算的总频段下限 |
| `total_freq_high` | 0.8 Hz | η 计算的总频段上限 |
| `window_length_sec` | 20.0 s | 滑窗长度 |
| `step_length_sec` | 1.0 s | 滑窗步长 |
| `nfft` | None（自动 = next_pow2(4×win_len)） | FFT 点数 |
| `min_valid_frac` | 0.70 | 有效样本比例阈值 |
| `eps` | 1e-12 | 数值稳定性 |

### 9.4 VotingConfig

| 参数 | B1 使用的值 | 说明 |
|------|-----------|------|
| `voting_strategy` | `"eta_rho_weighted"` | 权重策略：η·ρ 乘积 |
| `bin_resolution_bpm` | 1.0 | 直方图 bin 宽度（BPM） |
| `bpm_bin_low` | 6.0 | 直方图下限（BPM） |
| `bpm_bin_high` | 30.0 | 直方图上限（BPM） |
| `vote_threshold` | 0.3 | 低置信度阈值（B1 未使用，仅诊断） |

### 9.5 方法策略选择

```python
# B1 的两层策略在 estimate_systematic_fusion_segment 中指定:
channel_strategy = "vote"       # ← per-modal Voting（含 η·ρ 加权谱平均）
modal_strategy   = "equal"      # ← 三模态等权谱融合
```

---

## 附录 A：B1 与其他方法的区别

| 方法 | 信道融合 | 模态融合 | 跨域 mean |
|------|----------|----------|-----------|
| **B1 Vote→Equal** | Vote（η·ρ 加权谱平均） | Equal（1:1:1） | **8.45%** |
| B0 Single Remote | max-η 单信道 | Remote only | 10.45% |
| B1 Uniform Remote | 72 tone 等权谱平均 | Remote only | 11.02% |
| Modal top2 | max-η 单信道 per modal | Top2 equal | 9.45% |
| T0-V3 | Vote（η·ρ 直方图投票） | Remote only | 9.20% |
| B3 Vote→Top2 | Vote（同 B1） | Top2 equal | 9.92% |

**B1 独特的组合**：Voting 信道策略 + Equal 模态融合。Voting 降低了模态间差异（使其频谱更相似），Equal 避免了 Top2 在相似模态间的随机选择。

## 附录 B：关键公式汇总

| 公式 | 符号 | 代码位置 |
|------|------|----------|
| $\eta_i = E_{\text{breath}} / E_{\text{total}}$ | 呼吸频段能量比 | `chfusion.py:_energy_ratio` |
| $\rho_i = \max P_i / \text{median}(P_i)$ | 谱峰峰度 | `chfusion.py:_peak_prominence` |
| $w_i = \eta_i \cdot \rho_i$ | 综合质量权重 | `voting_fusion.py:_vote_weights` |
| $P_{\text{fused}}(f) = \sum_i w_i P_i(f) / \sum_i w_i$ | 加权谱平均 | `systematic_fusion.py:_weighted_spectrum_average` |
| $P_{\text{final}}(f) = \frac{1}{3}\sum_m P_{\text{fused}}^{(m)}(f)$ | 模态等权融合 | `systematic_fusion.py:modal_fusion_from_spectra` |
| $\text{BPM} = 60 \cdot \text{parabolic\_argmax}_f P_{\text{final}}(f)$ | BPM 估计 | `chfusion.py:_bpm_from_fused_spectrum` |
