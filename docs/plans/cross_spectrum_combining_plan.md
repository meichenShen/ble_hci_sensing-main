# 互功率谱合并 (Cross-Spectrum Combining) 对 BLE CS 呼吸感知的影响 — 实现计划

> **来源**：通信分集合并理论（Brennan 1959 "Linear Diversity Combining Techniques"）；Deng et al. (2024) "A statistical sensing method by utilizing Wi-Fi CSI subcarriers"；BLE CS 规范——tone 间相对相位误差约束  
> **目标报告**：`docs/reports/cross_spectrum_combining_report.md`（模板：`docs/templates/algorithm_validation_report.md`）  
> **建议 plan 路径**：`docs/plans/cross_spectrum_combining_plan.md`  
> **日期**：2026-06-16  
> **验证状态**：已完成

---

## 1. 动机与背景

### 1.1 问题：B1 丢弃了一份"免费的"相位信息

B1（逐模态 η·ρ Voting → 三模态等权谱融合）以跨域 mean **8.45%** 为当前全局最优。其信道融合的核心操作是：

$$\hat{P}_{\text{B1}}(f) = \sum_i w_i(\eta_i, \rho_i) \cdot \left| \text{FFT}\{x_i(t)\} \right|^2$$

即：对每个 tone 的 bandpass-filtered 波形做 FFT → **取功率谱** → η·ρ 加权平均。

取 |FFT|² 的代价是**丢弃了 FFT 输出的复相位信息**。这个相位信息在 BLE CS 场景中有特殊的物理价值：

- BLE CS 规范对 tone 间**相对相位误差**有严格限制（保障测距精度）
- PCT（Phase Correction Term）机制已抵消了 LO 漂移
- 各 tone 之间的**相位差**由硬件保障，不受器件相位噪声污染

但当前所有方法（包括 B1）都只在单个 tone 内部使用信号——从未计算过跨 tone 的相位关系。

### 1.2 互谱合并的核心优势

**互功率谱 (Cross-Spectrum)** 定义为两个信号的复频谱的共轭积：

$$C_{ij}(f) = X_i(f) \cdot X_j^*(f)$$

对 BLE CS 呼吸感知，互谱合并有三个理论优势：

**优势 1 — 天然压制不相关噪声**。对信号模型 xᵢ(t) = aᵢ · s(t) · cos(φᵢ) + nᵢ(t)：

$$\mathbb{E}[N_i(f) \cdot N_j^*(f)] = 0 \quad \text{(不相关噪声的交叉项期望为零)}$$

而功率谱 |Nᵢ(f)|² 始终为正，只能通过平均缓慢降低噪声平台。互谱的噪声项在统计上互相抵消——这直接回应了 Deng et al. (2024) 对"加权求和不能抑制 ICI 噪声"的批评。

**优势 2 — 利用 BLE CS 硬件保障的跨 tone 相位一致性**。互谱中的信号项为：

$$a_i a_j \cdot |S(f)|^2 \cdot \cos(\phi_i - \phi_j)$$

其中 φᵢ 是 tone i 的静态多径相位。硬件保障的是 φᵢ − φⱼ 的**硬件误差分量极小**（不受器件相位噪声污染）。虽然多径导致的 φᵢ − φⱼ 仍然存在，但只要 cos(φᵢ − φⱼ) > 0（即两个 tone 的呼吸信号大致同相），互谱在呼吸频率处就有正的贡献。

**优势 3 — "差分消共模"哲学的自然延伸**。BLE CS 硬件层通过 PCT 向量相乘抵消 LO 漂移（设备间差分）；互谱通过复共轭乘积消除绝对多径相位（tone 间差分）。两次"差分消共模"一脉相承，互谱是对硬件设计哲学的软件层延续。

### 1.3 与既有工作的关系

| 既有工作 | 与本 plan 的关系 |
|----------|-----------------|
| [systematic_modal_channel_fusion_plan.md](systematic_modal_channel_fusion_plan.md) — B1 验证 | 本 plan 是对 B1 的**信道融合步骤做消融替换**：功率谱加权平均 → 互谱合并。模态融合侧不变（Equal），确保对比的干净性 |
| [voting_fusion_plan.md](voting_fusion_plan.md) — Deng 2024 Voting | Deng 反对加权求和、提倡 Voting；互谱合并从**另一个角度**（频域相关而非离散投票）回应同样的批评 |
| [diversity_combining_exploration_plan.md](diversity_combining_exploration_plan.md) — 分集合并总框架 | 本 plan 是该框架下的第一个具体实验（Cross-Spectrum = Phase 1） |

