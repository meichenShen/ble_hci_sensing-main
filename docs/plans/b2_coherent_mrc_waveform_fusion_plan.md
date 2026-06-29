# B2 Coherent-MRC Waveform Fusion — 实现计划

> **来源**：`docs/suggestions/B2波形与呼吸规划.md`（GPT 5.5 Pro 研究建议）  
> **目标报告**：`docs/reports/b2_coherent_mrc_waveform_fusion_report.md`（模板：`docs/templates/algorithm_validation_report.md`）  
> **日期**：2026-06-23  
> **验证状态**：已完成（2026-06-23）

---

## 1. 动机与背景

### 1.1 问题

B1（逐模态 η·ρ Voting → 三模态等权谱融合，跨域 8.45%）在**谱域**做非相干融合——它对 tone 间相位/符号不敏感，融合对象是功率谱而非波形，因此不自然输出呼吸波形。

WiFi MRC 实验（`wifi_mrc_baselines`）已初步验证了时域 MRC 在 BLE CS 上的可行性：
- MRC-PCA-η-equal 跨域 10.78%，仍劣于 B1（8.45%），差距 2.33 pp
- PCA 符号校正确实有效（no-sign → sign: +3.9 pp）
- 差距被分解为：η·ρ 质量指标 (+2.73 pp) + Voting 信道融合 (+2.33 pp)

但 WiFi MRC 有两个关键限制：

| 限制 | 描述 | B2 的改进 |
|------|------|----------|
| 仅符号校正 | PCA/corr 只能补偿 0/π 相位差，无法处理连续相位偏移 | Hilbert 连续相位补偿 |
| 仅选最优模态 | 三模态各自 MRC → 选 η 最高者，未做模态间融合 | 两级相干融合（tone 级 → modal 级） |

B2 的核心假设是：**用 Hilbert 解析信号做连续相位对齐 + coherence gating + 两层级联融合**，可以在 BPM 精度上同时超越 B1（8.45%）和 WiFi MRC（10.78%），并且输出可用呼吸波形。

### 1.2 本 plan 定位

本 plan 是一个**新方法探索**（非 baseline 迁移），目标是在 BLE CS 上实现 **Two-Level Coherent MRC Waveform Fusion**，同时回答：

> 连续相位补偿（Hilbert）是否优于仅符号校正（PCA/corr）？  
> 两层级联融合是否优于单级 tone-level MRC？  
> B2 能否在 BPM 精度上达到或超越 B1（8.45%）？

| 项目 | 说明 |
|------|------|
| 问题 | 时域相干 MRC 波形融合能否超越谱域非相干融合（B1）？ |
| 相关脚本/文档 | `systematic_fusion.py`（B1）、`wifi_mrc.py`（WiFi MRC baseline）、`chfusion.py`（公共滤波/寻峰/评估） |
| 本 plan 定位 | 新方法探索——从「谱域非相干」推进到「时域相干」|

---

## 2. 物理与变量

### 2.1 B2 的物理直觉

把每个 tone 的带通呼吸波形建模为：

\[
z_i(t) = h_i \cdot s(t) + n_i(t)
\]

其中 \(z_i(t)\) 是第 i 个 tone 的解析信号，\(s(t)\) 是潜在真实呼吸解析信号，\(h_i = |h_i| e^{j\phi_i}\) 是该 tone 对呼吸的复响应，\(n_i(t)\) 是噪声。

经典 MRC 的融合是：

\[
\hat{s}(t) = \sum_i \frac{\overline{h_i}}{\sigma_i^2} z_i(t)
\]

B2 的近似是：

\[
\hat{s}(t) = \sum_i q_i \cdot e^{-j\hat{\phi_i}} \cdot z_i(t)
\]

其中 \(q_i\) 是质量权重（η·ρ 或 coherence-gated），\(\hat{\phi_i}\) 是相对于参考 tone 的呼吸相位差估计。

**物理上，B2 试图恢复一条"潜在呼吸波形"** ——它不是严格的胸腹位移，而是多个 tone 对同一呼吸运动的共同响应分量。相位对齐的目的是让所有 tone 的呼吸分量在相干叠加时建设性干涉，而非相互抵消。

### 2.2 可用观测量

| 变量 | 是否使用 | 理由 |
|------|----------|------|
| `remote_amplitudes` | ✅ | 72 tone 幅值，作为独立模态输入第一级 MRC |
| `local_amplitudes` | ✅ | 同上 |
| `phases`（总相位） | ✅ | 72 tone 相位（LO 已抵消），作为独立模态输入第一级 MRC |
| `amplitudes`（总幅值） | ❌ | 无独立物理意义（双方噪声乘积） |
| remote/local 单端相位 | ❌ | 含 LO 漂移，不可用 |

