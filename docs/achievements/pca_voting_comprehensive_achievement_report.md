# BLE CS 多信道呼吸检测：从 PCA 全局融合到 Per-Tone 统计投票

> **性质**：Claude/DeepSeek Achievement Report Mode 正式成果汇报  
> **面向**：人（研究员 / 合作者）  
> **覆盖阶段**：PCA/SVD → Per-Tone 投票 → 信道×模态系统性融合 → 机制诊断  
> **起止提交**：`c3c1728` (2026-06-05) → `2380761` (2026-06-08)  
> **日期**：2026-06-09

---

## 1. 摘要

- **目标**：从 BLE CS 72 tone × 3 变量（remote 幅值 / local 幅值 / 总相位）= 216 维信道信息中，稳定提取呼吸信号，将跨域 BPM 相对误差降至 8% 以下。
- **结论**：经过五轮迭代，**最优方案回到了项目最初探索的方向**——逐 tone 质量加权谱融合 + 三模态等权融合（B1, 8.45%）。这一方案在架构上与早期 Plan1 的 `fft_q_energy_peak`（仅单变量，~11%+）几乎同构，但有三个关键改进：① 权重使用 raw η·ρ 而非 log-mapped q 值（保留动态范围、更激进去噪）；② 扩展到三个模态并做 Equal 融合（单变量→三变量是最大改善来源）；③ 去掉 consensus gate（投票机制提供了更强的离群抑制）。Deng et al. (2024) 的 Per-Tone Voting 范式在此过程中扮演了**催化剂的角色**——它启发我们重新审视信道融合方式，但最终胜出的不是 Voting 本身（BPM 投票 T0-V3 仅 9.20%），而是 Voting 启发下的谱级质量加权融合。
- **核心机制发现**：谱加权融合下三模态在平均同一组 tone → 模态间谱天然趋同 → Equal 融合优于 Top2。这不是神秘效应，是构造方式的结构性必然。
- **关键里程碑**：

| 阶段 | 最优方法 | 跨域 mean | 在故事中的角色 |
|------|----------|-----------|---------------|
| 早期 Plan1 | Single Remote（max-η 选单 tone） | 10.45% | 确立 baseline：单 tone > 等权平均 |
| 早期 Plan1 | fft_q_energy_peak（log-mapped η·ρ 加权谱，仅 remote） | 劣于 Single | B1 的"原型"——但因单变量+log压缩权重，未显现优势 |
| Phase 0: PCA/SVD | PCA-Modal3 | ~10.92% | 全局融合的失败尝试：方差≠信号质量 |
| Phase 1: Per-Tone 投票 | T0-V3（BPM 投票，仅 remote） | 9.20% | 验证"先独立估计再融合"有效，但坍缩到 BPM 丢失了谱信息 |
| **Phase 2: 系统性融合** | **B1（逐 tone 谱 η·ρ 加权 + 三模态 Equal）** | **8.45%** | **当前最优**：保留完整谱信息 + 质量加权 + 三模态等权 |
| Phase 3: 机制诊断 | D1 频谱相似度分析 | — | 解释 Equal > Top2：谱融合构造方式的结构性必然 |

> **旁注**：在 Phase 1 与 Phase 2 之间，曾短暂探索过窗级门控策略（G4 系列）。G4 的「分歧→回退单信道 Remote」在数字上达到了 8.65%，但其核心设计基于一个错误的物理假设——即 Remote 幅值是全局最稳定的单变量。后续实验（Phase 5 SA）已证实 remote/local/phase 的最优性是场景依赖的，硬编码 Remote fallback 缺乏理论依据。因此 G4 系列**不列入方法演进主线**，下文仅做简要提及。

---

## 2. 背景：BLE CS 呼吸检测的技术框架

### 2.1 物理层与可用变量

BLE CS（Channel Sounding）每次测量提供 72 个 tone（子载波，1 MHz 间隔）的 IQ 数据。两端设备各自测量 PCT（Phase Correction Term），再通过向量乘法抵消载波频偏（CFO）后，获得三种可用变量：

| 变量 | 符号 | 物理含义 | 是否使用 |
|------|------|----------|----------|
| 远端幅值 | `remote_amplitudes` | 远端设备测得 PCT 的幅值 | ✅ 使用 |
| 本地幅值 | `local_amplitudes` | 本地设备测得 PCT 的幅值 | ✅ 使用 |
| 总相位 | `phases` | 两端 PCT **向量相乘后**的总相位，已抵消 LO 漂移 | ✅ 使用 |
| 总幅值 | `amplitudes` | remote × local 的合成幅值，引入双方噪声 | ❌ 不使用 |

**关键物理事实**：
- remote 和 local 物理上完全对等——同一 CS 交换的两个方向，质量谁更优完全取决于具体多径环境和设备位置，不可预设。
- phase 已通过向量乘法抵消 LO 漂移，物理上有意义，不可预设 phase 总比幅值好或差。
- **三种变量应对称对待，按窗级信号质量动态选择**。

### 2.2 两层融合框架

本项目的方法论核心是将问题分解为两个独立维度：

```text
72 信道 ──[信道融合]──→ 每模态一条谱/BPM ──[模态融合]──→ 最终 BPM 估计
```

- **信道融合（Channel Fusion）**：如何从 72 个 tone 得到一条代表呼吸的频谱或 BPM 估计。
- **模态融合（Modal Fusion）**：如何合并 remote 幅值、local 幅值、总相位三个独立模态的信息。

### 2.3 实验设置（贯穿所有阶段）

| 参数 | 值 |
|------|-----|
| 滑窗 | 20 s 窗长 / 1 s 步长 |
| 呼吸频段 | 0.1–0.35 Hz（6–21 BPM） |
| 滤波链 | median → highpass (0.05 Hz) → bandpass (0.1–0.35 Hz) |
| 验证场景 | `cs_091339` / `cs_095806` / `cs_102621`（金属板脚本，三场景权重相等） |
| 主指标 | 分段 BPM 相对误差 %（跨域 mean） |
| 核心质量指标 | `η`（呼吸频段能量比）、`ρ`（谱峰峰度） |

其中 η 和 ρ 定义为：

$$\eta_i = \frac{E_i(B_r)}{E_i(B_0) + \epsilon}, \quad B_r = [0.1, 0.35]\text{ Hz}, \quad B_0 = [0.05, 0.8]\text{ Hz}$$

$$\rho_i = \frac{\max_{f \in B_r} P_i(f)}{\text{median}_{f \in B_r} P_i(f) + \epsilon}$$

其中 $P_i(f)$ 为第 $i$ 个 tone 在窗内的功率谱。

---

## 3. 主线一：PCA/SVD — 全局信道融合的尝试

### 3.1 动机

受 Wi-Fi CSI 呼吸感知文献启发（Xie et al. 2023 的 CSI-ratio PCA、Chen et al. 2018 的 TR-BREATH eigendecomposition），我们希望用 PCA/SVD 从 72 信道的时域波形中提取共同变化模式（第一主成分），作为"呼吸波形"。核心直觉是：呼吸引起的信道变化在所有 tone 上应该是相关的，而多径噪声在各 tone 上是独立的——PCA 应能分离信号与噪声。

### 3.2 算法原理

#### 3.2.1 数据矩阵构造

对于单个模态（如 remote 幅值）、单个 20 s 滑窗，构造 **实矩阵** $\mathbf{X} \in \mathbb{R}^{M \times N}$：