### 1.4 本 plan 定位

| 项目 | 说明 |
|------|------|
| 问题 | 用互谱合并替换 B1 的功率谱加权平均，能否利用 BLE CS 跨 tone 相位一致性，进一步压制噪声、改善 BPM 估计？ |
| 相关文档 | `docs/plans/diversity_combining_exploration_plan.md`（框架）、`docs/achievements/systematic_modal_channel_fusion_achievement_report.md`（B1 结果） |
| 本 plan 定位 | **信道融合层的合并域消融实验**——在 B1 的两层框架中仅替换信道融合步骤，控制其他变量不变 |

---

## 2. 物理与变量

### 2.1 信号模型

对每个 tone i 的 bandpass-filtered 波形，呼吸分量模型为：

$$x_i(t) = \underbrace{a_i \cdot s(t) \cdot \cos(\phi_i)}_{\text{呼吸信号}} + \underbrace{n_i(t)}_{\text{噪声 + 干扰}}$$

其中 s(t) 是共同的呼吸波形，aᵢ 和 φᵢ = ∠Hᵢ,static 由频率选择性多径决定。

**三种频谱合并的数学对比**：

| 合并方式 | 公式 | 信号项 | 噪声项行为 |
|----------|------|--------|-----------|
| 功率谱 (B1) | Σᵢ wᵢ·\|Xᵢ\|² | aᵢ²\|S\|²cos²φᵢ | Σ\|Nᵢ\|² > 0（始终为正） |
| 互谱-幅值 | Σ wᵢⱼ·\|XᵢXⱼ*\| | aᵢaⱼ\|S\|²\|cos(φᵢ−φⱼ)\| | Σ\|NᵢNⱼ*\| ≈ 0（不相关噪声） |
| 互谱-实部 | Σ wᵢⱼ·Re{XᵢXⱼ*} | aᵢaⱼ\|S\|²cos(φᵢ−φⱼ) | Σ Re{NᵢNⱼ*} ≈ 0（不相关噪声） |
| 互谱-相干 | \|Σ wᵢⱼ·XᵢXⱼ*\| | 复数和后取模 | Σ NᵢNⱼ* → 0（大数定律） |

### 2.2 可用观测量

| 变量 | 是否使用 | 理由 |
|------|----------|------|
| `remote_amplitudes`（72 tone 带通滤波后） | ✅ 主变量 | 与 B1 的 remote 通道对齐，确保可比性；实信号 FFT 即可得到复频谱 |
| `local_amplitudes`（同上） | ✅（对照） | remote/local 物理对等，验证互谱增益是否对称 |
| `phases`（总相位，已消除 LO 漂移） | ✅（对照） | 总相位作为实信号输入；若效果优于幅值变量，说明相位包含额外信息 |
| `amplitudes`（总幅值） | ❌ | 无独立物理意义 |
| 单端原始相位（含 LO 漂移） | ❌ | 物理上不可靠 |

> **关于复信号构造**：本 plan 的初代实验将三种变量均作为**实信号**输入 FFT（不做 Hilbert 变换或复包络重构）。复包络（remote_amplitudes · e^{j·φ_total}）留作后续探索。这样最干净——FFT 对实信号给出共轭对称的复频谱，互谱 Xᵢ · Xⱼ* 的实部和虚部均有明确物理含义（co-spectrum 和 quad-spectrum）。

### 2.3 符号约定

| 符号 | 含义 |
|------|------|
| η | 呼吸频段能量比（per-tone per-window） |
| ρ | 谱峰峰度（per-tone per-window） |
| Xᵢ(f) | 第 i 个 tone 的复频谱（rFFT 输出，仅呼吸频段内） |
| Cᵢⱼ(f) = Xᵢ(f) · Xⱼ*(f) | tone i 和 j 的互功率谱 |
| wᵢⱼ = ηᵢ·ρᵢ · ηⱼ·ρⱼ | 质量权重（两个 tone 都好才给高权重） |
| Δk = \|i − j\| | tone 索引差（~频率间距，1 步 ≈ 1 MHz） |
| P_cross(f) | 合并后的互谱（标量，正值） |