### 2.3 相位对齐的物理前提

B2 估计的相位差**不是 2.4 GHz 载波相位差**，而是 **0.1–0.35 Hz 呼吸波形分量的相位差**。这要求：

1. 每个 tone 的带通波形中确实存在呼吸频率分量（由 η > 0 保证）
2. 两个 tone 的呼吸分量具有共同的频率 \(f_0\)（由 B1 coarse BPM 或窗口 PSD 主峰验证）
3. tone 间的相位偏移在 20 s 窗口内近似稳定 `[待确认]`

### 2.4 符号约定

| 符号 | 含义 |
|------|------|
| η | 呼吸频段能量比 \(E_{0.1-0.35} / E_{0.35-0.8}\) |
| ρ | 谱峰峰度 \(P_{max} / P_{median}\) |
| γ | Hilbert 相干性 \(\left|\sum z_i \overline{z_{ref}}\right| / \sqrt{\sum|z_i|^2 \sum|z_{ref}|^2}\) |
| \(\Delta\phi_i\) | tone i 相对于参考 tone 的呼吸相位差 |
| \(z_i(t)\) | tone i 的 Hilbert 解析信号 |
| \(q_i\) | 质量权重（η·ρ 或其 coherence-gated 变体） |

---

## 3. 算法步骤

### 3.1 预处理（与 B1 一致，完全复用）

对每个模态（remote_amplitudes / local_amplitudes / phases）的 72 tone 原始时间序列，逐 tone 执行：

```
median filter → highpass (0.05 Hz) → bandpass (0.1–0.35 Hz) → standardization (zero mean, unit std)
```

**复用**：`run_multichannel_segment_filtering()` in `chfusion.py`，滤波参数与 B1 完全相同。

### 3.2 滑窗

| 参数 | 值 | 说明 |
|------|-----|------|
| 窗长 | 20 s | 与所有 baseline 一致 |
| 步长 | 1 s | 与所有 baseline 一致 |
| 呼吸频段 | 0.1–0.35 Hz (6–21 BPM) | 与所有 baseline 一致 |
| FFT | rFFT, Hanning 窗, nfft = next_pow2(4 × win_len) | 与所有 baseline 一致 |

**复用**：`_sliding_window_indices()` in `segments.py`。

### 3.3 第一级：Tone-Level Coherent MRC（每个模态内部）

#### 3.3.1 输入

对给定模态（如 `remote_amplitudes`）的给定窗口，有：

\[
X = [T_{win}, 72], \quad \eta \in \mathbb{R}^{72}, \quad \rho \in \mathbb{R}^{72}
\]

每列是一个 tone 的 20 s 带通标准化波形。

#### 3.3.2 质量权重

\[
q_i = \eta_i \cdot \rho_i
\]

（基本权重；具体变体见 §3.3.4 决策矩阵）

#### 3.3.3 相位估计与对齐 — 四条技术路线

B2 Plan 的核心实验矩阵。对每个 tone i，估计其呼吸波形相对于参考的相位差 \(\Delta\phi_i\)：

**路线 A0：PCA 符号校正**（已有实现 `mrc_pca_fusion()` in `wifi_mrc.py`）

```
X_weighted[i] = X[i] · q_i                  # η·ρ 加权
X_weighted → PCA → 第一主成分 loading      # 对加权后 tone 做 PCA
sign_i = sign(loading_i)                    # loading 符号即为校正方向
w_i = sign_i · q_i / Σ|sign_j · q_j|
y(t) = Σ w_i · X_i(t)
```

- 相位范围：仅 {0, π}
- 参考依赖：**无**（全局 PCA 方向，非 pairwise）
- 优点：不依赖参考 tone 选择；已有实现，直接复用

**路线 A1：相关系数符号校正**（需新增）

```
ref = argmax_i q_i                          # 质量最高者
sign_i = sign(corr(X_i, X_ref))            # Pearson r < 0 → -1
w_i = sign_i · q_i
y(t) = Σ w_i · X_i(t) / Σ |w_i|
```

- 相位范围：仅 {0, π}
- 参考依赖：**是**（max-q tone）
- 优点：比 PCA 更直观；实现简单

**路线 B：Hilbert 解析信号相位差**（需新增，主推荐）