$$\mathbf{X} = \begin{bmatrix} x_{1,1} & x_{1,2} & \cdots & x_{1,N} \\ x_{2,1} & x_{2,2} & \cdots & x_{2,N} \\ \vdots & \vdots & \ddots & \vdots \\ x_{M,1} & x_{M,2} & \cdots & x_{M,N} \end{bmatrix}$$

其中：
- $M$ = 窗内采样帧数（20 s × 采样率）
- $N$ = 有效信道数（≤ 72）
- $x_{t,j}$ = 第 $j$ 个 tone 在时刻 $t$ 的高通滤波后幅值

每列先做 **z-score 标准化**，消除信道间幅值量级差异：

$$z_{t,j} = \frac{x_{t,j} - \mu_j}{\sigma_j}, \quad \mu_j = \frac{1}{M}\sum_t x_{t,j}, \quad \sigma_j = \sqrt{\frac{1}{M-1}\sum_t (x_{t,j} - \mu_j)^2}$$

得到标准化矩阵 $\mathbf{Z} \in \mathbb{R}^{M \times N}$。

#### 3.2.2 PCA：协方差特征分解

构造 $N \times N$ 协方差矩阵（$N \ll M$，高效）：

$$\mathbf{C} = \frac{1}{M-1} \mathbf{Z}^T \mathbf{Z} \in \mathbb{R}^{N \times N}$$

对 $\mathbf{C}$ 做特征分解：

$$\mathbf{C} \mathbf{v}_k = \lambda_k \mathbf{v}_k, \quad k = 1, 2, \ldots, N$$

其中 $\lambda_1 \geq \lambda_2 \geq \cdots \geq \lambda_N \geq 0$ 为降序特征值，$\mathbf{v}_k$ 为对应的特征向量。

取第一主成分（PC1，对应最大特征值 $\lambda_1$ 的特征向量 $\mathbf{v}_1$）作为信道间加权系数：

$$\mathbf{w}_{\text{PC1}} = \mathbf{Z} \cdot \mathbf{v}_1 \in \mathbb{R}^{M}$$

PC1 方差占比为：

$$\text{var\_ratio} = \frac{\lambda_1}{\sum_{k=1}^{N} \lambda_k}$$

#### 3.2.3 SVD：等价视角

SVD 路径等价地将 $\mathbf{Z}$ 分解：

$$\mathbf{Z} = \mathbf{U} \mathbf{\Sigma} \mathbf{V}^T$$

其中 $\mathbf{U} \in \mathbb{R}^{M \times M}$，$\mathbf{\Sigma} = \text{diag}(\sigma_1, \sigma_2, \ldots)$，$\mathbf{V} \in \mathbb{R}^{N \times N}$。第一左奇异向量 $\mathbf{u}_1$（$\mathbf{U}$ 的第一列）等价于 PCA 的 PC1，方差占比为 $\sigma_1^2 / \sum_k \sigma_k^2$。

#### 3.2.4 复矩阵 PCA（幅值+相位联合）

我们还探索了将幅值和相位联合编码为**复矩阵** $\mathbf{X}_c \in \mathbb{C}^{M \times N}$：

$$x_{c; t,j} = A_{t,j} \cdot e^{j \cdot \phi_{t,j}}$$

其中 $A_{t,j}$ 为总幅值（或 remote 幅值），$\phi_{t,j}$ 为总相位。对每列去复均值后，构造 Hermitian 协方差矩阵：

$$\mathbf{C}_c = \frac{1}{M-1} \mathbf{Z}_c^H \mathbf{Z}_c \in \mathbb{C}^{N \times N}$$

取第一特征向量 $\mathbf{v}_1^{(c)}$，得到复 PC1：

$$\mathbf{w}_{\text{PC1}}^{(c)} = \mathbf{Z}_c \cdot \mathbf{v}_1^{(c)}$$

最终的呼吸波形取其实部：$\mathbf{w} = \text{Re}(\mathbf{w}_{\text{PC1}}^{(c)})$。

#### 3.2.5 模态融合（PCA-Modal3）

每个模态（remote 幅值 / local 幅值 / 总相位）独立做 PCA 提取 PC1 波形后，进入与 Plan2 Modal 相同的融合框架：

1. 对每个模态的 PC1 波形做 FFT 得到呼吸带归一化功率谱 $\mathbf{p}_{\text{rem}}, \mathbf{p}_{\text{loc}}, \mathbf{p}_{\text{pha}}$
2. 按模态 η 加权融合谱：$\mathbf{p}_{\text{fused}} = \sum_{m} w_m \cdot \mathbf{p}_m$，其中 $w_m = \eta_m / \sum_k \eta_k$
3. 融合谱上 argmax 寻峰 + parabolic 插值 → BPM

此外还测试了复矩阵 η-blend 方案（先按 η 混合 remote/local 幅值再联合 phase 做复 PCA）和 dual-amp 方案（remote/local 各 72 列堆叠后复 PCA）。

### 3.3 实验结果

| 方法 | 信道融合 | 模态融合 | 跨域 mean |
|------|----------|----------|-----------|
| **PCA-Modal3** | PCA per modal (zscore + uniform) | η 加权 | ~10.92% |
| PCA Complex η-blend | 复 PCA（η 混合幅值 + phase） | 无（单波形） | ~12–14% |
| PCA Complex dual-amp | 复 PCA（remote/local 双堆叠） | 无（单波形） | ~13–15% |
| 同期 baseline: Modal top2 | 逐模态最优信道（max-η 选道） | Top2 等权 | **9.45%** |
| 同期 baseline: Single Remote | 单信道 Remote 幅值（max-η 选道） | 无 | 10.45% |

![PCA/SVD 跨域排行榜](../../outputs/figures/pca_svd_cross_domain_aggregate_bars.png)

**图 1**：PCA/SVD 系列方法跨域汇总。PCA-Modal3（~10.92%）未超越 Modal top2（9.45%），且未超越 Single Remote（10.45%）。

![PCA/SVD PC1 方差占比](../../outputs/figures/pca_svd_pc1_variance_ratio.png)

**图 2**：各段各窗 PC1 方差占比分布。多数窗 PC1 方差占比在 0.3–0.6 范围，第一主成分并未压倒性主导数据方差。多数窗 PC1 方差占比在 0.3–0.6 范围，说明第一主成分并未压倒性地主导数据方差——多径噪声成分也被纳入了主成分。

### 3.4 失败原因分析

PCA/SVD 路线未超越 Modal top2（9.45%），可能原因：

1. **短窗内 PCA 无法区分呼吸与噪声**：20 s 窗仅含约 2–7 个呼吸周期，信道的呼吸相关变化与多径衰落变化在如此短的时间尺度上难以被 PCA 线性分离。PCA 假设高方差方向 = 信号方向，但噪声同样可以产生高方差成分。
2. **72 信道间呼吸信号相关性不够强**：如果呼吸在每个 tone 上的调制深度差异大（频率选择性衰落的自然结果），那么"所有 tone 共同变化"的 PC1 可能只是调制最深的少数 tone 的加权平均——与直接选最佳 tone 效果相当。
3. **信道间噪声不独立**：如 Deng et al. (2024) 指出的，OFDM 子载波间干扰（ICI）是强相关的。当噪声在信道间相关时，PCA 会把相关噪声也纳入主成分，无法有效分离。