---

## 3. 算法步骤

### 3.1 总体框架（保持与 B1 相同的两层结构）

```text
输入: 72 tone × 3 模态的 bandpass-filtered 波形（20 s 窗 / 1 s 步）

层1 — 信道融合（替换部分）:
  对每个模态 m ∈ {remote_amp, local_amp, phase}:
    [新] per_modal_cross_spectrum()  ← 替代 B1 的 per_modal_voting_spectrum()
    输出: 该模态的融合互谱 P_cross^{(m)}(f) + BPM 估计

层2 — 模态融合（不变，与 B1 一致）:
  Equal weight: P_final(f) = (P_cross^(remote) + P_cross^(local) + P_cross^(phase)) / 3
  argmax → final BPM
```

### 3.2 公共前置（与现有一致）

```
数据源: BLE CS 72 tone (sampleData/CS_frames_*.jsonl)
分段: config/scenarios/cs_*.json
滤波: median → highpass (0.05 Hz) → bandpass (0.1–0.35 Hz)
滑窗: 20 s 窗 / 1 s 步
FFT: rFFT, Hanning 窗, nfft = next_pow2(4 × win_len)
呼吸频段: 0.1–0.35 Hz (6–21 BPM)
```

### 3.3 核心新函数：`per_modal_cross_spectrum()`

```text
输入:
  ch_list, ch_map, variable  — 同 per_modal_voting_spectrum()
  st, end, fs, cfg           — 窗参数
  nfft, band_mask, band_freqs, hann — FFT 参数
  cross_mode: 'magnitude' | 'real' | 'coherent'
  max_delta_k: int | None    — tone 对的最大索引差 (None = 全对)

步骤:
  1. 对每个 tone i:
     a. 取 bandpass_filtered 切片 bp[st:end]
     b. Hanning 窗后 rFFT → X_i_full
     c. 取呼吸频段: X_i = X_i_full[band_mask]  (复数)
     d. 计算 η_i (从 highpass 切片) 和 ρ_i (从 bp 切片)
     e. 质量权重: q_i = η_i · ρ_i

  2. 筛选有效 tone: q_i > 0 且 X_i 无 NaN

  3. 生成 tone 对列表:
     pairs = [(i,j) for i<j if both valid and |i-j| <= max_delta_k]
     pair_weights = [q_i * q_j for (i,j) in pairs]

  4. 根据 cross_mode 合并互谱:
     
     mode='magnitude' (非相干互谱):
       P_cross(f) = Σ_{(i,j)} w_ij · |X_i(f) · X_j*(f)|
       特点: 最安全，不要求跨 tone 相位对齐
     
     mode='real' (同相分量):
       P_cross(f) = Σ_{(i,j)} w_ij · max(0, Re{X_i(f) · X_j*(f)})
       特点: 仅取 cospectrum 正值部分——假设呼吸信号跨 tone 大致同相；
             clip 负值以避免不同相 tone 对的破坏性贡献
     
     mode='coherent' (相干互谱):
       C_total(f) = Σ_{(i,j)} w_ij · X_i(f) · X_j*(f)  (复数和)
       P_cross(f) = |C_total(f)|
       特点: 通信中最接近相干合并的方式；要求 cos(φ_i-φ_j) 统计上 > 0

  5. 在 P_cross(f) 上做 argmax + parabolic 插值 → BPM

  6. 返回: (fused_spectrum, bpm, info_dict)
```

### 3.4 待测方法（X0–X7）

所有方法均使用 `per_modal_cross_spectrum()` 做信道融合 + Equal 模态融合（与 B1 一致）。