```
z_i(t) = hilbert(X_i(t))                   # 解析信号
z_ref(t) = hilbert(X_ref(t))
Δφ_i = angle(Σ_t z_i(t) · conj(z_ref(t)))  # 互解析内积相位
γ_i = |Σ z_i · conj(z_ref)| / √(Σ|z_i|² · Σ|z_ref|²)   # 相干性
z_i_aligned(t) = z_i(t) · exp(-j · Δφ_i)
w_i = q_i · γ_i                             # coherence-gated 权重
z_fused(t) = Σ w_i · z_i_aligned(t) / Σ w_i
y(t) = real(z_fused(t))
```

- 相位范围：连续 [−π, π]
- 参考依赖：**是**（默认 max-q tone）
- 优点：连续相位补偿；自然输出相干性 γ；B2 文档主推荐

**路线 C：FFT 互谱相位差**（需新增）

```
B1 coarse BPM → f₀
R(f) = FFT(X_ref), X_i(f) = FFT(X_i)
C_i = Σ_{f ∈ f₀ ± 0.02 Hz} X_i(f) · conj(R(f))   # 窄带互谱
Δφ_i = angle(C_i)
γ_i = |C_i| / √(Σ|X_i|² · Σ|R|²)
z_i_aligned(t) = hilbert(X_i(t)) · exp(-j · Δφ_i)  # Hilbert 时域旋转
# 后续同路线 B
```

- 相位范围：连续 [−π, π]
- 参考依赖：**是** + **B1 coarse f₀**
- 优点：相位估计在频域完成（对窄带信号稳定）；与 B1 频谱框架天然兼容
- 风险：f₀ 误差会传播到相位估计 `[待确认]`

#### 3.3.4 第一级决策矩阵（完整 4×4 ablation 空间）

| 维度 | 选项 | 对应路线 |
|------|------|----------|
| 相位估计 | PCA sign / Corr sign / Hilbert / FFT cross-spectrum | A0 / A1 / B / C |
| 参考选择 | 无（全局 PCA）/ max-(η·ρ) / B1 coarse f₀ 引导 | 随路线定 |
| 质量权重 | η·ρ only / coherence-gated (q·γ) / coherence-gated² (q·γ²) | 所有路线可选 |
| 相干门控 | 无 / 软降权（乘 γ）/ 硬门控（γ < 0.2 → 排除）| B/C 可选 |

**建议执行顺序（渐进式，避免一次性全跑）**：

```
Phase 1: A0 vs A1（PCA vs corr sign，仅 η·ρ 权重，无相干门控）
    → 确定最优符号校正路线
Phase 2: A_best vs B（sign vs Hilbert continuous，η·ρ vs coherence-gated 权重）
    → 回答"连续相位补偿是否有增益？"
Phase 3: B vs C（时域 Hilbert vs 频域互谱相位估计）
    → 回答"相位估计在哪做更稳定？"
```

每个 Phase 内部做完整三场景评估。

#### 3.3.5 输出

对每个模态、每个窗口：

```python
{
    "modal_waveform": np.ndarray,       # shape [T_win] — 融合后呼吸波形
    "modal_bpm": float,                 # 从波形 PSD 估计的 BPM
    "modal_eta": float,                 # 融合波形的 η
    "phase_offsets": np.ndarray,        # shape [72] — 各 tone 相位补偿量
    "coherences": np.ndarray,           # shape [72] — 各 tone 相干性
    "weights": np.ndarray,              # shape [72] — 最终融合权重
    "ref_idx": int,                     # 参考 tone index
}
```

### 3.4 第二级：Modal-Level Coherent Fusion（三个模态之间）

#### 3.4.1 输入

第一级产出三条波形：

\[
y_r(t), \quad y_l(t), \quad y_p(t)
\]

分别对应 remote/local/phase 模态的 tone-level MRC 输出。

#### 3.4.2 模态间对齐

```
z_m(t) = hilbert(y_m(t))                 # m ∈ {r, l, p}
ref_modal = argmax_m η_m                 # 选 η 最高的模态
Δφ_m = angle(Σ_t z_m(t) · conj(z_ref(t)))
γ_m = |Σ z_m · conj(z_ref)| / √(Σ|z_m|² · Σ|z_ref|²)
W_m = η_m · γ_m                           # 或其他权重（见变体）
z_final(t) = Σ W_m · z_m(t) · exp(-j · Δφ_m) / Σ W_m
y_final(t) = real(z_final(t))
```

#### 3.4.3 模态权重变体

