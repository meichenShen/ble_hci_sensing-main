# WiFi MRC 方法迁移到 BLE CS — BPM Baseline 实现计划

> **来源**：
> - Fan et al., "A Contactless Breathing Pattern Recognition System Using Deep Learning and WiFi Signal," IEEE IoT-J, 2024. → `docs/papers/fan2024contactless.md`
> - Yu et al. (WiFi-Sleep), "WiFi-Sleep: Sleep Stage Monitoring Using Commodity Wi-Fi Devices," IEEE IoT-J, 2021. → `docs/papers/yu2021wifi.md`
> - GPT 5.5 Pro 研究规划建议 → `docs/papers/三篇文献gpt5.5规划建议.md`
> - Zhuo et al., "Position-Free Breath Detection During Sleep via Commodity WiFi," IEEE Sensors J, 2023. → `docs/papers/zhuo2023position.md`（本次暂不实现，见 §8.3）
>
> **目标报告**：`docs/reports/wifi_mrc_baselines_report.md`（模板：`docs/templates/algorithm_validation_report.md`）
> **日期**：2026-06-16
> **验证状态**：已完成（2026-06-16，见 §9）

---

## 1. 动机与背景

### 1.1 问题

当前 B1（逐模态 η·ρ Voting → 三模态等权谱融合）在跨域 BPM 误差上达到 8.45%，且物理自洽。但 B1 是在**谱域**做非相干融合——它对 tone 间相位/符号不敏感，也不自然输出呼吸波形。

WiFi 呼吸感知文献中有两条与 B1 形成直接对比的技术路线：

| 路线 | 代表工作 | 核心机制 | 与 B1 的关系 |
|------|----------|----------|-------------|
| BNR-MRC → Best Modal | Fan 2024 | 时域 BNR 加权 MRC 合并子载波，选 BNR 最高的模态 | B1 的"如果只选最优模态"对照 |
| SNR-MRC + PCA Sign | WiFi-Sleep (Yu 2021) | 时域 SNR-MRC + PCA 正负号校正，解决反相抵消 | B1 的"时域相干 vs 谱域非相干"对照 |

迁移这两个方法到 BLE CS，可以回答 GPT 5.5 规划建议中的核心研究问题：

> **谱域非相干融合（B1）是否优于时域 signed MRC-PCA（WiFi-Sleep）？**  
> **B1 的优势来自 Voting 信道融合，还是来自三模态 Equal 融合？**（Fan-BLE 可解耦此问题）

### 1.2 本 plan 定位

本 plan 在 BLE CS 数据上实现两个 **WiFi 文献迁移 baseline**，仅比较**呼吸频率（BPM）估计准确度**。波形质量对比留待 B2 Coherent-MRC Waveform Fusion（`docs/suggestions/B2波形与呼吸规划.md`）完成后再进行。

Zhuo 2023（复平面投影 + PCA-VMD）因复杂度高、需要长窗口（3 min vs 当前 20 s）、VMD 调参风险大，**本次不实现**，留作后续独立 plan。

| 项目 | 说明 |
|------|------|
| 问题 | WiFi MRC 方法在 BLE CS 上能否达到或超越 B1 的 BPM 精度？ |
| 相关脚本/文档 | `systematic_fusion.py`（B1）、`chfusion.py`（B0/B2 baseline）、`voting_fusion.py`（T0-V3） |
| 本 plan 定位 | 外部 baseline 迁移验证（非 B1 改进） |

---

## 2. 物理与变量

### 2.1 BLE CS 与 WiFi CSI 的关键差异

| 维度 | WiFi CSI | BLE CS |
|------|----------|--------|
| 子载波/ tone 数 | 30 | 72 |
| 天线结构 | 多 Rx 天线 → CSI ratio 消相位偏移 | 双向 PCT 相乘已抵消 LO 漂移 |
| 可用变量 | CSI ratio amplitude / phase | remote_amplitudes / local_amplitudes / phases |
| 是否需要 ratio | **是** — 否则原始 CSI phase 含随机偏移 | **否** — phases 已是 LO 抵消后的总相位 |
| 采样率 | 50–200 Hz | ~2 Hz（BLE CS 事件间隔 ~500 ms） |

**关键简化**：BLE CS 的 `phases` 已经是两端 PCT 向量相乘后的总相位，LO 漂移已抵消。因此**不需要 WiFi 文献中的 CSI ratio / WCI ratio 步骤**。三种变量可直接作为 MRC 的输入通道。