| 方法 ID | cross_mode | max_delta_k | 权重 | 说明 |
|---------|-----------|-------------|------|------|
| **X0** | —（功率谱） | — | η·ρ | **Baseline = B1 Vote→Equal**（`per_modal_voting_spectrum`） |
| **X1** | magnitude | None (全 2556 对) | ηᵢρᵢ·ηⱼρⱼ | 互谱幅值，全 tone 对——最直接替换 |
| **X2** | real | None (全 2556 对) | ηᵢρᵢ·ηⱼρⱼ | 互谱实部（仅正值），全 tone 对 |
| **X3** | coherent | None (全 2556 对) | ηᵢρᵢ·ηⱼρⱼ | 相干互谱，全 tone 对——最接近"MRC 在谱域" |
| **X4** | magnitude | 1 (Δf ≤ 1 MHz, ~71 对) | ηᵢρᵢ·ηⱼρⱼ | 仅相邻 tone——测试"近邻假设" |
| **X5** | real | 1 (Δf ≤ 1 MHz) | ηᵢρᵢ·ηⱼρⱼ | 相邻 tone 实部——假设邻近 tone 呼吸信号同相 |
| **X6** | magnitude | 5 (Δf ≤ 5 MHz) | ηᵢρᵢ·ηⱼρⱼ | 适度间距 tone 对 |
| **X7** | real | 5 (Δf ≤ 5 MHz) | ηᵢρᵢ·ηⱼρⱼ | 适度间距实部 |

**实验设计逻辑**：
- X1 vs X2 vs X3：比较三种互谱合并模式（幅值 / 实部 / 相干），在全部 tone 对上
- X1 vs X4 vs X6：扫描 tone 对间距对 magnitude 模式的影响（全对 → 相邻 → 适度间距）
- X2 vs X5 vs X7：同上，对 real 模式
- X* vs X0：互谱 vs 功率谱的 head-to-head 对比

### 3.5 诊断输出（除 BPM 外）

每个窗额外输出以下诊断量，用于理解互谱行为：

| 诊断量 | 含义 |
|--------|------|
| `cross_peak_significance` | 互谱峰与噪声平台的比值（类比 SNR）——预期 X* > X0（如果不相关噪声压制生效） |
| `n_effective_pairs` | 有效 tone 对数（ηᵢρᵢ·ηⱼρⱼ > 0 的 pair 数） |
| `mean_pair_weight` | 平均 tone 对权重 |
| `cross_spectrum_raw` | 融合前的互谱矩阵片段（用于调试）— 仅存几个示例窗 |

---

## 4. Baseline 对比

执行 Agent **必须**跑齐下表方法。

### 4.1 主实验方法

| 方法 ID | 标签 | 说明 | 来源 |
|---------|------|------|------|
| X0 | B1 Vote→Equal (baseline) | 功率谱 η·ρ 加权平均 → Equal 模态融合 | `systematic_fusion.py` |
| X1 | CrossSpec-mag-all | 互谱幅值 / 全 tone 对 / ηρ 权重 | 本 plan §3.4 |
| X2 | CrossSpec-real-all | 互谱实部 / 全 tone 对 / ηρ 权重 | 本 plan §3.4 |
| X3 | CrossSpec-coh-all | 相干互谱 / 全 tone 对 / ηρ 权重 | 本 plan §3.4 |
| X4 | CrossSpec-mag-d1 | 互谱幅值 / 相邻 tone / ηρ 权重 | 本 plan §3.4 |
| X5 | CrossSpec-real-d1 | 互谱实部 / 相邻 tone / ηρ 权重 | 本 plan §3.4 |
| X6 | CrossSpec-mag-d5 | 互谱幅值 / Δf≤5 MHz / ηρ 权重 | 本 plan §3.4 |
| X7 | CrossSpec-real-d5 | 互谱实部 / Δf≤5 MHz / ηρ 权重 | 本 plan §3.4 |

### 4.2 参考 Baseline（从既有结果导入，不需重跑）

| 方法 ID | 标签 | 跨域 mean | 来源 |
|---------|------|-----------|------|
| B0 | Single Remote | 10.45% | `voting_fusion.py` |
| B1 (old) | Uniform Remote | 11.02% | `voting_fusion.py` |
| B2 | Modal top2 equal | 9.45% | `systematic_fusion.py` |
| T0-V3 | Per-Tone η·ρ voting | 9.20% | `voting_fusion.py` |
| G4 | Single fallback gating | 8.65% | `consensus_gating.py` |

### 4.3 预期相对关系（研究假设，可被实验推翻）