| 变体 | 公式 | 说明 |
|------|------|------|
| Equal | \(W_r = W_l = W_p = 1\) | 最简，与 B1 的 equal modal 一致 |
| η-weight | \(W_m = \eta_m\) | 质量驱动 |
| η·γ | \(W_m = \eta_m \cdot \gamma_m\) | 质量 + 相干性 |
| Shrink-to-equal | \(W_m = (1-\lambda)/3 + \lambda \cdot s_m/\Sigma s_j\) | λ=0.5，保守自适应 |

#### 3.4.4 第二级 ablation 维度

| 维度 | 选项 |
|------|------|
| 是否做第二级 | 否（仅 tone-level，选最优 modal）/ 是（两级） |
| 模态对齐 | 符号校正 / Hilbert 连续相位 |
| 模态权重 | Equal / η / η·γ / shrink-to-equal |

### 3.5 最终 BPM 估计

从最终呼吸波形 \(y_{final}(t)\) 提取 BPM：

```
方法 1（主）：Welch PSD → argmax in 0.1–0.35 Hz → parabolic interpolation → BPM
方法 2（辅）：ACF → 峰值间隔 → BPM
方法 3（诊断）：波形峰值间隔 → BPM
```

**复用**：`estimate_bpm_from_waveform()` in `wifi_mrc.py`（Welch PSD 版本）。

**建议**：主报告使用 PSD 方法（与 B1 可比），ACF 和 peak-interval 作为诊断辅助。

### 3.6 B1 作为 Coarse f₀ 初始化的可选方案

对于路线 C（FFT 互谱），需要 f₀ 引导：

```
B1 coarse BPM → f₀ = BPM / 60
→ 所有 tone 在 f₀ ± 0.02 Hz 内估计互谱相位
→ coherent fusion → 重新估计 BPM
```

注意：
- B1 只提供 f₀ 初始化，B2 独立完成融合和 BPM 估计
- 应同时报告 B2 独立运行版本（路线 B，不需 f₀）和 B1 引导版本（路线 C）
- 最多迭代一次（B2 BPM 不再回传给 B1）

---

## 4. Baseline 对比

执行 Agent **必须**跑齐以下方法：

| 方法 ID | 描述性名称 | 实现参考 | 备注 |
|---------|-----------|----------|------|
| B0 | Single Remote（max-η） | `chfusion.py` | 项目最简基线 |
| B1 Uniform | Uniform Remote（72 tone 等权谱平均） | `chfusion.py` | 旧 B1，非当前推荐 |
| Modal top2 | 逐模态 max-η 最优信道 → Top2 等权谱融合 | `chfusion.py` | Plan2 最优，跨域 9.45% |
| **B1 Vote→Equal** | **逐模态 η·ρ Voting → 三模态等权谱融合** | `systematic_fusion.py` | **当前最优谱域方法，跨域 8.45%** |
| MRC-PCA-η-equal | √η-MRC + PCA 符号校正 → 三模态等权 | `wifi_mrc.py` | WiFi MRC 最优，跨域 10.78% |
| MRC-PCA-η-sqrt | √η-MRC + PCA 符号校正 → Best modal | `wifi_mrc.py` | WiFi MRC 原文范式，跨域 11.95% |

### B2 待测方法（需新增实现）

| 方法 ID | 描述性名称 | 路线 |
|---------|-----------|------|
| **B2-A0** | PCA 符号校正 MRC → 三模态等权 | A0（复用 `mrc_pca_fusion()`） |
| **B2-A1** | 相关系数符号校正 MRC → 三模态等权 | A1（新增） |
| **B2-B** | Hilbert 连续相位 MRC（η·ρ 权重，无相干门控）→ 三模态等权 | B |
| **B2-Bγ** | Hilbert 连续相位 MRC（coherence-gated η·ρ 权重）→ 三模态等权 | B + γ gate |
| **B2-C** | FFT 互谱相位 MRC（B1 coarse f₀ 引导）→ 三模态等权 | C |
| **B2-D** | **Two-Level Hilbert-MRC**：tone 级 B2-Bγ + modal 级 Hilbert 相干融合 | B + modal-level |
| **B2-D-eq** | Two-Level Hilbert-MRC，modal 级等权（不做模态间相位对齐）| B + modal equal |

> **注意**：B2-A0 复用 `wifi_mrc.py` 中已有的 `mrc_pca_fusion()`，仅需更换 BPM 提取和评估流程（加入 coherence 诊断、波形输出、modal 级等权融合），不应重写 PCA 部分。