### 2.2 可用观测量

| 变量 | 是否使用 | 理由 |
|------|----------|------|
| `remote_amplitudes` | ✅ | 72 tone 幅值，作为独立模态 |
| `local_amplitudes` | ✅ | 72 tone 幅值，作为独立模态 |
| `phases`（总相位） | ✅ | 72 tone 相位，作为独立模态 |
| `amplitudes`（总幅值） | ❌ | 无独立物理意义（双方噪声乘积） |
| remote/local 单端相位 | ❌ | 含 LO 漂移，不可用 |

### 2.3 符号约定

| 符号 | 含义 |
|------|------|
| η | 呼吸频段能量比 = E_breath / E_out_of_band（项目已有；WiFi 文献中称为 BNR 或 SNR，实质相同） |
| ρ | 谱峰峰度（项目已有） |
| `x_i(t)` | 第 i 个 tone 的带通滤波后波形 |
| `g_i` | MRC 正权重（由 η 导出） |
| `s_i` | PCA 正负号校正符号（±1） |
| `w_i` | 最终带符号 MRC 权重 = s_i · g_i |

> **关键简化**：WiFi 文献中的 BNR（Fan 2024）和 SNR（WiFi-Sleep）在本文中统一为项目已有的 **η**（呼吸频段能量比）。三者定义等价：呼吸频段内能量与带外能量之比。无需引入新指标。本 plan 中所有 MRC 权重均从 η 导出：线性权重 `g_i ∝ η_i`，平方根权重 `g_i ∝ √η_i`（对应 WiFi-Sleep 的 √SNR），含峰度权重 `g_i ∝ η_i·ρ_i`（对应 B1 当前方案）。

---

## 3. 算法步骤

本 plan 实现**两个独立方法**，共享前处理基础设施，但信道融合策略不同。

### 3.0 共享前处理

两个方法共用以下前处理（与 B1 一致）：

| 步骤 | 参数 | 说明 |
|------|------|------|
| 滑窗 | 20 s 窗长 / 1 s 步长 | 与 B1 相同 |
| 中值滤波 | window=3 | 去尖峰 |
| 高通滤波 | 0.05 Hz, order=1 | 去直流/趋势 |
| 带通滤波 | 0.1–0.35 Hz (6–21 BPM), order=2 | 呼吸频段 |
| 标准化 | 每 tone 去均值，除标准差 | 消除幅度差异 |

输出：对每个模态（remote_amplitudes / local_amplitudes / phases），每窗得到 `[72, T_win]` 的实数矩阵 `X_m`，其中 `T_win` 为窗内采样点数。

---

### 3.1 方法 A：Fan-BLE（η-MRC → Best Modal）

#### 3.1.1 方法来源

Fan 2024 的前端流程，适配到 BLE CS：

```text
WiFi 原文：
    WCI ratio → amplitude/phase (6 candidates)
    → Hampel → BNR per subcarrier
    → MRC across 30 subcarriers
    → select best of 6 candidates by BNR
    → Savitzky-Golay → PSD → BPM

BLE 适配：
    3 variables (remote_amp / local_amp / phases)
    → per-variable: η per tone → MRC across 72 tones
    → select best variable by MRC-output η
    → PSD peak → BPM
```

#### 3.1.2 步骤

```
对每个模态 m ∈ {remote_amplitudes, local_amplitudes, phases}：
    对每窗：
        1. 取该模态的 72 tone 带通波形 X_m: shape [72, T_win]
        2. 对每个 tone i，计算 η_i（呼吸频段能量比，复用现有 pipeline 已计算的 η）
        3. 计算 MRC 权重：
            g_i = η_i / (Σ_j η_j + ε)    # 线性 η 权重（对应 Fan 原文 BNR）
        4. 时域加权合并：
            y_m(t) = Σ_i g_i · x_i(t)
        5. 计算合并后波形的 η_m
    选择 η 最大的模态：
        m* = argmax_m η_m
    对该模态的融合波形做 PSD 寻峰：
        BPM = 60 × argmax_{f ∈ [0.1, 0.35]} PSD(f)
```

#### 3.1.3 关键公式

$$\eta_i = \frac{\sum_{f \in [0.1, 0.35]} P_i(f)}{\sum_{f \in (0.35, f_s/2]} P_i(f) + \epsilon}$$