| 对比 | 预期 | 理由 |
|------|------|------|
| X1–X7 vs X0 | 至少一种互谱模式 ≤ 8.45% | 互谱压制不相关噪声 + 利用跨 tone 相位一致性 |
| X5 vs X7 vs X2 | X5 最优（相邻 tone 实部） | 相邻 tone 的呼吸信号最可能同相；远距离 tone 的 cos(φᵢ−φⱼ) 可能为负 |
| X3 vs X1 | X3 略优 | 相干求和再取模保留相位信息；但若多 tone 对相位散乱，X3 反而退化 |
| X4 vs X1 | X4 相当或略优 | 远距离不相干 tone 对的互谱可能是纯噪声，剔除它们应改善 SNR |
| X* with remote vs local vs phase | phase 变量可能最受益 | phase 保留了完整的复信号信息，互谱的相位优势在 phase 上最能体现 |

---

## 5. 评估设计

### 5.1 场景

| 场景 JSON | 用途 |
|-----------|------|
| `config/scenarios/cs_091339.json` | voting 退化场景——若互谱能改善，说明相位信息在复杂多径中有独特价值 |
| `config/scenarios/cs_095806.json` | voting 优势场景——B1 已 6.50%，互谱能否进一步压低？ |
| `config/scenarios/cs_102621.json` | 跨域对照——B1 在此输给 G4（5.63% vs 4.51%） |

### 5.2 指标

| 指标 | 说明 | 优先级 |
|------|------|--------|
| 分段 BPM 相对误差 %（mean / std） | 主指标 | ★★★ |
| 跨域 mean | 三场景平均 mean err% | ★★★ |
| 跨域 std | 三场景间 mean err% 的标准差（方法稳定性） | ★★ |
| 窗级 cross_peak_significance | 互谱峰显著性 vs X0 功率谱峰显著性 | ★★（诊断） |
| n_effective_pairs 分布 | 有效 tone 对数的分布——若某场景大幅减少，说明 mutual quality 筛选过严 | ★（诊断） |

### 5.3 成功标准

| 级别 | 条件 |
|------|------|
| **理想** | 任一 X* 跨域 mean < **8.05%**（超越 G4-B1-v2，成为新的全局最优） |
| **良好** | 任一 X* 跨域 mean < **8.45%**（超越 B1，互谱优于功率谱得到验证） |
| **最低** | 任一 X* 跨域 mean ≤ 9.20%（不差于 T0-V3），且至少一个场景 X* 优于 X0 |
| **mixed** | 部分场景改善、部分退化 → 互谱为场景条件有效；需进一步诊断退化场景的 cos(φᵢ−φⱼ) 分布 |
| **失败** | 所有 X* 跨域 mean > 9.5%，且无场景改善 → 互谱在 BLE CS 呼吸感知中无效（也是重要的物理发现） |

---

## 6. 实现要点

### 6.1 建议文件

| 类型 | 路径 |
|------|------|
| 实验脚本 | `notebooks/scripts/chFusion_cross_spectrum.py` |
| 可复用模块（新增） | `src/ble_analysis/cross_spectrum.py` |
| 跨域汇总脚本 | `notebooks/scripts/chFusion_cross_spectrum_cross_domain.py` |
| 场景配置 | 沿用现有 JSON（不需新增） |

### 6.2 复用 API

```python
from ble_analysis.chfusion import (
    ChFusionConfig,
    _energy_ratio,
    _peak_prominence,
    _bpm_from_fused_spectrum,
    _overall_rel_error,
    _seg_bpm_stats,
    run_multichannel_segment_filtering,
)
from ble_analysis.systematic_fusion import (
    per_modal_voting_spectrum,   # X0 baseline
    modal_fusion_from_spectra,   # 模态融合（Equal, 不变）
    VAR_SHORT,
    MODAL_VOTING_VARIABLES,
)
from ble_analysis.segments import BreathMetricParams, FilterParams, _sliding_window_indices
```

### 6.3 新增模块接口草案

`src/ble_analysis/cross_spectrum.py`（~200 行）：