### 预期相对关系（研究阶段假设，可被实验推翻）

| 对比 | 预期 | 理由 |
|------|------|------|
| B2-A0 vs MRC-PCA-η-equal | ≈ 持平 | A0 实质相同，预期跨域 ~10.8% |
| B2-A1 vs B2-A0 | A1 ≈ A0 或略差 | PCA 全局决策 vs pairwise 参考依赖 |
| B2-B vs B2-A_best | **B 更优** | 连续相位补偿 > 仅符号校正（B2 核心假设） |
| B2-Bγ vs B2-B | **Bγ 更优** | coherence gating 抑制坏 tone |
| B2-C vs B2-B | 不确定 `[待确认]` | 频域相位估计 vs 时域，取决于 f₀ 精度 |
| B2-D vs B2-Bγ | **D 更优** | 模态间相干对齐应进一步抑制模态间相位冲突 |
| B2-D vs B1 Vote→Equal (8.45%) | **期望 D 接近或超越** | 连续相位补偿 + coherence gating + 两层级联 |

---

## 5. 评估设计

### 5.1 场景

| 场景 JSON | 用途 |
|-----------|------|
| `config/scenarios/cs_091339.json` | 跨域验证（复杂多径，所有方法 >12% 瓶颈场景） |
| `config/scenarios/cs_095806.json` | 跨域验证（Voting 优势场景） |
| `config/scenarios/cs_102621.json` | 跨域验证（G4 4.51% 最优场景） |

### 5.2 指标

| 指标 | 说明 | 优先级 |
|------|------|--------|
| 分段 BPM 相对误差 % mean | **主指标** | P0 |
| 分段 BPM 相对误差 % std | 稳定性 | P0 |
| 跨域 mean | 三场景平均 | P0 |
| per-window signed BPM error | 偏置诊断 | P1 |
| 融合波形 η | 波形质量 | P1 |
| per-tone coherence γ 分布 | 相位对齐可信度诊断 | P1 |
| 模态间 coherence γ 分布 | 模态融合可信度诊断 | P2 |
| ACF BPM vs PSD BPM 一致性 | BPM 估计方式鲁棒性 | P2 |

### 5.3 成功标准

| 级别 | 条件 |
|------|------|
| **理想** | B2-D 跨域 mean ≤ 8.45%（达到或超越 B1） |
| **最低** | B2-Bγ 跨域 mean ≤ 10.78%（超越 WiFi MRC 最优），且至少一个 Phase 假设被验证 |
| **部分成功** | 连续相位补偿（B）优于仅符号校正（A0/A1），但跨域未达 B1 |
| **失败** | 所有 B2 变体跨域 > 10.78%（即劣于已有 WiFi MRC）或 091339 > 20% |

### 5.4 物理自洽性检查

| # | 检查项 | B2 各变体 |
|---|--------|----------|
| 1 | remote/local 对称对待 | ✅ — 三模态各自独立做第一级 MRC |
| 2 | 三种变量对称对待 | ✅ — 模态融合 equal 或质量驱动，不预设 |
| 3 | 信道/模态选择由 per-window 信号质量动态决定 | ✅ — 参考 tone 和参考 modal 均 per-window 动态选择 |
| 4 | 无硬编码 fallback 到特定模态/信道 | ✅ — 无 fallback 机制 |
| 5 | 不使用总幅值 | ✅ |

---

## 6. 实现要点

### 6.1 建议文件

| 类型 | 路径 |
|------|------|
| 实验脚本 | `notebooks/scripts/chFusion_b2_coherent_mrc.py` |
| 可复用模块 | `src/ble_analysis/coherent_mrc.py`（**新建**） |
| 跨域脚本 | `notebooks/scripts/chFusion_b2_coherent_mrc_cross_domain.py` |
| 场景配置 | 沿用现有 `config/scenarios/cs_*.json` |

### 6.2 新建模块接口草案

`src/ble_analysis/coherent_mrc.py`：