$$g_i = \frac{\eta_i}{\sum_j \eta_j + \epsilon}$$

$$y_m(t) = \sum_{i=1}^{72} g_i \cdot x_{m,i}(t)$$

$$m^* = \arg\max_m \eta(y_m)$$

$$BPM = 60 \times \arg\max_{f \in [0.1, 0.35]} PSD_{y_{m^*}}(f)$$

#### 3.1.4 变体

为与 B1 做更细粒度对比，同时实现以下变体：

| 变体代号 | MRC 权重 | 模态选择 | 目的 |
|----------|----------|----------|------|
| Fan-η-linear | w_i = η_i（线性） | Best modal | 对应 Fan 原文 BNR-MRC |
| Fan-η-sqrt | w_i = √η_i | Best modal | 对应 WiFi-Sleep 的 √SNR 权重 |
| Fan-η-equal | w_i = η_i + 三模态 Equal | Equal | 对比 B1：MRC 信道融合 + Equal 模态融合 |

Fan-η-equal 可以直接回答："B1 的 Voting 信道融合 vs Fan 的 MRC 信道融合，在同样 Equal 模态融合下谁更优？"

---

### 3.2 方法 B：MRC-PCA-BLE（η-MRC + PCA Sign Correction）

#### 3.2.1 方法来源

WiFi-Sleep (Yu 2021) 的核心思想，适配到 BLE CS：

```text
WiFi 原文：
    CSI ratio → amplitude/phase candidates
    → bandpass → PSD-SNR
    → MRC gain = √SNR
    → PCA sign correction (第一主成分 loading 符号)
    → signed MRC waveform
    → ACF → RR

BLE 适配：
    3 variables (remote_amp / local_amp / phases)
    → per-variable: bandpass → η per tone（复用现有 η）
    → MRC gain = √η_i
    → PCA sign correction on weighted signals
    → signed MRC waveform
    → PSD peak → BPM
```

#### 3.2.2 步骤

```
对每个模态 m ∈ {remote_amplitudes, local_amplitudes, phases}：
    对每窗：
        1. 取该模态的 72 tone 带通波形 X_m: shape [72, T_win]
        2. 对每个 tone i，计算 η_i（复用现有 pipeline 已计算的 η）
        3. 计算 MRC 正权重：
            g_i = √η_i / (Σ_j √η_j + ε)
        4. 构造加权信号矩阵：
            X_weighted = X_m · diag(g)    # 每列乘对应权重
        5. 标准化 X_weighted（每列去均值，除标准差）
        6. PCA(n_components=1) 拟合 X_weighted
        7. 取第一主成分 loading v₁ ∈ R^72
        8. 符号校正：
            s_i = sign(v₁_i)，若为 0 则取 +1
        9. 最终权重：
            w_i = s_i · g_i
        10. 时域带符号加权合并：
            y_m(t) = Σ_i w_i · x_i(t)   # 注意：用原始带通信号，非加权信号
        11. 标准化 y_m(t)（去均值，除标准差）

三个模态各得一条波形 y_r(t), y_l(t), y_p(t)。
每窗对每条波形做 PSD 寻峰得到 BPM_r, BPM_l, BPM_p。

最终 BPM：
    - MRC-PCA-η-best：选 η 最高的模态的 BPM
    - MRC-PCA-η-equal：三模态 BPM 等权平均（或 median）
    - MRC-PCA-η-weighted：三模态按 η 加权平均 BPM
```

#### 3.2.3 关键公式

$$\eta_i = \frac{\sum_{f \in [0.1, 0.35]} P_i(f)}{\sum_{f \in (0.35, f_s/2]} P_i(f) + \epsilon}$$

$$g_i = \frac{\sqrt{\eta_i}}{\sum_j \sqrt{\eta_j} + \epsilon}$$

$$s_i = \text{sign}(v_{1,i})$$

$$w_i = s_i \cdot g_i$$

$$y_m(t) = \sum_{i=1}^{72} w_i \cdot x_{m,i}(t)$$

#### 3.2.4 变体

| 变体代号 | 权重 | 符号校正 | 模态融合 | 目的 |
|----------|------|----------|----------|------|
| MRC-PCA-η-sqrt | w_i = √η_i | PCA sign | Best modal | 对应 WiFi-Sleep 原版 √SNR-MRC |
| MRC-PCA-η-linear | w_i = η_i（线性） | PCA sign | Best modal | 对比权重形式（η vs √η） |
| MRC-PCA-η-equal | w_i = √η_i | PCA sign | Equal | 对比模态融合策略 |
| MRC-PCA-no-sign | w_i = √η_i | **无**（纯正权重） | Best modal | 消融：PCA 符号校正是否必要？ |