```python
__all__ = [
    "CrossSpectrumConfig",
    "CrossSpectrumMode",
    "per_modal_cross_spectrum",
    "estimate_cross_spectrum_segment",
    "run_cross_spectrum_benchmark",
]

CrossSpectrumMode = Literal["magnitude", "real", "coherent"]

@dataclass
class CrossSpectrumConfig:
    cross_mode: CrossSpectrumMode = "magnitude"
    max_delta_k: int | None = None  # None = all pairs
    weight_mode: str = "eta_rho_product"  # "eta_rho_product" | "eta_product" | "uniform"

def per_modal_cross_spectrum(
    ch_list: Sequence[Any],
    ch_map: dict,
    variable: str,
    st: int,
    end: int,
    fs: float,
    cfg: ChFusionConfig,
    xcfg: CrossSpectrumConfig,
    nfft: int,
    band_mask: np.ndarray,
    band_freqs: np.ndarray,
    hann: np.ndarray,
) -> Tuple[np.ndarray, float, dict]:
    """Cross-spectrum combining for one modal variable.

    Returns:
        fused_spectrum: (n_band_bins,) merged cross-spectrum
        bpm: estimated BPM from argmax + parabolic
        info: dict with 'cross_peak_significance', 'n_effective_pairs', etc.
    """
    ...

def estimate_cross_spectrum_segment(
    multichannel_by_var: dict,
    seg_name: str,
    *,
    config: ChFusionConfig,
    metric_params: BreathMetricParams,
    xcfg: CrossSpectrumConfig,
    verbose: bool = False,
) -> dict | None:
    """Run cross-spectrum pipeline on one breath segment. Returns per-window BPMs."""
    ...

def run_cross_spectrum_benchmark(
    frames,
    segment_config: dict,
    *,
    filter_params: FilterParams | None = None,
    metric_params: BreathMetricParams | None = None,
    config: ChFusionConfig | None = None,
    xcfg: CrossSpectrumConfig | None = None,
    verbose: bool = True,
    cache_dir: str | None = None,
    multichannel_by_var: dict | None = None,
) -> dict:
    """Full cross-spectrum benchmark across all segments and methods."""
    ...
```

### 6.4 核心实现提示

1. **获取复频谱**：`np.fft.rfft(windowed_signal, n=nfft)` 返回 complex ndarray，直接取 `[band_mask]` 得到呼吸频段内的复频谱——不需要额外处理
2. **互谱计算**：`np.outer` 不可用（不同 tone 的 FFT 频率 bin 是相同的）。正确做法是对每个频率 bin k，构造 (N_tones,) 的复向量 X[:, k]，然后 `X[i,k] * np.conj(X[j,k])`。避免嵌套循环——可以用 `np.einsum` 或广播
3. **性能**：全 2556 对的互谱对 72 tone × ~200 频率 bin ≈ 0.5M 次复数乘法/窗。三场景 × ~200 窗 ≈ 300M 次运算，Numba 加速或向量化后应在秒级完成
4. **与 B1 的对齐**：`per_modal_cross_spectrum()` 的输入参数签名应与 `per_modal_voting_spectrum()` 兼容，方便在 `estimate_systematic_fusion_segment()` 中做 clean swap

### 6.5 不做的事

- 不修改现有 `chfusion.py`、`voting_fusion.py`、`systematic_fusion.py`
- 不引入 Hilbert 变换或复包络重构（留作后续）
- 不改变滤波链、滑窗参数或评估逻辑
- 不做模态间互谱（仅 tone 间互谱，模态间仍用 Equal 谱融合）

---

## 7. 预期产出

| 产出 | 路径 |
|------|------|
| 验证报告 | `docs/reports/cross_spectrum_combining_report.md` |
| 单场景数值结果 | `outputs/reports/cross_spectrum_results.npy` |
| 跨域汇总 | `outputs/reports/cross_spectrum_cross_domain.npy` |
| 主排行榜图 | `outputs/figures/cross_spectrum_leaderboard.png` |
| 互谱 vs 功率谱对比图 | `outputs/figures/cross_spectrum_vs_power_spectrum.png`（同一窗的 P_B1(f) vs P_cross(f) 并排示例） |
| tone 对间距扫描图 | `outputs/figures/cross_spectrum_pair_spacing_scan.png`（X1/X4/X6 的跨域 mean vs max_delta_k） |
| 跨域汇总图 | `outputs/figures/cross_spectrum_cross_domain_aggregate_bars.png` |

---

## 8. 风险与保留问题

### 8.1 关键保留问题

| ID | 问题 | 备注 |
|----|------|------|
| Q1 | 相邻 tone 的呼吸信号是否足够相干（cos(φᵢ−φⱼ) > 0 普遍成立）？ | `[待确认]` — 若普遍 cos < 0，则 real 和 coherent 模式会退化 |
| Q2 | 互谱 noise floor 是否确实显著低于功率谱 noise floor？ | `[待确认]` — 诊断图直接验证 |
| Q3 | 全 tone 对 vs 邻近 tone 对的最优 trade-off？ | `[待确认]` — 通过 Δk 扫描回答 |
| Q4 | phase 变量的互谱是否优于 amplitude 变量？ | `[待确认]` — phase 保留了更多相位信息 |
| Q5 | 互谱对 091339（voting 退化场景）是否特别有效？ | `[待确认]` — 若有效，说明相位信息是 voting 所缺失的关键维度 |