```python
# --- 核心融合函数 ---

def estimate_phase_corr_sign(
    X: np.ndarray,           # [T, C] bandpass waveforms
    quality: np.ndarray,     # [C] η·ρ
    ref_idx: int | None = None,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """A1: Pairwise correlation sign correction. Returns (y, weights, info)."""
    ...

def estimate_phase_hilbert(
    X: np.ndarray,
    quality: np.ndarray,
    ref_idx: int | None = None,
    min_coherence: float = 0.0,     # 0 = no hard gate
    coherence_power: float = 1.0,   # 1.0 = w·γ, 2.0 = w·γ²
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """B: Hilbert analytic-signal phase alignment + coherence-gated MRC.
    Returns (y, phases_rad, coherences, info)."""
    ...

def estimate_phase_fft_cross_spectrum(
    X: np.ndarray,
    quality: np.ndarray,
    fs: float,
    f0: float,               # B1 coarse BPM / 60
    ref_idx: int | None = None,
    half_width_hz: float = 0.02,
    min_coherence: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """C: FFT cross-spectrum phase estimation around f0.
    Returns (y, phases_rad, coherences, info)."""
    ...

# --- 一级融合（per-modal tone-level） ---

def coherent_mrc_fuse_tones(
    X: np.ndarray,            # [T, 72]
    eta: np.ndarray,          # [72]
    rho: np.ndarray,          # [72]
    phase_method: str,        # "pca_sign" | "corr_sign" | "hilbert" | "fft_cross"
    weight_mode: str,         # "eta_rho" | "coherence_gated" | "coherence_gated_sq"
    ref_idx: int | None = None,
    f0: float | None = None,  # for FFT method
    fs: float = 2.0,
    min_coherence: float = 0.0,
) -> tuple[np.ndarray, dict]:
    """Tone-level coherent MRC: 72 tones → 1 modal waveform."""
    ...

# --- 二级融合（modal-level） ---

def coherent_mrc_fuse_modals(
    waveforms: dict[str, np.ndarray],  # {"remote": y_r, "local": y_l, "phase": y_p}
    modal_etas: dict[str, float],
    modal_weight_mode: str,    # "equal" | "eta" | "eta_coherence" | "shrink_to_equal"
    use_phase_align: bool = True,
) -> tuple[np.ndarray, dict]:
    """Modal-level coherent fusion: 3 modal waveforms → 1 final waveform."""
    ...

# --- BPM 估计 ---

def estimate_bpm_from_waveform_multi(
    y: np.ndarray,
    fs: float,
    breath_band: tuple[float, float] = (0.1, 0.35),
) -> dict:
    """Estimate BPM via PSD + ACF + peak-interval. Returns all three + consensus."""
    ...

# --- Per-segment 入口 ---

def estimate_b2_segment(
    multichannel_by_var: dict,
    seg_name: str,
    *,
    phase_method: str = "hilbert",
    weight_mode: str = "coherence_gated",
    modal_weight_mode: str = "equal",
    use_two_level: bool = False,
    use_modal_phase_align: bool = False,
    config: ChFusionConfig | None = None,
    metric_params: BreathMetricParams | None = None,
    f0_from_b1: bool = False,  # use B1 coarse BPM as f0 guide
) -> dict | None:
    """Per-segment B2 estimation entry point."""
    ...

# --- Benchmark & cross-domain ---

def run_b2_benchmark(...) -> dict: ...
def compute_b2_cross_domain(...) -> list[dict]: ...
```

### 6.3 关键复用 API

```python
# 滤波链（完全复用，不做任何修改）
from ble_analysis.chfusion import (
    ChFusionConfig,
    run_multichannel_segment_filtering,
    _energy_ratio,
    _peak_prominence,
    _parabolic_peak_freq,
    _seg_bpm_stats,
    _overall_rel_error,
)

# 滑窗
from ble_analysis.segments import (
    BreathMetricParams,
    FilterParams,
    _sliding_window_indices,
)

# 已有 PCA MRC（A0 路线直接复用）
from ble_analysis.wifi_mrc import (
    mrc_pca_fusion,
    estimate_bpm_from_waveform,
    compute_mrc_weights,
)

# B1 coarse BPM（路线 C 的 f₀ 引导）
from ble_analysis.systematic_fusion import (
    estimate_systematic_fusion_segment,
    per_modal_voting_spectrum,
    modal_fusion_from_spectra,
)

# B1 baseline 数据（跨域对比时直接引用已有结果）
from ble_analysis.voting_fusion import MODAL_VOTING_VARIABLES
```

### 6.4 诊断图表要求

除标准排行榜和跨域汇总图外，B2 需要额外的诊断图：