MRC-PCA-no-sign 消融实验直接验证：**BLE CS 中 tone 间是否存在呼吸波形反相？** 如果 MRC-PCA-η-sqrt 显著优于 MRC-PCA-no-sign，则说明反相确实存在且 PCA 符号校正是必要的。

#### 3.2.5 PCA 的注意事项

- PCA 输入是 `g_i` 加权后的信号（MRC gain 已乘），这确保 PCA 主要受高 η tone 驱动
- PCA 整体符号不确定性（`v₁` 和 `-v₁` 都合法）不影响 BPM——波形整体反相不改变频率
- 若 tone 数（72）大于时间点数（T_win ≈ 40），PCA 可能不稳定。此时可先按 η 筛选 top-K tone（K=24 或 36）再做 PCA

---

### 3.3 BPM 估计

两个方法的最终 BPM 估计均使用：

```text
1. 对融合波形 y(t) 做 Welch PSD
   - nperseg = min(T_win, 512)
   - noverlap = nperseg // 2
   - Hanning 窗
2. 在呼吸频段 [0.1, 0.35] Hz 内找最大峰值
3. BPM = 60 × f_peak
4. 可选：parabolic 插值细化峰值位置（与 B1 一致）
```

**暂不实现 ACF 呼吸率估计**（WiFi-Sleep 使用 ACF，Fan 使用 PSD）。ACF 作为 PSD 互补估计器留待后续 B1-ACF 或 B2 plan。本次统一用 PSD 以便与 B1 公平对比。

---

## 4. Baseline 对比

执行 Agent **必须**跑齐下表方法。

### 4.1 必跑方法

| 方法 ID | 说明 | 实现参考 |
|---------|------|----------|
| **B0** | Single Remote（max-η 单信道） | `chfusion.py` → B0 |
| **B1 Uniform** | 72 tone 等权谱平均（Remote） | `chfusion.py` → Uniform |
| **Modal top2** | 逐模态 max-η 最优信道 → Top2 等权谱融合 | `chfusion.py` → Modal top2 |
| **B1 (Vote→Equal)** | 逐模态 η·ρ Voting → 三模态等权谱融合 | `systematic_fusion.py` → B1 |
| **Fan-η-linear** | η-MRC（线性权重）→ Best modal | 本 plan §3.1 |
| **Fan-η-sqrt** | √η-MRC → Best modal | 本 plan §3.1 |
| **Fan-η-equal** | η-MRC + 三模态 Equal | 本 plan §3.1 |
| **MRC-PCA-η-sqrt** | √η-MRC + PCA sign → Best modal | 本 plan §3.2 |
| **MRC-PCA-η-equal** | √η-MRC + PCA sign → 三模态 Equal | 本 plan §3.2 |
| **MRC-PCA-no-sign** | √η-MRC **无** PCA sign → Best modal | 本 plan §3.2.4 |

### 4.2 可选变体（时间允许时跑）

| 方法 ID | 说明 |
|---------|------|
| MRC-PCA-η-linear | η-MRC（线性权重）+ PCA sign → Best modal |
| MRC-PCA-η-weighted | √η-MRC + PCA sign → 三模态 η 加权 |
| Fan-η-topK | η-MRC 仅用 top-K=36 tone |

### 4.3 预期相对关系（假设，可被实验推翻）

| 对比 | 预期 | 理由 |
|------|------|------|
| Fan-η-linear vs B1 | Fan 可能略差 | Fan 只用最优单模态，丢弃了 B1 利用的多模态互补 |
| Fan-η-equal vs B1 | 关键对比——Voting vs MRC 信道融合 | 若 Fan-η-equal 接近 B1，说明信道融合方式（MRC vs Voting）不是关键差异；若差距大，说明 Voting 信道融合有独立优势 |
| MRC-PCA-η-sqrt vs MRC-PCA-no-sign | MRC-PCA 应更优 | 若 BLE CS 存在 tone 间反相，PCA 符号校正应产生收益 |
| MRC-PCA-η-sqrt vs B1 | 不确定——这是本 plan 的核心研究问题 | WiFi-Sleep 在 WiFi 上 MRC-PCA 优于单 CSI，但 BLE 的 72 tone / ~2 Hz 采样率可能改变结论 |
| MRC-PCA-η-equal vs B1 | 同上 | 这是"时域 signed MRC + Equal"vs"谱域 Voting + Equal"的直接对比 |
| Fan-η-linear vs Fan-η-sqrt | √η 可能更稳 | √η 压缩了极端值，对 outlier tone 更鲁棒 |