### 8.2 算法风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| 远距离 tone 对的互谱为纯噪声，稀释了近邻对的增益 | X1/X2/X3（全对）退化 | X4–X7（邻近对）对比揭示：若邻近对显著优于全对，确认假设 |
| real 模式中 cos(φᵢ−φⱼ) < 0 的 tone 对被 clip 为 0，有效样本减少 | X2/X5/X7 退化 | real 模式已做 max(0, ·) clipping；若退化严重，优先用 magnitude |
| 互谱计算量大（全 2556 对 × ~200 bins × ~200 windows） | 运行时间过长 | 向量化 + 预筛选低 ηρ 的 tone 对（设 ηρ 阈值）；或 Numba jit |
| 模态融合侧未同步优化（仍用 Equal） | 互谱增益可能被模态融合的非最优权重掩盖 | 若 X* vs X0 差距小，但诊断显示互谱更干净 → 后续 plan 优化模态侧权重 |

### 8.3 数据与评估风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| 仅金属板三场景 → 结论可能域特定 | 高 | 明确标注；三场景已有足够多样性（voting 退化/优势/中性）来验证跨域一致性 |
| 实信号互谱的物理含义与复信号不完全相同 | 中 | 初代用实信号是故意的——最简单、最可复现、与 B1 直接可比。若效果 promising，后续引入复包络 |

---

## 9. 验证状态

| 字段 | 内容 |
|------|------|
| **验证状态** | 已完成 |
| **实际脚本** | `notebooks/scripts/chFusion_cross_spectrum.py` |
| **报告链接** | `docs/reports/cross_spectrum_combining_report.md` |
| **数值结果** | `outputs/reports/cross_spectrum_results.npy`、`cross_spectrum_cross_domain.npy` |
| **图表** | `outputs/figures/cross_spectrum_*.png`（4 张） |
| **一句话结论** | 全部互谱变体（X1–X7）跨域 mean 12.25%–14.95%，显著劣于 X0/B1 功率谱 8.45%；互谱合并在当前实信号框架下无效。 |

---

## 给执行 Agent 的首条指令

请在 Cursor Composer 中启用 `BLE CS 执行 Agent`，并严格执行：

`docs/plans/cross_spectrum_combining_plan.md`

**任务概要**：

1. 新建 `src/ble_analysis/cross_spectrum.py`（~200 行），实现 §3.3 的 `per_modal_cross_spectrum()` 和 §3.4 的 X1–X7 七种互谱变体
2. 新建 `notebooks/scripts/chFusion_cross_spectrum.py`，跑齐：
   - §4.1 的 X0–X7（8 方法 × 3 场景 = 24 组实验）
   - §4.2 的参考 baseline（从既有 .npy 导入，不需重跑）
3. 模态融合统一用 Equal（与 B1 一致），仅替换信道融合步骤
4. 生成 `docs/reports/cross_spectrum_combining_report.md`，使用模板 `docs/templates/algorithm_validation_report.md`
5. 生成 §7 列出的所有图表和数值结果
6. 回填本 plan §9

**关键对齐点**：
- 滤波链、滑窗参数、呼吸频段、FFT 参数与 B1/systematic_fusion 完全一致
- X0 baseline 从 `systematic_fusion.py` 的 B1 结果直接导入
- 所有 BPM 估计使用 `_bpm_from_fused_spectrum()` 而非 per-tone `_bpm_from_waveform()`——因为互谱输出的是一条融合谱，不是 per-tone BPM 列表
- `per_modal_cross_spectrum()` 的函数签名尽量贴近 `per_modal_voting_spectrum()`，便于后续在 `estimate_systematic_fusion_segment()` 中 clean swap

**诊断要求**：
- 保存 3–5 个示例窗的互谱 P_cross(f) 和功率谱 P_B1(f) 并排对比（同一 tone/窗），存入 `outputs/figures/cross_spectrum_vs_power_spectrum.png`