| 图 | 内容 | 用途 |
|----|------|------|
| `b2_phase_method_ablation.png` | A0/A1/B/C 跨域对比 | Phase 1–3 核心结论 |
| `b2_coherence_heatmap.png` | per-tone coherence γ × window 热力图（每场景）| 诊断哪些 tone/window 的相位对齐可信 |
| `b2_modal_coherence_dist.png` | 三模态两两 γ 直方图 | 判断模态间是否相干 |
| `b2_waveform_example.png` | best/worst/median 窗口的融合前后波形对比 | 可视化波形质量 |
| `b2_weight_mode_ablation.png` | η·ρ vs coherence-gated vs coherence-gated² 对比 | 权重策略贡献 |
| `b2_two_level_ablation.png` | tone-only vs two-level equal vs two-level coherent 对比 | 第二级增益 |
| `b2_vs_b1_per_window.png` | B2 vs B1 per-window BPM scatter | 逐窗行为差异 |

### 6.5 不做的事

- 不修改 `chfusion.py`、`systematic_fusion.py`、`wifi_mrc.py` 等已有模块
- 不修改滤波参数、滑窗参数、呼吸频段
- 不实现 Zhuo 2023 的 PCA-VMD 路线（留作后续独立 plan）
- 不在此 plan 阶段做 B1+B2 hybrid consensus
- 不做 apnea 检测（B2 是 BPM + 波形，非 apnea 方法）

---

## 7. 预期产出

| 产出 | 路径 |
|------|------|
| 可复用模块 | `src/ble_analysis/coherent_mrc.py` |
| 实验脚本 | `notebooks/scripts/chFusion_b2_coherent_mrc.py` |
| 跨域脚本 | `notebooks/scripts/chFusion_b2_coherent_mrc_cross_domain.py` |
| 验证报告 | `docs/reports/b2_coherent_mrc_waveform_fusion_report.md` |
| 数值结果 | `outputs/reports/b2_coherent_mrc_*.npy` |
| 诊断图 | `outputs/figures/b2_coherent_mrc_*.png` |

### 7.1 建议运行命令

```bash
# 单场景
python notebooks/scripts/chFusion_b2_coherent_mrc.py --scenario cs_091339
python notebooks/scripts/chFusion_b2_coherent_mrc.py --scenario cs_095806
python notebooks/scripts/chFusion_b2_coherent_mrc.py --scenario cs_102621

# 跨域汇总
python notebooks/scripts/chFusion_b2_coherent_mrc_cross_domain.py
```

---

## 8. 风险与保留问题

### 8.1 算法风险

| ID | 风险 | 缓解措施 |
|----|------|----------|
| R1 | Hilbert 连续相位旋转可能改变非正弦波形形态 | 报告 PSD BPM（对相位不敏感）作为主指标，波形仅作辅助诊断 |
| R2 | Coherence gating 阈值（γ < 0.2）可能过于激进，在低 SNR 窗口排除大部分 tone | 对比硬门控 vs 软降权 vs 无门控 |
| R3 | 20 s 窗口内呼吸周期仅 ~2–4 个（0.1–0.35 Hz），相位估计可能不稳定 | 对比 Hilbert（时域）vs FFT（频域），看哪种更稳定 |
| R4 | B1 提供的 f₀ 如果已有偏置，FFT 互谱相位会被系统性带偏 | 同时报告 B2 独立运行版本（路线 B，不需 f₀） |
| R5 | 三模态间可能天然不相干（remote/local/phase 对呼吸的响应函数不同） | 画 modal 间 γ 分布；如果整体偏低（median < 0.5），第二级仅做等权不做相位对齐 |
| R6 | 091339 场景复杂多径可能使 tone 间 γ 整体偏低，B2 在此场景退化 | 分场景报告 γ 分布，若 091339 γ 显著低于其他场景，标记为场景限制 |

### 8.2 数据与评估风险

| ID | 风险 | 缓解措施 |
|----|------|----------|
| R7 | 新方法在特定场景过拟合 | 三场景交叉验证，跨域 mean 为主指标 |
| R8 | coherence-gated 权重引入了额外超参数（min_coherence） | 固定 min_coherence=0.2，不做 per-scenario 调参 |
| R9 | `[待确认]` tone 间相位偏移在 20 s 窗口内是否近似稳定 | 诊断图：滑动子窗 coherence 时间序列 |

### 8.3 需要执行后确认的问题