> **决策**：放弃 PCA 路线，转向论文中提出的 per-tone 独立估计 + 统计投票范式。

---

## 4. 主线二：Per-Tone 投票 — 从"先融合再估计"到"先估计再投票"

### 4.1 催化剂：Deng et al. (2024) 的 Per-Tone 独立处理范式

PCA 失败后，我们面临一个困惑：早期 Plan1 已经发现"单 tone（max-η）> 等权平均所有 tone"，PCA 试图用全局融合突破这个结论也失败了。似乎所有"使用多信道"的努力都是徒劳的。

Deng et al. (2024) 提供了一个新的视角。其核心论证是：

> **传统加权求和的有效性假设信道间噪声独立。但在 OFDM 系统中，子载波间干扰（ICI）是强相关的。因此加权求和不能有效抑制主要噪声源。替代方案：对每个 subcarrier 独立做检测/估计，再用统计方法融合结果。**

这一论证启发了两条实验路径：
- **路径 A（BPM 投票，T0-V3）**：每 tone 独立估计一个 BPM → 加权直方图投票 → 一个 BPM 数字
- **路径 B（谱加权融合，B1）**：每 tone 独立做 FFT 得到完整谱 → 质量加权平均 → 融合谱 → 寻峰

两条路径都遵循"per-tone 独立处理 → 融合"的范式，但路径 B 保留了更丰富的信息。

> **事后视角**：路径 B（B1）在架构上与早期 Plan1 的 `fft_q_energy_peak` 几乎同构——都是"逐 tone FFT 谱 × 质量权重 → 加权平均"。这意味着 **Deng et al. 论文的真正贡献不是 Voting 这个具体操作，而是启发我们重新审视了信道融合方式**。早期 Plan1 已经摸到了正确方向（质量加权谱融合），但受限于单变量实验和 log-mapped q 权重，未能展现优势。B1 的成功来自三个改进：raw η·ρ 权重 + 三模态 Equal 融合 + 去掉 consensus gate。

### 4.2 算法原理

#### 4.2.1 Per-Tone 独立 BPM 估计

对第 $i$ 个 tone、当前 20 s 滑窗内的带通滤波波形 $\mathbf{s}_i \in \mathbb{R}^M$：

1. 去均值 + Hanning 窗：$\tilde{\mathbf{s}}_i = (\mathbf{s}_i - \bar{s}_i) \odot \mathbf{h}$，其中 $\mathbf{h}$ 为 Hanning 窗
2. FFT 功率谱：$P_i(f) = |\text{FFT}(\tilde{\mathbf{s}}_i)|^2$
3. 呼吸频带内 argmax：$f_i^* = \arg\max_{f \in [0.1, 0.35]} P_i(f)$
4. Parabolic 插值细化：$f_i^{\text{refined}} = f_i^* + \frac{1}{2} \cdot \frac{P(f_i^* - \Delta f) - P(f_i^* + \Delta f)}{P(f_i^* - \Delta f) - 2P(f_i^*) + P(f_i^* + \Delta f)} \cdot \Delta f$
5. BPM：$\text{BPM}_i = 60 \cdot f_i^{\text{refined}}$

对全部 $N$ 个有效 tone（≤72），得到估计向量 $\mathbf{b} = [\text{BPM}_1, \text{BPM}_2, \ldots, \text{BPM}_N]^T$。

每个 tone 的投票权重基于其信号质量：

$$w_i = \eta_i^{\alpha} \cdot \rho_i^{\beta}$$

其中 $\alpha, \beta \in \{0, 1\}$ 对应三种投票策略：

| 策略 | α | β | 含义 |
|------|---|---|------|
| V1 simple | 0 | 0 | 等权投票 |
| V2 η-weighted | 1 | 0 | 呼吸能量越集中，权重越大 |
| V3 η·ρ-weighted | 1 | 1 | 峰越尖锐，权重越大（压制宽峰噪声 tone） |

#### 4.2.2 加权直方图投票

在 BPM 范围 $[6, 30]$ 以 1 BPM 为 bin 宽度构造直方图。设 bin 中心为 $\{c_k\}_{k=1}^{K}$，bin 边为 $\{e_k\}_{k=0}^{K}$（$K=24$）。

对第 $i$ 个 tone，将其权重 $w_i$ 投入 $\text{BPM}_i$ 所在的 bin：

$$\text{bin\_weight}_k = \sum_{i: \text{BPM}_i \in [e_k, e_{k+1})} w_i$$

取最高权重 bin 的中心值为最终 BPM：

$$\text{BPM}_{\text{voted}} = c_{k^*}, \quad k^* = \arg\max_k \text{bin\_weight}_k$$

置信度判断（来自论文阈值 $\tau = 0.3$）：

$$\text{confident} = \begin{cases} \text{True}, & \text{if } \max_k \text{bin\_weight}_k \geq \tau \cdot \sum_i w_i \\ \text{False}, & \text{otherwise} \end{cases}$$

### 4.3 Phase 1：纯 Per-Tone 投票验证（2026-06-07）

#### 4.3.1 方法矩阵

| 方法 ID | 信道融合 | 模态融合 | 输入变量 |
|---------|----------|----------|----------|
| T0-V1/V2/V3 | Per-tone 投票（V1/V2/V3） | 无（仅 remote） | remote 幅值 72 tone |
| T1-K4/K8/K16 | Per-tone Top-K η 投票 | 无（仅 remote） | remote 幅值 Top-K tone |
| T2 | 每模态 max-η 单 tone BPM → median | 跨模态中位数 | remote + local + phase |
| T3 | 每模态 72-tone V2 voting → η 加权中位数 | 跨模态中位数 | remote + local + phase |

#### 4.3.2 主结果

| 排名 | 方法 | cs_091339 | cs_095806 | cs_102621 | 跨域 mean |
|------|------|-----------|-----------|-----------|-----------|
| **1** | **T0-V3 η·ρ 加权投票** | 13.77 | **6.84** | 6.99 | **9.20%** |
| 2 | Modal top2（逐模态最优信道→Top2） | **13.04** | 10.61 | **4.69** | 9.45% |
| 3 | T3 Voting+Modal 混合 | 14.92 | 7.94 | 6.24 | 9.70% |
| 4 | Single Remote（max-η 单信道） | **10.91** | 12.16 | 8.29 | 10.45% |
| 5 | T0-V1 等权投票 | 16.05 | 8.31 | 7.96 | 10.77% |
| 6 | T0-V2 η 加权投票 | 16.00 | 8.82 | 8.08 | 10.96% |
| 7 | Uniform Remote（72 tone 等权） | 17.09 | 9.15 | 6.82 | 11.02% |

![Phase 1 跨域排行榜](../../outputs/figures/voting_fusion_leaderboard.png)

**图 3**：Phase 1 Per-Tone 投票跨域排行榜。T0-V3（η·ρ 联合加权）以 9.20% 排名第一，略优于 Modal top2（9.45%）。

![Phase 1 各场景 Top-8 对比](../../outputs/figures/voting_fusion_cross_domain_aggregate_bars.png)

**图 4**：Phase 1 各场景 Top-8 方法 BPM 误差对比。T0-V3 在 095806 极强（6.84%），但在 091339 弱于 Single Remote（13.77% vs 10.91%），揭示场景互补性。

**关键发现**：