---

## 5. 评估设计

### 5.1 场景

| 场景 JSON | 用途 |
|-----------|------|
| `config/scenarios/cs_091339.json` | 复杂多径，所有方法 >12%，最困难场景 |
| `config/scenarios/cs_095806.json` | Voting 优势场景 |
| `config/scenarios/cs_102621.json` | 跨域对照 |

三场景**权重相等**，不分主次。

### 5.2 指标

| 指标 | 说明 |
|------|------|
| 分段 BPM 相对误差 % | **主指标**；报告 mean / std / median |
| 跨域 mean | 三场景平均 mean BPM err% |
| 90th percentile error | 大错窗口比例 |
| within 1 BPM ratio | BPM 估计与 GT 差距 ≤1 BPM 的窗口占比 |
| within 2 BPM ratio | ≤2 BPM 的窗口占比 |
| 各场景单独 mean | cs_091339 / cs_095806 / cs_102621 |

**本次不评估**：
- 波形质量（无 ground truth 波形，留待 B2 plan）
- apnea 检测
- IE ratio

### 5.3 成功标准

| 级别 | 条件 |
|------|------|
| **最低** | 至少一个 MRC 方法的跨域 mean ≤ 12%（优于已废弃的 X 系列） |
| **合格** | Fan-BLE 或 MRC-PCA-BLE 跨域 mean ≤ 10%（接近 Modal top2 水平） |
| **良好** | 某 MRC 方法跨域 mean ≤ 9%（接近 B1 水平），可作为有效 external baseline |
| **优秀** | 某 MRC 方法跨域 mean ≤ 8.5%（达到或超越 B1），发现时域相干融合在 BLE 上也有效 |
| **失败** | 所有 MRC 方法跨域 mean > 12%，说明直接迁移 WiFi MRC 到 BLE 不适用 |

关键的定性结论（不论数值结果如何）：
- **若 MRC-PCA-η-sqrt 明显优于 MRC-PCA-no-sign** → BLE 存在 tone 间反相，PCA 有价值
- **若 Fan-η-equal 与 B1 差距小** → Voting 信道融合非关键优势
- **若 Fan-η-linear（单模态）明显差于 Fan-η-equal** → 多模态互补确实重要（验证 B1 的设计选择）

---

## 6. 实现要点

### 6.1 建议文件

| 类型 | 路径 |
|------|------|
| 实验脚本 | `notebooks/scripts/chFusion_wifi_mrc_baselines.py` |
| 可复用模块 | `src/ble_analysis/wifi_mrc.py`（新建） |
| 跨域批量脚本 | `notebooks/scripts/chFusion_wifi_mrc_cross_domain.py`（或复用现有 cross_domain 框架） |
| 场景配置 | 沿用现有 `config/scenarios/cs_*.json` |

### 6.2 复用 API

```python
# 复用的现有模块
from ble_analysis.chfusion import (
    estimate_segment_bpm_methods,  # B0, B1 Uniform, Modal top2
)
from ble_analysis.systematic_fusion import (
    per_modal_voting_spectrum,     # B1 Vote→Equal
    modal_fusion_from_spectra,
)
from ble_analysis.segments import (
    FilterParams,
    BreathMetricParams,
    extract_segment_data,
)
from ble_analysis.filters import apply_filter_pipeline
from ble_analysis.metrics import _overall_rel_error, _seg_bpm_stats
from ble_analysis.scenarios import load_scenario

# 标准库
import numpy as np
from scipy.signal import welch, find_peaks
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
```

### 6.3 新模块接口草案：`src/ble_analysis/wifi_mrc.py`

**注意**：η 直接复用现有 pipeline 已计算的 per-tone per-window 能量比。不需要新增 PSD/SNR/BNR 计算函数。新模块只负责：用已有 η 做 MRC 权重 → 时域融合 → BPM。