| ID | 问题 | 确认方式 |
|----|------|----------|
| Q1 | 连续相位补偿（B）是否显著优于仅符号校正（A0/A1）？ | Phase 2 跨域对比 |
| Q2 | Coherence gating 是否有正向贡献？ | B vs Bγ 对比 |
| Q3 | FFT 互谱（C）是否比 Hilbert（B）更稳定？ | Phase 3 跨域对比 |
| Q4 | 两层级联（D）是否优于单级 tone-level？ | D vs Bγ 对比 |
| Q5 | Modal 级相位对齐是否有增益（D vs D-eq）？ | D vs D-eq 对比 |
| Q6 | B2 最优变体能否 ≤ B1 8.45%？ | 跨域 leaderboard |
| Q7 | 091339 上 B2 是否有灾难性退化（>20%）？ | 分场景报告 |
| Q8 | 融合波形的 η 是否高于单 tone？ | per-window η 对比 |

---

## 9. 验证状态

| 字段 | 内容 |
|------|------|
| **验证状态** | 已完成（Review 2026-06-23：挂起——BPM 不推荐部署，波形路线保留供未来真人验证） |
| **实际脚本** | `notebooks/scripts/chFusion_b2_coherent_mrc.py`、`chFusion_b2_coherent_mrc_cross_domain.py` |
| **实际模块** | `src/ble_analysis/coherent_mrc.py` |
| **数值结果** | `outputs/reports/b2_coherent_mrc_all_results.npy` |
| **图表** | `outputs/figures/b2_coherent_mrc_leaderboard.png` 等 |
| **报告链接** | `docs/reports/b2_coherent_mrc_waveform_fusion_report.md` |
| **一句话结论** | B2-D 跨域 9.43% 为 B2 最优，全面优于 WiFi MRC（10.78%）但未超越 B1（8.45%）；BPM 不推荐部署，波形输出保留 |

结论摘要：
- Phase 1：A1 corr sign（11.06%）优于 A0 PCA sign（12.33%）
- Phase 2：Hilbert 连续相位（B 10.91%）略优于 A1；coherence gating（Bγ）几乎无增益
- Phase 3：FFT 互谱 + B1 f₀（C 9.50%）优于 B
- Phase 4：两级 Hilbert-MRC（D 9.43%）为 B2 全局最优，modal Hilbert 相位对齐 −1.46 pp（占 A0→D 总提升 ~50%）

遗留问题：
- 091339 tone 间 γ 分布诊断（coherence 热力图）未生成
- B2 融合波形 η vs 单 tone 对比未输出
- B2 挂起保留供未来真人场景波形验证
- 后续可探索：B1+B2 per-window 动态选择器（B2 在 095806 5.82% 优于 B1 6.50%，存在互补性）

### 保留问题

| ID | 问题 | 备注 |
|----|------|------|
| Q1 | tone 间呼吸相位偏移在 20 s 窗口内是否稳定？ | `[待确认]` — 若不稳定，Hilbert 相位估计的物理基础动摇 |
| Q2 | BLE CS ~2 Hz 采样率下 Hilbert 变换的边界效应是否可接受？ | `[待确认]` — 可用 padding 缓解 |
| Q3 | 三模态呼吸波形的响应函数是否同构？ | `[待确认]` — 若异构，模态间相位对齐失去物理意义 |

---

## 10. 给执行 Agent 的首条指令

请在 Cursor Composer 中启用 `BLE CS 执行 Agent`，并严格执行：

`docs/plans/b2_coherent_mrc_waveform_fusion_plan.md`

**执行顺序**（按 Phase 递进，每 Phase 完成后先评估结果再进入下一 Phase）：

1. **Phase 1**：实现 A0（复用 `mrc_pca_fusion()`）和 A1（新增 corr sign），仅 η·ρ 权重，三模态等权融合，三场景评估 → 确定最优符号校正路线
2. **Phase 2**：实现路线 B（Hilbert 连续相位）+ 对比 B vs Bγ（coherence gating），与 A_best 对比 → 回答"连续相位是否有增益"
3. **Phase 3**：实现路线 C（FFT 互谱 + B1 coarse f₀），与 B 对比
4. **Phase 4**：实现两层级联 D 和 D-eq，与单级最优对比

每 Phase 完成后，请返回以下材料给 Claude/DeepSeek Review：

- 对应 plan 和本 Phase 的部分结果
- `outputs/reports/b2_coherent_mrc_phase{N}_*.npy`
- `outputs/figures/b2_coherent_mrc_phase{N}_*.png`
- 关键脚本路径
- git commit message 或 git diff 摘要

全部 Phase 完成后撰写完整 `docs/reports/b2_coherent_mrc_waveform_fusion_report.md`，更新本 plan §9 验证状态，并准备阶段性 git commit。

Review 完成后，若结论改变方法推荐/废弃状态，Claude/DeepSeek 负责更新 `docs/methods/README.md`。