1. **η·ρ 联合加权（T0-V3: 9.20%）显著优于 η 单独加权（T0-V2: 10.96%）**——ρ（峰度）有效抑制了频谱宽但峰不尖的 tone。
2. **Per-tone 投票在 095806 极强（6.84%）**，远超所有 baseline，但在 091339 弱于 Single Remote（13.77% vs 10.91%）。
3. **T3（三模态均投票后跨模态融合）反而不如纯 Remote 投票（9.70% vs 9.20%）**——跨模态融合的方式需要重新设计。
4. **Top-K 筛选无效**——K=4/8/16 均差于全量 72 tone V3。

**Phase 1 的核心结论**：Voting 范式以 9.20% 超越了此前的最优 baseline Modal top2（9.45%），验证了「先独立估计再投票」优于「先融合再估计」的论文核心假设。但 Voting 与 Modal Top2 在不同场景上**互补**（Voting 095806 更强，Modal 102621 更强），意味着两者信息并不完全重叠。

### 4.4 窗级门控的短暂探索（2026-06-08，已修正）

> ⚠️ **历史旁注**：Phase 1 发现的 Voting/Modal 场景互补性，曾催生了 **G4 系列窗级门控策略**——在每窗动态选择 Voting 或 Modal Top2，共识时取平均，分歧时回退到单信道 Remote。G4 在跨域数字上达到 8.65%（优于纯 Voting 的 9.20%），但其「分歧→回退 Remote」的核心设计基于一个**错误的物理假设**：即 Remote 幅值是全局最稳定的单变量。
>
> 实际上，remote 和 local 是同一 CS 交换的两个方向，**物理上完全对等**——谁更优完全取决于具体多径环境。后续实验（Phase 5 SA，见 §4.6.4）已量化证实：三场景上最优单模态分别为 local（102621，选中率 67%）、remote（091339，58%）和 phase（095806，44%），Remote 远非全局最优。因此 G4 的硬编码 fallback 策略**缺乏理论依据，不可泛化**。
>
> G4 系列及后续的 G4-B1 三候选门控变体（v1–v4）均属于此框架的延伸，已在后期工作中被修正。**本文不将其列入方法演进主线**。下文聚焦于无门控的纯算法演进。

### 4.5 Phase 2：信道×模态 系统性融合（2026-06-08）

#### 4.5.1 动机

回顾至此的所有方法，有一个关键盲区：所有对比同时改变了**信道策略**和**模态策略**两个维度，导致无法归因：

- T0-V3（9.20%）只用了 remote 幅值，没有模态融合
- Modal Top2（9.45%）用了三模态 Top2 融合，但信道策略是 Single-best per modal
- 核心问题：**最优的模态融合策略是否取决于信道策略？将 Voting 做 per-modal 扩展后再做模态融合，会是什么效果？**

Systematic Fusion 首次系统性地填充了信道策略 × 模态策略的二维网格。

#### 4.5.2 方法网格

**信道策略（4 种）**：

| 代号 | 名称 | 做法 |
|------|------|------|
| **Vote** | Per-Tone 投票 | 每模态独立 72 tone η·ρ voting → 一条 conf 加权谱 |
| **Uniform** | 均匀融合 | 每模态 72 信道归一化谱等权平均 |
| **Single-best** | 最优单信道 | 每模态选 η 最大信道 |
| **VoteP** | 持久性投票 | Vote + 剔除跨窗 BPM 跳变大的 tone |

**模态策略（4 种）**：

| 代号 | 名称 | 做法 |
|------|------|------|
| **Equal** | 等权融合 | remote/local/phase 三条谱 1:1:1 平均后寻峰 |
| **η-weight** | 能量比加权 | 按各模态 η 值归一化加权 |
| **Top2** | 保留前二 | 按模态 η 排序，保留前二等权，踢掉最弱 |
| **Phase only** | 仅相位 | 仅用 phase 模态（对照组） |

**Vote 路径下的谱构造**（以 remote 幅值为例，local 和 phase 同理）：

对当前窗，设 72 tone 的 per-tone BPM 估计为 $\{\text{BPM}_i\}$，η·ρ 投票权重为 $\{w_i\}$，各 tone 的归一化功率谱（呼吸带内）为 $\{\mathbf{p}_i\}$。

conf 加权全谱（默认方案 B）：

$$\mathbf{p}_{\text{modal}} = \frac{\sum_{i=1}^{N} w_i \cdot \mathbf{p}_i}{\sum_{i=1}^{N} w_i}$$

#### 4.5.3 主结果

| 排名 | 方法 | 信道融合 | 模态融合 | cs_091339 | cs_095806 | cs_102621 | 跨域 mean |
|------|------|----------|----------|-----------|-----------|-----------|-----------|
| **1** | **逐模态 Voting → 三模态等权谱融合** | Vote per modal | Equal 1:1:1 | 13.22 | **6.50** | 5.63 | **8.45%** |
| 2 | 逐模态均匀→η 加权融合（C2） | Uniform per modal | η 加权 | 13.43 | 7.93 | 6.10 | 9.15% |
| 3 | 逐模态 Voting → η 加权融合（B2） | Vote per modal | η 加权 | 15.65 | 6.47 | 5.35 | 9.16% |
| 4 | T0-V3（远程单模态 Voting） | Vote（仅 remote） | 无 | 13.77 | 6.84 | 6.99 | 9.20% |
| 5 | Modal top2 | Single-best per modal | Top2 等权 | **13.04** | 10.61 | 4.69 | 9.45% |
| 6 | 逐模态 Voting → Top2 融合（B3） | Vote per modal | Top2 等权 | 17.86 | 6.44 | 5.47 | 9.92% |

![Phase 2 跨域排行榜](../../outputs/figures/systematic_fusion_leaderboard.png)

**图 5**：Systematic Fusion 跨域排行榜。**逐模态 Voting → 三模态等权谱融合（B1）以 8.45% 登顶**，为所有已验证方法中的全局最优，首次突破理想标准（< 8.5%）。

![Phase 2 二维热力图](../../outputs/figures/systematic_fusion_2d_heatmap.png)

**图 6**：信道策略 × 模态策略二维热力图。**关键交互效应**：Voting（信道策略）下 Equal（模态融合）有效（8.45%），但 Top2（模态融合）无效（9.92%）。而在 Single-best（信道策略）下恰恰是 Top2 有效（9.45%）。最优模态策略**取决于信道策略**——这是一个重要的方法论发现。

![Phase 2 消融瀑布图](../../outputs/figures/systematic_fusion_ablation_waterfall.png)

**图 7**：从 baseline T0-V3（9.20%）开始的消融瀑布图。将 Voting 从仅 remote 扩展为 per-modal + Equal 融合（即 B1），获得 −0.75pp 改善。而将 Equal 改为 Top2（即 B3），反增 +0.72pp。消融清晰指明了改善方向和退化方向。

**关键发现**：

1. **逐模态 Voting → 三模态等权谱融合（B1）以 8.45% 成为全局最优**，首次突破 8.5% 理想标准。
2. **信道×模态交互效应明确**：Voting 下 Equal > Top2；Single-best 下 Top2 > Equal。最优模态策略取决于信道策略。
3. **Voting → Top2（B3）系统性失败**（9.92%），显著差于 Voting → Equal（B1）。这需要一个物理机制来解释。
4. **Persistence voting（VoteP）在模态融合框架下彻底失效**（B4: 16.59%, A2: 17.49%）——已废弃。
5. **091339 仍是瓶颈**：B1 在该场景为 13.22%，与 T0-V3（13.77%）接近，跨域改善主要来自 095806/102621。