```python
# --- 共享工具：从已有 η 计算 MRC 权重 ---

def compute_mrc_weights(
    eta: np.ndarray,          # shape [n_tones], 每个 tone 的 η（呼吸能量比）
    mode: str = "sqrt",       # "linear" | "sqrt" | "eta_rho"
    rho: np.ndarray = None,   # shape [n_tones], ρ 值（仅 mode="eta_rho" 时需要）
    eps=1e-12,
) -> np.ndarray:
    """从 η 导出 MRC 正权重。
    - "linear": g_i = η_i / Ση_j
    - "sqrt":   g_i = √η_i / Σ√η_j
    - "eta_rho": g_i = η_i·ρ_i / Σ(η_j·ρ_j)
    Returns g: shape [n_tones], sum(g) = 1."""
    ...


# --- 方法 A：Fan-BLE（η-MRC → Best Modal）---

def fan_mrc_fusion(
    X: np.ndarray,            # shape [n_tones, T_win], 已滤波
    eta: np.ndarray,          # shape [n_tones], per-tone η
    weight_mode: str = "linear",  # "linear" | "sqrt"
    eps=1e-12,
) -> tuple[np.ndarray, float, dict]:
    """Fan 风格 η-MRC 融合：η 加权时域合并 → 选 η 最高模态。
    Returns (waveform, eta_fused, info)."""
    ...


# --- 方法 B：MRC-PCA-BLE（η-MRC + PCA Sign）---

def mrc_pca_fusion(
    X: np.ndarray,            # shape [n_tones, T_win], 已滤波
    eta: np.ndarray,          # shape [n_tones], per-tone η
    weight_mode: str = "sqrt",   # "linear" | "sqrt"
    use_pca_sign: bool = True,
    top_k: int = None,           # 先按 η 筛选 top-K tone 再做 PCA
    eps=1e-12,
) -> tuple[np.ndarray, dict]:
    """WiFi-Sleep 风格 √η-MRC + PCA sign 融合。
    Returns (waveform, info dict with weights, signs, coherences)."""
    ...


# --- BPM 估计（复用现有 PSD 寻峰逻辑）---

def estimate_bpm_from_waveform(
    y: np.ndarray,            # shape [T], 呼吸波形
    fs: float,
    breath_band=(0.1, 0.35),
    nfft=None,
) -> tuple[float, float, np.ndarray, np.ndarray]:
    """从波形做 PSD 寻峰估计 BPM。
    Returns (bpm, f_peak, freqs, pxx)."""
    ...
```

### 6.4 实现注意事项

1. **BLE CS 采样率低（~2 Hz）**：20 s 窗口只有约 40 个采样点。η 的计算复用现有 pipeline（已在 B1 中验证），无需额外 PSD 计算。
2. **PCA 时的维度问题**：72 tone × ~40 时间点 → 需先按 η 筛选 top-K tone（建议 K=24 或 36），否则 PCA 协方差矩阵估计不可靠。
3. **与 B1 滤波链一致**：使用相同的 `FilterParams(median_window=3, highpass_cutoff=0.05, bandpass_lowcut=0.1, bandpass_highcut=0.35)`，确保对比公平。
4. **Hampel filter**：Fan 2024 原文使用 Hampel，但 B1 未用。为公平对比，可先不加 Hampel，作为可选变体单独测试。
5. **Savitzky-Golay filter**：Fan 2024 用 S-G 平滑，但 BLE 低采样率下 S-G 窗口长度难以合理设置（101 点 ≈ 50 s）。建议暂不加 S-G，或以小窗口（5–7 点）测试。
6. **η 数值边界**：η 可能出现极端值（某 tone 噪声极低时）。weights 计算需要 clip 或加 ε 防止除零。

### 6.5 不做的事

- 不实现 CSI ratio / WCI ratio（BLE CS 已抵消 LO 漂移）
- 不实现 ACF 呼吸率估计（留待后续）
- 不实现 VMD（Zhuo 2023 的方法，留待后续）
- 不实现复平面投影角度搜索（同上）
- 不修改 B1 或现有 baseline 的实现
- 不评估波形质量、呼吸形态特征

---

## 7. 预期产出