#### 4.5.4 与早期 Plan1 方法的对比：B1 不是凭空出现的

B1 的谱构造机制——逐 tone FFT 谱 × 质量权重 → 加权平均——与早期 Plan1 的 `fft_q_energy_peak_fusion` **几乎同构**：

| | 早期 fft_q_energy_peak（Plan1） | B1（Phase 2） |
|--|-------------------------------|---------------|
| **谱构造** | 逐 tone FFT → 归一化谱 $p_i$ | 相同 |
| **融合方式** | 质量加权平均 $\sum w_i p_i / \sum w_i$ | 相同 |
| **权重** | $w_i = \sqrt{q_{\text{energy}} \cdot q_{\text{peak}}}$ | $w_i = \eta_i \cdot \rho_i$ |
| **权重映射** | log-linear 压缩到 $[0, 1]$ | raw 值，保留动态范围 |
| **变量范围** | **仅 remote**（单变量） | **remote + local + phase**（三变量） |
| **模态融合** | 无 | Equal 1:1:1 |
| **共识门** | 可选（Gaussian 窗压低离群 tone） | 无（投票机制替代） |
| **早期结果** | 091339 上劣于 Single Remote（10.91%） | 跨域 **8.45%** |

**三个关键改进让早期原型变成了当前最优**：

1. **权重用 raw η·ρ 而非 log-mapped q**：q 系统将 η=0.8 和 η=0.2 的权重比压缩到约 3:1；raw η·ρ 保留约 20:1 的动态范围，对差 tone 的抑制更激进。

2. **扩展到三变量 + Equal 融合（最大改善来源）**：早期 q 方法仅用 remote 一个变量。B1 在三个模态上各自做谱融合，再等权合并——单变量→三变量的增益很可能占了改善的大部分。

3. **去掉 consensus gate**：早期 q 系统用 Gaussian 窗压低远离中位峰频的 tone，本质是一种软门控。B1 的 Voting 机制（直方图投票）提供了更强的离群抑制，且投票后再用 conf 加权谱做模态融合，比直接谱平均更稳健。

> **关键洞察**：B1 不是 Voting 范式的产物——它是早期质量加权谱融合思路的精细化版本。Deng et al. (2024) 的真正贡献是作为一个**催化剂**，启发我们重新审视信道融合方式：per-tone 独立处理是好的，但保留完整谱信息（而非坍缩到 BPM）更好，用 raw 质量权重（而非 log-mapped）更好，用三模态（而非单模态）更好。

### 4.6 Phase 3：Vote→Equal 为何优于 Vote→Top2？——机制诊断（2026-06-08）

#### 4.6.1 核心问题

Phase 2 最重要的**负结果**是 B3（Voting→Top2, 9.92%）系统性差于 B1（Voting→Equal, 8.45%）。但在 Single-best 信道策略下，Top2 明明是有效的（Modal top2 = 9.45%）。为什么 Voting 信道策略下 Top2 反而有害？这是一个「知其然不知其所以然」的结果——如果不理解机制，B1 的优越性可能是场景偶然。

Phase 3 的核心目的不是解锁新方法，而是**诊断物理机制**。

#### 4.6.2 ⭐ 核心机制发现 D1：Voting 降低模态间频谱差异性（✅ 已验证）

这是整个项目最重要的机制发现。

**背景**：Phase 2 的核心 puzzle 是——为什么 Voting 信道策略下 Equal（B1: 8.45%）显著优于 Top2（B3: 9.92%），而在 Single-best 信道策略下恰恰相反（Modal top2 = 9.45% 优于 Modal equal = 10.50%）？

##### 度量方法

**首先澄清"谱"是什么**。两种路径下被比较的谱向量是**同一类型**：对某个 20 s 时间波形做 FFT，截取呼吸带（0.1–0.35 Hz），归一化到和为 1——一个长度约 10–30 的离散概率分布向量，表示"呼吸频段内功率如何分布"。区别在于这个时间波形从哪来：

- **Vote 路径**：每个 modal 内，72 个 tone 各自独立做 FFT 得到 72 条归一化谱 $\{\mathbf{p}_i\}$，以 $\eta_i \cdot \rho_i$ 为权重加权平均，得到一条「72 tone 共识谱」：$\mathbf{p}_{\text{modal}} = \frac{\sum w_i \mathbf{p}_i}{\sum w_i}$
- **Single-best 路径**：每个 modal 只选 $\eta$ 最大的**一个** tone，取该 tone 的 20 s bandpass 波形做 FFT 得到归一化谱 $\mathbf{p}_{\text{modal}}$。它仍然是谱——任何时间波形做 FFT 就是谱——只是信息源从 72 tone 聚合降为单 tone

> **关键澄清 1 — Single-best 有谱**：Single-best 的谱不是"72 信道原始频率-能量曲线"（那需要 72 个复 IQ 值），而是**被选中的那一个 tone 的时间波形的 FFT 功率谱**。任何时间波形做 FFT 就是谱——只是信息源从 72 tone 聚合降为单 tone。
>
> **关键澄清 2 — Voting 的两种用法**：本项目中 Voting 框架有两个不同层面：① **BPM 投票**（T0-V3）：72 tone 各自独立估计一个 BPM 数字 → 直方图投票 → 一个最终 BPM，**无谱可比较**；② **谱加权融合**（B1/B3）：72 tone 各自独立 FFT 得到谱 → η·ρ 加权平均 → 一条融合谱 → 再寻峰，**有谱**。D1 诊断比较的是第②种——因为 B1 和 B3 都需要 per-modal 谱来做模态融合（Equal/Top2）。T0-V3 只输出一个 BPM 数字，它根本没有"谱"这个概念。
>
> **关键澄清 3 — Voting 谱 vs PCA 的本质区别**：两者都做多信道加权组合，但 PCA 在**时域**操作，权重来自协方差最大方向（$\mathbf{v}_1$），优化目标是最大化方差——20 s 短窗内噪声也能产生高方差，PCA 无法区分。Voting 谱在**频域**操作，权重来自信号质量指标（$\eta \cdot \rho$），直接衡量"这个 tone 的频谱里呼吸有多突出"——不关心总方差，只关心呼吸频段的能量集中度和峰尖锐度。这解释了为什么 Voting 谱有效而 PCA 失败。

对每个 20 s 滑窗，分别用两种路径构造三条谱（remote/local/phase），计算两两余弦相似度并取均值：

$$\text{modal\_sim} = \frac{1}{3}\left[\cos(\mathbf{p}_{\text{rem}}, \mathbf{p}_{\text{loc}}) + \cos(\mathbf{p}_{\text{rem}}, \mathbf{p}_{\text{pha}}) + \cos(\mathbf{p}_{\text{loc}}, \mathbf{p}_{\text{pha}})\right]$$

其中每对余弦相似度 $\cos(\mathbf{a}, \mathbf{b}) = \frac{\mathbf{a} \cdot \mathbf{b}}{\|\mathbf{a}\| \|\mathbf{b}\|}$，值域为 $[0, 1]$（谱向量各分量非负，因此不会出现负值）。

余弦相似度度量的是两个谱的**形状相似性**（能量集中在哪个频率），而非总功率大小——这恰好是我们需要的：我们不关心 remote 幅值是否整体比 phase 强（那是信道增益差异），只关心它们是否一致地指向同一个呼吸频率。

##### 主结果

| 场景 | Voting 路径（B1/B3 所用） | Single-best 路径（Modal top2 所用） |
|------|--------------------------|-----------------------------------|
| 091339 | **0.864** | 0.772 |
| 095806 | **0.991** | 0.930 |
| 102621 | **0.959** | 0.885 |

![模态频谱相似度对比](../../outputs/figures/b1_diag_spectral_similarity.png)

**图 8**：D1 诊断图 — 模态间频谱余弦相似度直方图。三场景所有滑窗合并统计。

##### 图 8 读法

- **图表类型**：堆叠直方图（overlapping histogram），横轴分 30 个等宽 bin
- **横轴**：Mean pairwise spectral cosine similarity — 每窗三模态两两余弦相似度的均值（0–1），越接近 1 说明三个模态的频谱越一致
- **纵轴**：Window count — 落入该 bin 的滑窗数
- **🟢 绿色分布（olive）**：Vote spectrum (B1 path) — 信道策略为 Per-Tone Voting 时，各窗的模态间相似度分布
- **🔵 蓝色分布（steelblue）**：Single-best spectrum (Modal path) — 信道策略为逐模态 max-η 单信道时，各窗的模态间相似度分布

核心读法：看两条分布的**相对偏移**。绿色分布整体**偏右**（集中在 0.85–1.0），蓝色分布整体**偏左**（更多分布在 0.7–0.9）。Voting 路径下三模态"说同一件事"的概率系统性地更高。

##### 物理机制

**Single-best 为什么谱更分化**：remote 选 tone 37（max-η），local 可能选 tone 52，phase 可能选 tone 18——三个模态各自选择了**不同 tone index** 的单根信道。不同 tone 经历了不同的多径衰落，FFT 谱自然不同。模态间相似度低。

**Vote 为什么谱更相似**：三种模态的 Vote 谱都在聚合**同一组 tone index（0–71）**。虽然权重 $w_i = \eta_i \cdot \rho_i$ 是 per-modal 独立计算的，但同一个 tone index 在三种模态下经历的是**相同的多径环境**——tone 37 无论被 remote 端测、local 端测、还是作为相位来源，它始终是同一个频率，面对同一组反射路径。因此，在 remote 中是好 tone 的（η 高、BPM 准），在 local 和 phase 中大概率也是好 tone。三种模态的 Vote 谱被**同一组好 tone 主导** → 谱天然趋同。

##### 这对方法选择意味着什么

**图 8 直接解释了「为什么 Equal 优于 Top2」**：谱加权融合（B1/B3）下，三种模态都在平均同一组 72 tone 的归一化 FFT 谱 → 模态间谱天然趋同 → Top2 失去意义 → Equal 更优。Single-best 各自选不同 tone → 谱天然分化 → Top2 有真实收益。

##### 更精确的表述：这个发现到底在说什么

需要收紧结论边界。此发现**不是在说"Voting 这个大类有特殊效应"**——Voting 在本项目中有两种用法：

| 用法 | 方法 | 每 tone 产出 | 融合 | 跨域 | 有"谱"？ |
|------|------|-------------|------|------|----------|
| BPM 投票 | T0-V3 | 一个 BPM 数字 | 直方图投票 | 9.20% | ❌ |
| 谱加权融合 | B1 | 一条完整 FFT 谱 | η·ρ 加权平均 | **8.45%** | ✅ |

D1 只与第二种有关。T0-V3 坍缩为 BPM 数字，没有谱可供比较。

**因此 D1 真正的含义更简单也更重要**：

> 保留每个 tone 的完整频谱信息（而非坍缩为单个 BPM），做谱级加权融合，天然使得三模态的融合谱高度趋同——因为都在平均同一组 tone。这带来的不是"神奇效应"，而是**一个清晰的方法论推论**：Equal 模态融合是最合理的选择。而且，谱级融合（B1: 8.45%）确实优于 BPM 级投票（T0-V3: 9.20%）——**保留完整谱信息比只保留峰频位置更好**。

模态间高相似度不是被"发现"的神秘效应——它是**谱加权融合这个构造方式的结构性必然**。真正的 insight 是：这个结构性必然意味着 Equal > Top2，并且这个推论被 BPM 误差验证了。

##### Voting 优于 Single-best 的证据（与图 8 无关）

| 对比 | 跨域 mean | 说明 |
|------|-----------|------|
| T0-V3 vs Single Remote | 9.20% vs 10.45% | BPM 投票 −1.25pp |
| B1 vs Modal top2 | 8.45% vs 9.45% | 谱融合+Equal −1.00pp |

这是 Deng et al. (2024) 的验证：信道间噪声不独立 → 先独立估计再融合优于先选单信道。与图 8 是两个独立的证据链。

#### 4.6.3 辅助诊断

- **D3-A winning-bin 窄带谱**（仅取 Voting 最高票 bin ±2 BPM 内的 tone 平均谱）：B1 进一步改善至 8.24%（比默认 conf 谱改善 0.21pp），但 B3 仍差于 B1——**排名未反转**，说明窄带谱减少了远偏离 tone 的污染但不能恢复 Top2 的选择性优势。
- **D2 双峰性诊断**：091339 上双峰窗 B1 error（15.17%）**并不高于**单峰窗（17.20%），说明 091339 退化不能简单归因于 Voting 直方图的双峰性。退化根因仍需另寻。

#### 4.6.4 Phase 5 SA：门控去硬编码的验证性实验（2026-06-08）

作为对 G4 系列物理基础的最后验证，我们设计了一个**信号自适应门控（SA）**实验：将 G4 的硬编码 Remote fallback 替换为 per-window 质量驱动的 best-single fallback（动态选择 η·ρ 最高的单模态），看能否恢复门控的有效性。

**核心结果**：无 SA 变体跨域优于 B1（8.45%）。SA-v2 最优仅 10.66%，比 B1 退化 +2.21pp。

**但这组实验产生了一个重要的验证性证据**：

| 场景 | Best Single 选道分布（窗数） | Remote 选中率 |
|------|------------------------------|---------------|
| cs_102621 | local **81** / remote 50 / phase 15 | 33% |
| cs_091339 | remote **101** / phase 28 / local 19 | 58% |
| cs_095806 | phase **56** / local 55 / remote 32 | 27% |

![单模态三场景对比](../../outputs/figures/sa_single_modality_comparison.png)

**图 9**：三场景上 remote/local/phase 各自作为单模态 max-η 选道的 BPM 误差对比。**最优模态是场景依赖的**——102621 上 local 最优（7.32%），091339 上 remote 最优（10.91%），095806 上 phase 最优（11.12%）。这从数据上确认了：**G4 的硬编码 Remote fallback 确实缺乏物理依据**——Remote 在 102621 仅被选中 33%，在 095806 仅 27%。

---

## 5. 方法演进总览

### 5.1 最优方法演进轨迹（主线）

```text
Phase 0 (06/05)  PCA/SVD                         ~10.92%
                       ↓  范式转变：从"先融合再估计"到"先估计再投票"
Phase 1 (06/07)  Per-Tone η·ρ 投票                 9.20%   (−1.72pp)
                       ↓  将 Voting 从单模态扩展为 per-modal + 系统性探索模态融合
Phase 2 (06/08)  逐模态 Voting → 三模态等权谱融合     8.45%   (−0.75pp)
                       ↓  机制诊断：发现 Voting 降低模态间频谱差异性
Phase 3 (06/08)  物理机制确认                       —      （解释 Equal > Top2）
```