| 产出 | 路径 |
|------|------|
| 验证报告 | `docs/reports/wifi_mrc_baselines_report.md` |
| 数值结果 | `outputs/reports/wifi_mrc_baselines_results.npy`（或 `.json`） |
| 跨域汇总图 | `outputs/figures/wifi_mrc_baselines_cross_domain_summary.png` |
| 排行榜图 | `outputs/figures/wifi_mrc_baselines_leaderboard.png` |
| 场景单独对比图 | `outputs/figures/wifi_mrc_baselines_{scenario}.png`（每场景一张） |
| 消融对比图 | `outputs/figures/wifi_mrc_baselines_ablation.png`（MRC-PCA vs no-sign 等） |

### 7.1 建议运行命令

```bash
# 单场景
python notebooks/scripts/chFusion_wifi_mrc_baselines.py --scenario cs_091339
python notebooks/scripts/chFusion_wifi_mrc_baselines.py --scenario cs_095806
python notebooks/scripts/chFusion_wifi_mrc_baselines.py --scenario cs_102621

# 跨域汇总
python notebooks/scripts/chFusion_wifi_mrc_cross_domain.py
```

---

## 8. 风险与保留问题

### 8.1 算法风险

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| PCA 在低采样率下不稳定 | 中 | MRC-PCA 符号估计不可靠 | 按 η 筛选 top-K tone；增加 `no_sign` 消融对照 |
| η 估计在短窗口（~40 点）下方差大 | 高 | 权重噪声大，MRC 收益有限 | 报告 η 的窗口间稳定性；对比等权 baseline |
| 时域 MRC 反相抵消 | 中 | MRC-PCA-no-sign 甚至比单 tone 差 | 这正是 PCA 符号校正要解决的——若 PCA 也失败，说明 BLE 下非相干融合确实更合理 |
| Fan 的 Best-modal 选择不稳定 | 中 | 窗间模态切换剧烈 | 报告模态选择分布；对比 Fan-η-equal |

### 8.2 数据风险

| 风险 | 说明 |
|------|------|
| 采样率不均匀 | BLE CS 事件间隔可能有抖动。当前 pipeline 假设均匀采样。若抖动严重（>20%），需先重采样 |

### 8.3 Zhuo 2023 为何本次不做

Zhuo 2023 的方法（复平面投影 + BNR/Variance 联合评分 + PCA-VMD）暂不实现，原因：

1. **VMD 需要长窗口**：论文用 3 min 片段，而当前标准滑窗仅 20 s。20 s 对 VMD（K=3）可能不足以稳定分解。
2. **100 角度投影搜索计算量大**：60 个 CSI ratio stream × 100 角度 × 12 s 选择窗口 → 每窗大量 FFT。在 BLE 上对应 60 × 100 = 6000 次投影评估/窗。
3. **参数调优风险高**：VMD 的 α、τ、DC、init、tol 均未在论文中明确给出，容易调参过拟合。
4. **分阶段验证更合理**：先验证简单的 MRC baseline（本 plan），若时域相干融合在 BLE 上确实有效，再考虑更复杂的 PCA-VMD 增强。

建议 Zhuo 作为**独立后续 plan**（`docs/plans/zhuo_pca_vmd_plan.md`），在以下条件满足后启动：
- 本 plan 确认时域 MRC 在 BLE 上有基本有效性
- B2 plan 建立了波形质量评估框架
- 积累了对 BLE 低采样率下 PCA 行为的理解

### 8.4 需要执行后确认的问题

| ID | 问题 | 确认方式 |
|----|------|----------|
| Q1 | BLE CS 的 72 tone 间是否存在呼吸波形反相？ | 对比 MRC-PCA-η-sqrt vs MRC-PCA-no-sign |
| Q2 | 纯 η 和 η·ρ 在 per-tone 质量排序上是否一致？ | 计算两种指标在相同窗口上的 Spearman 相关系数 |
| Q3 | Best-modal 策略的窗间模态切换频率如何？ | 统计每个场景的模态选择分布直方图 |
| Q4 | 低采样率（~2 Hz）下 η 估计是否稳定？ | 报告 η 在相邻窗口间的自相关系数 |
| Q5 | Fan-η-equal 与 B1 的差距来自信道融合（MRC vs Voting）还是质量指标（η vs η·ρ）？ | 增加 Fan 使用 η·ρ 权重的变体做消融 |

---

## 9. 验证状态