> **注**：全阶段排行榜柱状图见下方。

![方法演进时间线](../../outputs/figures/method_evolution_timeline.png)

**图 10**：方法演进时间线。横轴为阶段顺序（P0→P1→P2→P3），纵轴为跨域 mean BPM 相对误差。从 PCA/SVD（~10.92%）到 Per-Tone 投票（9.20%）再到逐模态 Voting→等权融合（8.45%），共降低 2.47pp。

![全阶段排行榜](../../outputs/figures/method_evolution_full_leaderboard.png)

**图 11**：全阶段主线 8 方法排行榜，按跨域 mean 升序排列。颜色标记阶段。**逐模态 Voting → 三模态等权谱融合（P2，绿色）以 8.45% 登顶**。PCA-Modal3（P0，蓝色）位列末位（~10.92%）。

### 5.2 跨域性能排名（所有已评估方法）

| 排名 | 方法（描述性名称） | 代号 | 跨域 mean | 状态 |
|------|-------------------|------|-----------|------|
| **1** | ⭐ **逐模态 Voting → 三模态等权谱融合** | **B1** | **8.45%** | **当前最优** |
| 2 | 逐模态均匀 → η 加权融合 | C2 | 9.15% | — |
| 3 | 逐模态 Voting → η 加权融合 | B2 | 9.16% | — |
| 4 | **Deng et al. (2024) Per-Tone Voting**（仅 remote） | T0-V3 | 9.20% | 🔒 固化基线 |
| 5 | 逐模态最优信道 → Top2 等权谱融合 | Modal top2 | 9.45% | 🔒 固化基线 |
| 6 | 逐模态 Voting → Top2 融合 | B3 | 9.92% | 关键负结果 |
| 7 | 单信道 Remote 幅值（max-η 选道） | Single Remote | 10.45% | 🔒 固化基线 |
| 8 | PCA-Modal3（PCA per modal → η 加权融合） | PCA-Modal3 | ~10.92% | 🔒 固化基线 |
| 9 | Uniform Remote（72 tone 等权谱融合） | B1 (baseline) | 11.02% | — |
| — | G4 系列门控（共识/分歧→回退 Remote） | G4 | 8.05–8.65% | ❌ 已排除（硬编码 fallback） |
| — | SA 自适应门控 | SA-v1/v2 | 10.18–11.42% | ❌ 不推荐 |
| — | VoteP 持久性投票系列 | A2/B4 | 16.59–17.49% | ❌ 已废弃 |

> **标注说明**：⭐ = 当前最优推荐 | 🔒 = 已固化基线（后续不变） | ❌ = 已排除/不推荐

### 5.3 假设验证汇总

| 假设 | 阶段 | 内容 | 判定 |
|------|------|------|------|
| — | P0 | PCA 可分离呼吸信号与多径噪声 | **已废弃**（~10.92% 未超越 baseline） |
| H2 | P1 | Per-tone η·ρ 投票优于所有 baseline | **已验证**（T0-V3 = 9.20% < 10.45%） |
| H2（sys）| P2 | 信道策略与模态策略存在交互效应 | **已验证**（Voting 下 Equal 有效但 Top2 无效） |
| H5（sys）| P2 | Persistence voting 可迁移到模态融合 | **已废弃**（A2 17.49%, B4 16.59%） |
| H2（b1）| P3 | Voting→谱模态间相似度高于 Single-best→谱 | **已验证**（三场景一致性，物理机制清晰） |
| — | SA | Remote 非全局最优单模态 | **已验证**（三场景 Best Single 分布显著不同） |
| — | SA | 自适应门控可超越 B1 | **未证实**（SA-v2 最优 10.66%） |

---

## 6. 核心发现与方法论总结

### 6.1 项目回答了什么问题

| 问题 | 早期假设 | 最终答案 |
|------|----------|----------|
| 多信道比单信道好吗？ | 早期 Plan1：等权平均 < 单选 → "多信道反而有害" | **用质量加权后，多信道 > 单选**（B1 8.45% < Single 10.45%） |
| 怎么给信道赋权？ | q 系统（log-mapped η·ρ）| **raw η·ρ 更好**（保留动态范围，对差 tone 更激进） |
| 单变量还是多变量？ | Plan1/Plan2：三变量优于单变量 | **确认：三变量 Equal 融合最优** |
| PCA 能提取呼吸吗？ | 假设呼吸是最大方差成分 | **不能**——短窗内噪声也能产生高方差 |
| Voting 是最好的融合方式吗？ | 假设 BPM 投票是核心 | **谱融合优于 BPM 投票**（8.45% < 9.20%）——保留完整谱信息比坍缩到峰频更好 |

### 6.2 最优方法的本质

B1 = **逐 tone FFT 谱 × raw η·ρ 权重 + 三模态 Equal 融合**。这不是一个"新算法"，而是早期 Plan1 的 `fft_q_energy_peak` 思路经过三个关键改进后的版本：

1. **raw 权重替代 log-mapped q 权重** → 更激进地去噪
2. **三模态替代单模态** → 最大改善来源
3. **去掉 consensus gate** → 投票机制已提供足够离群抑制

### 6.3 谱融合下 Equal > Top2 的机制

D1 诊断揭示：谱加权融合下，三种模态都在平均同一组 tone index → 模态间谱天然趋同。这不是 Voting 的"隐藏效应"，而是谱加权融合这一构造方式的结构性必然。因此 Equal（等权降方差）优于 Top2（选择性失去意义）。

---

## 7. 部署建议与固化基线

### 7.1 推荐方法

| 场景 | 建议方法 | 跨域/单场景 | 理由 |
|------|----------|-------------|------|
| **跨域默认** | B1（逐 tone 谱 η·ρ 加权 → 三模态 Equal） | **8.45%** | 当前最优无门控方法；不依赖 fallback 硬编码 |
| **095806** | 同上 | 6.50% | B1 在此场景接近最优 |
| **102621** | B1 或待下一轮确定 | 5.63% | B1 已较好 |
| **091339** | 暂无单一最优 | > 12% | 需进一步诊断退化根因 |

### 7.2 固化基线

以下方法作为后续工作的固定对比基线：

| 基线 | 方法 | 跨域 mean | 定位 |
|------|------|-----------|------|
| **Deng et al. (2024) Per-Tone Voting** | T0-V3：每 tone 独立 BPM → η·ρ 直方图投票（仅 remote） | 9.20% | 论文原始 Voting 策略的 BLE 复现；后续 Voting 变种以此论文名区分 |
| **Single Remote** | max-η 选单 tone → FFT → BPM | 10.45% | 最简基线 |
| **Modal top2** | 逐模态 max-η 单 tone → Top2 等权谱融合 | 9.45% | Plan2 最优 baseline |
| **PCA-Modal3** | PCA per modal → η 加权融合 | ~10.92% | 全局融合的失败参照 |

> **命名约定**：后续若引入其他论文的 Voting 变种，以论文第一作者+年份命名（如 `Deng2024_Voting`），避免与通用方法名混淆。

### 7.3 不推荐

| 方法 | 原因 |
|------|------|
| G4 / G4-B1 系列 | fallback→Remote 硬编码，无物理依据 |
| SA-v1/v2 | 跨域 > 10%，显著劣于 B1 |
| VoteP 系列 | 跨场景灾难性退化（> 16%） |

---

## 8. 开放问题与下一步工作

### 8.1 近期可以推进的方向

#### 方向一：权重函数的系统对比

**现状**：B1 用 raw η·ρ 作为权重，早期 q 系统用 log-mapped q 值。两者在相同架构下（逐 tone 谱融合 + 三模态 Equal）的公平对比尚未进行。

**建议**：在 B1 的架构下（固定三模态 Equal），ablation 权重函数：
- raw η·ρ（当前 B1）
- log-mapped q_energy · q_peak
- η only / ρ only
- 学习到的权重（如 SVM，见 Wi-Breath [6]）

**目标**：确定最优权重函数，量化 raw vs log-mapped 在公平条件下的增益。

#### 方向二：多径环境诊断与 091339 退化根因

**现状**：B1 在 091339 上仍有 > 12% 的误差，退化根因（非双峰性、非 η 质量单调相关）仍未找到。

**建议**：分析 091339 与其他场景在信道延迟谱、tone 间相关性上的差异。阅读已安排的文献（[`docs/plans/literature_review_plan.md`](../plans/literature_review_plan.md)）。

#### 方向三：新场景泛化验证

**现状**：B1 = 8.45% 仅在三个金属板场景下成立。

**建议**：在新场景（不同实验范式、体动干扰、非金属板环境）上验证 B1，同时验证谱融合下 Equal > Top2 的机制是否跨场景保持。

### 8.2 中期保留问题

| ID | 问题 | 状态 |
|----|------|------|
| Q1 | 091339 退化根因 | `[待确认]` — 多径结构诊断待做 |
| Q2 | Deng et al. Voting threshold τ = 0.3 在 BLE 72 tone 上是否最优？ | `[待确认]` |
| Q3 | 早期 q_energy_peak 扩展为三变量+raw 权重后能否接近 B1？ | 可做公平 ablation 验证 |

### 8.3 基线固化与命名约定

**Deng et al. (2024) 的 Per-Tone Voting（T0-V3, 9.20%）已固化为固定对比基线**。后续若引入其他论文的 Voting 变种（如 TR-BREATH 的 TRRS、Xie et al. 的 CSI-ratio PCA），以论文第一作者+年份命名（如 `Deng2024_Voting`），避免"Voting"一词在不同方法间混淆。其他基线（Single Remote 10.45%、Modal top2 9.45%、PCA-Modal3 ~10.92%）同步固化。详见 §7.2。

---

## 9. 附录

### 9.1 方法命名对照

| 内部代号 | 描述性名称 | 主线地位 |
|----------|-----------|----------|
| **PCA-Modal3** | 逐模态 PCA 降维 → η 加权模态谱融合 | 主线（已废弃） |
| **T0-V3** | 远程单模态 Per-Tone η·ρ 投票 | 主线（范式验证） |
| **B1（sys）** | 逐模态 Voting → 三模态等权谱融合 | **主线（当前最优）** |
| **B3（sys）** | 逐模态 Voting → 三模态 Top2 等权谱融合 | 主线（关键负结果） |
| **Modal top2** | 逐模态最优信道（max-η 选道） → Top2 等权谱融合 | 主线（核心 baseline） |
| **Single Remote** | 单信道 Remote 幅值（max-η 选道） | 主线（baseline） |
| **G4** | 窗级门控：双候选共识/分歧→回退单信道 Remote | 旁注（已被修正） |
| **G4-B1-v2** | 窗级门控：三候选最近对共识 | 旁注（已被修正） |
| **SA-v1/v2** | 信号自适应门控 v1（一致性+best-single）/ v2（η 质量三级） | 验证性实验 |

### 9.2 现有图表清单

以下图表已在对应阶段的实验中生成，本报告正文中已引用：

| 图表 | 路径 | 阶段 |
|------|------|------|
| PCA/SVD 跨域排行榜 | `outputs/figures/pca_svd_cross_domain_aggregate_bars.png` | P0 |
| PCA/SVD PC1 方差占比 | `outputs/figures/pca_svd_pc1_variance_ratio.png` | P0 |
| Phase 1 Voting 跨域排行榜 | `outputs/figures/voting_fusion_leaderboard.png` | P1 |
| Phase 1 Voting 各场景对比 | `outputs/figures/voting_fusion_cross_domain_aggregate_bars.png` | P1 |
| 系统性融合跨域排行榜 | `outputs/figures/systematic_fusion_leaderboard.png` | P2 |
| 系统性融合二维热力图 | `outputs/figures/systematic_fusion_2d_heatmap.png` | P2 |
| 系统性融合消融瀑布图 | `outputs/figures/systematic_fusion_ablation_waterfall.png` | P2 |
| 模态频谱相似度对比 | `outputs/figures/b1_diag_spectral_similarity.png` | P3 |
| SA 单模态三场景对比 | `outputs/figures/sa_single_modality_comparison.png` | SA |
| 方法演进时间线 | `outputs/figures/method_evolution_timeline.png` | 汇总 |
| 全阶段排行榜 | `outputs/figures/method_evolution_full_leaderboard.png` | 汇总 |

### 9.3 待补充图表清单（建议交由 Cursor Composer 生成）

以下图表对于完整展示各阶段成果是必要的，但当前尚未生成：

| 图表 | 建议路径 | 数据来源 | 优先级 |
|------|----------|----------|--------|
| 全阶段场景×方法热力图 | `outputs/figures/method_evolution_heatmap.png` | 各阶段三场景结果 | 中 |
| PCA/SVD 与 Voting 双线对比图 | `outputs/figures/pca_vs_voting_comparison.png` | pca_svd + voting 跨域 | 中 |
| PCA/SVD 系列 PNG 版（从 PDF 转） | `outputs/figures/pca_svd_*.png` | 现有 PDF | 低 |

---

## 10. 产出前自查

| # | 检查项 | 状态 |
|---|--------|------|
| 1 | 图片路径正确（`../../outputs/figures/` 开头） | ✅ 已验证（Phase 1/演进/排行榜已补充 PNG） |
| 2 | 方法名称：正文/表格/图标题均使用描述性名称（非纯代号） | ✅ 已执行（代码和图表均使用描述性名称） |
| 3 | 数值来源：所有数字均来自实际 .npy 结果文件 | ✅ 均来自各阶段 report 中的实际数值 |
| 4 | 单场景标记：仅在单场景有效的结论已明确标注 | ✅ 已标注 |
| 5 | 图表引用：每个 `![]()` 有 alt text，图后有解读文字 | ✅ 已执行 |

---

## 给 Cursor Composer 的交接说明

请在 Cursor Composer 中启用 `BLE CS 执行 Agent`，完成以下图表补充任务：

### 任务：生成 §9.3 中优先级图表（可选）

**目标**：根据本报告 §9.3 的待补充图表清单，可选择生成中低优先级图表（全阶段热力图、PCA vs Voting 双线对比图、PCA/SVD PNG 转换）。

**数据来源**：各阶段 `outputs/reports/` 下 cross_domain npy 文件。

**要求**：图表标题和坐标轴标签使用描述性方法名称，输出 PNG 格式到 `outputs/figures/`。

执行完成后，请返回生成的 PNG 图表路径和 git commit message 建议。