| 字段 | 内容 |
|------|------|
| **验证状态** | 已完成 |
| **实际脚本** | `notebooks/scripts/chFusion_wifi_mrc_baselines.py`、`notebooks/scripts/chFusion_wifi_mrc_cross_domain.py` |
| **核心模块** | `src/ble_analysis/wifi_mrc.py` |
| **报告链接** | `docs/reports/wifi_mrc_baselines_report.md` |
| **数值结果** | `outputs/reports/wifi_mrc_baselines_results.npy` |
| **图表** | `outputs/figures/wifi_mrc_baselines_*.png` |
| **一句话结论** | WiFi 时域 MRC 可运行且 PCA 符号校正有效，但跨域 BPM 最优仍为 B1（8.45%）；最优 MRC MRC-PCA-η-equal 为 10.78%。 |

### 保留问题

| ID | 问题 | 备注 |
|----|------|------|
| Q1 | BLE CS tone 间反相存在性 | **已支持**：MRC-PCA-η-sqrt 11.95% vs no-sign 15.82% |
| Q2 | 时域相干 vs 谱域非相干 在 BLE 上孰优 | **谱域 B1 仍优**；MRC-PCA-η-equal 10.78% |
| Q3 | Zhuo 2023 是否值得后续尝试 | 取决于 B2；本 plan 未证实时域 MRC BPM 优势 |
| Q4 | B2 Coherent-MRC Waveform Fusion 优先级 | 可继续波形方向，BPM 超越 B1 预期有限 |

---

## 10. 给执行 Agent 的首条指令

请在 Cursor Composer 中启用 `BLE CS 执行 Agent`，并严格执行：

`docs/plans/wifi_mrc_baselines_plan.md`

执行要点：

1. 新建 `src/ble_analysis/wifi_mrc.py`，实现 §3 中的 Fan-BLE 和 MRC-PCA-BLE
2. 新建 `notebooks/scripts/chFusion_wifi_mrc_baselines.py`，跑齐 §4.1 必跑方法 × 3 场景
3. 使用 `docs/templates/algorithm_validation_report.md` 撰写 `docs/reports/wifi_mrc_baselines_report.md`
4. 生成 §7 列出的图表
5. 回填本 plan §9 验证状态
6. 特别注意 §6.4 中的 BLE 低采样率适配（Welch nperseg、PCA top-K、S-G 窗口）

执行完成后，请返回以下材料给 Claude/DeepSeek Review：

- `docs/plans/wifi_mrc_baselines_plan.md`（已回填状态）
- `docs/reports/wifi_mrc_baselines_report.md`
- `outputs/reports/wifi_mrc_baselines_*.npy`
- `outputs/figures/wifi_mrc_baselines_*.png`
- `src/ble_analysis/wifi_mrc.py`
- `notebooks/scripts/chFusion_wifi_mrc_baselines.py`
- git commit message 或 git diff 摘要

Review 完成后，若结论改变方法推荐/废弃状态，Claude/DeepSeek 负责更新 `docs/methods/README.md`。

---

## 附录 A：与 GPT 5.5 规划建议的对应关系

本 plan 覆盖了 GPT 5.5 建议的以下实验：

| GPT 5.5 编号 | 方法 | 本 plan 对应 |
|-------------|------|-------------|
| Fan-BLE | BNR-MRC → best modal | §3.1 Fan-η-linear / Fan-η-sqrt（BNR = η） |
| MRC-PCA-BLE | signed time-domain MRC | §3.2 MRC-PCA-η-sqrt（SNR = η） |
| B1-SNR | w_i = √SNR | 未直接覆盖（属于 B1 内部消融，但 Fan-η-sqrt 和 MRC-PCA-η-sqrt 已使用 √η，等价） |
| B1-ACF | ηρ 加权 ACF 融合 | 未覆盖（留待 B1-ACF 或 B2 plan） |
| B1-shrink-modal | shrink-to-equal | 未覆盖（属于模态融合升级，建议后续 plan） |

## 附录 B：与其他 plan 的关系

```text
本 plan (wifi_mrc_baselines)
    ↓ 验证时域 MRC 在 BLE 上的基本有效性
    ↓
┌───────────────────────┬───────────────────────┬───────────────────────┐
│ B1 消融 plan         │ B2 Coherent-MRC       │ Zhuo PCA-VMD plan     │
│ (权重族 / Top-K /    │ Waveform Fusion       │ (投影 + VMD)          │
│  log-spectrum /      │ (Hilbert 相位对齐)     │ (高风险高收益)         │
│  shrink-to-equal)    │ (用户原始想法)         │                       │
└───────────────────────┴───────────────────────┴───────────────────────┘
```
